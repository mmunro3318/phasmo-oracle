"""Tests for the pure-Python deduction engine.

These tests require no LLM, no audio, and no running services.  They must
always pass before any commit (see AGENTS.md).
"""
from __future__ import annotations

import pytest

from graph.deduction import (
    all_ghost_names,
    apply_observation_eliminator,
    narrow_candidates,
    reload_db,
)


# Reload the DB from the correct path for the test environment
@pytest.fixture(autouse=True)
def use_db(tmp_path):
    """Point the deduction engine at the project ghost_database.yaml."""
    reload_db("config/ghost_database.yaml")
    yield
    reload_db("config/ghost_database.yaml")


# ── Basic loading ─────────────────────────────────────────────────────────────


def test_all_ghosts_loaded():
    """Expect exactly 27 ghosts in the database."""
    assert len(all_ghost_names()) == 27


def test_all_ghost_names_are_strings():
    names = all_ghost_names()
    assert all(isinstance(n, str) for n in names)


# ── Confirmed evidence narrows candidates ─────────────────────────────────────


def test_no_evidence_returns_all_27():
    candidates = narrow_candidates([], [], [], "professional")
    assert len(candidates) == 27


def test_orb_confirmed_removes_non_orb_ghosts():
    candidates = narrow_candidates(["orb"], [], [], "professional")
    # All returned ghosts must list "orb" in their evidence
    from graph.deduction import load_db

    db = load_db()
    ghost_map = {g["name"]: set(g.get("evidence", [])) for g in db["ghosts"]}
    for name in candidates:
        assert "orb" in ghost_map[name], f"{name} has no orb evidence but survived"


def test_two_confirmed_further_narrows():
    c1 = narrow_candidates(["orb"], [], [], "professional")
    c2 = narrow_candidates(["orb", "writing"], [], [], "professional")
    assert len(c2) <= len(c1)


def test_impossible_evidence_combo_returns_empty():
    # All 7 evidence types confirmed — impossible for any single ghost
    all_evidence = ["emf_5", "dots", "uv", "freezing", "orb", "writing", "spirit_box"]
    candidates = narrow_candidates(all_evidence, [], [], "professional")
    assert candidates == []


# ── Ruled-out evidence eliminates ghosts ─────────────────────────────────────


def test_ruled_out_evidence_eliminates_matching_ghosts():
    full = narrow_candidates([], [], [], "professional")
    ruled_orb = narrow_candidates([], ["orb"], [], "professional")
    # Ruling out orb should remove some ghosts
    assert len(ruled_orb) < len(full)


def test_mimic_survives_orb_ruled_out():
    """The Mimic's fake_evidence orb must not eliminate it when orb is ruled out.

    This is a critical invariant — see AGENTS.md.
    """
    candidates = narrow_candidates([], ["orb"], [], "professional")
    assert "The Mimic" in candidates, "The Mimic should survive orb ruled-out"


# ── Behavioural eliminators ───────────────────────────────────────────────────


def test_eliminated_ghost_never_returns():
    full = all_ghost_names()
    for ghost in full:
        candidates = narrow_candidates([], [], [ghost], "professional")
        assert ghost not in candidates


def test_apply_observation_eliminator_salt():
    eliminated = apply_observation_eliminator("ghost_stepped_in_salt")
    assert "Wraith" in eliminated


def test_apply_observation_eliminator_unknown_key():
    eliminated = apply_observation_eliminator("nonexistent_key_xyz")
    assert eliminated == []


def test_behavioral_eliminator_removes_from_candidates():
    eliminated = apply_observation_eliminator("ghost_stepped_in_salt")
    candidates = narrow_candidates([], [], eliminated, "professional")
    assert "Wraith" not in candidates


# ── Difficulty modes ──────────────────────────────────────────────────────────


def test_nightmare_is_more_permissive_than_professional():
    """On Nightmare, evidence can be hidden so more ghosts remain as candidates."""
    evidence = ["emf_5", "freezing"]  # only 2 confirmed
    pro = narrow_candidates(evidence, [], [], "professional")
    nm = narrow_candidates(evidence, [], [], "nightmare")
    # Nightmare should have >= candidates than professional (permissive)
    assert len(nm) >= len(pro)


def test_professional_eliminates_ghosts_missing_confirmed():
    """On professional, a ghost lacking confirmed evidence is removed."""
    candidates_pro = narrow_candidates(["emf_5"], [], [], "professional")
    from graph.deduction import load_db

    db = load_db()
    ghost_map = {g["name"]: set(g.get("evidence", [])) for g in db["ghosts"]}
    for name in candidates_pro:
        assert "emf_5" in ghost_map[name]
