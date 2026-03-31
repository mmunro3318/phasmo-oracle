"""Database layer tests — schema creation and CRUD operations."""
from __future__ import annotations

import time

import pytest

from db.database import (
    _reset_connection,
    close_session,
    create_session,
    get_session,
    init_db,
    write_death,
    write_evidence_event,
    write_ghost_event,
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Create a fresh in-memory-like SQLite DB in tmp_path for each test."""
    db_file = str(tmp_path / "test_oracle.db")
    monkeypatch.setenv("SQLITE_PATH", db_file)
    _reset_connection()
    # Override settings to point at tmp db
    import config.settings as settings_module

    original = settings_module.config.SQLITE_PATH
    settings_module.config.SQLITE_PATH = db_file  # type: ignore[attr-defined]
    init_db(db_file)
    yield db_file
    _reset_connection()
    settings_module.config.SQLITE_PATH = original  # type: ignore[attr-defined]


def test_init_db_creates_tables(db):
    import sqlite3

    conn = sqlite3.connect(db)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sessions", "evidence_events", "ghost_events", "deaths"}.issubset(tables)
    conn.close()


def test_create_and_get_session(db):
    create_session("s1", "professional", time.time())
    row = get_session("s1")
    assert row is not None
    assert row["session_id"] == "s1"
    assert row["difficulty"] == "professional"


def test_close_session_sets_fields(db):
    ts = time.time()
    create_session("s2", "nightmare", ts)
    close_session("s2", "Wraith", 1)
    row = get_session("s2")
    assert row["true_ghost"] == "Wraith"
    assert row["oracle_correct"] == 1


def test_close_session_inconclusive(db):
    create_session("s3", "insanity", time.time())
    close_session("s3", "Shade", None)
    row = get_session("s3")
    assert row["oracle_correct"] is None


def test_write_evidence_event(db):
    import sqlite3

    create_session("s4", "professional", time.time())
    write_evidence_event("s4", "orb", "confirmed", 45.2, 11)
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT * FROM evidence_events WHERE session_id='s4'").fetchall()
    assert len(rows) == 1
    assert rows[0][2] == "orb"
    conn.close()


def test_write_ghost_event(db):
    import sqlite3

    create_session("s5", "professional", time.time())
    write_ghost_event("s5", "hunt", "3-minute mark", 120.0)
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT * FROM ghost_events WHERE session_id='s5'").fetchall()
    assert len(rows) == 1
    assert rows[0][2] == "hunt"
    conn.close()


def test_write_death(db):
    import sqlite3

    create_session("s6", "professional", time.time())
    write_death("s6", "Mike", 200.0)
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT * FROM deaths WHERE session_id='s6'").fetchall()
    assert len(rows) == 1
    assert rows[0][2] == "Mike"
    conn.close()


def test_create_session_idempotent(db):
    ts = time.time()
    create_session("s7", "professional", ts)
    create_session("s7", "professional", ts)  # duplicate — should not raise
    row = get_session("s7")
    assert row is not None


def test_get_session_missing(db):
    assert get_session("does_not_exist") is None
