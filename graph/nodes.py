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
    confirm_true_ghost,
    register_players,
    record_theory,
    StructuredToolResult,
)
from .deduction import (
    eliminate_by_guaranteed_evidence,
    evidence_threshold_reached,
    rank_discriminating_tests,
    get_ghost,
    load_db,
)

logger = logging.getLogger("oracle.nodes")

# ── System prompts ───────────────────────────────────────────────────────────

_NARRATOR_PROMPT = """\
You are Oracle — a sardonic, bone-dry British advisor who takes ghost identification \
seriously but finds the players' panic mildly amusing. Think dry BBC presenter \
meets reluctant paranormal consultant. You've seen too many amateurs scream at EMF \
readers to be impressed, but you do appreciate competent fieldwork.

Given the tool result below, write EXACTLY 1-2 sentences summarizing what happened \
or answering the player's question. Never exceed 2 sentences. Never invent information \
not present in the tool result. Stay in character.

Examples of your tone:
- "Spirit Box confirmed. Marvellous — now we're getting somewhere. That narrows things considerably."
- "No freezing temperatures. Cross that off the list, then, and do try not to touch the thermometer with your warm fingers next time."
- "Three candidates remain, and I assure you none of them are friendly."

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

    # Endgame guard: when investigation is over, only allow new game or endgame actions
    if not state.get("investigation_active", True):
        allowed = {"init_investigation", "confirm_true_ghost"}
        if intent.action not in allowed:
            return {"parsed_intent": {
                "action": "direct_response",
                "raw_text": "Investigation is over. Start a new investigation or tell me what the ghost was.",
            }}

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
        elif action == "confirm_true_ghost":
            ghost_name = intent.get("ghost_name", "")
            if not ghost_name:
                return {"tool_result": "Game over acknowledged. What was the ghost type?"}
            result = confirm_true_ghost.invoke({"ghost_name": ghost_name})
        elif action == "record_behavioral_event":
            result = record_behavioral_event.invoke({
                "observation": intent.get("observation", ""),
                "eliminator_key": intent.get("eliminator_key", ""),
            })
        elif action == "register_players":
            names = intent.get("player_names", [])
            result = register_players.invoke({
                "player_names": ", ".join(names) if isinstance(names, list) else str(names),
            })
        elif action == "record_theory":
            result = record_theory.invoke({
                "player_name": intent.get("player_name", ""),
                "ghost_name": intent.get("ghost_name", ""),
            })
        elif action == "query_tests":
            ghost_name = intent.get("ghost_name")
            if ghost_name:
                ghost = get_ghost(ghost_name)
                if ghost:
                    tests = ghost.get("community_tests", [])
                    if tests:
                        lines = [f"Tests for {ghost['name']}:"]
                        for t in tests:
                            lines.append(f"- {t.get('name', 'unnamed')}: {t.get('procedure', '')}")
                            if t.get("confidence"):
                                lines[-1] += f" (confidence: {t['confidence']})"
                        result = "\n".join(lines)
                    else:
                        result = (
                            f"No known community tests for {ghost['name']}. "
                            "Try checking behavioral tells instead."
                        )
                else:
                    result = f"Ghost '{ghost_name}' not found."
            else:
                # General test query — suggest discriminating tests
                candidates = state.get("candidates", [])
                ranked = rank_discriminating_tests(candidates)
                if ranked:
                    lines = ["Discriminating tests for remaining candidates:"]
                    for rt in ranked[:5]:  # Top 5
                        lines.append(
                            f"- [{rt.ghost_name}] {rt.test_name}: {rt.procedure}"
                        )
                    result = "\n".join(lines)
                else:
                    result = "No discriminating tests available for current candidates."
        elif action == "query_behavior":
            # Search behavioral profiles for a keyword
            keyword = intent.get("observation", "").lower()
            db = load_db()
            matches = []
            for g in db["ghosts"]:
                tells = g.get("behavioral_tells", [])
                flags = g.get("hard_flags", {})
                for tell in tells:
                    if keyword in tell.lower():
                        matches.append(f"{g['name']}: {tell}")
                for flag_key, flag_val in flags.items():
                    if keyword in flag_key.lower():
                        matches.append(f"{g['name']}: {flag_key} = {flag_val}")

            candidates = state.get("candidates", [])
            if matches:
                lines = [f"Ghosts with behavior matching '{keyword}':"]
                for m in matches:
                    ghost_name_part = m.split(":")[0]
                    status_tag = ""
                    if ghost_name_part not in candidates:
                        status_tag = " [ELIMINATED]"
                    lines.append(f"- {m}{status_tag}")
                result = "\n".join(lines)
            else:
                result = f"No ghost behaviors found matching '{keyword}'."
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

def _narrate_single_beat(tool_result: str, tone: str = "inform") -> str:
    """Narrate a single beat of a tool result with the Oracle persona."""
    from .llm import get_llm
    llm = get_llm()

    tone_directive = ""
    if tone == "warn":
        tone_directive = "\nTone: deliver this as a warning — something the player should be concerned about."
    elif tone == "celebrate":
        tone_directive = "\nTone: deliver this with satisfaction — a successful deduction."
    elif tone == "suggest":
        tone_directive = "\nTone: deliver this as a suggestion — guiding the player's next move."

    messages = [
        SystemMessage(content=_NARRATOR_PROMPT.format(tool_result=tool_result) + tone_directive),
        HumanMessage(content="Write Oracle's response."),
    ]
    response = llm.invoke(messages)
    return response.content.strip()


def narrate_node(state: OracleState) -> dict:
    """Generate Oracle's persona response from the tool result.

    Handles both plain string results (single narration call) and
    StructuredToolResult (beat-by-beat narration, capped at 2 in text mode).
    """
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

    # Handle StructuredToolResult (multi-beat)
    if isinstance(tool_result, StructuredToolResult):
        beats = tool_result.beats[:2]  # Cap at 2 beats in text mode
        narrated_parts = []
        for beat in beats:
            try:
                narrated = _narrate_single_beat(beat.content, beat.tone)
                narrated_parts.append(narrated)
            except Exception as exc:
                logger.error("Beat narration failed: %s", exc)
                # Return what we have so far
                break
        return {"oracle_response": "\n\n".join(narrated_parts) if narrated_parts else None}

    # For plain string tool results, narrate with personality
    narrated = _narrate_single_beat(str(tool_result))
    return {"oracle_response": narrated}


# ── Sprint 2: Post-tool conditional routing ─────────────────────────────────

def route_after_tools(state: OracleState) -> str:
    """Route after tool execution based on investigation state.

    Priority order:
    1. identify — 1 candidate + threshold reached + not yet identified
    2. phase_shift — threshold reached + >1 candidates + still in evidence phase
    3. comment — candidates changed this turn + 1 < n <= 5
    4. normal — everything else
    """
    candidates = state.get("candidates", [])
    confirmed = state.get("evidence_confirmed", [])
    difficulty = state.get("difficulty", "professional")
    n = len(candidates)

    threshold_met = evidence_threshold_reached(confirmed, difficulty)

    # Guard: already identified → normal
    if state.get("identified_ghost") is not None:
        return "normal"

    # 1. Identification
    if n == 1 and threshold_met:
        return "identify"

    # 2. Phase shift (only fires once — from evidence → behavioral)
    if (threshold_met
            and n > 1
            and state.get("investigation_phase") == "evidence"):
        return "phase_shift"

    # 3. Commentary on narrowed candidates
    prev_count = state.get("prev_candidate_count", 27)
    if n != prev_count and 1 < n <= 5:
        return "comment"

    return "normal"


def identify_node(state: OracleState) -> dict:
    """Announce ghost identification when 1 candidate remains."""
    candidates = state.get("candidates", [])
    if not candidates or state.get("identified_ghost") is not None:
        return {"tool_result": state.get("tool_result", "")}

    ghost_name = candidates[0]
    return {
        "identified_ghost": ghost_name,
        "tool_result": (
            f"IDENTIFICATION: The ghost is {ghost_name}. "
            "Lock it in on the whiteboard and get back to the truck."
        ),
    }


def phase_shift_node(state: OracleState) -> dict:
    """Run guaranteed evidence elimination and transition to behavioral phase."""
    candidates = list(state.get("candidates", []))
    confirmed = state.get("evidence_confirmed", [])
    difficulty = state.get("difficulty", "professional")

    # Run guaranteed evidence elimination
    remaining = eliminate_by_guaranteed_evidence(candidates, confirmed, difficulty)
    eliminated_by_ge = [c for c in candidates if c not in remaining]

    parts = []
    if eliminated_by_ge:
        parts.append(
            f"Eliminated {len(eliminated_by_ge)} ghost(s) missing guaranteed evidence: "
            f"{', '.join(eliminated_by_ge)}."
        )

    parts.append(
        f"That's all the hard evidence we're going to get on {difficulty}. "
        f"Remaining candidates ({len(remaining)}): {', '.join(remaining)}."
    )

    if remaining:
        parts.append("Let me suggest some behavioral tests to narrow it down further.")

    result = {
        "investigation_phase": "behavioral",
        "candidates": remaining,
        "tool_result": " ".join(parts),
    }

    # If guaranteed evidence elimination narrowed to 1, identify immediately
    if len(remaining) == 1:
        result["identified_ghost"] = remaining[0]
        result["tool_result"] += (
            f" IDENTIFICATION: The ghost is {remaining[0]}."
        )

    return result


def commentary_node(state: OracleState) -> dict:
    """Generate LLM commentary when candidates narrow to 5 or fewer."""
    candidates = state.get("candidates", [])
    tool_result = state.get("tool_result", "")
    n = len(candidates)

    commentary_context = (
        f"The candidate list just narrowed to {n}: {', '.join(candidates)}. "
        f"Previous tool result: {tool_result}"
    )

    try:
        from .llm import get_llm
        llm = get_llm()
        messages = [
            SystemMessage(content=(
                "You are Oracle — a sardonic, bone-dry British advisor for Phasmophobia. "
                "The candidate list just narrowed. Write EXACTLY 2 sentences: "
                "acknowledge the narrowing and suggest what to focus on next. "
                "Be specific about the remaining ghosts. Stay in character."
            )),
            HumanMessage(content=commentary_context),
        ]
        response = llm.invoke(messages)
        return {"oracle_response": response.content.strip()}
    except Exception as exc:
        logger.error("Commentary LLM failed: %s", exc)
        return {"oracle_response": f"Narrowed to {n} candidates: {', '.join(candidates)}."}


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
