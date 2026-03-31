"""Pure Python deduction engine — no LLM, no external services.

This module is the algorithmic heart of Oracle. It loads ghost_database.yaml
once and exposes ``narrow_candidates()``, which deterministically returns the
ghosts still consistent with the current evidence state.

Hard invariants (see AGENTS.md):
- Zero imports from langchain / ollama / graph.llm — this stays testable with
  ``pytest`` and no running services.
- ``narrow_candidates`` is a pure function; it never mutates global state.
"""
from __future__ import annotations

from pathlib import Path

import yaml

# Module-level DB cache.  Loaded lazily on first call to load_db().
_DB: dict | None = None
_DB_PATH: str = "config/ghost_database.yaml"


# ── Database loading ──────────────────────────────────────────────────────────


def load_db(path: str | None = None) -> dict:
    """Load and cache the ghost database YAML.

    Args:
        path: Override path for testing.  Defaults to ``config/ghost_database.yaml``.

    Returns:
        Parsed YAML dict with a ``ghosts`` list and supporting sections.
    """
    global _DB
    if _DB is None:
        resolved = Path(path or _DB_PATH)
        with resolved.open(encoding="utf-8") as fh:
            _DB = yaml.safe_load(fh)
    return _DB


def reload_db(path: str | None = None) -> dict:
    """Force a reload of the database (useful in tests that swap YAML files)."""
    global _DB
    _DB = None
    return load_db(path)


def all_ghost_names() -> list[str]:
    """Return the canonical list of all 27 ghost names."""
    return [g["name"] for g in load_db()["ghosts"]]


# ── Core deduction ────────────────────────────────────────────────────────────


def narrow_candidates(
    confirmed: list[str],
    ruled_out: list[str],
    eliminated: list[str],
    difficulty: str,
) -> list[str]:
    """Return ghosts still consistent with the current evidence state.

    Rules applied in order:
    1. Ghosts in *eliminated* are always removed (behavioral evidence).
    2. Ruled-out evidence removes a ghost **unless** it is that ghost's
       ``fake_evidence`` (The Mimic's forced Ghost Orb is not real evidence).
    3. Confirmed evidence removes a ghost that lacks that evidence type,
       **except** on Nightmare difficulty where a ghost may hide exactly one
       non-guaranteed evidence (permissive — better to over-report candidates
       than to miss the real ghost).

    Args:
        confirmed:  Evidence IDs the player has confirmed present.
        ruled_out:  Evidence IDs the player has confirmed absent.
        eliminated: Ghost names removed via behavioral observation.
        difficulty: One of amateur / intermediate / professional / nightmare / insanity.

    Returns:
        List of ghost names that survive all filters.
    """
    db = load_db()
    candidates: list[str] = []

    for ghost in db["ghosts"]:
        name: str = ghost["name"]
        evidence_set: set[str] = set(ghost.get("evidence", []))
        fake: str | None = ghost.get("fake_evidence")  # e.g. "orb" for The Mimic

        # 1. Hard behavioural eliminator
        if name in eliminated:
            continue

        # 2. Ruled-out check
        if _ghost_has_ruled_out_evidence(evidence_set, ruled_out, fake):
            continue

        # 3. Confirmed check
        if _ghost_missing_confirmed_evidence(evidence_set, confirmed, difficulty):
            continue

        candidates.append(name)

    return candidates


def _ghost_has_ruled_out_evidence(
    evidence_set: set[str],
    ruled_out: list[str],
    fake: str | None,
) -> bool:
    """Return True if the ghost should be eliminated due to ruled-out evidence."""
    for e in ruled_out:
        if e in evidence_set:
            # The Mimic's fake_evidence is not a real evidence type for it
            if fake and e == fake:
                continue
            return True
    return False


def _ghost_missing_confirmed_evidence(
    evidence_set: set[str],
    confirmed: list[str],
    difficulty: str,
) -> bool:
    """Return True if the ghost should be eliminated due to missing confirmed evidence.

    On Nightmare the ghost can suppress one evidence; we are permissive and keep
    it in candidates rather than risk eliminating the real ghost.
    """
    if difficulty == "nightmare":
        # Permissive: any number of missing evidence is tolerated on Nightmare.
        # A stricter implementation could track guaranteed_evidence, but the
        # docs specify this should remain permissive for Nightmare.
        return False

    for e in confirmed:
        if e not in evidence_set:
            return True
    return False


# ── Observation eliminators ───────────────────────────────────────────────────


def apply_observation_eliminator(key: str) -> list[str]:
    """Return ghost names eliminated by a known behavioural-observation key.

    Args:
        key: Snake-case key from ``observation_eliminators`` in the YAML
             (e.g. ``"ghost_stepped_in_salt"``).

    Returns:
        List of ghost names to add to ``eliminated_ghosts``, or ``[]`` if the
        key is not recognised.
    """
    db = load_db()
    eliminators = db.get("observation_eliminators", {})

    entry = eliminators.get(key)
    if entry is None:
        return []
    return entry.get("eliminates", [])
