"""Read-only analytics queries — never mutates the database."""
from __future__ import annotations

from typing import Any

from db.database import _get_conn


def success_rate() -> float | None:
    """Overall Oracle identification accuracy (excludes inconclusive sessions).

    Returns:
        Fraction in [0, 1], or None if no conclusive sessions exist.
    """
    conn = _get_conn()
    row = conn.execute(
        "SELECT AVG(oracle_correct) FROM sessions WHERE oracle_correct IS NOT NULL"
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def sessions_by_difficulty() -> list[dict[str, Any]]:
    """Return per-difficulty counts and success rates."""
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT
            difficulty,
            COUNT(*) AS total,
            SUM(CASE WHEN oracle_correct = 1 THEN 1 ELSE 0 END) AS correct,
            AVG(CASE WHEN oracle_correct IS NOT NULL THEN oracle_correct END) AS rate
        FROM sessions
        GROUP BY difficulty
        ORDER BY difficulty
        """
    ).fetchall()
    return [dict(r) for r in rows]


def sessions_by_ghost() -> list[dict[str, Any]]:
    """Return per-true-ghost counts and Oracle accuracy."""
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT
            true_ghost,
            COUNT(*) AS total,
            AVG(CASE WHEN oracle_correct IS NOT NULL THEN oracle_correct END) AS rate
        FROM sessions
        WHERE true_ghost IS NOT NULL
        GROUP BY true_ghost
        ORDER BY true_ghost
        """
    ).fetchall()
    return [dict(r) for r in rows]


def average_time_to_identify() -> float | None:
    """Average elapsed seconds between session start and last confirmed evidence
    for sessions where Oracle correctly identified the ghost.

    Returns:
        Mean elapsed_s, or None if no data.
    """
    conn = _get_conn()
    row = conn.execute(
        """
        SELECT AVG(e.elapsed_s)
        FROM evidence_events e
        JOIN sessions s ON e.session_id = s.session_id
        WHERE s.oracle_correct = 1
          AND e.status = 'confirmed'
        """
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def recent_sessions(limit: int = 10) -> list[dict[str, Any]]:
    """Return the most recent *limit* sessions."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]
