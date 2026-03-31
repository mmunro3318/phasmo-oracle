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
        # real evidence set. Fake evidence is NOT real — ruling out orbs
        # does NOT eliminate the Mimic because those orbs are fake.
        skip = False
        for e in ruled_out:
            if e in evidence_set:
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
            # Nightmare/Insanity: ghost can hide non-guaranteed evidence.
            # Count how many confirmed types the ghost is missing.
            missing = [e for e in confirmed if e not in observable_set]
            # A ghost can hide at most 1 evidence on Nightmare, 2 on Insanity.
            # But it can NEVER hide its guaranteed evidence.
            max_hidden = 1 if difficulty == "nightmare" else 2
            if len(missing) > max_hidden:
                skip = True
            else:
                # Check that none of the missing evidence is guaranteed
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


def get_ghost(name: str) -> dict | None:
    """Return a ghost dict by name (case-insensitive), or None."""
    db = load_db()
    return next(
        (g for g in db["ghosts"] if g["name"].lower() == name.lower()),
        None,
    )
