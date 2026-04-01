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
    EVIDENCE_THRESHOLDS,
    evidence_threshold_reached,
)
from config.settings import config
from .state import DEFAULT_SOFT_FACTS

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
    _state["investigation_active"] = True
    _state["identified_ghost"] = None
    _state["true_ghost"] = None

    # Sprint 2 fields
    _state["investigation_phase"] = "evidence"
    _state["soft_facts"] = dict(DEFAULT_SOFT_FACTS)
    _state["players"] = []
    _state["theories"] = {}
    _state["prev_candidate_count"] = len(_state["candidates"])

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

    # Difficulty-aware evidence threshold
    difficulty = _state.get("difficulty", "professional")
    threshold = EVIDENCE_THRESHOLDS.get(difficulty, 3)

    # Phase rollback: if evidence was retracted below threshold, reset phase
    if (_state.get("investigation_phase") == "behavioral"
            and not evidence_threshold_reached(confirmed, difficulty)):
        _state["investigation_phase"] = "evidence"

    # Over-proofed / threshold detection
    if status == "confirmed" and len(confirmed) > threshold:
        if "orb" in confirmed:
            # Exceeding threshold with orbs = Mimic lock-in
            parts.append(
                f"{len(confirmed)} evidence types confirmed on {difficulty} difficulty "
                f"(max expected: {threshold}), including Ghost Orb. "
                "This is The Mimic — only The Mimic produces extra evidence via Ghost Orbs."
            )
        else:
            parts.append(
                f"{len(confirmed)} evidence types confirmed but {difficulty} difficulty "
                f"only allows {threshold}. "
                "You may have recorded something incorrectly — consider rechecking."
            )
    elif status == "confirmed" and len(confirmed) == threshold:
        # Threshold reached
        parts.append(
            f"That's {len(confirmed)} evidence confirmed — the maximum observable "
            f"on {difficulty} difficulty."
        )

    parts.append(f"{n} candidate(s) remain after recording {evidence_id} as {status}: {names}")

    # Definitive identification
    if n == 1:
        ghost_name = _state["candidates"][0]
        _state["identified_ghost"] = ghost_name
        parts.append(
            f"IDENTIFICATION: The ghost is {ghost_name}. "
            "Lock it in on the whiteboard and get back to the truck."
        )
    elif n == 0:
        parts.append(
            "No ghosts match this evidence combination. "
            "Something may be recorded incorrectly."
        )

    # Mimic awareness: when orbs are confirmed and Mimic is still a candidate
    if (status == "confirmed" and evidence_id == "orb"
            and "The Mimic" in _state["candidates"] and n > 1):
        parts.append(
            "Note: Ghost Orbs are present — The Mimic is always a possibility "
            "since it generates Ghost Orbs as fake evidence."
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

    # Full summary with evidence status relative to current investigation
    ge = ghost.get("guaranteed_evidence")
    ghost_evidence = ghost.get("evidence", [])
    confirmed = set(_state.get("evidence_confirmed", []))
    ruled_out = set(_state.get("evidence_ruled_out", []))

    # Show each evidence type with its status
    evidence_status_parts = []
    for e in ghost_evidence:
        label = _EVIDENCE_LABELS.get(e, e)
        if e in confirmed:
            evidence_status_parts.append(f"{label} (CONFIRMED)")
        elif e in ruled_out:
            evidence_status_parts.append(f"{label} (RULED OUT)")
        else:
            evidence_status_parts.append(f"{label} (untested)")

    # Check if ghost has fake evidence (Mimic)
    fake = ghost.get("fake_evidence")
    if fake:
        fake_label = _EVIDENCE_LABELS.get(fake, fake)
        evidence_status_parts.append(f"{fake_label} (fake — always present)")

    lines = [
        f"Ghost: {ghost['name']}",
        f"Evidence: {', '.join(evidence_status_parts)}",
        f"Guaranteed evidence (Nightmare): {ge or 'none'}",
        f"Hunt threshold: {ghost.get('hunt_threshold', {})}",
        f"Behavioral tells: {'; '.join(ghost.get('behavioral_tells', [])) or 'none'}",
    ]

    # Show which evidence still needs testing for this ghost
    remaining = [e for e in ghost_evidence if e not in confirmed and e not in ruled_out]
    if remaining:
        remaining_labels = [_EVIDENCE_LABELS.get(e, e) for e in remaining]
        lines.append(f"Still need to test: {', '.join(remaining_labels)}")

    return "\n".join(lines)


# ── Evidence labels for human-readable output ────────────────────────────────

_EVIDENCE_LABELS = {
    "emf_5": "EMF Level 5",
    "dots": "D.O.T.S. Projector",
    "uv": "Ultraviolet",
    "freezing": "Freezing Temperatures",
    "orb": "Ghost Orb",
    "writing": "Ghost Writing",
    "spirit_box": "Spirit Box",
}


@tool
def suggest_next_evidence() -> str:
    """Suggest which evidence types to test next based on current state.
    Call this when the player asks 'what should we do next?' or
    'what evidence should we look for?'
    """
    confirmed = set(_state.get("evidence_confirmed", []))
    ruled_out = set(_state.get("evidence_ruled_out", []))
    tested = confirmed | ruled_out
    remaining = VALID_EVIDENCE - tested

    difficulty = _state.get("difficulty", "professional")
    threshold = EVIDENCE_THRESHOLDS.get(difficulty, 3)
    candidates = _state.get("candidates", [])
    n_confirmed = len(confirmed)

    parts = []

    # Check if evidence threshold reached
    if n_confirmed >= threshold:
        parts.append(
            f"You've confirmed {n_confirmed} evidence type(s) — that's the maximum "
            f"observable on {difficulty} difficulty."
        )
        if len(candidates) == 1:
            parts.append(f"The ghost is {candidates[0]}.")
        elif len(candidates) <= 5:
            parts.append(f"Remaining candidates: {', '.join(candidates)}.")
            parts.append("Use behavioral observations or rule out evidence to narrow further.")
        else:
            parts.append(f"{len(candidates)} candidates remain. Rule out evidence to narrow the field.")
        return " ".join(parts)

    # Suggest remaining evidence
    if remaining:
        remaining_labels = [_EVIDENCE_LABELS.get(e, e) for e in sorted(remaining)]
        parts.append(f"Evidence not yet tested: {', '.join(remaining_labels)}.")

        # If candidates are narrow, suggest evidence that would help most
        if 1 < len(candidates) <= 8:
            # Find which untested evidence types appear most/least among candidates
            # to suggest the most discriminating one
            from .deduction import get_ghost
            evidence_counts: dict[str, int] = {}
            for e in remaining:
                count = sum(
                    1 for c in candidates
                    if (ghost := get_ghost(c)) and e in ghost.get("evidence", [])
                )
                evidence_counts[e] = count

            # Best discriminator: evidence that ~half the candidates have
            half = len(candidates) / 2
            best = min(evidence_counts, key=lambda e: abs(evidence_counts[e] - half))
            best_label = _EVIDENCE_LABELS.get(best, best)
            parts.append(f"Try {best_label} next — it will narrow the field most effectively.")
    else:
        parts.append("All evidence types have been tested.")

    parts.append(f"{len(candidates)} candidate(s) remain.")
    return " ".join(parts)


@tool
def confirm_true_ghost(ghost_name: str) -> str:
    """End the investigation by confirming what the ghost actually was.
    Call this when the player says 'it was a Wraith', 'the ghost was a Demon',
    'game over it was a Banshee', etc.
    """
    ghost = get_ghost(ghost_name)
    if not ghost:
        all_names = [g["name"] for g in load_db()["ghosts"]]
        return (
            f"Ghost '{ghost_name}' not found. "
            f"Known ghosts: {', '.join(all_names)}"
        )

    true_name = ghost["name"]
    _state["true_ghost"] = true_name
    _state["investigation_active"] = False

    identified = _state.get("identified_ghost")
    candidates = _state.get("candidates", [])
    confirmed_evidence = _state.get("evidence_confirmed", [])
    difficulty = _state.get("difficulty", "professional")

    parts = [f"Investigation complete. The ghost was {true_name}."]

    if identified:
        if identified == true_name:
            parts.append(f"Oracle correctly identified {true_name}.")
        else:
            parts.append(
                f"Oracle identified {identified}, but the ghost was actually {true_name}."
            )
    elif true_name in candidates:
        parts.append(f"{true_name} was among our {len(candidates)} remaining candidates.")
    else:
        parts.append(
            f"{true_name} was NOT in our candidate list. "
            "Evidence may have been recorded incorrectly."
        )

    parts.append(f"Evidence collected: {len(confirmed_evidence)} on {difficulty}.")
    parts.append("Tell me when you're ready for a new investigation.")

    return " ".join(parts)


# ── Multi-beat response structure ─────────────────────────────────────────────

from dataclasses import dataclass, field as dc_field


@dataclass
class ToolResultBeat:
    """A single beat in a multi-part Oracle response."""
    content: str
    tone: str = "inform"  # "inform" | "warn" | "celebrate" | "suggest"


@dataclass
class StructuredToolResult:
    """Multi-beat tool result. narrate_node handles each beat separately."""
    beats: list[ToolResultBeat] = dc_field(default_factory=list)


# ── Player registration + theory tools ───────────────────────────────────────

@tool
def register_players(player_names: str) -> str:
    """Register one or more players for this investigation.
    player_names: comma-separated names (e.g. 'Mike, Kayden')
    """
    names = [n.strip() for n in player_names.split(",") if n.strip()]
    if not names:
        return "No player names provided."

    existing = _state.setdefault("players", [])
    added = []
    for name in names:
        if name not in existing:
            existing.append(name)
            added.append(name)

    # Initialize theories for new players
    theories = _state.setdefault("theories", {})
    for name in added:
        if name not in theories:
            theories[name] = None

    if added:
        return f"Registered player(s): {', '.join(added)}. {len(existing)} total."
    return f"All players already registered. {len(existing)} total."


@tool
def record_theory(player_name: str, ghost_name: str) -> str:
    """Log a player's theory about the ghost type.
    player_name: who suspects this ghost
    ghost_name: which ghost they suspect
    """
    ghost = get_ghost(ghost_name)
    if not ghost:
        all_names = [g["name"] for g in load_db()["ghosts"]]
        return (
            f"Ghost '{ghost_name}' not found. "
            f"Known ghosts: {', '.join(all_names)}"
        )

    true_name = ghost["name"]
    players = _state.setdefault("players", [])
    theories = _state.setdefault("theories", {})

    # Auto-register unknown players
    if player_name not in players:
        players.append(player_name)

    old_theory = theories.get(player_name)
    theories[player_name] = true_name

    candidates = _state.get("candidates", [])
    parts = [f"{player_name}'s theory: {true_name}."]

    if old_theory and old_theory != true_name:
        parts.append(f"(Previously suspected {old_theory}.)")

    if true_name not in candidates:
        parts.append(
            f"Note: {true_name} has been eliminated based on current evidence. "
            "Either the theory is wrong, or evidence was recorded incorrectly."
        )

    return " ".join(parts)


ORACLE_TOOLS = [
    init_investigation,
    record_evidence,
    record_behavioral_event,
    get_investigation_state,
    query_ghost_database,
    suggest_next_evidence,
    confirm_true_ghost,
    register_players,
    record_theory,
]
