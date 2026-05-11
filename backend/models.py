from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import uuid


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Team(str, Enum):
    LEFT = "left"
    RIGHT = "right"


class Role(str, Enum):
    PSYCHIC = "psychic"
    GUESSER = "guesser"


class GamePhase(str, Enum):
    LOBBY = "lobby"             # Waiting for players
    GIVING_HINT = "giving_hint" # Psychic sees target, writes clue
    GUESSING = "guessing"       # Active team places the dial
    OPPOSING_GUESS = "opposing" # Opposing team guesses left / right
    REVEALING = "revealing"     # Target revealed, scores calculated
    GAME_OVER = "game_over"     # A team reached the winning score


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------

@dataclass
class Player:
    name: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    team: Optional[Team] = None
    role: Optional[Role] = None
    is_connected: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "team": self.team.value if self.team else None,
            "role": self.role.value if self.role else None,
            "is_connected": self.is_connected,
        }


# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------

@dataclass
class GameState:
    phase: GamePhase = GamePhase.LOBBY

    # Round logistics
    round_number: int = 0
    current_team: Optional[Team] = None       # Team whose turn it is
    psychic_id: Optional[str] = None          # Player.id of the active psychic

    # Spectrum card drawn for the round (pole labels)
    spectrum_left: Optional[str] = None       # e.g. "Hot"
    spectrum_right: Optional[str] = None      # e.g. "Cold"

    # Hidden from guessers until reveal
    target_position: Optional[float] = None   # 0.0 (left) … 100.0 (right)

    # Submitted by the psychic
    hint: Optional[str] = None

    # Submitted by the active team
    guess_position: Optional[float] = None    # 0.0 … 100.0

    # Submitted by the opposing team ("left" | "right")
    opposing_guess: Optional[str] = None

    # Accumulated scores  {Team.LEFT: int, Team.RIGHT: int}
    scores: dict = field(
        default_factory=lambda: {Team.LEFT: 0, Team.RIGHT: 0}
    )

    # First team to reach this score wins
    winning_score: int = 10

    def to_dict(self, *, reveal: bool = False) -> dict:
        """
        Serialize to a plain dict safe for JSON transport.

        Pass reveal=True (e.g. in REVEALING / GAME_OVER phases) to expose
        the target_position that is otherwise hidden from the wire.
        """
        return {
            "phase": self.phase.value,
            "round_number": self.round_number,
            "current_team": self.current_team.value if self.current_team else None,
            "psychic_id": self.psychic_id,
            "spectrum_left": self.spectrum_left,
            "spectrum_right": self.spectrum_right,
            # Only expose target when it's safe to do so
            "target_position": self.target_position if reveal else None,
            "hint": self.hint,
            "guess_position": self.guess_position,
            "opposing_guess": self.opposing_guess,
            "scores": {team.value: pts for team, pts in self.scores.items()},
            "winning_score": self.winning_score,
        }


# ---------------------------------------------------------------------------
# Room
# ---------------------------------------------------------------------------

@dataclass
class Room:
    code: str                                  # Short human-readable join code
    host_id: str                               # Player.id of the room creator
    players: list[Player] = field(default_factory=list)
    game_state: GameState = field(default_factory=GameState)
    max_players: int = 12
    left_team_name: str = "Left"
    right_team_name: str = "Right"

    # ------------------------------------------------------------------
    # Player management
    # ------------------------------------------------------------------

    def get_player(self, player_id: str) -> Optional[Player]:
        return next((p for p in self.players if p.id == player_id), None)

    def add_player(self, player: Player) -> bool:
        """Return False if the room is full or the player is already in."""
        if len(self.players) >= self.max_players:
            return False
        if self.get_player(player.id):
            return False
        self.players.append(player)
        return True

    def remove_player(self, player_id: str) -> bool:
        player = self.get_player(player_id)
        if player is None:
            return False
        self.players.remove(player)
        return True

    def connected_players(self) -> list[Player]:
        return [p for p in self.players if p.is_connected]

    def players_by_team(self, team: Team) -> list[Player]:
        return [p for p in self.players if p.team == team]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self, *, viewer_id: Optional[str] = None) -> dict:
        """
        viewer_id: if provided and the viewer is the psychic, the target
        position is revealed to them even before the REVEALING phase.
        """
        is_psychic = (
            viewer_id is not None
            and viewer_id == self.game_state.psychic_id
        )
        reveal = is_psychic or self.game_state.phase in (
            GamePhase.REVEALING,
            GamePhase.GAME_OVER,
        )

        return {
            "code": self.code,
            "host_id": self.host_id,
            "max_players": self.max_players,
            "left_team_name": self.left_team_name,
            "right_team_name": self.right_team_name,
            "players": [p.to_dict() for p in self.players],
            "game_state": self.game_state.to_dict(reveal=reveal),
        }
