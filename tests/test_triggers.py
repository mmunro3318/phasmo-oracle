"""Tests for the auto-trigger routing logic.

These tests verify that route_after_tools fires identify/commentary/llm at the
correct thresholds.  No LLM or audio required.

Critical tests (must always pass — see AGENTS.md):
- test_identify_does_not_fire_with_insufficient_evidence
- test_commentary_does_not_fire_when_count_unchanged
"""
from __future__ import annotations

from graph.nodes import route_after_tools

# ── Identify trigger ──────────────────────────────────────────────────────────


def _state(candidates, confirmed, difficulty="professional", prev_count=None):
    if prev_count is None:
        prev_count = len(candidates) + 5  # simulate "changed" by default
    return {
        "candidates": candidates,
        "evidence_confirmed": confirmed,
        "difficulty": difficulty,
        "prev_candidate_count": prev_count,
    }


def test_identify_fires_at_one_candidate_three_evidence():
    state = _state(["Wraith"], ["emf_5", "spirit_box", "writing"])
    assert route_after_tools(state) == "identify"


def test_identify_does_not_fire_with_insufficient_evidence():
    """Only 2 evidence confirmed on professional — must NOT identify."""
    state = _state(["Wraith"], ["emf_5", "spirit_box"])
    assert route_after_tools(state) != "identify"


def test_identify_nightmare_threshold_is_two():
    state = _state(["Shade"], ["uv", "orb"], difficulty="nightmare")
    assert route_after_tools(state) == "identify"


def test_identify_insanity_threshold_is_one():
    state = _state(["Moroi"], ["spirit_box"], difficulty="insanity")
    assert route_after_tools(state) == "identify"


def test_identify_does_not_fire_with_zero_candidates():
    state = _state([], ["emf_5", "spirit_box", "writing"])
    assert route_after_tools(state) != "identify"


def test_identify_does_not_fire_with_multiple_candidates():
    state = _state(["Wraith", "Shade"], ["emf_5", "spirit_box", "writing"])
    assert route_after_tools(state) != "identify"


# ── Commentary trigger ────────────────────────────────────────────────────────


def test_commentary_fires_when_candidates_changed_and_five_or_fewer():
    # 3 candidates, prev_count was 6 (so count changed)
    state = _state(["Wraith", "Shade", "Revenant"], ["emf_5"], prev_count=6)
    assert route_after_tools(state) == "commentary"


def test_commentary_fires_at_exactly_five():
    ghosts = ["Wraith", "Shade", "Revenant", "Goryo", "Banshee"]
    state = _state(ghosts, ["orb"], prev_count=10)
    assert route_after_tools(state) == "commentary"


def test_commentary_does_not_fire_when_count_unchanged():
    """Candidate count unchanged — commentary must NOT fire."""
    ghosts = ["Wraith", "Shade", "Revenant"]
    state = _state(ghosts, ["emf_5"], prev_count=len(ghosts))
    assert route_after_tools(state) != "commentary"


def test_commentary_does_not_fire_when_more_than_five():
    ghosts = [f"Ghost{i}" for i in range(6)]
    state = _state(ghosts, ["orb"], prev_count=20)
    assert route_after_tools(state) != "commentary"


def test_commentary_does_not_fire_on_single_candidate_below_threshold():
    """Single candidate but only 1 evidence on professional — no identify, no commentary."""
    state = _state(["Wraith"], ["emf_5"], prev_count=5)
    result = route_after_tools(state)
    # Should loop back to llm, not commentary or identify
    assert result == "llm"


# ── Default routing ───────────────────────────────────────────────────────────


def test_llm_route_when_many_candidates_unchanged():
    ghosts = [f"Ghost{i}" for i in range(15)]
    state = _state(ghosts, ["emf_5"], prev_count=len(ghosts))
    assert route_after_tools(state) == "llm"


def test_llm_route_on_empty_state():
    state = {
        "candidates": [],
        "evidence_confirmed": [],
        "difficulty": "professional",
        "prev_candidate_count": 27,
    }
    assert route_after_tools(state) == "llm"
