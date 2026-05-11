"""
Pure-Python game-logic engine for the Spectrum party game.

The engine is intentionally stateless per call: every public method
receives a Room object (which contains a mutable GameState) and mutates
it in-place, then returns a result dict.

Return value contract
─────────────────────
Every public method returns a dict that always contains:
    {"ok": bool, "error": str | None, ...extra keys...}

On success ok=True, error=None, plus method-specific keys.
On failure ok=False, error=<human-readable reason>, no extra keys.
"""

from __future__ import annotations

import random
from typing import Optional

from .models import GamePhase, Player, Role, Room, Team
from .spectrum_cards import get_spectrum_cards

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# How many recently-used cards to exclude before allowing re-use.
_RECENT_CARD_EXCLUSION_COUNT = 5

# Scoring thresholds as half-widths around the target (0–100 scale).
# Checked from tightest to widest; first match wins.
_SCORE_ZONES: list[tuple[float, int]] = [
    (6.25,  4),   # bullseye:     target ± 6.25  → 4 pts
    (12.5,  3),   # inner ring:   target ± 12.5  → 3 pts
    (18.75, 2),   # middle ring:  target ± 18.75 → 2 pts
    (25.0,  1),   # outer ring:   target ± 25.0  → 1 pt
    # beyond 25.0                               → 0 pts
]

# Target is restricted to this range to avoid degenerate near-edge targets.
_TARGET_MIN = 10.0
_TARGET_MAX = 90.0


# ---------------------------------------------------------------------------
# GameEngine
# ---------------------------------------------------------------------------

class GameEngine:
    """All game logic for a Wavelength room."""

    def __init__(self) -> None:
        # room_code → list of (left, right) cards used recently
        self._card_history: dict[str, list[tuple[str, str]]] = {}

    # ------------------------------------------------------------------
    # Public methods — team / lobby management
    # ------------------------------------------------------------------

    def assign_teams(
        self, room: Room, assignments: dict[str, str]
    ) -> dict:
        """
        Assign players to teams from an explicit host-provided mapping.

        Parameters
        ----------
        assignments : {player_id: "left" | "right"}
            Players not present keep their current team assignment.
        """
        if room.game_state.phase != GamePhase.LOBBY:
            return {"ok": False, "error": "Cannot reassign teams after game starts"}

        for player_id, team_str in assignments.items():
            if team_str not in ("left", "right"):
                return {
                    "ok": False,
                    "error": f"Invalid team '{team_str}'; must be 'left' or 'right'",
                }
            player = room.get_player(player_id)
            if player is None:
                continue  # silently skip unknown ids
            player.team = Team(team_str)

        return {"ok": True, "error": None, "assignments": assignments}

    def auto_assign_teams(self, room: Room) -> dict:
        """
        Evenly distribute all players between LEFT and RIGHT at random.

        Returns the resulting assignment in {"left": [...ids], "right": [...ids]}.
        """
        if room.game_state.phase != GamePhase.LOBBY:
            return {"ok": False, "error": "Cannot reassign teams after game starts"}

        players = list(room.players)
        random.shuffle(players)
        mid = len(players) // 2  # RIGHT gets the smaller half on odd counts

        left_ids: list[str] = []
        right_ids: list[str] = []

        for i, player in enumerate(players):
            if i < len(players) - mid:
                player.team = Team.LEFT
                left_ids.append(player.id)
            else:
                player.team = Team.RIGHT
                right_ids.append(player.id)

        return {"ok": True, "error": None, "left": left_ids, "right": right_ids}

    # ------------------------------------------------------------------
    # Public methods — game lifecycle
    # ------------------------------------------------------------------

    def start_game(self, room: Room) -> dict:
        """
        Validate pre-conditions and transition LOBBY → GIVING_HINT.

        Requires ≥2 connected players on each team.
        """
        gs = room.game_state

        if gs.phase != GamePhase.LOBBY:
            return {"ok": False, "error": "Game is already in progress"}

        left_connected = [
            p for p in room.connected_players() if p.team == Team.LEFT
        ]
        right_connected = [
            p for p in room.connected_players() if p.team == Team.RIGHT
        ]

        if len(left_connected) < 2 or len(right_connected) < 2:
            return {
                "ok": False,
                "error": "Each team needs at least 2 players",
            }

        starting_team = random.choice([Team.LEFT, Team.RIGHT])
        self._assign_initial_roles(room, starting_team)

        first_psychic_id = self._next_psychic(room, starting_team)
        left_label, right_label = self._draw_spectrum(room)
        target = self._pick_target()

        gs.phase = GamePhase.GIVING_HINT
        gs.round_number = 1
        gs.current_team = starting_team
        gs.psychic_id = first_psychic_id
        gs.spectrum_left = left_label
        gs.spectrum_right = right_label
        gs.target_position = target
        gs.hint = None
        gs.guess_position = None
        gs.opposing_guess = None

        # Update the chosen player's role to PSYCHIC
        psychic_player = room.get_player(first_psychic_id)
        if psychic_player:
            psychic_player.role = Role.PSYCHIC

        return {"ok": True, "error": None}

    def submit_hint(self, room: Room, player_id: str, hint: str) -> dict:
        """
        Record the psychic's hint and advance GIVING_HINT → GUESSING.
        """
        gs = room.game_state

        if gs.phase != GamePhase.GIVING_HINT:
            return {"ok": False, "error": "Hint can only be submitted during the hint phase"}

        if player_id != gs.psychic_id:
            return {"ok": False, "error": "Only the psychic can submit a hint"}

        stripped = hint.strip() if hint else ""
        if not stripped:
            return {"ok": False, "error": "Hint must be a non-empty string"}

        gs.hint = stripped
        gs.phase = GamePhase.GUESSING

        return {"ok": True, "error": None, "hint": stripped}

    def submit_guess(
        self, room: Room, player_id: str, position: float
    ) -> dict:
        """
        Record the active team's dial position and advance GUESSING → OPPOSING_GUESS.

        Only a GUESSER on the current team may submit (not the psychic).
        """
        gs = room.game_state

        if gs.phase != GamePhase.GUESSING:
            return {"ok": False, "error": "Guess can only be submitted during guessing phase"}

        player = room.get_player(player_id)
        if player is None:
            return {"ok": False, "error": "Player not found"}

        if player.team != gs.current_team:
            return {"ok": False, "error": "Only the active team can submit a guess"}

        if player.role == Role.PSYCHIC:
            return {"ok": False, "error": "The psychic cannot submit the team's guess"}

        try:
            position = float(position)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Position must be a number"}

        if not (0.0 <= position <= 100.0):
            return {"ok": False, "error": "Position must be between 0.0 and 100.0"}

        gs.guess_position = position
        gs.phase = GamePhase.OPPOSING_GUESS

        return {"ok": True, "error": None, "position": position}

    def submit_opposing_guess(
        self, room: Room, player_id: str, direction: str
    ) -> dict:
        """
        Record opposing team's left/right guess and advance OPPOSING_GUESS → REVEALING.

        direction="left"  → player believes the target is LEFT  of guess_position
        direction="right" → player believes the target is RIGHT of guess_position
        """
        gs = room.game_state

        if gs.phase != GamePhase.OPPOSING_GUESS:
            return {
                "ok": False,
                "error": "Opposing guess only valid during opposing guess phase",
            }

        player = room.get_player(player_id)
        if player is None:
            return {"ok": False, "error": "Player not found"}

        opposing_team = self._get_opposing_team(gs.current_team)
        if player.team != opposing_team:
            return {"ok": False, "error": "Only the opposing team can submit an opposing guess"}

        if direction not in ("left", "right"):
            return {"ok": False, "error": "Direction must be 'left' or 'right'"}

        gs.opposing_guess = direction
        gs.phase = GamePhase.REVEALING

        return {"ok": True, "error": None, "direction": direction}

    def score_round(self, room: Room) -> dict:
        """
        Calculate and apply scores for the just-completed round.

        Transitions OPPOSING_GUESS → REVEALING (or GAME_OVER).
        Does NOT rotate teams/psychic or draw a new card — that happens
        in advance_round(), which is called when the host/players advance.
        """
        gs = room.game_state

        if gs.phase != GamePhase.REVEALING:
            return {"ok": False, "error": "score_round only valid in revealing phase"}

        current_team = gs.current_team
        opposing_team = self._get_opposing_team(current_team)

        # --- scoring ---
        main_score = self._calculate_round_score(gs.target_position, gs.guess_position)

        if gs.target_position != gs.guess_position:
            actual_direction = "left" if gs.target_position < gs.guess_position else "right"
            opposing_bonus = 1 if gs.opposing_guess == actual_direction else 0
        else:
            opposing_bonus = 0  # exact hit — no valid direction for the opposing team

        gs.scores[current_team] += main_score
        gs.scores[opposing_team] += opposing_bonus

        # --- check for game over ---
        left_score = gs.scores[Team.LEFT]
        right_score = gs.scores[Team.RIGHT]
        game_over = left_score >= gs.winning_score or right_score >= gs.winning_score

        winner: Optional[Team] = None

        if game_over:
            if left_score > right_score:
                winner = Team.LEFT
            elif right_score > left_score:
                winner = Team.RIGHT
            else:
                winner = current_team  # tiebreak: team that just scored
            gs.phase = GamePhase.GAME_OVER

        # Phase stays REVEALING (or becomes GAME_OVER) — do NOT advance yet.

        return {
            "ok": True,
            "error": None,
            "round_scores": {
                "main_score": main_score,
                "opposing_bonus": opposing_bonus,
                "active_team": current_team.value,
                "opposing_team": opposing_team.value,
            },
            "total_scores": {
                Team.LEFT.value: gs.scores[Team.LEFT],
                Team.RIGHT.value: gs.scores[Team.RIGHT],
            },
            "game_over": game_over,
            "winner": winner.value if winner else None,
        }

    def advance_round(self, room: Room) -> dict:
        """
        Rotate teams/psychic, draw a new card, and transition REVEALING → GIVING_HINT.

        Called when all players are done viewing the reveal screen.
        Not valid once the game is over.
        """
        gs = room.game_state

        if gs.phase != GamePhase.REVEALING:
            return {"ok": False, "error": "advance_round only valid in revealing phase"}

        current_team = gs.current_team
        opposing_team = self._get_opposing_team(current_team)
        next_team = opposing_team

        next_psychic_id = self._next_psychic(room, next_team)

        old_psychic = room.get_player(gs.psychic_id)
        if old_psychic:
            old_psychic.role = Role.GUESSER
        new_psychic = room.get_player(next_psychic_id)
        if new_psychic:
            new_psychic.role = Role.PSYCHIC

        left_label, right_label = self._draw_spectrum(room)
        target = self._pick_target()

        gs.phase = GamePhase.GIVING_HINT
        gs.round_number += 1
        gs.current_team = next_team
        gs.psychic_id = next_psychic_id
        gs.spectrum_left = left_label
        gs.spectrum_right = right_label
        gs.target_position = target
        gs.hint = None
        gs.guess_position = None
        gs.opposing_guess = None

        return {"ok": True, "error": None}

    def set_team_name(self, room: Room, side: str, name: str) -> dict:
        """Rename a team. Only allowed in the lobby."""
        if room.game_state.phase != GamePhase.LOBBY:
            return {"ok": False, "error": "Can only rename teams in the lobby"}
        name = name.strip()[:20]
        if not name:
            return {"ok": False, "error": "Team name cannot be empty"}
        if side == "left":
            room.left_team_name = name
        elif side == "right":
            room.right_team_name = name
        else:
            return {"ok": False, "error": "Side must be 'left' or 'right'"}
        return {"ok": True, "error": None}

    def reset_game(self, room: Room) -> dict:
        """Reset a finished (or in-progress) game back to the lobby."""
        gs = room.game_state
        gs.phase = GamePhase.LOBBY
        gs.round_number = 0
        gs.current_team = None
        gs.psychic_id = None
        gs.spectrum_left = None
        gs.spectrum_right = None
        gs.target_position = None
        gs.hint = None
        gs.guess_position = None
        gs.opposing_guess = None
        gs.scores = {Team.LEFT: 0, Team.RIGHT: 0}
        for player in room.players:
            player.role = None
        return {"ok": True, "error": None}

    def reveal(self, room: Room) -> dict:
        """
        Backward-compatible wrapper: score_round() then advance_round().

        Kept for any direct callers; the server now uses score_round() /
        advance_round() separately so the REVEALING phase is actually shown.
        """
        result = self.score_round(room)
        if not result["ok"]:
            return result
        if not result["game_over"]:
            self.advance_round(room)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _calculate_round_score(self, target: float, guess: float) -> int:
        """
        Return points (0–4) based on how close guess is to target.

        Zones (distance = abs(target - guess)):
            ≤  6.25 → 4 pts  (bullseye)
            ≤ 12.5  → 3 pts
            ≤ 18.75 → 2 pts
            ≤ 25.0  → 1 pt
            > 25.0  → 0 pts
        """
        distance = abs(target - guess)
        for threshold, points in _SCORE_ZONES:
            if distance <= threshold:
                return points
        return 0

    def _next_psychic(self, room: Room, team: Team) -> str:
        """
        Return the player_id of the next psychic for `team`.

        Rotates through connected team members in join order.
        Falls back to all team members if none are connected.
        """
        candidates = [p for p in room.players if p.team == team and p.is_connected]
        if not candidates:
            candidates = [p for p in room.players if p.team == team]
        if not candidates:
            raise ValueError(f"No players on team {team.value}")

        current_psychic = room.get_player(room.game_state.psychic_id)

        if current_psychic is not None and current_psychic in candidates:
            idx = candidates.index(current_psychic)
        else:
            idx = -1

        next_idx = (idx + 1) % len(candidates)
        return candidates[next_idx].id

    def _draw_spectrum(self, room: Room) -> tuple[str, str]:
        """
        Pick a spectrum card for this room, excluding recently used ones.
        """
        deck = get_spectrum_cards()
        history = self._card_history.get(room.code, [])
        recent = set(history[-_RECENT_CARD_EXCLUSION_COUNT:]) if history else set()

        available = [c for c in deck if c not in recent]
        if not available:
            available = deck  # fallback if exclusion window is too large

        chosen = random.choice(available)
        history.append(chosen)
        # Cap history at 2× deck size to prevent unbounded growth
        self._card_history[room.code] = history[-(2 * len(deck)):]

        return chosen

    @staticmethod
    def _pick_target() -> float:
        """
        Pick a random target in [_TARGET_MIN, _TARGET_MAX], rounded to 2 dp.
        """
        return round(random.uniform(_TARGET_MIN, _TARGET_MAX), 2)

    def _assign_initial_roles(self, room: Room, starting_team: Team) -> None:
        """
        Set player.role for all players before the first round.

        All players start as GUESSER. The psychic for the starting team
        will be set to PSYCHIC by start_game() after _next_psychic() is called.
        """
        for player in room.players:
            player.role = Role.GUESSER

    @staticmethod
    def _get_opposing_team(team: Team) -> Team:
        """Return the other team."""
        return Team.RIGHT if team == Team.LEFT else Team.LEFT
