from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

EvidenceID = Literal[
    "emf_5", "dots", "uv", "freezing", "orb", "writing", "spirit_box"
]

Difficulty = Literal[
    "amateur", "intermediate", "professional", "nightmare", "insanity"
]


class OracleState(TypedDict):
    # Input
    user_text: str
    speaker: str
    difficulty: Difficulty

    # Evidence tracking
    evidence_confirmed: list[EvidenceID]
    evidence_ruled_out: list[EvidenceID]
    behavioral_observations: list[str]

    # Deduction (written by tools only, never by LLM)
    eliminated_ghosts: list[str]
    candidates: list[str]

    # Investigation lifecycle
    investigation_active: bool  # False after endgame confirmation
    identified_ghost: str | None  # Oracle's best guess (when 1 candidate remains)
    true_ghost: str | None  # Confirmed by player at end of game

    # Two-stage chain state
    parsed_intent: dict  # Output of deterministic parser or LLM classifier
    tool_result: str | None  # Output of tool execution

    # Output
    oracle_response: str | None

    # LangGraph message history (append-only)
    messages: Annotated[list, operator.add]
