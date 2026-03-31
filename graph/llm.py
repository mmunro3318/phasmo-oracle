"""LLM factory — Ollama primary, Anthropic fallback.

Usage:
    from graph.llm import init_llm, get_llm, get_commentary_llm, current_backend

    init_llm()          # call once in main()
    llm = get_llm()     # temperature=0, for tool calls and direct answers
    llm = get_commentary_llm()  # temperature=0.3, for auto-commentary prose
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_llm = None
_commentary_llm = None
_backend: str = "none"


def _ollama_available(base_url: str) -> bool:
    """Return True if Ollama is reachable at *base_url*."""
    try:
        resp = httpx.get(f"{base_url}/api/tags", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


def init_llm() -> None:
    """Initialise LLM instances.  Must be called once before ``get_llm()``."""
    global _llm, _commentary_llm, _backend

    from config.settings import config

    if _ollama_available(config.OLLAMA_BASE_URL):
        from langchain_ollama import ChatOllama

        _llm = ChatOllama(
            model=config.OLLAMA_MODEL,
            base_url=config.OLLAMA_BASE_URL,
            temperature=0,
        )
        _commentary_llm = ChatOllama(
            model=config.OLLAMA_MODEL,
            base_url=config.OLLAMA_BASE_URL,
            temperature=0.3,
        )
        _backend = "ollama"
        logger.info("LLM backend: Ollama (%s)", config.OLLAMA_MODEL)
        return

    if config.FALLBACK_ENABLED and config.ANTHROPIC_API_KEY:
        from langchain_anthropic import ChatAnthropic

        _llm = ChatAnthropic(
            model=config.FALLBACK_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            temperature=0,
        )
        _commentary_llm = ChatAnthropic(
            model=config.FALLBACK_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            temperature=0.3,
        )
        _backend = "anthropic"
        logger.warning("Ollama unreachable — using Anthropic fallback (%s)", config.FALLBACK_MODEL)
        return

    raise RuntimeError(
        "No LLM available. Start Ollama ('ollama serve') or set ANTHROPIC_API_KEY "
        "in config/.env.local with FALLBACK_ENABLED=true."
    )


def get_llm():
    """Return the primary LLM (temperature=0).  Raises if ``init_llm()`` was not called."""
    if _llm is None:
        raise RuntimeError("LLM not initialised — call init_llm() first.")
    return _llm


def get_commentary_llm():
    """Return the commentary LLM (temperature=0.3)."""
    if _commentary_llm is None:
        raise RuntimeError("LLM not initialised — call init_llm() first.")
    return _commentary_llm


def current_backend() -> str:
    """Return 'ollama', 'anthropic', or 'none'."""
    return _backend
