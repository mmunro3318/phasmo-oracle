"""Oracle tools — all state mutations happen here.

Tools read/write a shared mutable state dict. The bind_state() call
before each graph invoke points all tools at the live state.
"""
from __future__ import annotations

import yaml
from pathlib import Path
from langchain_core.tools import tool

from .deduction import (
    narrow_candidates,
    all_ghost_names,
    apply_observation_eliminator,
    get_ghost,
    load_db,
)
from config.settings import config

# ── Shared mutable state — bound before each graph invoke ────────────────────

_state: dict = {}


def bind_state(state: dict) -> None:
    """Point all tools at the current session state."""
    _state.clear()
    _state.update(state)


def sync_state_from(state: dict) -> None:
    """Pull back any mutations tools made into the caller's dict."""
    state.update(_state)


# ── Evidence synonym loading ─────────────────────────────────────────────────

_SYNONYMS: dict[str, str] | None = None


def _load_synonyms() -> dict[str, str]:
    global _SYNONYMS
    if _SYNONYMS is None:
        p = Path(config.SYNONYMS_PATH)
        if p.exists():
            with open(p) as f:
                raw = yaml.safe_load(f) or {}
            _SYNONYMS = {k.lower(): v for k, v in raw.items()}
        else:
            _SYNONYMS = {}
    return _SYNONYMS


def normalize_evidence_id(evidence_id: str) -> str:
    """Normalize an evidence ID using the synonym map.

    Returns the canonical ID if a synonym is found, otherwise
    returns the input unchanged (validation happens downstream).
    """
    synonyms = _load_synonyms()
    key = evidence_id.lower().strip()
    return synonyms.get(key, key)


# ── Canonical evidence IDs ───────────────────────────────────────────────────

VALID_EVIDENCE = {"emf_5", "dots", "uv", "freezing", "orb", "writing", "spirit_box"}


# ── Tools ────────────────────────────────────────────────────────────────────

@tool
def init_investigation(difficulty: str) -> str:
    """Start a new investigation. Resets all evidence, observations, and
    candidates to the full 27-ghost pool.
    difficulty must be one of: amateur, intermediate, professional, nightmare, insanity.
    """
    valid = {"amateur", "intermediate", "professional", "nightmare", "insanity"}
    if difficulty not in valid:
        difficulty = "professional"

    _state["difficulty"] = difficulty
    _state["evidence_confirmed"] = []
    _state["evidence_ruled_out"] = []
    _state["behavioral_observations"] = []
    _state["eliminated_ghosts"] = []
    _state["candidates"] = all_ghost_names()
    n = len(_state["candidates"])
    return f"New investigation started on {difficulty}. {n} ghost candidates active."


@tool
def record_evidence(evidence_id: str, status: str) -> str:
    """Record a confirmed or ruled-out evidence type.
    evidence_id: one of emf_5, dots, uv, freezing, orb, writing, spirit_box
    status: 'confirmed' or 'ruled_out'
    """
    # Normalize via synonym map
    evidence_id = normalize_evidence_id(evidence_id)

    if evidence_id not in VALID_EVIDENCE:
        return (
            f"Unknown evidence type '{evidence_id}'. "
            f"Valid types: {', '.join(sorted(VALID_EVIDENCE))}"
        )
    if status not in ("confirmed", "ruled_out"):
        return f"Invalid status '{status}'. Use 'confirmed' or 'ruled_out'."

    confirmed = _state.setdefault("evidence_confirmed", [])
    ruled_out = _state.setdefault("evidence_ruled_out", [])

    # Track status changes for user feedback
    status_changed = False
    old_status = None

    if status == "confirmed":
        if evidence_id in ruled_out:
            ruled_out.remove(evidence_id)
            status_changed = True
            old_status = "ruled_out"
        if evidence_id not in confirmed:
            confirmed.append(evidence_id)
    elif status == "ruled_out":
        if evidence_id in confirmed:
            confirmed.remove(evidence_id)
            status_changed = True
            old_status = "confirmed"
        if evidence_id not in ruled_out:
            ruled_out.append(evidence_id)

    # Re-run deduction
    _state["candidates"] = narrow_candidates(
        confirmed,
        ruled_out,
        _state.get("eliminated_ghosts", []),
        _state.get("difficulty", "professional"),
    )

    n = len(_state["candidates"])
    names = ", ".join(_state["candidates"]) if n <= 8 else f"{n} ghosts"
    parts = []

    # Status-change feedback
    if status_changed:
        evidence_label = load_db().get("evidence_types", {}).get(evidence_id, evidence_id)
        parts.append(
            f"{evidence_label} was previously {old_status.replace('_', ' ')}. "
            f"Updated to {status.replace('_', ' ')}."
        )

    # Over-proofed detection
    if len(confirmed) > 3:
        if len(confirmed) == 4 and "orb" in confirmed:
            parts.append(
                "4 evidence types confirmed (including Ghost Orb). "
                "This is very likely The Mimic, or you may have recorded something incorrectly."
            )
        else:
            parts.append(
                f"{len(confirmed)} evidence types confirmed. "
                "Ghosts can only have 3 evidence types. "
                "You may have recorded something incorrectly — consider rechecking."
            )

    parts.append(f"{n} candidate(s) remain after recording {evidence_id} as {status}: {names}")

    if n == 0:
        parts.append(
            "No ghosts match this evidence combination. "
            "Something may be recorded incorrectly."
        )

    return " ".join(parts)


@tool
def record_behavioral_event(observation: str, eliminator_key: str = "") -> str:
    """Log a behavioral observation in free text.
    If eliminator_key matches a known pattern (e.g. 'ghost_stepped_in_salt'),
    those ghosts are immediately removed from candidates.
    Leave eliminator_key empty if no known eliminator applies.
    """
    _state.setdefault("behavioral_observations", []).append(observation)

    newly_eliminated = []
    if eliminator_key:
        to_eliminate = apply_observation_eliminator(eliminator_key)
        existing = _state.setdefault("eliminated_ghosts", [])
        for ghost_name in to_eliminate:
            if ghost_name not in existing:
                existing.append(ghost_name)
                newly_eliminated.append(ghost_name)

        if newly_eliminated:
            _state["candidates"] = narrow_candidates(
                _state.get("evidence_confirmed", []),
                _state.get("evidence_ruled_out", []),
                _state["eliminated_ghosts"],
                _state.get("difficulty", "professional"),
            )

    n = len(_state.get("candidates", []))
    if newly_eliminated:
        return (
            f"Observation logged. Eliminated: {', '.join(newly_eliminated)}. "
            f"{n} candidate(s) remain."
        )
    return f"Observation logged. {n} candidate(s) remain."


@tool
def get_investigation_state() -> str:
    """Return a full summary of the current investigation state: difficulty,
    confirmed evidence, ruled-out evidence, observations, eliminated ghosts,
    and remaining candidates.
    """
    s = _state
    candidates = s.get("candidates", [])
    n = len(candidates)
    names = ", ".join(candidates) if n <= 12 else f"{n} ghosts (use record_evidence to narrow)"
    lines = [
        f"Difficulty: {s.get('difficulty', 'unknown')}",
        f"Confirmed evidence ({len(s.get('evidence_confirmed', []))}): "
        f"{', '.join(s.get('evidence_confirmed', [])) or 'none'}",
        f"Ruled out ({len(s.get('evidence_ruled_out', []))}): "
        f"{', '.join(s.get('evidence_ruled_out', [])) or 'none'}",
        f"Behavioral observations: {len(s.get('behavioral_observations', []))} logged",
        f"Eliminated ghosts: {', '.join(s.get('eliminated_ghosts', [])) or 'none'}",
        f"Candidates ({n}): {names}",
    ]
    return "\n".join(lines)


@tool
def query_ghost_database(ghost_name: str, field: str = "") -> str:
    """Look up a ghost in the database by name.
    Optional field: evidence, hunt_threshold, behavioral_tells, community_tests, hard_flags.
    Leave field empty for a full summary.
    """
    ghost = get_ghost(ghost_name)
    if not ghost:
        all_names = [g["name"] for g in load_db()["ghosts"]]
        return (
            f"Ghost '{ghost_name}' not found. "
            f"Known ghosts: {', '.join(all_names)}"
        )

    if field:
        val = ghost.get(field)
        if val is None:
            return f"Field '{field}' not found for {ghost['name']}."
        return f"{ghost['name']} — {field}: {val}"

    # Full summary
    ge = ghost.get("guaranteed_evidence")
    lines = [
        f"Ghost: {ghost['name']}",
        f"Evidence: {', '.join(ghost.get('evidence', []))}",
        f"Guaranteed evidence (Nightmare): {ge or 'none'}",
        f"Hunt threshold: {ghost.get('hunt_threshold', {})}",
        f"Hard flags: {ghost.get('hard_flags', {})}",
        f"Behavioral tells: {'; '.join(ghost.get('behavioral_tells', [])) or 'none'}",
        f"Community tests: {'; '.join(t.get('name', '') for t in ghost.get('community_tests', [])) or 'none'}",
    ]
    return "\n".join(lines)


ORACLE_TOOLS = [
    init_investigation,
    record_evidence,
    record_behavioral_event,
    get_investigation_state,
    query_ghost_database,
]
