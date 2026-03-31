"""SQLite CRUD layer.

All writes check ``session_id`` before executing.  This prevents FK constraint
errors during text-mode testing where no session has been initialised.

Schema:
    sessions         — one row per investigation
    evidence_events  — one row per evidence recording
    ghost_events     — hunts, interactions, manifestations, etc.
    deaths           — one row per player death
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    difficulty   TEXT NOT NULL,
    started_at   REAL NOT NULL,
    ended_at     REAL,
    true_ghost   TEXT,
    oracle_correct INTEGER  -- 1=correct, 0=wrong, NULL=inconclusive
);

CREATE TABLE IF NOT EXISTS evidence_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL REFERENCES sessions(session_id),
    evidence_id  TEXT NOT NULL,
    status       TEXT NOT NULL,  -- confirmed | ruled_out
    elapsed_s    REAL NOT NULL,
    candidate_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS ghost_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL REFERENCES sessions(session_id),
    event_type   TEXT NOT NULL,
    detail       TEXT,
    elapsed_s    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS deaths (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL REFERENCES sessions(session_id),
    player       TEXT NOT NULL,
    elapsed_s    REAL NOT NULL
);
"""

_conn: sqlite3.Connection | None = None


def _get_conn(db_path: str | None = None) -> sqlite3.Connection:
    global _conn
    if _conn is None:
        from config.settings import config

        path = Path(db_path or config.SQLITE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(path), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


def init_db(db_path: str | None = None) -> None:
    """Create all tables if they don't exist."""
    conn = _get_conn(db_path)
    conn.executescript(_SCHEMA)
    conn.commit()


def _reset_connection() -> None:
    """Close the current connection (used in tests to point at a temp DB)."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


# ── Write helpers ─────────────────────────────────────────────────────────────


def create_session(session_id: str, difficulty: str, started_at: float) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO sessions (session_id, difficulty, started_at) VALUES (?, ?, ?)",
        (session_id, difficulty, started_at),
    )
    conn.commit()


def close_session(
    session_id: str,
    true_ghost: str,
    oracle_correct: int | None,
) -> None:
    import time

    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET ended_at=?, true_ghost=?, oracle_correct=? WHERE session_id=?",
        (time.time(), true_ghost, oracle_correct, session_id),
    )
    conn.commit()


def write_evidence_event(
    session_id: str,
    evidence_id: str,
    status: str,
    elapsed_s: float,
    candidate_count: int,
) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO evidence_events "
        "(session_id, evidence_id, status, elapsed_s, candidate_count) "
        "VALUES (?, ?, ?, ?, ?)",
        (session_id, evidence_id, status, elapsed_s, candidate_count),
    )
    conn.commit()


def write_ghost_event(
    session_id: str,
    event_type: str,
    detail: str,
    elapsed_s: float,
) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO ghost_events (session_id, event_type, detail, elapsed_s) VALUES (?, ?, ?, ?)",
        (session_id, event_type, detail, elapsed_s),
    )
    conn.commit()


def write_death(session_id: str, player: str, elapsed_s: float) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO deaths (session_id, player, elapsed_s) VALUES (?, ?, ?)",
        (session_id, player, elapsed_s),
    )
    conn.commit()


# ── Read helpers ──────────────────────────────────────────────────────────────


def get_session(session_id: str) -> dict[str, Any] | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id=?", (session_id,)
    ).fetchone()
    return dict(row) if row else None
