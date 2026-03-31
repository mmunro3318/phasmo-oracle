"""LangChain tool definitions — all state mutations happen here.

Hard invariants (see AGENTS.md):
- Every tool writes to the module-level ``_state`` dict bound by ``bind_state()``.
- Tools never create local copies of state and return them.
- DB writes are guarded: ``if session_id`` before any write call.
"""
from __future__ import annotations

import time
from typing import Any

from langchain_core.tools import tool

from graph.deduction import (
    all_ghost_names,
    apply_observation_eliminator,
    load_db,
    narrow_candidates,
)

# Module-level state dict.  Bound before each graph invocation via bind_state().
_state: dict[str, Any] = {}


def bind_state(state: dict[str, Any]) -> None:
    """Point the tools at the caller's live state dict."""
    global _state
    _state = state


def sync_state_from(target: dict[str, Any]) -> None:
    """Copy tool mutations from ``_state`` back into *target* after invoke()."""
    for key, value in _state.items():
        target[key] = value


# ── Tools ─────────────────────────────────────────────────────────────────────


@tool
def init_investigation(difficulty: str) -> str:
    """Start a new ghost investigation and reset all evidence.

    Args:
        difficulty: Game difficulty — amateur | intermediate | professional |
                    nightmare | insanity.
    """
    _state["difficulty"] = difficulty
    _state["evidence_confirmed"] = []
    _state["evidence_ruled_out"] = []
    _state["behavioral_observations"] = []
    _state["eliminated_ghosts"] = []
    _state["candidates"] = all_ghost_names()
    _state["session_start_time"] = time.time()
    _state["oracle_response"] = None

    session_id = _state.get("session_id")
    if session_id:
        from db.database import create_session

        create_session(session_id, difficulty, _state["session_start_time"])

    return (
        f"New investigation started on {difficulty}. "
        f"{len(_state['candidates'])} ghost candidates active."
    )


@tool
def record_evidence(evidence_id: str, status: str) -> str:
    """Record a confirmed or ruled-out evidence type and narrow candidates.

    Args:
        evidence_id: One of emf_5 | dots | uv | freezing | orb | writing | spirit_box.
        status: "confirmed" or "ruled_out".
    """
    confirmed: list[str] = _state.get("evidence_confirmed", [])
    ruled_out: list[str] = _state.get("evidence_ruled_out", [])
    eliminated: list[str] = _state.get("eliminated_ghosts", [])
    difficulty: str = _state.get("difficulty", "professional")

    if status == "confirmed" and evidence_id not in confirmed:
        confirmed = [*confirmed, evidence_id]
        _state["evidence_confirmed"] = confirmed
    elif status == "ruled_out" and evidence_id not in ruled_out:
        ruled_out = [*ruled_out, evidence_id]
        _state["evidence_ruled_out"] = ruled_out

    new_candidates = narrow_candidates(confirmed, ruled_out, eliminated, difficulty)
    _state["candidates"] = new_candidates

    session_id = _state.get("session_id")
    if session_id:
        from db.database import write_evidence_event

        elapsed = time.time() - (_state.get("session_start_time") or time.time())
        write_evidence_event(session_id, evidence_id, status, elapsed, len(new_candidates))

    names = ", ".join(new_candidates) if new_candidates else "none"
    return (
        f"{len(new_candidates)} candidates remain after recording {evidence_id} "
        f"as {status}: {names}"
    )


@tool
def record_behavioral_event(observation: str, eliminator_key: str | None = None) -> str:
    """Log a behavioural observation and optionally eliminate ghosts.

    Args:
        observation: Free-text description of what was observed.
        eliminator_key: Optional snake-case key from observation_eliminators in
                        ghost_database.yaml (e.g. "ghost_stepped_in_salt").
    """
    observations: list[str] = _state.get("behavioral_observations", [])
    observations = [*observations, observation]
    _state["behavioral_observations"] = observations

    eliminated: list[str] = _state.get("eliminated_ghosts", [])

    if eliminator_key:
        newly_eliminated = apply_observation_eliminator(eliminator_key)
        for name in newly_eliminated:
            if name not in eliminated:
                eliminated = [*eliminated, name]
        _state["eliminated_ghosts"] = eliminated

        confirmed = _state.get("evidence_confirmed", [])
        ruled_out = _state.get("evidence_ruled_out", [])
        difficulty = _state.get("difficulty", "professional")
        _state["candidates"] = narrow_candidates(confirmed, ruled_out, eliminated, difficulty)

    n = len(_state.get("candidates", []))
    if eliminator_key and newly_eliminated:  # type: ignore[possibly-undefined]
        return (
            f"Observation logged. Eliminated: {', '.join(newly_eliminated)}. "
            f"{n} candidates remain."
        )
    return f"Observation logged. {n} candidates remain."


@tool
def get_investigation_state() -> str:
    """Return a full summary of the current investigation state (read-only)."""
    confirmed = _state.get("evidence_confirmed", [])
    ruled_out = _state.get("evidence_ruled_out", [])
    observations = _state.get("behavioral_observations", [])
    candidates = _state.get("candidates", [])
    difficulty = _state.get("difficulty", "unknown")

    lines = [
        f"Difficulty: {difficulty}",
        f"Confirmed evidence: {', '.join(confirmed) if confirmed else 'none'}",
        f"Ruled-out evidence: {', '.join(ruled_out) if ruled_out else 'none'}",
        f"Observations: {len(observations)}",
        f"Candidates ({len(candidates)}): {', '.join(candidates) if candidates else 'none'}",
    ]
    return "\n".join(lines)


@tool
def query_ghost_database(ghost_name: str, field: str | None = None) -> str:
    """Look up a ghost in the database and return its properties.

    Args:
        ghost_name: Ghost name (case-insensitive).
        field: Optional specific field to return (e.g. "evidence", "hunt_threshold").
               If omitted, returns the full entry.
    """
    db = load_db()
    target = ghost_name.strip().lower()
    for ghost in db["ghosts"]:
        if ghost["name"].lower() == target:
            if field:
                value = ghost.get(field, "Field not found.")
                return f"{ghost['name']} — {field}: {value}"
            # Return a formatted summary
            lines = [f"**{ghost['name']}**"]
            for k, v in ghost.items():
                if k != "name":
                    lines.append(f"  {k}: {v}")
            return "\n".join(lines)
    return f"Ghost '{ghost_name}' not found in the database."


@tool
def record_ghost_event(event_type: str, detail: str | None = None) -> str:
    """Log a notable ghost event (hunt, interaction, manifestation, etc.).

    Args:
        event_type: Type of event — hunt | interaction | manifestation |
                    ghost_photo | fingerprint | footstep | other.
        detail: Optional free-text detail.
    """
    _GHOST_EVENT_TYPES = {
        "hunt",
        "interaction",
        "manifestation",
        "ghost_photo",
        "fingerprint",
        "footstep",
        "other",
    }
    normalised = event_type.lower() if event_type.lower() in _GHOST_EVENT_TYPES else "other"

    session_id = _state.get("session_id")
    if session_id:
        from db.database import write_ghost_event

        elapsed = time.time() - (_state.get("session_start_time") or time.time())
        write_ghost_event(session_id, normalised, detail or "", elapsed)

    return f"Ghost event recorded: {normalised}" + (f" — {detail}" if detail else ".")


@tool
def record_death(player: str | None = None) -> str:
    """Record a player death.

    Args:
        player: Player name. Defaults to the current speaker if omitted.
    """
    player_name = player or _state.get("speaker", "Unknown")

    session_id = _state.get("session_id")
    if session_id:
        from db.database import write_death

        elapsed = time.time() - (_state.get("session_start_time") or time.time())
        write_death(session_id, player_name, elapsed)
        # Increment in-memory death counter
        _state["death_count"] = _state.get("death_count", 0) + 1

    return f"{player_name}'s death recorded."


@tool
def confirm_true_ghost(ghost_name: str) -> str:
    """Confirm the actual ghost type after the investigation ends.

    Sets ``oracle_correct`` to 1 if Oracle's identification matched, 0 if not,
    or leaves it None if Oracle never reached a single candidate.

    Args:
        ghost_name: The ghost's actual name.
    """
    candidates = _state.get("candidates", [])
    if len(candidates) == 1:
        oracle_correct: int | None = 1 if candidates[0].lower() == ghost_name.strip().lower() else 0
    else:
        oracle_correct = None

    session_id = _state.get("session_id")
    if session_id:
        from db.database import close_session

        close_session(session_id, ghost_name, oracle_correct)

    correctness = {1: "correct", 0: "incorrect", None: "inconclusive"}[oracle_correct]
    return f"Investigation closed. True ghost: {ghost_name}. Oracle was {correctness}."


# Convenience list for tool binding in graph.py
ALL_TOOLS = [
    init_investigation,
    record_evidence,
    record_behavioral_event,
    get_investigation_state,
    query_ghost_database,
    record_ghost_event,
    record_death,
    confirm_true_ghost,
]
