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
    # ── Input ─────────────────────────────────────────────────────────────────
    user_text: str
    speaker: str  # "Mike" | "Kayden"
    difficulty: Difficulty

    # ── Evidence tracking ─────────────────────────────────────────────────────
    evidence_confirmed: list[EvidenceID]
    evidence_ruled_out: list[EvidenceID]
    behavioral_observations: list[str]

    # ── Deduction state (written by tools only, never by the LLM) ─────────────
    eliminated_ghosts: list[str]
    candidates: list[str]

    # ── Session metadata ──────────────────────────────────────────────────────
    session_id: str | None
    session_start_time: float | None

    # ── Turn metadata ─────────────────────────────────────────────────────────
    prev_candidate_count: int  # snapshotted before each invoke(); used by triggers

    # ── Output ────────────────────────────────────────────────────────────────
    oracle_response: str | None

    # ── LangGraph message thread (append-only, reset each turn) ───────────────
    messages: Annotated[list, operator.add]


def make_initial_state(difficulty: Difficulty = "professional", speaker: str = "Mike") -> OracleState:
    """Return a zeroed-out OracleState ready for the first investigation."""
    return OracleState(
        user_text="",
        speaker=speaker,
        difficulty=difficulty,
        evidence_confirmed=[],
        evidence_ruled_out=[],
        behavioral_observations=[],
        eliminated_ghosts=[],
        candidates=[],
        session_id=None,
        session_start_time=None,
        prev_candidate_count=27,
        oracle_response=None,
        messages=[],
    )
