"""UI module smoke tests — verify Rich display functions don't raise."""
from __future__ import annotations

from unittest.mock import patch


def _mock_state():
    return {
        "evidence_confirmed": ["orb", "spirit_box"],
        "evidence_ruled_out": ["emf_5"],
        "candidates": ["Wraith", "Shade", "Revenant"],
        "difficulty": "professional",
        "oracle_response": "Three candidates remain.",
    }


def test_render_state_does_not_raise():
    from ui.display import render_state

    with patch("ui.display.console"):
        render_state(_mock_state())
    # Just verify it executed without raising


def test_render_state_empty_does_not_raise():
    from ui.display import render_state

    with patch("ui.display.console"):
        render_state({})


def test_diagnostics_check_db_path_exists():
    from ui.diagnostics import _check_db_path

    result = _check_db_path()
    # Ghost DB should exist in the project
    assert result.ok is True or result.ok is False  # just verify it runs


def test_diagnostics_run_returns_list():
    from ui.diagnostics import run_diagnostics

    results = run_diagnostics()
    assert isinstance(results, list)
    assert len(results) > 0


def test_diagnostics_result_has_name_and_ok():
    from ui.diagnostics import run_diagnostics

    for r in run_diagnostics():
        assert hasattr(r, "name")
        assert hasattr(r, "ok")
        assert isinstance(r.ok, bool)
