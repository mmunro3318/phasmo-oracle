"""LLM factory — init once, use everywhere.

Call init_llm() at startup. Then get_llm() returns the initialized instance.
Never instantiate ChatOllama directly in nodes.
"""
from __future__ import annotations

import logging

import httpx
from langchain_ollama import ChatOllama

from config.settings import config
from .tools import ORACLE_TOOLS

logger = logging.getLogger("oracle.llm")

_llm: ChatOllama | None = None
_backend: str = "unknown"


def _check_ollama_health() -> bool:
    """Return True if Ollama is reachable and the model is available."""
    try:
        resp = httpx.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=5.0)
        resp.raise_for_status()
        models = resp.json().get("models", [])
        # Match by full name (e.g., "qwen2.5:7b") or base name (e.g., "qwen2.5")
        model_names = [m.get("name", "") for m in models]
        target = config.OLLAMA_MODEL
        target_base = target.split(":")[0]
        found = any(
            name == target or name.startswith(target + "-") or name.split(":")[0] == target_base
            for name in model_names
        )
        if not found:
            logger.warning(
                "Ollama is running but model '%s' is not pulled. "
                "Run: ollama pull %s",
                config.OLLAMA_MODEL,
                config.OLLAMA_MODEL,
            )
            return False
        return True
    except (httpx.ConnectError, httpx.TimeoutException):
        return False
    except Exception as exc:
        logger.warning("Unexpected error checking Ollama: %s", exc)
        return False


def _validate_tool_calling(llm_with_tools: ChatOllama) -> bool:
    """Verify the model can emit structured tool calls."""
    from langchain_core.messages import HumanMessage

    try:
        response = llm_with_tools.invoke(
            [HumanMessage(content="What is the current investigation state?")]
        )
        # Check if the response contains tool calls
        if hasattr(response, "tool_calls") and response.tool_calls:
            logger.info("Tool-call validation passed: model emits structured calls.")
            return True
        # Some models return tool calls differently — check for any sign of tool usage
        if hasattr(response, "additional_kwargs"):
            tool_calls = response.additional_kwargs.get("tool_calls", [])
            if tool_calls:
                logger.info("Tool-call validation passed (via additional_kwargs).")
                return True
        logger.warning(
            "Tool-call validation: model did not emit a tool call for a "
            "test prompt. Tool routing may not work reliably."
        )
        return False
    except Exception as exc:
        logger.warning("Tool-call validation failed: %s", exc)
        return False


def init_llm() -> None:
    """Initialize the LLM. Call once at startup.

    Checks Ollama health, creates the ChatOllama instance, and optionally
    validates tool calling.
    """
    global _llm, _backend

    if not _check_ollama_health():
        raise RuntimeError(
            f"Ollama is not reachable at {config.OLLAMA_BASE_URL} or model "
            f"'{config.OLLAMA_MODEL}' is not pulled.\n"
            f"Start Ollama and run: ollama pull {config.OLLAMA_MODEL}"
        )

    llm = ChatOllama(
        model=config.OLLAMA_MODEL,
        temperature=0,
        base_url=config.OLLAMA_BASE_URL,
    )
    llm_with_tools = llm.bind_tools(ORACLE_TOOLS)

    _validate_tool_calling(llm_with_tools)

    _llm = llm_with_tools
    _backend = "ollama"
    logger.info("LLM initialized: %s via %s", config.OLLAMA_MODEL, _backend)


def get_llm() -> ChatOllama:
    """Return the initialized LLM with tools bound.

    Raises RuntimeError if init_llm() hasn't been called.
    """
    if _llm is None:
        raise RuntimeError("LLM not initialized. Call init_llm() first.")
    return _llm


def current_backend() -> str:
    """Return 'ollama' or 'unknown'."""
    return _backend
