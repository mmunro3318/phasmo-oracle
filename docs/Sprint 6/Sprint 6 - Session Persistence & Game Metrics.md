**Goal:** Every investigation is persisted to a local SQLite database. Oracle can record ghost events, deaths, and post-game confirmations via voice. A `--stats` flag surfaces cumulative performance metrics — success rate, speed trends, per-ghost and per-difficulty breakdowns.

**Builds on:** Sprint 5's complete voice loop, session logging, and terminal UI.

**No new LangGraph changes.** This sprint is a persistence and tooling layer. The graph topology, deduction engine, and voice pipeline are unchanged.

**Exit criteria:**

- Every investigation creates a row in `sessions` and child rows in `evidence_events`, `ghost_events`, `deaths`, `candidate_snapshots`
- "oracle, the ghost hunted" → `record_ghost_event` called, event written to DB
- "oracle, I died" → `record_death` called, event written to DB
- "oracle, it was a Wraith" → `confirm_true_ghost` called, session closed with `oracle_correct` flag
- `python main.py --stats` renders a Rich stats table and exits
- `oracle_correct` is computed automatically (Oracle's final guess vs true ghost)
- All Sprint 1–5 tests still pass

---

## Data Model

SQLite lives at `data/oracle_stats.db`. Five tables. All timestamps are Unix floats. `elapsed_s` is seconds since session start — computed at write time, no joins required for time analytics.

```
sessions
  id, started_at, ended_at, difficulty, players (JSON), map,
  true_ghost, oracle_guess, oracle_correct, outcome, turn_count, death_count

evidence_events
  id, session_id, ts, elapsed_s, evidence_id, status, speaker

ghost_events
  id, session_id, ts, elapsed_s, event_type, notes, speaker

deaths
  id, session_id, ts, elapsed_s, player, cause

candidate_snapshots
  id, session_id, ts, turn_id, candidates (JSON), candidate_count, trigger_event
```

### What gets tracked automatically vs. by voice

|Event|How it enters the DB|
|---|---|
|Session start|`init_investigation` tool call|
|Evidence confirmed/ruled out|`record_evidence` tool call (already exists)|
|Candidate narrowing|`post_tool_check` in graph — `candidate_snapshots` row written|
|Ghost hunt / interaction|`record_ghost_event` tool ← **new**|
|Player death|`record_death` tool ← **new**|
|True ghost confirmation|`confirm_true_ghost` tool ← **new**|
|Session end|On quit / Ctrl+C, `close_session()` called in `main.py`|

Evidence events and candidate snapshots are automatic — no extra voice commands needed. Ghost events, deaths, and the final confirmation require a voice trigger. **We will likely need to distinguish between Ghost "events" (ghost manifests itself) and "hunts" (ghost manifests and tries to kill the player)**

---

## New Voice Commands

These are the natural-language phrases that map to the three new tools. phi4-mini should route these reliably given clear tool docstrings.

```
"oracle, the ghost just hunted"           → record_ghost_event("hunt")
"oracle, we had a ghost interaction"      → record_ghost_event("interaction")
"oracle, the ghost manifested"            → record_ghost_event("manifestation")
"oracle, we spotted an orb"              → record_ghost_event("orb_sighting")

"oracle, I died"                          → record_death("Mike")
"oracle, Kayden died"                     → record_death("Kayden")
"oracle, mark a death"                    → record_death(player from state["speaker"])

"oracle, it was a Wraith"                → confirm_true_ghost("Wraith")
"oracle, confirm the ghost was a Banshee" → confirm_true_ghost("Banshee")
"oracle, we got it wrong, it was a Demon" → confirm_true_ghost("Demon")
```

---

## Session Lifecycle

```
init_investigation()
    → INSERT sessions row (started_at = now, outcome = "in_progress")
    → state["session_start_time"] = now

record_evidence() [existing, augmented]
    → INSERT evidence_events row
    → INSERT candidate_snapshots row

record_ghost_event() [new]
    → INSERT ghost_events row

record_death() [new]
    → INSERT deaths row
    → UPDATE sessions SET death_count = death_count + 1

confirm_true_ghost() [new]
    → UPDATE sessions SET true_ghost = ?, oracle_guess = ?,
                          oracle_correct = ?, outcome = "identified", ended_at = now

close_session() [called from main.py on exit]
    → UPDATE sessions SET ended_at = now, outcome = "abandoned"
      WHERE ended_at IS NULL AND id = current_session_id
    → Optionally prompt: "What was the true ghost? (Enter to skip)"
```

---

## Implementation Order

```
1. db/database.py        ← SQLite connection, schema creation, CRUD helpers
2. db/queries.py         ← analytics queries (success rate, speed metrics, etc.)
3. graph/state.py        ← add session_start_time, current_session_id
4. graph/tools.py        ← augment record_evidence; add record_ghost_event,
                            record_death, confirm_true_ghost
5. graph/nodes.py        ← write candidate_snapshot after post_tool_check
6. graph/session_log.py  ← route key events to db/database.py alongside JSONL
7. ui/display.py         ← add session summary panel (deaths, ghost events, elapsed)
8. ui/stats.py           ← NEW: Rich stats renderer for --stats flag
9. main.py               ← close_session() on exit, --stats flag, end-of-session prompt
10. tests/test_db.py     ← schema creation, CRUD, analytics queries
```

---

## Scaffold Code

### `db/database.py`

```python
"""
SQLite persistence layer for Oracle game metrics.
One database file: data/oracle_stats.db
All timestamps are Unix floats. elapsed_s is seconds since session start.
"""

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_PATH = Path("data/oracle_stats.db")
_SCHEMA  = """
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT    PRIMARY KEY,
    started_at      REAL    NOT NULL,
    ended_at        REAL,
    difficulty      TEXT    NOT NULL DEFAULT 'professional',
    players         TEXT    NOT NULL DEFAULT '["Mike"]',
    map             TEXT,
    true_ghost      TEXT,
    oracle_guess    TEXT,
    oracle_correct  INTEGER,
    outcome         TEXT    NOT NULL DEFAULT 'in_progress',
    turn_count      INTEGER NOT NULL DEFAULT 0,
    death_count     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS evidence_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL REFERENCES sessions(id),
    ts          REAL    NOT NULL,
    elapsed_s   REAL    NOT NULL,
    evidence_id TEXT    NOT NULL,
    status      TEXT    NOT NULL,
    speaker     TEXT
);

CREATE TABLE IF NOT EXISTS ghost_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL REFERENCES sessions(id),
    ts          REAL    NOT NULL,
    elapsed_s   REAL    NOT NULL,
    event_type  TEXT    NOT NULL,
    notes       TEXT,
    speaker     TEXT
);

CREATE TABLE IF NOT EXISTS deaths (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL REFERENCES sessions(id),
    ts          REAL    NOT NULL,
    elapsed_s   REAL    NOT NULL,
    player      TEXT    NOT NULL,
    cause       TEXT
);

CREATE TABLE IF NOT EXISTS candidate_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL REFERENCES sessions(id),
    ts              REAL    NOT NULL,
    turn_id         INTEGER,
    candidates      TEXT    NOT NULL,
    candidate_count INTEGER NOT NULL,
    trigger_event   TEXT
);
"""


def init_db(path: str | Path | None = None) -> None:
    """Create the database file and tables if they don't exist."""
    global _DB_PATH
    if path:
        _DB_PATH = Path(path)
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(_SCHEMA)
    logger.info(f"Database ready: {_DB_PATH}")


@contextmanager
def _connect():
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Session CRUD ──────────────────────────────────────────────────────────────

def create_session(
    session_id: str,
    difficulty: str,
    players: list[str],
    map_name: str | None = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO sessions (id, started_at, difficulty, players, map)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, time.time(), difficulty, json.dumps(players), map_name),
        )
    logger.info(f"DB: session created — {session_id}")


def close_session(
    session_id: str,
    outcome: str = "abandoned",
    true_ghost: str | None = None,
    oracle_guess: str | None = None,
) -> None:
    oracle_correct = None
    if true_ghost and oracle_guess:
        oracle_correct = 1 if true_ghost.lower() == oracle_guess.lower() else 0

    with _connect() as conn:
        conn.execute(
            """UPDATE sessions
               SET ended_at = ?, outcome = ?, true_ghost = ?,
                   oracle_guess = ?, oracle_correct = ?
               WHERE id = ? AND ended_at IS NULL""",
            (time.time(), outcome, true_ghost, oracle_guess, oracle_correct, session_id),
        )
    logger.info(
        f"DB: session closed — {session_id} | outcome={outcome} | "
        f"correct={oracle_correct}"
    )


def increment_turn_count(session_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE sessions SET turn_count = turn_count + 1 WHERE id = ?",
            (session_id,),
        )


# ── Event CRUD ────────────────────────────────────────────────────────────────

def write_evidence_event(
    session_id: str,
    session_start: float,
    evidence_id: str,
    status: str,
    speaker: str | None = None,
) -> None:
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO evidence_events
               (session_id, ts, elapsed_s, evidence_id, status, speaker)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, now, now - session_start, evidence_id, status, speaker),
        )


def write_ghost_event(
    session_id: str,
    session_start: float,
    event_type: str,
    notes: str | None = None,
    speaker: str | None = None,
) -> None:
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO ghost_events
               (session_id, ts, elapsed_s, event_type, notes, speaker)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, now, now - session_start, event_type, notes, speaker),
        )


def write_death(
    session_id: str,
    session_start: float,
    player: str,
    cause: str | None = None,
) -> None:
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO deaths
               (session_id, ts, elapsed_s, player, cause)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, now, now - session_start, player, cause),
        )
        conn.execute(
            "UPDATE sessions SET death_count = death_count + 1 WHERE id = ?",
            (session_id,),
        )


def write_candidate_snapshot(
    session_id: str,
    turn_id: int,
    candidates: list[str],
    trigger: str | None = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO candidate_snapshots
               (session_id, ts, turn_id, candidates, candidate_count, trigger_event)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, time.time(), turn_id,
             json.dumps(candidates), len(candidates), trigger),
        )


def confirm_ghost(
    session_id: str,
    true_ghost: str,
    oracle_guess: str | None,
) -> int | None:
    """Set true_ghost and compute oracle_correct. Returns 1, 0, or None."""
    oracle_correct = None
    if oracle_guess:
        oracle_correct = 1 if true_ghost.lower() == oracle_guess.lower() else 0
    with _connect() as conn:
        conn.execute(
            """UPDATE sessions
               SET true_ghost = ?, oracle_guess = ?, oracle_correct = ?,
                   outcome = 'identified', ended_at = COALESCE(ended_at, ?)
               WHERE id = ?""",
            (true_ghost, oracle_guess, oracle_correct, time.time(), session_id),
        )
    return oracle_correct
```

---

### `db/queries.py`

```python
"""
Analytics queries over the Oracle stats database.
All functions return plain Python dicts/lists — no SQLite Row objects.
"""

import json
import sqlite3
from pathlib import Path

from db.database import _DB_PATH, _connect


def session_summary(session_id: str) -> dict | None:
    """Full stats for a single session."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None

        evidence = conn.execute(
            """SELECT evidence_id, status, elapsed_s, speaker
               FROM evidence_events WHERE session_id = ?
               ORDER BY ts""",
            (session_id,),
        ).fetchall()

        ghost_evs = conn.execute(
            """SELECT event_type, elapsed_s, notes
               FROM ghost_events WHERE session_id = ?
               ORDER BY ts""",
            (session_id,),
        ).fetchall()

        deaths_ = conn.execute(
            """SELECT player, elapsed_s, cause
               FROM deaths WHERE session_id = ?
               ORDER BY ts""",
            (session_id,),
        ).fetchall()

    duration = None
    if row["ended_at"] and row["started_at"]:
        duration = row["ended_at"] - row["started_at"]

    return {
        "session_id":     row["id"],
        "started_at":     row["started_at"],
        "difficulty":     row["difficulty"],
        "players":        json.loads(row["players"] or "[]"),
        "true_ghost":     row["true_ghost"],
        "oracle_guess":   row["oracle_guess"],
        "oracle_correct": row["oracle_correct"],
        "outcome":        row["outcome"],
        "duration_s":     duration,
        "turn_count":     row["turn_count"],
        "death_count":    row["death_count"],
        "evidence":       [dict(e) for e in evidence],
        "ghost_events":   [dict(g) for g in ghost_evs],
        "deaths":         [dict(d) for d in deaths_],
    }


def overall_stats() -> dict:
    """Aggregate stats across all completed sessions."""
    with _connect() as conn:
        row = conn.execute(
            """SELECT
                COUNT(*)                                          AS total,
                SUM(CASE WHEN oracle_correct = 1 THEN 1 ELSE 0 END) AS correct,
                SUM(CASE WHEN oracle_correct = 0 THEN 1 ELSE 0 END) AS incorrect,
                AVG(CASE WHEN ended_at IS NOT NULL
                         THEN ended_at - started_at END)         AS avg_duration_s,
                AVG(death_count)                                 AS avg_deaths
               FROM sessions
               WHERE outcome != 'in_progress'
                 AND true_ghost IS NOT NULL""",
        ).fetchone()

        by_difficulty = conn.execute(
            """SELECT difficulty,
                      COUNT(*) AS total,
                      SUM(CASE WHEN oracle_correct = 1 THEN 1 ELSE 0 END) AS correct
               FROM sessions
               WHERE outcome != 'in_progress' AND true_ghost IS NOT NULL
               GROUP BY difficulty
               ORDER BY difficulty""",
        ).fetchall()

        by_ghost = conn.execute(
            """SELECT true_ghost,
                      COUNT(*) AS total,
                      SUM(CASE WHEN oracle_correct = 1 THEN 1 ELSE 0 END) AS correct
               FROM sessions
               WHERE outcome != 'in_progress' AND true_ghost IS NOT NULL
               GROUP BY true_ghost
               ORDER BY total DESC""",
        ).fetchall()

        avg_evidence_speed = conn.execute(
            """SELECT
                AVG(first_ev.elapsed_s) AS avg_first_evidence_s,
                AVG(CASE WHEN ev_count.n >= 2 THEN second_ev.elapsed_s - first_ev.elapsed_s END)
                    AS avg_between_evidence_s
               FROM (
                   SELECT session_id, MIN(elapsed_s) AS elapsed_s
                   FROM evidence_events WHERE status = 'confirmed'
                   GROUP BY session_id
               ) first_ev
               LEFT JOIN (
                   SELECT session_id, MIN(elapsed_s) AS elapsed_s
                   FROM evidence_events WHERE status = 'confirmed'
                     AND evidence_id NOT IN (
                         SELECT evidence_id FROM evidence_events e2
                         WHERE e2.session_id = evidence_events.session_id
                           AND e2.elapsed_s = (
                               SELECT MIN(elapsed_s) FROM evidence_events e3
                               WHERE e3.session_id = e2.session_id
                                 AND e3.status = 'confirmed'
                           )
                     )
                   GROUP BY session_id
               ) second_ev ON first_ev.session_id = second_ev.session_id
               LEFT JOIN (
                   SELECT session_id, COUNT(*) AS n
                   FROM evidence_events WHERE status = 'confirmed'
                   GROUP BY session_id
               ) ev_count ON first_ev.session_id = ev_count.session_id""",
        ).fetchone()

    total     = row["total"] or 0
    correct   = row["correct"] or 0
    success_rate = (correct / total * 100) if total > 0 else None

    return {
        "total_sessions":        total,
        "correct":               correct,
        "incorrect":             row["incorrect"] or 0,
        "success_rate_pct":      round(success_rate, 1) if success_rate else None,
        "avg_duration_s":        row["avg_duration_s"],
        "avg_deaths":            row["avg_deaths"],
        "avg_first_evidence_s":  (avg_evidence_speed or {}).get("avg_first_evidence_s"),
        "avg_between_evidence_s":(avg_evidence_speed or {}).get("avg_between_evidence_s"),
        "by_difficulty":         [dict(r) for r in by_difficulty],
        "by_ghost":              [dict(r) for r in by_ghost],
    }


def recent_sessions(limit: int = 10) -> list[dict]:
    """Last N completed sessions, most recent first."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, started_at, difficulty, true_ghost, oracle_guess,
                      oracle_correct, outcome,
                      (ended_at - started_at) AS duration_s,
                      death_count
               FROM sessions
               WHERE outcome != 'in_progress'
               ORDER BY started_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def ghost_event_frequency(session_id: str) -> dict[str, int]:
    """Count of each ghost event type in a session."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT event_type, COUNT(*) AS n
               FROM ghost_events WHERE session_id = ?
               GROUP BY event_type""",
            (session_id,),
        ).fetchall()
    return {r["event_type"]: r["n"] for r in rows}
```

---

### `graph/state.py` (updated)

```python
from typing import TypedDict, Literal, Annotated
import operator

EvidenceID = Literal[
    "emf_5", "dots", "uv", "freezing", "orb", "writing", "spirit_box"
]
Difficulty = Literal[
    "amateur", "intermediate", "professional", "nightmare", "insanity"
]

class OracleState(TypedDict):
    # Input
    user_text: str
    speaker: str
    difficulty: Difficulty

    # Evidence tracking
    evidence_confirmed: list[EvidenceID]
    evidence_ruled_out: list[EvidenceID]
    behavioral_observations: list[str]

    # Deduction
    eliminated_ghosts: list[str]
    candidates: list[str]

    # Auto-trigger tracking
    prev_candidate_count: int
    turn_id: int

    # Sprint 6: session persistence
    session_id: str              # "20260330_142000"
    session_start_time: float    # Unix timestamp of init_investigation call
    ghost_events: list[str]      # in-memory list of event_type strings (for display)
    deaths: list[str]            # in-memory list of player names (for display)

    # Output
    oracle_response: str | None
    messages: Annotated[list, operator.add]
```

---

### `graph/tools.py` (additions)

Add these three tools below the existing five. Wire them into `ORACLE_TOOLS`.

```python
_GHOST_EVENT_TYPES = {
    "hunt", "interaction", "manifestation", "orb_sighting",
    "poltergeist_throw", "ghost_writing_spotted", "dots_spotted",
    "freezing_temps_spotted", "emf_spike", "spirit_box_response",
    "footsteps", "cursed_item_activated", "other",
}

@tool
def record_ghost_event(event_type: str, notes: str = "") -> str:
    """
    Log a ghost event observed during the investigation.
    event_type should be one of: hunt, interaction, manifestation, orb_sighting,
    poltergeist_throw, ghost_writing_spotted, dots_spotted, freezing_temps_spotted,
    emf_spike, spirit_box_response, footsteps, cursed_item_activated, other.
    notes is optional free-text context.
    """
    # Normalise loose event_type values
    normalised = event_type.lower().replace(" ", "_")
    if normalised not in _GHOST_EVENT_TYPES:
        normalised = "other"

    _state.setdefault("ghost_events", []).append(normalised)

    session_id    = _state.get("session_id")
    session_start = _state.get("session_start_time", 0.0)
    speaker       = _state.get("speaker")

    if session_id:
        from db.database import write_ghost_event
        write_ghost_event(session_id, session_start, normalised, notes or None, speaker)

    return f"Ghost event logged: {normalised}." + (f" Notes: {notes}" if notes else "")


@tool
def record_death(player: str = "") -> str:
    """
    Log a player death during the investigation.
    player: the player who died (e.g. 'Mike' or 'Kayden').
    If not specified, defaults to the current speaker.
    """
    if not player:
        player = _state.get("speaker", "unknown")

    _state.setdefault("deaths", []).append(player)

    session_id    = _state.get("session_id")
    session_start = _state.get("session_start_time", 0.0)

    if session_id:
        from db.database import write_death
        write_death(session_id, session_start, player)

    death_count = len(_state.get("deaths", []))
    return f"{player} death recorded. Total deaths this session: {death_count}."


@tool
def confirm_true_ghost(ghost_name: str) -> str:
    """
    Record the true ghost type at the end of an investigation.
    Call this after the post-game results screen reveals the actual ghost.
    This closes the session and records whether Oracle's identification was correct.
    ghost_name: the actual ghost type (e.g. 'Wraith', 'Banshee', etc.)
    """
    from graph.deduction import get_ghost
    ghost = get_ghost(ghost_name)
    if not ghost:
        from graph.deduction import load_db
        all_names = [g["name"] for g in load_db()["ghosts"]]
        return (
            f"Ghost '{ghost_name}' not recognised. "
            f"Known ghosts: {', '.join(all_names)}"
        )

    true_name     = ghost["name"]
    session_id    = _state.get("session_id")
    candidates    = _state.get("candidates", [])
    oracle_guess  = candidates[0] if len(candidates) == 1 else None

    correct: int | None = None
    if session_id:
        from db.database import confirm_ghost
        correct = confirm_ghost(session_id, true_name, oracle_guess)

    if correct == 1:
        verdict = "Oracle was correct."
    elif correct == 0:
        verdict = f"Oracle guessed {oracle_guess} — that was wrong."
    else:
        verdict = "No Oracle guess on record to compare."

    return f"True ghost confirmed: {true_name}. {verdict}"


# Update the exported list
ORACLE_TOOLS = [
    init_investigation,
    record_evidence,
    record_behavioral_event,
    get_investigation_state,
    query_ghost_database,
    record_ghost_event,    # Sprint 6
    record_death,          # Sprint 6
    confirm_true_ghost,    # Sprint 6
]
```

---

### `graph/tools.py` — augment `init_investigation` (diff only)

Add DB session creation to the existing tool:

```python
@tool
def init_investigation(difficulty: str) -> str:
    """Start a new investigation..."""
    import time
    valid = {"amateur", "intermediate", "professional", "nightmare", "insanity"}
    if difficulty not in valid:
        difficulty = "professional"

    _state["difficulty"]      = difficulty
    _state["evidence_confirmed"]  = []
    _state["evidence_ruled_out"]  = []
    _state["behavioral_observations"] = []
    _state["eliminated_ghosts"] = []
    _state["candidates"]      = all_ghost_names()
    _state["ghost_events"]    = []           # Sprint 6
    _state["deaths"]          = []           # Sprint 6
    _state["session_start_time"] = time.time()  # Sprint 6

    # Sprint 6: persist to DB
    session_id = _state.get("session_id")
    if session_id:
        from db.database import create_session
        players = [_state.get("speaker", "Mike")]
        create_session(session_id, difficulty, players)

    n = len(_state["candidates"])
    return f"New investigation started on {difficulty}. {n} ghost candidates active."
```

---

### `graph/tools.py` — augment `record_evidence` (diff only)

Write to DB after existing deduction logic:

```python
    # [existing deduction logic here — no changes]

    # Sprint 6: persist evidence event
    session_id    = _state.get("session_id")
    session_start = _state.get("session_start_time", 0.0)
    if session_id:
        from db.database import write_evidence_event
        write_evidence_event(
            session_id, session_start, evidence_id, status,
            _state.get("speaker"),
        )

    n = len(_state["candidates"])
    names = ", ".join(_state["candidates"]) if n <= 8 else f"{n} ghosts"
    return (
        f"{n} candidate(s) remain after recording {evidence_id} as {status}: {names}"
    )
```

---

### `graph/nodes.py` — write candidate snapshot after `identify_node` and `commentary_node`

Add this call at the end of both nodes, before returning:

```python
    # Sprint 6: persist candidate snapshot
    session_id = state.get("session_id")
    if session_id:
        from db.database import write_candidate_snapshot
        write_candidate_snapshot(
            session_id,
            turn_id=state.get("turn_id", 0),
            candidates=state.get("candidates", []),
            trigger="auto_identify" if ...,  # "auto_identify" or "auto_commentary"
        )
```

---

### `ui/stats.py`

```python
"""
Rich stats renderer for --stats flag.
Queries db/queries.py and renders a terminal report.
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
import datetime

console = Console()


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s"


def _fmt_pct(correct: int, total: int) -> str:
    if total == 0:
        return "—"
    return f"{correct / total * 100:.1f}%"


def _fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "—"
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def render_stats() -> None:
    from db.queries import overall_stats, recent_sessions

    stats   = overall_stats()
    recent  = recent_sessions(limit=10)

    # ── Header panel ─────────────────────────────────────────────────────────
    total    = stats["total_sessions"]
    correct  = stats["correct"]
    pct      = f"{stats['success_rate_pct']}%" if stats["success_rate_pct"] else "—"
    avg_dur  = _fmt_duration(stats["avg_duration_s"])
    avg_dead = f"{stats['avg_deaths']:.1f}" if stats["avg_deaths"] else "—"
    t1_s     = _fmt_duration(stats["avg_first_evidence_s"])
    t_btw_s  = _fmt_duration(stats["avg_between_evidence_s"])

    summary = Table(box=None, show_header=False, padding=(0, 2))
    summary.add_column("key",   style="dim")
    summary.add_column("value", style="bold cyan")
    summary.add_row("Total sessions",           str(total))
    summary.add_row("Overall success rate",     pct)
    summary.add_row("Avg session duration",     avg_dur)
    summary.add_row("Avg deaths per session",   avg_dead)
    summary.add_row("Avg time to 1st evidence", t1_s)
    summary.add_row("Avg time between evidence",t_btw_s)
    console.print(Panel(summary, title="[bold cyan]Oracle Statistics[/bold cyan]",
                         box=box.ROUNDED))

    # ── By difficulty ─────────────────────────────────────────────────────────
    if stats["by_difficulty"]:
        dt = Table(title="By Difficulty", box=box.SIMPLE_HEAD)
        dt.add_column("Difficulty", style="bold")
        dt.add_column("Sessions",   justify="right")
        dt.add_column("Correct",    justify="right")
        dt.add_column("Success",    justify="right", style="green")
        for row in stats["by_difficulty"]:
            dt.add_row(
                row["difficulty"].capitalize(),
                str(row["total"]),
                str(row["correct"]),
                _fmt_pct(row["correct"], row["total"]),
            )
        console.print(dt)

    # ── By ghost ─────────────────────────────────────────────────────────────
    if stats["by_ghost"]:
        gt = Table(title="By Ghost Type", box=box.SIMPLE_HEAD)
        gt.add_column("Ghost",    style="bold")
        gt.add_column("Seen",     justify="right")
        gt.add_column("Correct",  justify="right")
        gt.add_column("Success",  justify="right")
        for row in stats["by_ghost"]:
            pct_str = _fmt_pct(row["correct"], row["total"])
            style   = "green" if row["correct"] == row["total"] else \
                      "yellow" if row["correct"] > 0 else "red"
            gt.add_row(
                row["true_ghost"],
                str(row["total"]),
                str(row["correct"]),
                f"[{style}]{pct_str}[/{style}]",
            )
        console.print(gt)

    # ── Recent sessions ───────────────────────────────────────────────────────
    if recent:
        rt = Table(title="Recent Sessions", box=box.SIMPLE_HEAD)
        rt.add_column("Date",        style="dim")
        rt.add_column("Difficulty")
        rt.add_column("True Ghost",  style="bold")
        rt.add_column("Oracle Guess")
        rt.add_column("Result",      justify="center")
        rt.add_column("Duration",    justify="right")
        rt.add_column("Deaths",      justify="center")
        for row in recent:
            if row["oracle_correct"] == 1:
                result = "[green]✓[/green]"
            elif row["oracle_correct"] == 0:
                result = "[red]✗[/red]"
            else:
                result = "[dim]?[/dim]"
            rt.add_row(
                _fmt_ts(row["started_at"]),
                (row["difficulty"] or "").capitalize(),
                row["true_ghost"] or "—",
                row["oracle_guess"] or "—",
                result,
                _fmt_duration(row["duration_s"]),
                str(row["death_count"]),
            )
        console.print(rt)
```

---

### `main.py` — additions (diff only)

```python
# 1. Add to make_initial_state():
"session_id":         session_id,   # passed in from main()
"session_start_time": 0.0,
"ghost_events":       [],
"deaths":             [],

# 2. Add init_db() call in main() before session setup:
from db.database import init_db
init_db()

# 3. Add --stats flag:
parser.add_argument("--stats", action="store_true", help="Show game statistics and exit")

# 4. Handle --stats before session start:
if args.stats:
    from ui.stats import render_stats
    render_stats()
    return

# 5. Add close_session() call in finally blocks of both loops:
from db.database import close_session as db_close_session
db_close_session(session_id, outcome="abandoned")

# 6. Add end-of-session confirmation prompt in run_text_loop():
def _prompt_true_ghost(state: dict) -> None:
    """Ask the player what the true ghost was after session ends."""
    try:
        answer = input(
            "\nWhat was the true ghost? "
            "(press Enter to skip, or type ghost name): "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return
    if answer:
        response = run_turn(state, f"confirm true ghost {answer}")
        if response:
            print(f"Oracle: {response}")

# Call _prompt_true_ghost(state) in run_text_loop() after the main while loop exits.
# In voice mode, the player uses the voice command "oracle, it was a Wraith" instead.
```

---

### `tests/test_db.py`

```python
"""Tests for the database layer and analytics queries."""

import json
import time
import tempfile
from pathlib import Path
import pytest


@pytest.fixture
def tmp_db(tmp_path):
    """Each test gets a fresh database."""
    import db.database as db_mod
    original = db_mod._DB_PATH
    db_mod._DB_PATH = tmp_path / "test_oracle.db"
    db_mod.init_db()
    yield db_mod._DB_PATH
    db_mod._DB_PATH = original


# ── Schema ────────────────────────────────────────────────────────────────────

def test_init_creates_all_tables(tmp_db):
    import sqlite3
    conn = sqlite3.connect(tmp_db)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert tables == {
        "sessions", "evidence_events", "ghost_events", "deaths", "candidate_snapshots"
    }
    conn.close()


# ── Session CRUD ──────────────────────────────────────────────────────────────

def test_create_and_close_session(tmp_db):
    from db.database import create_session, close_session, _connect
    create_session("s001", "professional", ["Mike"])
    close_session("s001", outcome="identified", true_ghost="Wraith", oracle_guess="Wraith")
    with _connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = 's001'").fetchone()
    assert row["true_ghost"] == "Wraith"
    assert row["oracle_correct"] == 1
    assert row["outcome"] == "identified"


def test_close_session_marks_incorrect(tmp_db):
    from db.database import create_session, close_session, _connect
    create_session("s002", "professional", ["Mike"])
    close_session("s002", true_ghost="Banshee", oracle_guess="Wraith")
    with _connect() as conn:
        row = conn.execute("SELECT oracle_correct FROM sessions WHERE id = 's002'").fetchone()
    assert row["oracle_correct"] == 0


def test_close_session_null_when_no_guess(tmp_db):
    from db.database import create_session, close_session, _connect
    create_session("s003", "professional", ["Mike"])
    close_session("s003", true_ghost="Banshee", oracle_guess=None)
    with _connect() as conn:
        row = conn.execute("SELECT oracle_correct FROM sessions WHERE id = 's003'").fetchone()
    assert row["oracle_correct"] is None


# ── Event CRUD ────────────────────────────────────────────────────────────────

def test_write_evidence_event(tmp_db):
    from db.database import create_session, write_evidence_event, _connect
    create_session("s004", "professional", ["Mike"])
    write_evidence_event("s004", time.time() - 10, "emf_5", "confirmed", "Mike")
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM evidence_events WHERE session_id = 's004'"
        ).fetchone()
    assert row["evidence_id"] == "emf_5"
    assert row["elapsed_s"] > 0


def test_write_death_increments_count(tmp_db):
    from db.database import create_session, write_death, _connect
    create_session("s005", "nightmare", ["Mike", "Kayden"])
    start = time.time() - 60
    write_death("s005", start, "Mike")
    write_death("s005", start, "Kayden")
    with _connect() as conn:
        row = conn.execute(
            "SELECT death_count FROM sessions WHERE id = 's005'"
        ).fetchone()
    assert row["death_count"] == 2


def test_write_ghost_event(tmp_db):
    from db.database import create_session, write_ghost_event, _connect
    create_session("s006", "professional", ["Mike"])
    write_ghost_event("s006", time.time() - 30, "hunt", "Ghost hunted from kitchen")
    with _connect() as conn:
        row = conn.execute(
            "SELECT event_type, notes FROM ghost_events WHERE session_id = 's006'"
        ).fetchone()
    assert row["event_type"] == "hunt"
    assert "kitchen" in row["notes"]


# ── Analytics queries ─────────────────────────────────────────────────────────

def _seed_sessions(tmp_db, records):
    """Insert pre-baked sessions directly for analytics tests."""
    import sqlite3, time as t
    conn = sqlite3.connect(tmp_db)
    for r in records:
        conn.execute(
            """INSERT INTO sessions
               (id, started_at, ended_at, difficulty, players, true_ghost,
                oracle_guess, oracle_correct, outcome, death_count)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            r,
        )
    conn.commit()
    conn.close()


def test_overall_stats_success_rate(tmp_db):
    from db.queries import overall_stats
    now = time.time()
    _seed_sessions(tmp_db, [
        ("a", now-600, now-300, "professional", '["Mike"]',
         "Wraith",  "Wraith",  1, "identified", 0),
        ("b", now-300, now-120, "professional", '["Mike"]',
         "Banshee", "Wraith",  0, "identified", 1),
        ("c", now-200, now-60,  "professional", '["Mike"]',
         "Demon",   "Demon",   1, "identified", 0),
    ])
    stats = overall_stats()
    assert stats["total_sessions"] == 3
    assert stats["correct"] == 2
    assert abs(stats["success_rate_pct"] - 66.7) < 0.1


def test_recent_sessions_ordering(tmp_db):
    from db.queries import recent_sessions
    now = time.time()
    _seed_sessions(tmp_db, [
        ("old", now-1000, now-900, "professional", '["Mike"]',
         "Wraith",  "Wraith",  1, "identified", 0),
        ("new", now-100,  now-50,  "professional", '["Mike"]',
         "Banshee", "Banshee", 1, "identified", 0),
    ])
    recent = recent_sessions(limit=5)
    assert recent[0]["id"] == "new"
    assert recent[1]["id"] == "old"


def test_ghost_event_frequency(tmp_db):
    from db.database import create_session, write_ghost_event
    from db.queries import ghost_event_frequency
    create_session("s007", "professional", ["Mike"])
    start = time.time() - 120
    write_ghost_event("s007", start, "hunt")
    write_ghost_event("s007", start, "hunt")
    write_ghost_event("s007", start, "interaction")
    freq = ghost_event_frequency("s007")
    assert freq["hunt"] == 2
    assert freq["interaction"] == 1
```

---

## Installation (Sprint 6 additions)

```bash
# No new pip packages required — sqlite3 is standard library.

# Create data directory (gitignore it)
mkdir -p data
echo "data/" >> .gitignore

# Run tests
pytest tests/ -v

# Normal session (DB created automatically on first run)
python main.py

# View stats
python main.py --stats

# Confirm ghost by voice during/after investigation:
# "oracle, it was a Wraith"

# Or by text in --text mode:
# You: confirm true ghost Wraith
```

---

## Example Stats Output

```
╭─ Oracle Statistics ───────────────────────────────────╮
│  Total sessions              47                        │
│  Overall success rate        78.7%                     │
│  Avg session duration        7m 42s                    │
│  Avg deaths per session      0.9                       │
│  Avg time to 1st evidence    1m 12s                    │
│  Avg time between evidence   2m 08s                    │
╰────────────────────────────────────────────────────────╯

 By Difficulty
 Difficulty      Sessions   Correct   Success
 Professional    32         27        84.4%
 Nightmare       15         10        66.7%

 By Ghost Type
 Ghost           Seen   Correct   Success
 Wraith          8      7         87.5%
 Banshee         6      5         83.3%
 Revenant        5      5         100.0%
 Demon           4      2         50.0%
 ...

 Recent Sessions
 Date                Difficulty      True Ghost   Oracle Guess   Result   Duration   Deaths
 2026-03-30 14:20   Professional   Wraith        Wraith         ✓        5m 12s     0
 2026-03-29 21:15   Nightmare      Banshee       Banshee        ✓        8m 34s     2
 2026-03-28 18:45   Professional   Demon         Wraith         ✗        6m 10s     1
```

---

## Task Board

### Backlog

|ID|Task|Notes|
|---|---|---|
|S6-01|Create `db/` package (`__init__.py`)|Empty init|
|S6-02|Create `db/database.py`|Schema, `init_db()`, all CRUD helpers|
|S6-03|Create `db/queries.py`|`overall_stats()`, `recent_sessions()`, `session_summary()`, `ghost_event_frequency()`|
|S6-04|Update `graph/state.py`|Add `session_id`, `session_start_time`, `ghost_events`, `deaths`|
|S6-05|Augment `init_investigation` tool|Call `create_session()`, set `session_start_time`|
|S6-06|Augment `record_evidence` tool|Call `write_evidence_event()` after deduction|
|S6-07|Add `record_ghost_event` tool|DB write + in-memory `ghost_events` list|
|S6-08|Add `record_death` tool|DB write + in-memory `deaths` list + death count|
|S6-09|Add `confirm_true_ghost` tool|`confirm_ghost()` DB call, oracle_correct computed|
|S6-10|Add candidate snapshot writes to `graph/nodes.py`|After `identify_node` and `commentary_node`|
|S6-11|Create `ui/stats.py`|Rich renderer for all three stats tables|
|S6-12|Update `main.py`|`init_db()`, `--stats` flag, `close_session()` in finally, end-of-session prompt|
|S6-13|Update `make_initial_state()`|Pass `session_id` and new Sprint 6 fields|
|S6-14|Create `data/` directory, add to `.gitignore`||
|S6-15|Write `tests/test_db.py`|Schema creation, all CRUD, analytics query tests|
|S6-16|Run full test suite|`pytest tests/ -v` — all Sprint 1–6 tests pass|
|S6-17|Smoke test: session created in DB on `init_investigation`|Query DB after voice command|
|S6-18|Smoke test: evidence events written|Confirm evidence → check `evidence_events` table|
|S6-19|Smoke test: ghost event via voice|"oracle, the ghost just hunted" → check `ghost_events`|
|S6-20|Smoke test: death via voice|"oracle, I died" → `death_count` incremented in `sessions`|
|S6-21|Smoke test: confirm true ghost|"oracle, it was a Banshee" → `oracle_correct` set|
|S6-22|Smoke test: `--stats` output|After 3+ sessions, confirm all tables render correctly|
|S6-23|Smoke test: success rate accuracy|Manually verify `oracle_correct` flags match session outcomes|
|S6-24|Full session test|Complete match with ghost events, death, and post-game confirmation|

### Definition of Done (Sprint 6)

- [ ] All `test_db.py` tests pass
- [ ] All Sprint 1–5 tests still pass
- [ ] `data/oracle_stats.db` created automatically on first run
- [ ] Every `init_investigation` call creates a `sessions` row
- [ ] Every `record_evidence` call creates an `evidence_events` row
- [ ] Ghost events and deaths persist to DB via voice commands
- [ ] `confirm_true_ghost` correctly sets `oracle_correct` to 1 or 0
- [ ] `python main.py --stats` renders all three tables without errors
- [ ] Sessions abandoned via Ctrl+C are marked `outcome = 'abandoned'` not left as `in_progress`
- [ ] `data/` is in `.gitignore` (no accidental stats commits)

---

## Known Risks

**`oracle_guess` is only set when Oracle reached exactly 1 candidate.** If the game ended before the candidate pool narrowed to 1, `oracle_guess` is null and `oracle_correct` is null. This is intentional — inconclusive sessions are tracked separately from wrong identifications. The stats queries distinguish these cases in `success_rate_pct` (excludes null-correct rows from the denominator).

**Concurrent DB writes from two capture threads.** In bidirectional voice mode (Sprint 4), Mike and Kayden may trigger tool calls within milliseconds of each other. SQLite in WAL mode handles concurrent reads fine but serialises writes. The `_connect()` context manager's `commit()`/`rollback()` pattern is safe for single-writer scenarios; if write contention causes `OperationalError: database is locked`, add `conn.execute("PRAGMA journal_mode=WAL")` to `init_db()`.

**`session_start_time` is 0.0 until `init_investigation` is called.** If a player reports evidence before saying "new investigation", `elapsed_s` will be meaningless (large numbers). A startup default of `time.time()` in `make_initial_state()` would self-heal this, or Oracle can detect `session_start_time == 0.0` and emit a warning prompting the player to run `init_investigation` first.

**Ghost event type normalisation is lossy.** Any unrecognised `event_type` from the LLM becomes `"other"`. If phi4-mini consistently uses a non-standard label (e.g. `"ghost_hunt"` instead of `"hunt"`), entries pile up in `"other"` and the frequency stats lose meaning. Log raw event types at DEBUG level so you can spot and add synonyms to the normalisation map over time.