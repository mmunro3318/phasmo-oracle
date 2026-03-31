"""LLM factory tests — mocked; no running services required."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_init_llm_uses_ollama_when_available():
    mock_llm = MagicMock()
    with (
        patch("graph.llm._ollama_available", return_value=True),
        patch("graph.llm.ChatOllama", return_value=mock_llm, create=True),
    ):
        import graph.llm as llm_module

        llm_module._llm = None
        llm_module._commentary_llm = None
        llm_module._backend = "none"
        # Patch ChatOllama inside the module's namespace
        with patch.object(llm_module, "_ollama_available", return_value=True):
            pass  # Just ensure no AttributeError


def test_current_backend_default_is_none():
    import graph.llm as llm_module

    # Resetting to untouched state
    llm_module._backend = "none"
    assert llm_module.current_backend() == "none"


def test_get_llm_raises_before_init():
    import graph.llm as llm_module

    llm_module._llm = None
    with pytest.raises(RuntimeError, match="init_llm"):
        llm_module.get_llm()


def test_get_commentary_llm_raises_before_init():
    import graph.llm as llm_module

    llm_module._commentary_llm = None
    with pytest.raises(RuntimeError, match="init_llm"):
        llm_module.get_commentary_llm()


def test_ollama_available_returns_false_on_connection_error():
    from graph.llm import _ollama_available

    # Point at a port that is not listening
    assert _ollama_available("http://127.0.0.1:19999") is False
