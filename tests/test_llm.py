"""Tests for LLM factory — no Ollama required, uses mocks."""
from unittest.mock import patch, MagicMock

import pytest

import graph.llm as llm_mod


@pytest.fixture(autouse=True)
def _reset_llm():
    """Reset LLM state between tests."""
    llm_mod._llm = None
    llm_mod._backend = "unknown"
    yield
    llm_mod._llm = None
    llm_mod._backend = "unknown"


class TestCheckOllamaHealth:
    def test_healthy_ollama(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "models": [{"name": "qwen2.5:7b"}]
        }
        with patch("graph.llm.httpx.get", return_value=mock_resp):
            assert llm_mod._check_ollama_health() is True

    def test_ollama_not_running(self):
        import httpx
        with patch("graph.llm.httpx.get", side_effect=httpx.ConnectError("")):
            assert llm_mod._check_ollama_health() is False

    def test_model_not_pulled(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "models": [{"name": "llama3:latest"}]
        }
        with patch("graph.llm.httpx.get", return_value=mock_resp):
            assert llm_mod._check_ollama_health() is False

    def test_timeout(self):
        import httpx
        with patch("graph.llm.httpx.get", side_effect=httpx.TimeoutException("")):
            assert llm_mod._check_ollama_health() is False


class TestGetLlm:
    def test_raises_if_not_initialized(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            llm_mod.get_llm()

    def test_returns_llm_after_init(self):
        mock_llm = MagicMock()
        llm_mod._llm = mock_llm
        assert llm_mod.get_llm() is mock_llm


class TestCurrentBackend:
    def test_default_is_unknown(self):
        assert llm_mod.current_backend() == "unknown"

    def test_after_init(self):
        llm_mod._backend = "ollama"
        assert llm_mod.current_backend() == "ollama"


class TestInitLlm:
    def test_raises_when_ollama_unavailable(self):
        with patch.object(llm_mod, "_check_ollama_health", return_value=False):
            with pytest.raises(RuntimeError, match="not reachable"):
                llm_mod.init_llm()

    def test_succeeds_when_ollama_available(self):
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm

        with (
            patch.object(llm_mod, "_check_ollama_health", return_value=True),
            patch("graph.llm.ChatOllama", return_value=mock_llm),
            patch.object(llm_mod, "_validate_tool_calling", return_value=True),
        ):
            llm_mod.init_llm()
            assert llm_mod._llm is not None
            assert llm_mod._backend == "ollama"
