"""Tests for main.py — no Ollama required for most tests."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from main import make_initial_state, run_diagnostics, SessionLogger


class TestMakeInitialState:
    def test_returns_correct_defaults(self):
        state = make_initial_state()
        assert state["speaker"] == "Mike"
        assert state["difficulty"] == "professional"
        assert state["evidence_confirmed"] == []
        assert state["evidence_ruled_out"] == []
        assert state["behavioral_observations"] == []
        assert state["eliminated_ghosts"] == []
        assert state["oracle_response"] is None
        assert state["messages"] == []

    def test_has_27_candidates(self):
        state = make_initial_state()
        assert len(state["candidates"]) == 27

    def test_all_candidates_are_strings(self):
        state = make_initial_state()
        for name in state["candidates"]:
            assert isinstance(name, str)


class TestSessionLogger:
    def test_writes_valid_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(Path, "mkdir"):
                logger = SessionLogger.__new__(SessionLogger)
                logger.path = Path(tmpdir) / "test.jsonl"
                logger._file = open(logger.path, "a", encoding="utf-8")

                logger.log_turn(
                    user_text="ghost orb confirmed",
                    candidates_before=["A", "B", "C"],
                    candidates_after=["A", "B"],
                    oracle_response="2 candidates remain.",
                )
                logger.log_turn(
                    user_text="rule out emf",
                    candidates_before=["A", "B"],
                    candidates_after=["A"],
                    oracle_response="1 candidate remains.",
                )
                logger.close()

                # Read and validate JSONL
                with open(logger.path) as f:
                    lines = f.readlines()

                assert len(lines) == 2
                for line in lines:
                    entry = json.loads(line)
                    assert "ts" in entry
                    assert "user_text" in entry
                    assert "candidates_before" in entry
                    assert "candidates_after" in entry
                    assert "oracle_response" in entry

    def test_first_entry_has_correct_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SessionLogger.__new__(SessionLogger)
            logger.path = Path(tmpdir) / "test.jsonl"
            logger._file = open(logger.path, "a", encoding="utf-8")

            logger.log_turn(
                user_text="test input",
                candidates_before=["Ghost1"],
                candidates_after=[],
                oracle_response=None,
            )
            logger.close()

            with open(logger.path) as f:
                entry = json.loads(f.readline())

            assert entry["user_text"] == "test input"
            assert entry["candidates_before"] == ["Ghost1"]
            assert entry["candidates_after"] == []
            assert entry["oracle_response"] is None


class TestRunDiagnostics:
    def test_ghost_database_check_passes(self):
        checks = run_diagnostics()
        db_check = next(c for c in checks if c[0] == "Ghost database")
        assert db_check[1] is True
        assert "27" in db_check[2]

    def test_ollama_check_fails_gracefully(self):
        """When Ollama is not running, diagnostics should fail gracefully."""
        import httpx
        with patch("httpx.get", side_effect=httpx.ConnectError("")):
            checks = run_diagnostics()
            ollama_check = next(c for c in checks if c[0] == "Ollama connection")
            assert ollama_check[1] is False
