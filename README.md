# Spectrum

> **Inspired by the Wavelength board game (Palm Court / Asmodee) — unofficial fan project, not affiliated.**
> Wavelength was designed by Alex Hague, Justin Vickers, and Wolfgang Warsch.
> Please support the original by purchasing the official game.

---

## About

A browser-based multiplayer party game, playable over a local network.
Up to 12 players split into two teams and take turns giving and guessing clues on a hidden spectrum dial.

**This project is free, open source, and will never be monetised.**

---

## Requirements

- Python 3.10+
- pip

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
# Local only (http://localhost:8000)
uvicorn backend.server:app --reload

# LAN (replace with your machine's IP)
uvicorn backend.server:app --host 0.0.0.0 --port 8765 --reload
```

Open the printed URL in a browser. Share the URL (and room code) with other players on the same network.

---

## How to play

1. One player creates a room and shares the room code.
2. Players join and the host assigns teams (or uses Auto-Assign).
3. Each round, the active team's **Psychic** sees a secret target on a spectrum dial and gives a one-word clue.
4. The rest of the team drags the dial to their best guess.
5. The opposing team then calls whether the true target is **left** or **right** of the needle.
6. Scores are revealed — first team to **10 points** wins.

---

## Project structure

```
spectrum/
├── backend/
│   ├── server.py          # FastAPI + WebSocket hub
│   ├── game_engine.py     # Pure-Python game logic
│   ├── models.py          # Data classes (Room, Player, GameState)
│   └── spectrum_cards.py  # Spectrum card deck
├── frontend/
│   ├── index.html         # Single-page UI (7 screens)
│   ├── style.css          # Dark theme + dial CSS
│   └── main.js            # WebSocket client + rendering
└── requirements.txt
```

---

## Credits

Inspired by **Wavelength** by Alex Hague, Justin Vickers & Wolfgang Warsch — published by **Palm Court / Asmodee**.
Fan implementation by dennvar.
