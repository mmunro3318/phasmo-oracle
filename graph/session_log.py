"""Append-only JSONL session log.

Every turn is logged as a single JSON line to ``sessions/<session_id>.jsonl``.
Log files are gitignored.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _log_path(session_id: str, sessions_dir: str = "sessions") -> Path:
    return Path(sessions_dir) / f"{session_id}.jsonl"


def log_turn(
    session_id: str,
    user_text: str,
    oracle_response: str | None,
    state_snapshot: dict[str, Any],
    sessions_dir: str = "sessions",
) -> None:
    """Append one turn to the session JSONL log.

    Args:
        session_id:      Unique session identifier.
        user_text:       Raw text from the player this turn.
        oracle_response: Oracle's spoken response, or None if silent.
        state_snapshot:  A copy of the relevant OracleState fields for audit.
        sessions_dir:    Directory to write log files into.
    """
    path = _log_path(session_id, sessions_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    entry: dict[str, Any] = {
        "ts": time.time(),
        "user_text": user_text,
        "oracle_response": oracle_response,
        "candidates": state_snapshot.get("candidates", []),
        "evidence_confirmed": state_snapshot.get("evidence_confirmed", []),
        "evidence_ruled_out": state_snapshot.get("evidence_ruled_out", []),
        "eliminated_ghosts": state_snapshot.get("eliminated_ghosts", []),
        "difficulty": state_snapshot.get("difficulty"),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def load_log(session_id: str, sessions_dir: str = "sessions") -> list[dict[str, Any]]:
    """Load all turns from a session JSONL log.

    Args:
        session_id:   Unique session identifier.
        sessions_dir: Directory containing log files.

    Returns:
        List of turn dicts in chronological order.
    """
    path = _log_path(session_id, sessions_dir)
    if not path.exists():
        return []
    turns = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                turns.append(json.loads(line))
    return turns
