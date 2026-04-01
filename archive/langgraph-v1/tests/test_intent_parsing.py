"""LLM intent-parsing regression tests.

These tests require a running Ollama instance with phi4-mini.
They are automatically skipped when Ollama is unavailable.

Run with: pytest tests/test_intent_parsing.py -v
Skip with: pytest -m "not llm"
"""
from __future__ import annotations

import pytest
import httpx

from config.settings import config

# ── Auto-skip when Ollama is unavailable ────────────────────────────────────


def _ollama_available() -> bool:
    try:
        resp = httpx.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=5.0)
        resp.raise_for_status()
        models = resp.json().get("models", [])
        model_names = [m.get("name", "").split(":")[0] for m in models]
        return config.OLLAMA_MODEL.split(":")[0] in model_names
    except Exception:
        return False


pytestmark = pytest.mark.llm
skip_no_ollama = pytest.mark.skipif(
    not _ollama_available(),
    reason=f"Ollama not available or {config.OLLAMA_MODEL} not pulled",
)


# ── Test infrastructure ─────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def graph_and_state():
    """Initialize the LLM and graph once for all tests in this module."""
    from graph.llm import init_llm
    from graph.graph import oracle_graph
    from graph.deduction import all_ghost_names
    from graph.tools import bind_state, sync_state_from

    init_llm()

    def run_turn(user_text: str, state: dict | None = None) -> tuple[dict, dict]:
        """Run a single turn and return (state, result)."""
        if state is None:
            state = {
                "user_text": user_text,
                "speaker": "Mike",
                "difficulty": "professional",
                "evidence_confirmed": [],
                "evidence_ruled_out": [],
                "behavioral_observations": [],
                "eliminated_ghosts": [],
                "candidates": all_ghost_names(),
                "oracle_response": None,
                "messages": [],
            }
        else:
            state["user_text"] = user_text
            state["messages"] = []

        bind_state(state)
        result = oracle_graph.invoke(state)
        sync_state_from(state)
        return state, result

    return run_turn


# ── Intent parsing tests ────────────────────────────────────────────────────

@skip_no_ollama
class TestEvidenceConfirmed:
    """Test that various phrasings of 'we found X' result in evidence being CONFIRMED."""

    def test_explicit_confirmed(self, graph_and_state):
        run = graph_and_state
        state, _ = run("ghost orb confirmed")
        assert "orb" in state["evidence_confirmed"]
        assert "orb" not in state["evidence_ruled_out"]

    def test_we_found(self, graph_and_state):
        run = graph_and_state
        state, _ = run("we found freezing temperatures")
        assert "freezing" in state["evidence_confirmed"]

    def test_we_got(self, graph_and_state):
        run = graph_and_state
        state, _ = run("we've got EMF 5")
        assert "emf_5" in state["evidence_confirmed"]

    def test_detected(self, graph_and_state):
        run = graph_and_state
        state, _ = run("we detected ghost orbs")
        assert "orb" in state["evidence_confirmed"]


@skip_no_ollama
class TestEvidenceRuledOut:
    """Test that various phrasings of 'no X' result in evidence being RULED OUT."""

    def test_explicit_ruled_out(self, graph_and_state):
        run = graph_and_state
        state, _ = run("rule out spirit box")
        assert "spirit_box" in state["evidence_ruled_out"]
        assert "spirit_box" not in state["evidence_confirmed"]

    def test_no_evidence(self, graph_and_state):
        run = graph_and_state
        state, _ = run("no EMF 5")
        assert "emf_5" in state["evidence_ruled_out"]

    def test_eliminated(self, graph_and_state):
        run = graph_and_state
        state, _ = run("we've eliminated ghost writing")
        assert "writing" in state["evidence_ruled_out"]


@skip_no_ollama
class TestInvestigationManagement:
    def test_new_investigation(self, graph_and_state):
        run = graph_and_state
        state, _ = run("new investigation on nightmare")
        assert state["difficulty"] == "nightmare"
        assert len(state["candidates"]) == 27

    def test_what_ghosts_left(self, graph_and_state):
        run = graph_and_state
        _, result = run("what ghosts are left?")
        response = result.get("oracle_response", "")
        # Should produce a response (not None) since this queries state
        assert response is not None


@skip_no_ollama
class TestGhostLookup:
    def test_ghost_query(self, graph_and_state):
        run = graph_and_state
        _, result = run("what does the Banshee do?")
        response = result.get("oracle_response", "")
        assert response is not None
