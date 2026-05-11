"""
FastAPI server for the Spectrum multiplayer game.

REST:
  POST /rooms              — create room (host)
  POST /rooms/{code}/join  — join room
  GET  /                   — serve frontend

WebSocket:
  WS /ws/{room_code}/{player_id}
"""

from __future__ import annotations

import random
import string

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .game_engine import GameEngine
from .models import GamePhase, Player, Room

# ---------------------------------------------------------------------------
# App + shared state
# ---------------------------------------------------------------------------

app = FastAPI(title="Spectrum")
engine = GameEngine()

rooms: dict[str, Room] = {}
# connections[room_code][player_id] = WebSocket
connections: dict[str, dict[str, WebSocket]] = {}

app.mount("/static", StaticFiles(directory="frontend"), name="static")


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class CreateRoomRequest(BaseModel):
    name: str


class JoinRoomRequest(BaseModel):
    name: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_room_code() -> str:
    while True:
        code = "".join(random.choices(string.ascii_uppercase, k=4))
        if code not in rooms:
            return code


async def _broadcast(
    room_code: str, message: dict, exclude: str | None = None
) -> None:
    """Send the same message to all connected players (except `exclude`)."""
    dead: list[str] = []
    for pid, ws in list(connections.get(room_code, {}).items()):
        if pid == exclude:
            continue
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(pid)
    for pid in dead:
        connections[room_code].pop(pid, None)


async def _send_state_update(room_code: str) -> None:
    """
    Send a personalised state_update to every connected player.

    Each player gets room.to_dict(viewer_id=their_id) so the psychic
    sees target_position while everyone else gets null.
    """
    room = rooms[room_code]
    dead: list[str] = []
    for player_id, ws in list(connections.get(room_code, {}).items()):
        msg = {"type": "state_update", "room": room.to_dict(viewer_id=player_id)}
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(player_id)
    for pid in dead:
        connections[room_code].pop(pid, None)


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def root() -> FileResponse:
    return FileResponse("frontend/index.html")


@app.post("/rooms")
async def create_room(body: CreateRoomRequest) -> dict:
    code = _generate_room_code()
    player = Player(name=body.name.strip())
    room = Room(code=code, host_id=player.id)
    room.add_player(player)
    rooms[code] = room
    connections[code] = {}
    return {"room_code": code, "player_id": player.id}


@app.post("/rooms/{code}/join")
async def join_room(code: str, body: JoinRoomRequest) -> dict:
    code = code.upper()
    room = rooms.get(code)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    if room.game_state.phase != GamePhase.LOBBY:
        raise HTTPException(status_code=400, detail="Game already started")
    if len(room.players) >= room.max_players:
        raise HTTPException(status_code=400, detail="Room is full")

    player = Player(name=body.name.strip())
    room.add_player(player)
    return {"player_id": player.id}


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws/{room_code}/{player_id}")
async def websocket_endpoint(
    ws: WebSocket, room_code: str, player_id: str
) -> None:
    await ws.accept()

    room = rooms.get(room_code)
    if room is None:
        await ws.send_json({"type": "error", "message": "Room not found"})
        await ws.close()
        return

    player = room.get_player(player_id)
    if player is None:
        await ws.send_json({"type": "error", "message": "Player not found"})
        await ws.close()
        return

    # Register connection
    connections[room_code][player_id] = ws
    player.is_connected = True

    # Notify others, then send full state to everyone
    await _broadcast(
        room_code,
        {"type": "player_joined", "player": player.to_dict()},
        exclude=player_id,
    )
    await _send_state_update(room_code)

    try:
        while True:
            data = await ws.receive_json()
            await _handle_message(room_code, player_id, ws, data)
    except WebSocketDisconnect:
        player.is_connected = False
        connections[room_code].pop(player_id, None)
        await _broadcast(
            room_code, {"type": "player_left", "player_id": player_id}
        )


# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------

async def _handle_message(
    room_code: str, player_id: str, ws: WebSocket, data: dict
) -> None:
    room = rooms.get(room_code)
    if room is None:
        return

    msg_type = data.get("type")
    is_host = player_id == room.host_id

    # --- host-only actions ---
    if msg_type in ("assign_teams", "auto_assign", "start_game", "set_team_name", "reset_game") and not is_host:
        await ws.send_json({"type": "error", "message": "Only the host can do that"})
        return

    if msg_type == "assign_teams":
        result = engine.assign_teams(room, data.get("assignments", {}))

    elif msg_type == "auto_assign":
        result = engine.auto_assign_teams(room)

    elif msg_type == "start_game":
        result = engine.start_game(room)

    elif msg_type == "set_team_name":
        result = engine.set_team_name(room, data.get("side", ""), data.get("name", ""))

    elif msg_type == "reset_game":
        result = engine.reset_game(room)

    elif msg_type == "submit_hint":
        # Guard: if hint already submitted (phase moved on), silently ignore
        if room.game_state.phase != GamePhase.GIVING_HINT:
            return
        result = engine.submit_hint(room, player_id, data.get("hint", ""))

    elif msg_type == "submit_guess":
        # Guard: first guesser wins; ignore duplicate clicks / late submissions
        if room.game_state.phase != GamePhase.GUESSING:
            return
        result = engine.submit_guess(room, player_id, data.get("position", 50.0))

    elif msg_type == "opposing_guess":
        # Guard: first opposing player wins; ignore the rest silently
        if room.game_state.phase != GamePhase.OPPOSING_GUESS:
            return
        result = engine.submit_opposing_guess(
            room, player_id, data.get("direction", "")
        )
        if result["ok"]:
            # Score the round — phase stays REVEALING so players see the reveal screen
            score_result = engine.score_round(room)
            if score_result["ok"]:
                # Send round_result BEFORE state_update so the client has it
                # when renderRevealing() runs
                await _broadcast(
                    room_code,
                    {
                        "type": "round_result",
                        "round_scores": score_result["round_scores"],
                        "total_scores": score_result["total_scores"],
                        "game_over": score_result["game_over"],
                        "winner": score_result["winner"],
                    },
                )
            await _send_state_update(room_code)
            return

    elif msg_type == "next_round":
        # Guard: if multiple players click simultaneously, only the first matters
        if room.game_state.phase != GamePhase.REVEALING:
            return
        result = engine.advance_round(room)
        if result["ok"]:
            await _send_state_update(room_code)
        else:
            await ws.send_json({"type": "error", "message": result["error"]})
        return

    elif msg_type == "reveal":
        # Legacy / host fallback: score + advance in one step
        result = engine.reveal(room)
        if result["ok"]:
            await _broadcast(
                room_code,
                {
                    "type": "round_result",
                    "round_scores": result["round_scores"],
                    "total_scores": result["total_scores"],
                    "game_over": result["game_over"],
                    "winner": result["winner"],
                },
            )
            await _send_state_update(room_code)
        else:
            await ws.send_json({"type": "error", "message": result["error"]})
        return

    else:
        await ws.send_json({"type": "error", "message": f"Unknown action: {msg_type}"})
        return

    if not result["ok"]:
        await ws.send_json({"type": "error", "message": result["error"]})
        return

    await _send_state_update(room_code)
