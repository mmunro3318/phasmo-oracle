from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

EvidenceID = Literal[
    "emf_5", "dots", "uv", "freezing", "orb", "writing", "spirit_box"
]

Difficulty = Literal[
    "amateur", "intermediate", "professional", "nightmare", "insanity"
]


InvestigationPhase = Literal["evidence", "behavioral"]

# Default soft facts — reset on every new investigation
DEFAULT_SOFT_FACTS: dict = {
    "model_gender": "unknown",
    "ghost_age": None,
    "favorite_room_changed": False,
    "banshee_scream": False,
    "fusebox_emf": False,
    "turned_on_breaker": False,
    "freezing_breath_during_hunt": False,
    "ghost_turned_on_light_switch": False,
    "dots_visible_naked_eye": False,
    "ghost_stepped_in_salt": False,
    "ghost_hunted_from_player_room": False,
    "airball_event": False,
}


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

    # Sprint 2: Investigation phase + soft facts
    investigation_phase: InvestigationPhase  # "evidence" or "behavioral"
    soft_facts: dict  # Structured observational facts (see DEFAULT_SOFT_FACTS)
    prev_candidate_count: int  # Set in main.py before each invoke

    # Sprint 2: Player tracking
    players: list[str]  # ["Mike", "Kayden"]
    theories: dict  # {"Mike": "Wraith", "Kayden": None}

    # Two-stage chain state
    parsed_intent: dict  # Output of deterministic parser or LLM classifier
    tool_result: str | None  # Output of tool execution

    # Output
    oracle_response: str | None

    # LangGraph message history (append-only)
    messages: Annotated[list, operator.add]
