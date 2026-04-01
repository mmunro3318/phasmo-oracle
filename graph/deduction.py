"""Pure Python deduction engine — no LLM, ever.

This module loads ghost_database.yaml and narrows the candidate list
by evidence, ruled-out evidence, and behavioral eliminators. It is
fully testable with pytest and no running services.
"""
from __future__ import annotations

import yaml
from pathlib import Path

_DB: dict | None = None
_DB_PATH: str = str(Path(__file__).parent.parent / "config" / "ghost_database.yaml")


def load_db(path: str | None = None) -> dict:
    """Load and cache the ghost database from YAML."""
    global _DB
    if _DB is None:
        p = Path(path or _DB_PATH)
        with open(p) as f:
            _DB = yaml.safe_load(f)
    return _DB


def reset_db() -> None:
    """Clear the cached database (useful for testing)."""
    global _DB
    _DB = None


def all_ghost_names(path: str | None = None) -> list[str]:
    """Return the names of all ghosts in the database."""
    return [g["name"] for g in load_db(path)["ghosts"]]


def narrow_candidates(
    confirmed: list[str],
    ruled_out: list[str],
    eliminated: list[str],
    difficulty: str,
) -> list[str]:
    """Return ghosts consistent with the current evidence state.

    Rules:
    - A ghost is eliminated if it lacks any confirmed evidence type.
      Exception (Nightmare/Insanity): a ghost may hide non-guaranteed evidence.
    - A ghost is eliminated if it has any ruled-out evidence type.
      Exception (Mimic): its fake_evidence field is not real evidence.
    - A ghost explicitly in `eliminated` is always removed.
    """
    db = load_db()
    candidates = []
    permissive = difficulty in ("nightmare", "insanity")

    for ghost in db["ghosts"]:
        name = ghost["name"]
        evidence_set = set(ghost.get("evidence", []))
        fake = ghost.get("fake_evidence")  # e.g. "orb" for Mimic

        # The Mimic always produces its fake evidence (Ghost Orbs), so for
        # the purpose of checking confirmed evidence, fake_evidence counts
        # as an observable evidence type.
        observable_set = evidence_set | ({fake} if fake else set())

        # guaranteed_evidence can be a string or null — normalize to a set
        ge = ghost.get("guaranteed_evidence")
        guaranteed_set = {ge} if ge else set()

        if name in eliminated:
            continue

        # --- Ruled-out check ---
        # A ghost is eliminated if it has any ruled-out evidence in its
        # observable set. This includes fake_evidence — if Ghost Orbs are
        # ruled out, the Mimic is eliminated because it ALWAYS produces orbs.
        skip = False
        for e in ruled_out:
            if e in observable_set:
                skip = True
                break
        if skip:
            continue

        # --- Confirmed check ---
        # A ghost must have all confirmed evidence in its observable set
        # (real evidence + fake evidence). This means confirming Ghost Orbs
        # does NOT eliminate the Mimic, because orbs are in its observable set.
        if not permissive:
            # Standard mode: ghost must have ALL confirmed evidence
            for e in confirmed:
                if e not in observable_set:
                    skip = True
                    break
        else:
            # Nightmare/Insanity: the difficulty hides some real evidence,
            # but fake_evidence is NEVER hidden (Mimic always shows orbs).
            # So we check against observable_set but only allow hiding from
            # the real evidence_set.
            missing = [e for e in confirmed if e not in observable_set]
            # How many real evidence types could this ghost be hiding?
            max_hidden = 1 if difficulty == "nightmare" else 2
            if len(missing) > max_hidden:
                skip = True
            else:
                # Guaranteed evidence can never be hidden
                for m in missing:
                    if m in guaranteed_set:
                        skip = True
                        break

        if skip:
            continue

        candidates.append(name)

    return candidates


def apply_observation_eliminator(key: str) -> list[str]:
    """Return ghost names eliminated by a known observation key.

    Returns [] if key is not found in observation_eliminators.
    """
    db = load_db()
    eliminators = db.get("observation_eliminators", {})
    entry = eliminators.get(key)
    if entry is None:
        return []
    return entry.get("eliminates", [])


# ── Evidence thresholds by difficulty ──────────────────────────────────────

EVIDENCE_THRESHOLDS = {
    "amateur": 3,
    "intermediate": 3,
    "professional": 3,
    "nightmare": 2,
    "insanity": 1,
}


def evidence_threshold_reached(
    confirmed: list[str], difficulty: str
) -> bool:
    """Return True if confirmed evidence count meets the difficulty threshold."""
    threshold = EVIDENCE_THRESHOLDS.get(difficulty, 3)
    return len(confirmed) >= threshold


# ── Guaranteed evidence elimination (Sprint 2) ────────────────────────────

def eliminate_by_guaranteed_evidence(
    candidates: list[str],
    evidence_confirmed: list[str],
    difficulty: str,
) -> list[str]:
    """After evidence threshold reached, eliminate ghosts missing guaranteed evidence.

    On Nightmare/Insanity, some ghosts always show one specific evidence type.
    If that evidence wasn't observed despite reaching the threshold, the ghost
    can be eliminated.

    On Amateur/Intermediate/Professional all 3 evidence types are visible,
    so guaranteed evidence adds no extra elimination power — return unchanged.

    Mimic note: The Mimic has guaranteed_evidence=null and fake_evidence=orb.
    Since guaranteed is null, Mimic always survives this check (falls into the
    "no guaranteed evidence" branch). Mimic orb elimination is handled by the
    normal evidence deduction path.
    """
    if difficulty not in ("nightmare", "insanity"):
        return candidates

    db = load_db()
    confirmed_set = set(evidence_confirmed)
    remaining = []

    for name in candidates:
        ghost = next(
            (g for g in db["ghosts"] if g["name"] == name), None
        )
        if ghost is None:
            remaining.append(name)
            continue

        guaranteed = ghost.get("guaranteed_evidence")
        if guaranteed is None:
            # No guaranteed evidence — can't eliminate this way
            remaining.append(name)
        elif guaranteed in confirmed_set:
            # Guaranteed evidence was found — keep
            remaining.append(name)
        # else: guaranteed evidence NOT found — eliminate

    return remaining


# ── Discriminating test ranker (Sprint 2) ─────────────────────────────────

from dataclasses import dataclass


@dataclass
class RankedTest:
    """A community test ranked by its discrimination power."""
    ghost_name: str
    test_name: str
    procedure: str
    confidence: str
    score: float  # Higher = more discriminating


def rank_discriminating_tests(candidates: list[str]) -> list["RankedTest"]:
    """Return community tests ranked by how well they discriminate among candidates.

    A test unique to one ghost scores highest (confirms/denies that ghost).
    A test shared by all candidates scores 0 (tells you nothing).
    """
    if len(candidates) <= 1:
        # Single or zero candidates — return all tests for the one ghost unranked
        if candidates:
            ghost = get_ghost(candidates[0])
            if ghost:
                return [
                    RankedTest(
                        ghost_name=candidates[0],
                        test_name=t.get("name", "unnamed"),
                        procedure=t.get("procedure", ""),
                        confidence=t.get("confidence", "unknown"),
                        score=1.0,
                    )
                    for t in ghost.get("community_tests", [])
                ]
        return []

    # Collect all tests from all candidates
    all_tests: list[RankedTest] = []
    n = len(candidates)

    for name in candidates:
        ghost = get_ghost(name)
        if not ghost:
            continue
        for t in ghost.get("community_tests", []):
            # Score: how unique is this test to this ghost among candidates?
            # Count how many OTHER candidates also have a test with the same name
            test_name = t.get("name", "unnamed")
            shared_count = 0
            for other_name in candidates:
                if other_name == name:
                    continue
                other = get_ghost(other_name)
                if other and any(
                    ot.get("name") == test_name
                    for ot in other.get("community_tests", [])
                ):
                    shared_count += 1

            # Score: 1.0 if unique to this ghost, 0.0 if all candidates share it
            score = 1.0 - (shared_count / (n - 1)) if n > 1 else 1.0

            all_tests.append(RankedTest(
                ghost_name=name,
                test_name=test_name,
                procedure=t.get("procedure", ""),
                confidence=t.get("confidence", "unknown"),
                score=score,
            ))

    # Sort by score descending, then by ghost name for stability
    all_tests.sort(key=lambda t: (-t.score, t.ghost_name))
    return all_tests


# ── Soft fact eliminators (Sprint 2) ──────────────────────────────────────

def apply_soft_fact_eliminators(
    soft_facts: dict, candidates: list[str]
) -> list[str]:
    """Return ghost names that should be eliminated based on soft facts.

    Reads `soft_fact_eliminators` from each ghost's YAML entry.
    Returns a list of ghost names to eliminate (not the surviving list).
    """
    db = load_db()
    to_eliminate = []

    for name in candidates:
        ghost = next(
            (g for g in db["ghosts"] if g["name"] == name), None
        )
        if not ghost:
            continue

        eliminators = ghost.get("soft_fact_eliminators", {})
        for fact_key, rule in eliminators.items():
            fact_value = soft_facts.get(fact_key)
            # Skip unknown/unset facts
            if fact_value is None or fact_value == "unknown" or fact_value is False:
                continue
            eliminates_if = rule.get("eliminates_if")
            if eliminates_if is not None and fact_value == eliminates_if:
                if name not in to_eliminate:
                    to_eliminate.append(name)
                break  # One match is enough to eliminate

    return to_eliminate


def get_ghost(name: str) -> dict | None:
    """Return a ghost dict by name (case-insensitive), or None."""
    db = load_db()
    return next(
        (g for g in db["ghosts"] if g["name"].lower() == name.lower()),
        None,
    )
