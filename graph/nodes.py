"""Graph nodes — two-stage chain: parse → execute → narrate.

Architecture:
  user_text → Deterministic Parser → Tool Execution → LLM Narrator
                    |
                    └── [no match] → LLM Classifier → Tool Execution → LLM Narrator
"""
from __future__ import annotations

import json
import logging
import re

from langchain_core.messages import SystemMessage, HumanMessage

from .intent_router import ParsedIntent, parse_intent
from .state import OracleState
from .tools import (
    bind_state,
    init_investigation,
    record_evidence,
    record_behavioral_event,
    get_investigation_state,
    query_ghost_database,
    suggest_next_evidence,
)

logger = logging.getLogger("oracle.nodes")

# ── System prompts ───────────────────────────────────────────────────────────

_NARRATOR_PROMPT = """\
You are Oracle — a sardonic, bone-dry British advisor who takes ghost identification \
seriously but finds the players' panic mildly amusing. Your tone is professional \
with an undercurrent of quiet exasperation. You never break character.

Given the tool result below, write EXACTLY 1-2 sentences summarizing what happened \
or answering the player's question. Never exceed 2 sentences. Never invent information \
not present in the tool result. Stay in character.

Tool result:
{tool_result}"""

_CLASSIFIER_PROMPT = """\
You are an intent classifier for a Phasmophobia ghost investigation tool.
Given the player's message, output ONLY valid JSON matching this schema — no other text:

{{"action": "record_evidence"|"init_investigation"|"record_behavioral_event"|"get_investigation_state"|"query_ghost_database"|"direct_response", \
"evidence_id": "emf_5"|"dots"|"uv"|"freezing"|"orb"|"writing"|"spirit_box", \
"status": "confirmed"|"ruled_out", \
"difficulty": "amateur"|"intermediate"|"professional"|"nightmare"|"insanity", \
"ghost_name": "string", \
"observation": "string", \
"eliminator_key": "string"}}

Include only the fields relevant to the action. Examples:

"we found freezing temps" → {{"action":"record_evidence","evidence_id":"freezing","status":"confirmed"}}
"no EMF 5" → {{"action":"record_evidence","evidence_id":"emf_5","status":"ruled_out"}}
"new game nightmare" → {{"action":"init_investigation","difficulty":"nightmare"}}
"what ghosts are left" → {{"action":"get_investigation_state"}}
"tell me about the Banshee" → {{"action":"query_ghost_database","ghost_name":"Banshee"}}
"ghost stepped in salt" → {{"action":"record_behavioral_event","observation":"ghost stepped in salt","eliminator_key":"ghost_stepped_in_salt"}}

RULES:
- "found/got/have/confirmed/detected" = status "confirmed"
- "no/ruled out/eliminated/doesn't have" = status "ruled_out"
- "freezing temps/temperatures" = evidence_id "freezing" (NOT emf_5)
- Output ONLY the JSON object. No explanation."""

_DIRECT_RESPONSE_PROMPT = """\
You are Oracle — a sardonic, bone-dry British advisor for Phasmophobia ghost identification.
Respond in EXACTLY 2 sentences using only the facts in the investigation state below. Stay in character.

{state_summary}"""


# ── Node: Deterministic intent parsing ───────────────────────────────────────

def parse_intent_node(state: OracleState) -> dict:
    """Deterministically parse user input into a structured intent."""
    intent = parse_intent(state.get("user_text", ""))
    logger.info("Parsed intent: action=%s, evidence=%s, status=%s, confidence=%.1f",
                intent.action, intent.evidence_id, intent.status, intent.confidence)
    return {"parsed_intent": intent.__dict__}


# ── Node: LLM fallback classifier ───────────────────────────────────────────

def llm_classify_node(state: OracleState) -> dict:
    """LLM-based intent classification for inputs the deterministic parser can't handle."""
    from .llm import get_llm

    llm = get_llm()
    user_text = state.get("user_text", "")
    summary = build_state_summary(state)

    messages = [
        SystemMessage(content=_CLASSIFIER_PROMPT),
        HumanMessage(content=f"{summary}\n\nPlayer says: {user_text}"),
    ]

    try:
        response = llm.invoke(messages)
        content = response.content.strip()

        # Try to parse JSON from the response
        try:
            intent_dict = json.loads(content)
        except json.JSONDecodeError:
            # Try extracting JSON from markdown code block or surrounding text
            match = re.search(r'\{[^}]+\}', content, re.DOTALL)
            if match:
                intent_dict = json.loads(match.group())
            else:
                logger.warning("LLM classifier returned unparseable response: %s", content)
                intent_dict = {"action": "direct_response"}

        logger.info("LLM classified intent: %s", intent_dict)
        return {"parsed_intent": intent_dict}

    except Exception as exc:
        logger.error("LLM classifier failed: %s", exc)
        return {"parsed_intent": {"action": "direct_response"}}


# ── Node: Tool execution ────────────────────────────────────────────────────

def execute_tool_node(state: OracleState) -> dict:
    """Execute the appropriate tool based on the parsed intent."""
    intent = state.get("parsed_intent", {})
    action = intent.get("action", "null")

    try:
        if action == "record_evidence":
            result = record_evidence.invoke({
                "evidence_id": intent.get("evidence_id", ""),
                "status": intent.get("status", "confirmed"),
            })
        elif action == "init_investigation":
            result = init_investigation.invoke({
                "difficulty": intent.get("difficulty", "professional"),
            })
        elif action == "get_investigation_state":
            result = get_investigation_state.invoke({})
        elif action == "query_ghost_database":
            result = query_ghost_database.invoke({
                "ghost_name": intent.get("ghost_name", ""),
                "field": intent.get("query_field", "") or intent.get("field", ""),
            })
        elif action == "suggest_next_evidence":
            result = suggest_next_evidence.invoke({})
        elif action == "record_behavioral_event":
            result = record_behavioral_event.invoke({
                "observation": intent.get("observation", ""),
                "eliminator_key": intent.get("eliminator_key", ""),
            })
        elif action == "direct_response":
            # No tool to call — the narrator will generate a response from state
            return {"tool_result": f"Player asked: {intent.get('raw_text', state.get('user_text', ''))}"}
        else:
            return {"tool_result": None}

        logger.info("Tool result: %s", result[:100] if result else "None")
        return {"tool_result": result}

    except Exception as exc:
        logger.error("Tool execution failed: %s", exc)
        return {"tool_result": f"Error: {exc}"}


# ── Node: LLM narrator ──────────────────────────────────────────────────────

def narrate_node(state: OracleState) -> dict:
    """Generate Oracle's persona response from the tool result."""
    tool_result = state.get("tool_result")

    if not tool_result:
        return {"oracle_response": None}

    intent = state.get("parsed_intent", {})

    # For direct responses (no tool was called), use state-aware prompt
    if intent.get("action") == "direct_response":
        from .llm import get_llm
        llm = get_llm()
        summary = build_state_summary(state)
        messages = [
            SystemMessage(content=_DIRECT_RESPONSE_PROMPT.format(state_summary=summary)),
            HumanMessage(content=state.get("user_text", "")),
        ]
        response = llm.invoke(messages)
        content = response.content.strip()
        if content.upper() == "NULL" or not content:
            return {"oracle_response": None}
        return {"oracle_response": content}

    # For tool results, narrate them with personality
    from .llm import get_llm
    llm = get_llm()
    messages = [
        SystemMessage(content=_NARRATOR_PROMPT.format(tool_result=tool_result)),
        HumanMessage(content="Write Oracle's response."),
    ]
    response = llm.invoke(messages)
    return {"oracle_response": response.content.strip()}


# ── Routing function ─────────────────────────────────────────────────────────

def route_after_parse(state: OracleState) -> str:
    """Route based on deterministic parse confidence."""
    intent = state.get("parsed_intent", {})
    if intent.get("action") == "llm_fallback":
        return "llm_classify"
    return "execute_tool"


# ── Helper ───────────────────────────────────────────────────────────────────

def build_state_summary(state: OracleState) -> str:
    """Build a terse state summary for the LLM's context window."""
    candidates = state.get("candidates", [])
    n = len(candidates)
    names = ", ".join(candidates) if n <= 12 else f"{n} ghosts"
    return (
        f"[Investigation State]\n"
        f"Difficulty: {state.get('difficulty', 'professional')}\n"
        f"Confirmed: {', '.join(state.get('evidence_confirmed', [])) or 'none'}\n"
        f"Ruled out: {', '.join(state.get('evidence_ruled_out', [])) or 'none'}\n"
        f"Eliminated: {', '.join(state.get('eliminated_ghosts', [])) or 'none'}\n"
        f"Candidates ({n}): {names}"
    )
