"""LangGraph node functions — llm_node, tools_node, identify_node, etc.

Hard invariants (see AGENTS.md):
- ``route_after_tools`` is a pure function: reads state, returns a string,
  no side effects.
- ``identify_node`` is triggered by the graph's conditional edge, never by
  the LLM as a tool call.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from graph.deduction import all_ghost_names

logger = logging.getLogger(__name__)

# Evidence thresholds for auto-identification by difficulty
_EVIDENCE_THRESHOLD: dict[str, int] = {
    "amateur": 3,
    "intermediate": 3,
    "professional": 3,
    "nightmare": 2,
    "insanity": 1,
}

_SYSTEM_PROMPT = """\
You are Oracle, a Phasmophobia ghost-identification assistant.
You help players identify the ghost by recording evidence, logging observations,
and querying the ghost database.  You are direct, concise, and calm.

Rules:
- ALWAYS call a tool when the player reports evidence, an observation, or asks
  about ghost information.
- NEVER name a ghost as the answer — that is done automatically when the
  deduction engine narrows to exactly one candidate.
- Keep responses to one or two short sentences.
- Do not repeat evidence the player just told you back to them in detail.
"""


def _build_state_summary(state: dict[str, Any]) -> str:
    confirmed = state.get("evidence_confirmed", [])
    ruled_out = state.get("evidence_ruled_out", [])
    candidates = state.get("candidates", [])
    difficulty = state.get("difficulty", "professional")
    return (
        f"[State] Difficulty: {difficulty} | "
        f"Confirmed: {confirmed} | Ruled out: {ruled_out} | "
        f"Candidates ({len(candidates)}): {candidates}"
    )


# ── Primary nodes ─────────────────────────────────────────────────────────────


def llm_node(state: dict[str, Any]) -> dict[str, Any]:
    """Call the LLM with the current state summary and the user's message.

    The LLM may emit a tool call or a direct text response.
    """
    from graph.llm import get_llm
    from graph.tools import ALL_TOOLS

    llm_with_tools = get_llm().bind_tools(ALL_TOOLS)

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        SystemMessage(content=_build_state_summary(state)),
    ]
    for msg in state.get("messages", []):
        messages.append(msg)

    user_text = state.get("user_text", "")
    if user_text:
        messages.append(HumanMessage(content=user_text))

    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def identify_node(state: dict[str, Any]) -> dict[str, Any]:
    """Generate the ghost identification announcement.

    Called by the graph's conditional edge when exactly one candidate remains
    with sufficient evidence confirmed.  Never called by the LLM directly.
    """
    candidates = state.get("candidates", [])
    confirmed = state.get("evidence_confirmed", [])
    ghost = candidates[0] if candidates else "Unknown"
    evidence_str = ", ".join(confirmed) if confirmed else "no evidence"

    response = (
        f"Ghost identified: {ghost}. "
        f"Confirmed evidence: {evidence_str}."
    )
    logger.info("Identification: %s", ghost)
    return {"oracle_response": response}


def commentary_node(state: dict[str, Any]) -> dict[str, Any]:
    """Generate a short auto-commentary when candidates have just narrowed."""
    from graph.llm import get_commentary_llm

    candidates = state.get("candidates", [])
    confirmed = state.get("evidence_confirmed", [])
    ruled_out = state.get("evidence_ruled_out", [])

    prompt = (
        f"The investigation has narrowed to {len(candidates)} ghost candidates: "
        f"{', '.join(candidates)}.\n"
        f"Confirmed evidence: {', '.join(confirmed) if confirmed else 'none'}.\n"
        f"Ruled out: {', '.join(ruled_out) if ruled_out else 'none'}.\n"
        "In one or two sentences, briefly comment on which evidence could "
        "narrow this further.  Do not name a ghost as the answer."
    )
    response = get_commentary_llm().invoke([HumanMessage(content=prompt)])
    text = response.content if isinstance(response.content, str) else str(response.content)
    return {"oracle_response": text}


def respond_node(state: dict[str, Any]) -> dict[str, Any]:
    """Extract a plain-text oracle_response from the last LLM message."""
    messages = state.get("messages", [])
    if not messages:
        return {"oracle_response": "I'm not sure how to respond to that."}

    last = messages[-1]
    if isinstance(last, AIMessage):
        content = last.content
        if isinstance(content, str) and content.strip():
            return {"oracle_response": content.strip()}

    # If the last message is a tool call with no text, give a minimal ack.
    return {"oracle_response": "Done."}


# ── Conditional routing ───────────────────────────────────────────────────────


def route_after_tools(state: dict[str, Any]) -> str:
    """Pure routing function — no side effects.

    Returns:
        "identify"    — exactly one candidate with sufficient evidence.
        "commentary"  — candidates changed this turn and ≤ 5 remain.
        "llm"         — loop back to the LLM.
    """
    candidates = state.get("candidates", [])
    confirmed = state.get("evidence_confirmed", [])
    difficulty = state.get("difficulty", "professional")
    prev_count = state.get("prev_candidate_count", len(all_ghost_names()))

    threshold = _EVIDENCE_THRESHOLD.get(difficulty, 3)

    if len(candidates) == 1 and len(confirmed) >= threshold:
        return "identify"

    if len(candidates) != prev_count and 1 < len(candidates) <= 5:
        return "commentary"

    return "llm"


def route_after_llm(state: dict[str, Any]) -> str:
    """Route after the LLM node: if the LLM emitted a tool call go to tools,
    otherwise go straight to respond."""
    messages = state.get("messages", [])
    if not messages:
        return "respond"
    last = messages[-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "respond"
