"""Tests for graph nodes — no Ollama required, uses mocks."""
from unittest.mock import MagicMock, patch

from graph.nodes import build_state_summary, parse_intent_node, execute_tool_node, route_after_parse


def _make_state(**overrides) -> dict:
    base = {
        "user_text": "",
        "speaker": "Mike",
        "difficulty": "professional",
        "evidence_confirmed": [],
        "evidence_ruled_out": [],
        "behavioral_observations": [],
        "eliminated_ghosts": [],
        "candidates": ["Banshee", "Demon", "Spirit"],
        "parsed_intent": {},
        "tool_result": None,
        "oracle_response": None,
        "messages": [],
    }
    base.update(overrides)
    return base


# ── build_state_summary ─────────────────────────────────────────────────────

class TestBuildStateSummary:
    def test_includes_difficulty(self):
        state = _make_state(difficulty="nightmare")
        summary = build_state_summary(state)
        assert "nightmare" in summary

    def test_includes_confirmed_evidence(self):
        state = _make_state(evidence_confirmed=["orb", "freezing"])
        summary = build_state_summary(state)
        assert "orb" in summary
        assert "freezing" in summary

    def test_includes_ruled_out_evidence(self):
        state = _make_state(evidence_ruled_out=["emf_5"])
        summary = build_state_summary(state)
        assert "emf_5" in summary

    def test_includes_candidate_count(self):
        state = _make_state(candidates=["Banshee", "Demon"])
        summary = build_state_summary(state)
        assert "2" in summary
        assert "Banshee" in summary
        assert "Demon" in summary

    def test_shows_none_when_empty(self):
        state = _make_state(evidence_confirmed=[], evidence_ruled_out=[])
        summary = build_state_summary(state)
        assert "none" in summary

    def test_truncates_large_candidate_list(self):
        state = _make_state(candidates=[f"Ghost{i}" for i in range(20)])
        summary = build_state_summary(state)
        assert "20 ghosts" in summary


# ── parse_intent_node ────────────────────────────────────────────────────────

class TestParseIntentNode:
    def test_parses_evidence_confirm(self):
        state = _make_state(user_text="we found ghost orbs")
        result = parse_intent_node(state)
        intent = result["parsed_intent"]
        assert intent["action"] == "record_evidence"
        assert intent["evidence_id"] == "orb"
        assert intent["status"] == "confirmed"

    def test_parses_evidence_rule_out(self):
        state = _make_state(user_text="no EMF 5")
        result = parse_intent_node(state)
        intent = result["parsed_intent"]
        assert intent["action"] == "record_evidence"
        assert intent["evidence_id"] == "emf_5"
        assert intent["status"] == "ruled_out"

    def test_parses_investigation_init(self):
        state = _make_state(user_text="new game on nightmare")
        result = parse_intent_node(state)
        intent = result["parsed_intent"]
        assert intent["action"] == "init_investigation"
        assert intent["difficulty"] == "nightmare"

    def test_parses_state_query(self):
        state = _make_state(user_text="what ghosts are left?")
        result = parse_intent_node(state)
        intent = result["parsed_intent"]
        assert intent["action"] == "get_investigation_state"

    def test_falls_back_to_llm_on_ambiguous(self):
        state = _make_state(user_text="I'm scared")
        result = parse_intent_node(state)
        intent = result["parsed_intent"]
        assert intent["action"] == "llm_fallback"


# ── route_after_parse ────────────────────────────────────────────────────────

class TestRouteAfterParse:
    def test_routes_to_execute_on_match(self):
        state = _make_state(parsed_intent={"action": "record_evidence"})
        assert route_after_parse(state) == "execute_tool"

    def test_routes_to_llm_on_fallback(self):
        state = _make_state(parsed_intent={"action": "llm_fallback"})
        assert route_after_parse(state) == "llm_classify"


# ── execute_tool_node ────────────────────────────────────────────────────────

class TestExecuteToolNode:
    def test_returns_none_for_null_action(self):
        state = _make_state(parsed_intent={"action": "null"})
        from graph.tools import bind_state
        bind_state(state)
        result = execute_tool_node(state)
        assert result["tool_result"] is None

    def test_returns_result_for_get_state(self):
        state = _make_state(parsed_intent={"action": "get_investigation_state"})
        from graph.tools import bind_state
        bind_state(state)
        result = execute_tool_node(state)
        assert result["tool_result"] is not None
        assert "Difficulty" in result["tool_result"]
