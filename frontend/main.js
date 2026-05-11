/* =========================================================
   Spectrum — frontend client
   ========================================================= */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const state = {
  myPlayerId:           null,
  myTeam:               null,   // "left" | "right" | null
  myRole:               null,   // "psychic" | "guesser" | null
  roomCode:             null,
  hostId:               null,
  gameState:            null,
  players:              [],
  lastRoundResult:      null,
  currentGuessPosition: 50,
  leftTeamName:         "Left",
  rightTeamName:        "Right",
};

let ws = null;

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Session persistence — survive browser refresh
// ---------------------------------------------------------------------------

function saveSession(roomCode, playerId) {
  try {
    sessionStorage.setItem("wl_room", roomCode);
    sessionStorage.setItem("wl_pid",  playerId);
  } catch (_) {}
}

function clearSession() {
  try {
    sessionStorage.removeItem("wl_room");
    sessionStorage.removeItem("wl_pid");
  } catch (_) {}
}

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------

function connect(roomCode, playerId) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/${roomCode}/${playerId}`);

  ws.onmessage = (event) => {
    try {
      handleMessage(JSON.parse(event.data));
    } catch (e) {
      console.error("Bad message", e);
    }
  };

  ws.onerror = () => {
    if (!state.gameState) {
      clearSession();
      showError("Connection error — check the server is running.");
    }
  };

  ws.onclose = () => {
    if (!state.gameState) {
      // Never got a state_update → room/player no longer exists
      clearSession();
    } else {
      showToast("Disconnected. Refresh to rejoin.");
    }
  };
}

function sendAction(type, payload = {}) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type, ...payload }));
  }
}

// ---------------------------------------------------------------------------
// Message handler
// ---------------------------------------------------------------------------

function handleMessage(data) {
  switch (data.type) {
    case "state_update":
      applyStateUpdate(data.room);
      break;
    case "player_joined":
      // Merge into players; the subsequent state_update will fully sync
      if (!state.players.find(p => p.id === data.player.id)) {
        state.players.push(data.player);
      }
      break;
    case "player_left":
      {
        const p = state.players.find(pl => pl.id === data.player_id);
        if (p) p.is_connected = false;
      }
      break;
    case "round_result":
      // Store before the following state_update triggers renderRevealing
      state.lastRoundResult = data;
      break;
    case "error":
      showError(data.message);
      break;
    default:
      console.warn("Unknown message type:", data.type);
  }
}

function applyStateUpdate(roomDict) {
  state.players      = roomDict.players;
  state.gameState    = roomDict.game_state;
  state.hostId       = roomDict.host_id;
  state.leftTeamName  = roomDict.left_team_name  || "Left";
  state.rightTeamName = roomDict.right_team_name || "Right";

  const me = state.players.find(p => p.id === state.myPlayerId);
  if (me) {
    state.myTeam = me.team;
    state.myRole = me.role;
  }

  renderCurrentScreen();
}

/** Return the display name for "left" or "right". */
function teamName(side) {
  return side === "left" ? state.leftTeamName : state.rightTeamName;
}

// ---------------------------------------------------------------------------
// Screen routing
// ---------------------------------------------------------------------------

function hideAllScreens() {
  document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
}

function showScreen(id) {
  document.getElementById(id).classList.add("active");
}

function renderCurrentScreen() {
  const phase = state.gameState?.phase;
  hideAllScreens();
  switch (phase) {
    case "lobby":        showScreen("screen-lobby");        renderLobby();       break;
    case "giving_hint":  showScreen("screen-giving-hint");  renderGivingHint();  break;
    case "guessing":     showScreen("screen-guessing");      renderGuessing();    break;
    case "opposing":     showScreen("screen-opposing");      renderOpposing();    break;
    case "revealing":    showScreen("screen-revealing");     renderRevealing();   break;
    case "game_over":    showScreen("screen-game-over");     renderGameOver();    break;
    default:
      // Not connected yet — keep join screen
      showScreen("screen-join");
  }
}

// ---------------------------------------------------------------------------
// Per-screen renders
// ---------------------------------------------------------------------------

/* ── Lobby ── */
function renderLobby() {
  const gs = state.gameState;

  el("lobby-room-code").textContent = state.roomCode;

  // Team headings
  el("lobby-heading-left").textContent  = state.leftTeamName;
  el("lobby-heading-right").textContent = state.rightTeamName;

  // Scores
  const scores = gs.scores || {};
  el("lobby-scores").textContent =
    `${state.leftTeamName} ${scores.left ?? 0} – ${scores.right ?? 0} ${state.rightTeamName}`;

  // Player lists
  const leftList       = el("lobby-players-left");
  const rightList      = el("lobby-players-right");
  const unassignedList = el("lobby-players-unassigned");
  leftList.innerHTML = rightList.innerHTML = unassignedList.innerHTML = "";

  for (const player of state.players) {
    const li = document.createElement("li");
    li.dataset.playerId = player.id;
    li.textContent = player.name + (player.id === state.hostId ? " ★" : "");
    if (!player.is_connected) li.classList.add("disconnected");

    if (player.team === "left")       leftList.appendChild(li);
    else if (player.team === "right") rightList.appendChild(li);
    else                              unassignedList.appendChild(li);
  }

  // Host controls + team name editor
  const isHost = state.myPlayerId === state.hostId;
  toggleHidden("host-controls", !isHost);
  toggleHidden("team-name-editor", !isHost);
  if (isHost) {
    el("lobby-status").textContent = "Rename teams, assign players, then start.";
    // Sync name inputs to current names (avoid overwriting if user is typing)
    const leftInput  = el("input-left-name");
    const rightInput = el("input-right-name");
    if (leftInput  && document.activeElement !== leftInput)  leftInput.value  = state.leftTeamName;
    if (rightInput && document.activeElement !== rightInput) rightInput.value = state.rightTeamName;
  }
}

/* ── Giving Hint ── */
function renderGivingHint() {
  const gs = state.gameState;

  el("hint-round-num").textContent  = `Round ${gs.round_number}`;
  setTeamBadge("hint-current-team", gs.current_team);
  el("hint-spectrum-left").textContent  = gs.spectrum_left  ?? "";
  el("hint-spectrum-right").textContent = gs.spectrum_right ?? "";
  updateInGameScores("hint");

  const isPsychic = state.myRole === "psychic";
  toggleHidden("psychic-hint-input", !isPsychic);
  toggleHidden("waiting-hint", isPsychic);

  if (isPsychic) {
    const target = gs.target_position ?? 50;
    el("target-position-label").textContent = target.toFixed(1);
    setNeedleAngle("hint-target-needle", target);
    el("hint-target-needle").classList.remove("hidden");
    // Psychic sees scoring zones centred on their target
    drawZoneArcs("hint-dial", target, true);
  } else {
    drawZoneArcs("hint-dial", 50); // decorative for non-psychic watchers
    el("hint-target-needle").classList.add("hidden");
    const psychic = state.players.find(p => p.id === gs.psychic_id);
    el("psychic-name-hint").textContent =
      psychic ? `${psychic.name} is thinking…` : "";
  }
}

/* ── Guessing ── */
let dialDragActive = false;   // prevent re-registering drag listeners

function renderGuessing() {
  const gs = state.gameState;

  el("guess-round-num").textContent  = `Round ${gs.round_number}`;
  setTeamBadge("guess-current-team", gs.current_team);
  el("guess-hint-text").textContent      = gs.hint ?? "";
  el("guess-spectrum-left").textContent  = gs.spectrum_left  ?? "";
  el("guess-spectrum-right").textContent = gs.spectrum_right ?? "";
  updateInGameScores("guess");

  drawZoneArcs("guess-dial", 50); // decorative

  // Active guesser: my team is current and I'm not the psychic
  const isActiveGuesser =
    state.myTeam === gs.current_team && state.myRole !== "psychic";

  toggleHidden("guesser-controls", !isActiveGuesser);
  toggleHidden("waiting-guess", isActiveGuesser);

  if (isActiveGuesser) {
    state.currentGuessPosition = 50;
    el("guess-position-display").textContent = 50;
    setNeedleAngle("guess-needle", 50);

    if (!dialDragActive) {
      dialDragActive = true;
      initDialDrag("guess-dial", (pos) => {
        state.currentGuessPosition = pos;
        el("guess-position-display").textContent = pos;
        setNeedleAngle("guess-needle", pos);
      });
    }
  }
}

/* ── Opposing Guess ── */
function renderOpposing() {
  const gs = state.gameState;

  el("opp-round-num").textContent       = `Round ${gs.round_number}`;
  el("opp-hint-text").textContent        = gs.hint ?? "";
  el("opp-spectrum-left").textContent    = gs.spectrum_left  ?? "";
  el("opp-spectrum-right").textContent   = gs.spectrum_right ?? "";
  updateInGameScores("opp");

  drawZoneArcs("opp-dial", 50);

  const guessPos = gs.guess_position ?? 50;
  setNeedleAngle("opp-guess-needle", guessPos);

  const opposingTeam = gs.current_team === "left" ? "right" : "left";
  const isOpposing   = state.myTeam === opposingTeam;

  toggleHidden("opposing-controls", !isOpposing);
  toggleHidden("waiting-opposing", isOpposing);
}

/* ── Revealing ── */
function renderRevealing() {
  const gs = state.gameState;

  el("reveal-hint-text").textContent      = gs.hint          ?? "";
  el("reveal-spectrum-left").textContent  = gs.spectrum_left  ?? "";
  el("reveal-spectrum-right").textContent = gs.spectrum_right ?? "";

  // Totals bar labels
  el("reveal-label-left").textContent  = state.leftTeamName;
  el("reveal-label-right").textContent = state.rightTeamName;

  const guessPos  = gs.guess_position  ?? 50;
  const targetPos = gs.target_position ?? 50;

  setNeedleAngle("reveal-guess-needle",  guessPos);
  setNeedleAngle("reveal-target-needle", targetPos);

  // Coloured zones centred on the actual target
  drawZoneArcs("reveal-dial", targetPos, true);

  // Opposing arrow
  const arrow = el("reveal-opposing-arrow");
  if (gs.opposing_guess === "left")       arrow.textContent = "←";
  else if (gs.opposing_guess === "right") arrow.textContent = "→";
  else                                    arrow.textContent = "";

  // Score breakdown — clearly name which team scored what
  const result = state.lastRoundResult;
  if (result) {
    const rs = result.round_scores;
    const activeName   = teamName(rs.active_team);
    const opposingName = teamName(rs.opposing_team);

    el("reveal-active-team-name").textContent   = activeName;
    el("reveal-opposing-team-name").textContent = opposingName;
    el("reveal-main-score").textContent         = `+${rs.main_score} pts`;
    el("reveal-opposing-bonus").textContent     = rs.opposing_bonus > 0
      ? `+${rs.opposing_bonus} pt`
      : "0 pts";

    const ts = result.total_scores;
    el("reveal-left-total").textContent  = ts.left  ?? 0;
    el("reveal-right-total").textContent = ts.right ?? 0;
  } else {
    el("reveal-active-team-name").textContent   = teamName(gs.current_team ?? "left");
    el("reveal-opposing-team-name").textContent = teamName(gs.current_team === "left" ? "right" : "left");
    const scores = gs.scores || {};
    el("reveal-left-total").textContent  = scores.left  ?? 0;
    el("reveal-right-total").textContent = scores.right ?? 0;
  }
}

/* ── Game Over ── */
function renderGameOver() {
  const scores  = state.gameState?.scores || {};
  const leftPts  = scores.left  ?? 0;
  const rightPts = scores.right ?? 0;

  // Determine winner: prefer explicit round_result, fall back to score comparison
  let winner;
  if (state.lastRoundResult?.winner) {
    winner = state.lastRoundResult.winner;
  } else if (leftPts > rightPts) {
    winner = "left";
  } else if (rightPts > leftPts) {
    winner = "right";
  } else {
    winner = state.gameState?.current_team ?? "left"; // tiebreak
  }

  const isTie = leftPts === rightPts;
  el("game-over-winner").textContent = isTie
    ? `${teamName(winner)} wins on tie-break!`
    : `${teamName(winner)} wins!`;

  el("final-left-name").textContent   = state.leftTeamName;
  el("final-right-name").textContent  = state.rightTeamName;
  el("final-left-score").textContent  = leftPts;
  el("final-right-score").textContent = rightPts;

  const isHost = state.myPlayerId === state.hostId;
  toggleHidden("btn-play-again",    !isHost);
  toggleHidden("gameover-waiting",   isHost);
}

// ---------------------------------------------------------------------------
// In-game score helper
// ---------------------------------------------------------------------------

function updateInGameScores(prefix) {
  const scores = state.gameState?.scores || {};
  const leftScoreEl  = el(`${prefix}-score-left`);
  const rightScoreEl = el(`${prefix}-score-right`);
  const leftLabelEl  = el(`${prefix}-label-left`);
  const rightLabelEl = el(`${prefix}-label-right`);
  if (leftScoreEl)  leftScoreEl.textContent  = scores.left  ?? 0;
  if (rightScoreEl) rightScoreEl.textContent = scores.right ?? 0;
  if (leftLabelEl)  leftLabelEl.textContent  = state.leftTeamName;
  if (rightLabelEl) rightLabelEl.textContent = state.rightTeamName;
}

// ---------------------------------------------------------------------------
// Dial
// ---------------------------------------------------------------------------

function setNeedleAngle(needleId, position) {
  const angle = (position - 50) * 1.8; // maps 0→-90, 50→0, 100→+90
  const el2 = document.getElementById(needleId);
  if (el2) el2.style.setProperty("--angle", angle);
}

/**
 * Draw the four scoring zone arcs as SVG path segments on the dial.
 *
 * @param {string}  dialId          - element id of the .dial container
 * @param {number}  centrePosition  - 0–100; centre of the zone bands
 * @param {boolean} scoring         - true = distinct colours per zone (reveal screen);
 *                                    false = subtle uniform yellow (decorative)
 */
function drawZoneArcs(dialId, centrePosition, scoring = false) {
  const dialEl = document.getElementById(dialId);
  if (!dialEl) return;

  const svgEl = dialEl.querySelector(".dial-zones");
  if (!svgEl) return;

  const R  = 106;
  const cx = 140;
  const cy = 140;

  // Outermost zone first (painted under inner zones)
  const zones = [
    { hw: 25.0,  sel: ".zone-1pt",
      scoreColor: "rgba(248,113,113,0.55)",  // red   — 1 pt
      decoColor:  "rgba(250,204,21,0.10)" },
    { hw: 18.75, sel: ".zone-2pt",
      scoreColor: "rgba(251,146,60,0.65)",   // orange — 2 pt
      decoColor:  "rgba(250,204,21,0.18)" },
    { hw: 12.5,  sel: ".zone-3pt",
      scoreColor: "rgba(250,204,21,0.80)",   // yellow — 3 pt
      decoColor:  "rgba(250,204,21,0.30)" },
    { hw: 6.25,  sel: ".zone-4pt",
      scoreColor: "rgba(74,222,128,0.95)",   // green  — 4 pt (bullseye)
      decoColor:  "rgba(250,204,21,0.50)" },
  ];

  for (const { hw, sel, scoreColor, decoColor } of zones) {
    const pathEl = svgEl.querySelector(sel);
    if (!pathEl) continue;

    const leftPos  = Math.max(0,   centrePosition - hw);
    const rightPos = Math.min(100, centrePosition + hw);

    const startAngleDeg = (leftPos  - 50) * 1.8;
    const endAngleDeg   = (rightPos - 50) * 1.8;

    pathEl.setAttribute("d", arcPath(cx, cy, R, startAngleDeg, endAngleDeg));
    pathEl.style.stroke = scoring ? scoreColor : decoColor;
  }
}

/**
 * Compute SVG arc path string.
 * Angles are in degrees from 12-o'clock, clockwise.
 */
function arcPath(cx, cy, r, startDeg, endDeg) {
  const toRad = (d) => (d - 90) * (Math.PI / 180);
  const startRad = toRad(startDeg);
  const endRad   = toRad(endDeg);

  const x1 = cx + r * Math.cos(startRad);
  const y1 = cy + r * Math.sin(startRad);
  const x2 = cx + r * Math.cos(endRad);
  const y2 = cy + r * Math.sin(endRad);

  const largeArc = (endDeg - startDeg) > 180 ? 1 : 0;

  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${largeArc} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
}

/**
 * Attach pointer + touch drag listeners to a dial element.
 * Calls onPositionChange(position: 0–100) as the user drags.
 */
function initDialDrag(dialId, onPositionChange) {
  const dialEl = document.getElementById(dialId);
  if (!dialEl) return;

  let dragging = false;

  function positionFromEvent(e) {
    const rect = dialEl.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.bottom; // pivot is the flat base, not the centre

    let clientX, clientY;
    if (e.touches && e.touches.length > 0) {
      clientX = e.touches[0].clientX;
      clientY = e.touches[0].clientY;
    } else {
      clientX = e.clientX;
      clientY = e.clientY;
    }

    const dx = clientX - cx;
    const dy = clientY - cy;

    // atan2(dx, -dy): angle from top, clockwise, in degrees
    let angleDeg = Math.atan2(dx, -dy) * (180 / Math.PI);
    angleDeg = Math.max(-90, Math.min(90, angleDeg)); // clamp to half-circle
    return Math.round((angleDeg + 90) / 1.8);         // → 0–100
  }

  dialEl.addEventListener("pointerdown", (e) => {
    dragging = true;
    dialEl.setPointerCapture(e.pointerId);
    onPositionChange(positionFromEvent(e));
  });
  dialEl.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    onPositionChange(positionFromEvent(e));
  });
  dialEl.addEventListener("pointerup",   () => { dragging = false; });
  dialEl.addEventListener("pointercancel", () => { dragging = false; });
}

// ---------------------------------------------------------------------------
// REST helpers
// ---------------------------------------------------------------------------

async function createRoom(name) {
  const resp = await fetch("/rooms", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ name }),
  });
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(data.detail || "Failed to create room");
  }
  return resp.json();
}

async function joinRoom(code, name) {
  const resp = await fetch(`/rooms/${code.toUpperCase()}/join`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ name }),
  });
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(data.detail || "Failed to join room");
  }
  return resp.json();
}

// ---------------------------------------------------------------------------
// Error display
// ---------------------------------------------------------------------------

function showError(message) {
  const joinErrEl  = document.getElementById("join-error");
  const joinScreen = document.getElementById("screen-join");

  if (joinScreen.classList.contains("active")) {
    joinErrEl.textContent = message;
    setTimeout(() => { joinErrEl.textContent = ""; }, 4000);
  } else {
    showToast(message);
  }
}

function showToast(message) {
  const toast = document.createElement("div");
  toast.className   = "toast";
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

// ---------------------------------------------------------------------------
// DOM helpers
// ---------------------------------------------------------------------------

function el(id) {
  return document.getElementById(id);
}

function toggleHidden(id, shouldHide) {
  const element = document.getElementById(id);
  if (element) {
    element.classList.toggle("hidden", shouldHide);
  }
}

function setTeamBadge(id, team) {
  const badge = document.getElementById(id);
  if (!badge) return;
  badge.textContent = team ? teamName(team) : "";
  badge.className = "team-badge" + (team ? ` ${team}` : "");
}

// ---------------------------------------------------------------------------
// Event listeners
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {

  /* ── Join screen ── */
  el("btn-create").addEventListener("click", async () => {
    const name = el("input-name").value.trim();
    if (!name) { showError("Enter your name first."); return; }
    try {
      const { room_code, player_id } = await createRoom(name);
      state.myPlayerId = player_id;
      state.roomCode   = room_code;
      saveSession(room_code, player_id);
      connect(room_code, player_id);
    } catch (e) {
      showError(e.message);
    }
  });

  el("btn-join").addEventListener("click", async () => {
    const name = el("input-name").value.trim();
    const code = el("input-room-code").value.trim().toUpperCase();
    if (!name) { showError("Enter your name first."); return; }
    if (!code) { showError("Enter the room code."); return; }
    try {
      const { player_id } = await joinRoom(code, name);
      state.myPlayerId = player_id;
      state.roomCode   = code;
      saveSession(code, player_id);
      connect(code, player_id);
    } catch (e) {
      showError(e.message);
    }
  });

  // Allow Enter key on room code input
  el("input-room-code").addEventListener("keydown", (e) => {
    if (e.key === "Enter") el("btn-join").click();
  });

  el("input-name").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const code = el("input-room-code").value.trim();
      if (code) el("btn-join").click(); else el("btn-create").click();
    }
  });

  /* ── Lobby host controls ── */
  el("btn-auto-assign").addEventListener("click", () => sendAction("auto_assign"));
  el("btn-start-game").addEventListener("click",  () => sendAction("start_game"));

  /* ── Giving Hint ── */
  el("btn-submit-hint").addEventListener("click", () => {
    const hint = el("input-hint").value.trim();
    if (!hint) return;
    sendAction("submit_hint", { hint });
    el("input-hint").value = "";
    dialDragActive = false; // reset for next guessing phase
  });

  el("input-hint").addEventListener("keydown", (e) => {
    if (e.key === "Enter") el("btn-submit-hint").click();
  });

  /* ── Guessing ── */
  el("btn-submit-guess").addEventListener("click", () => {
    sendAction("submit_guess", { position: state.currentGuessPosition });
    dialDragActive = false;
  });

  /* ── Opposing Guess ── */
  el("btn-guess-left").addEventListener("click",  () => sendAction("opposing_guess", { direction: "left"  }));
  el("btn-guess-right").addEventListener("click", () => sendAction("opposing_guess", { direction: "right" }));

  /* ── Reveal → next round ── */
  el("btn-next-round").addEventListener("click", () => sendAction("next_round"));

  /* ── Game Over ── */
  el("btn-play-again").addEventListener("click", () => sendAction("reset_game"));

  /* ── Lobby: team name inputs (host only, fire on change/blur) ── */
  function sendTeamName(side, inputId) {
    const name = el(inputId)?.value.trim();
    if (name) sendAction("set_team_name", { side, name });
  }
  el("input-left-name").addEventListener("change",  () => sendTeamName("left",  "input-left-name"));
  el("input-right-name").addEventListener("change", () => sendTeamName("right", "input-right-name"));
  el("input-left-name").addEventListener("blur",    () => sendTeamName("left",  "input-left-name"));
  el("input-right-name").addEventListener("blur",   () => sendTeamName("right", "input-right-name"));

  /* ── Auto-reconnect on refresh ── */
  const savedRoom = sessionStorage.getItem("wl_room");
  const savedPid  = sessionStorage.getItem("wl_pid");
  if (savedRoom && savedPid) {
    state.myPlayerId = savedPid;
    state.roomCode   = savedRoom;
    connect(savedRoom, savedPid);
  }
});
