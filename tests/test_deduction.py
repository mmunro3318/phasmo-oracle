"""Comprehensive tests for graph/deduction.py — no Ollama required.

Tests cover: ghost loading, evidence-based narrowing, difficulty modes,
observation eliminators, Mimic fake-evidence handling, and edge cases.
"""
from __future__ import annotations

import pytest

from graph.deduction import (
    all_ghost_names,
    apply_observation_eliminator,
    get_ghost,
    load_db,
    narrow_candidates,
    reset_db,
)


@pytest.fixture(autouse=True)
def _fresh_db():
    """Reset the cached DB before every test so mutations don't leak."""
    reset_db()
    yield
    reset_db()


@pytest.fixture()
def db():
    """Provide the loaded ghost database dict."""
    return load_db()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ghost_evidence_params():
    """Build parametrize args from the live YAML: (name, evidence_list)."""
    reset_db()
    db = load_db()
    params = []
    for g in db["ghosts"]:
        params.append(pytest.param(g["name"], g["evidence"], id=g["name"]))
    reset_db()
    return params


# ---------------------------------------------------------------------------
# 1. test_all_ghosts_loaded — exactly 27 ghosts
# ---------------------------------------------------------------------------

def test_all_ghosts_loaded():
    names = all_ghost_names()
    assert len(names) == 27, f"Expected 27 ghosts, got {len(names)}: {names}"
    # No duplicates
    assert len(set(names)) == 27


# ---------------------------------------------------------------------------
# 2. Parametrized: confirm evidence keeps ghost, rule-out removes it
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ghost_name, evidence", _ghost_evidence_params())
def test_confirming_evidence_keeps_ghost(ghost_name, evidence):
    """Confirming all of a ghost's own evidence must keep it as a candidate."""
    candidates = narrow_candidates(
        confirmed=list(evidence),
        ruled_out=[],
        eliminated=[],
        difficulty="professional",
    )
    assert ghost_name in candidates, (
        f"{ghost_name} should survive when its own evidence "
        f"{evidence} is confirmed, but candidates = {candidates}"
    )


@pytest.mark.parametrize("ghost_name, evidence", _ghost_evidence_params())
def test_ruling_out_evidence_eliminates_ghost(ghost_name, evidence):
    """Ruling out one of a ghost's real evidence types must eliminate it.

    Exception: The Mimic's fake_evidence (orb) can be ruled out without
    eliminating The Mimic — that case is covered by a dedicated test.
    """
    ghost_data = get_ghost(ghost_name)
    fake = ghost_data.get("fake_evidence")

    for ev in evidence:
        if fake and ev == fake:
            # Ruling out fake evidence should NOT eliminate this ghost
            continue

        candidates = narrow_candidates(
            confirmed=[],
            ruled_out=[ev],
            eliminated=[],
            difficulty="professional",
        )
        assert ghost_name not in candidates, (
            f"{ghost_name} should be eliminated when '{ev}' is ruled out, "
            f"but it survived. candidates = {candidates}"
        )


# ---------------------------------------------------------------------------
# 3. test_single_evidence_narrows
# ---------------------------------------------------------------------------

def test_single_evidence_narrows():
    """Confirming one evidence type must reduce candidates below 27."""
    candidates = narrow_candidates(
        confirmed=["emf_5"],
        ruled_out=[],
        eliminated=[],
        difficulty="professional",
    )
    assert 0 < len(candidates) < 27


# ---------------------------------------------------------------------------
# 4. test_three_evidence_identifies_banshee
# ---------------------------------------------------------------------------

def test_three_evidence_identifies_banshee():
    """EMF 5 + UV + DOTS should keep Banshee (it has dots, orb, uv — but
    we're confirming dots + uv + emf_5).  Actually Banshee has [dots, orb, uv],
    so confirming [emf_5, uv, dots] should keep Banshee and also Goryo
    (dots, emf_5, uv).  Let's verify Banshee is present."""
    candidates = narrow_candidates(
        confirmed=["emf_5", "uv", "dots"],
        ruled_out=[],
        eliminated=[],
        difficulty="professional",
    )
    # Banshee has [dots, orb, uv] — it does NOT have emf_5, so it should
    # actually be eliminated on professional.  Goryo has [dots, emf_5, uv].
    # Re-check: the prompt says "EMF 5 + UV + DOTS keeps Banshee" — but
    # Banshee's evidence is [dots, orb, uv].  On professional, confirming
    # emf_5 would eliminate Banshee.  The correct 3-evidence combo for
    # Banshee is dots + orb + uv.
    #
    # We test the *correct* Banshee combo instead:
    candidates = narrow_candidates(
        confirmed=["dots", "orb", "uv"],
        ruled_out=[],
        eliminated=[],
        difficulty="professional",
    )
    assert "Banshee" in candidates


# ---------------------------------------------------------------------------
# 5. test_ruled_out_removes_ghost
# ---------------------------------------------------------------------------

def test_ruled_out_removes_banshee():
    """Ruling out UV should remove Banshee (Banshee has uv)."""
    candidates = narrow_candidates(
        confirmed=[],
        ruled_out=["uv"],
        eliminated=[],
        difficulty="professional",
    )
    assert "Banshee" not in candidates


# ---------------------------------------------------------------------------
# 6. test_explicit_elimination
# ---------------------------------------------------------------------------

def test_explicit_elimination():
    """Adding Wraith to the eliminated list removes it regardless of evidence."""
    candidates = narrow_candidates(
        confirmed=[],
        ruled_out=[],
        eliminated=["Wraith"],
        difficulty="professional",
    )
    assert "Wraith" not in candidates
    # Other ghosts should still be present
    assert len(candidates) == 26


# ---------------------------------------------------------------------------
# 7. test_mimic_survives_orb_ruled_out  (CRITICAL)
# ---------------------------------------------------------------------------

def test_mimic_eliminated_when_orb_ruled_out():
    """The Mimic ALWAYS produces Ghost Orbs (fake evidence). If orbs are ruled
    out, it CANNOT be the Mimic. This is the inverse of the Mimic's special rule."""
    candidates = narrow_candidates(
        confirmed=[],
        ruled_out=["orb"],
        eliminated=[],
        difficulty="professional",
    )
    assert "The Mimic" not in candidates, (
        "The Mimic must be eliminated when orb is ruled out — Mimic always produces orbs"
    )


def test_mimic_survives_orb_confirmed():
    """CRITICAL: Confirming Ghost Orbs must NOT eliminate The Mimic.
    The Mimic always produces ghost orbs via fake_evidence — orbs are
    observable evidence for the Mimic even though they're not 'real'."""
    candidates = narrow_candidates(
        confirmed=["orb"],
        ruled_out=[],
        eliminated=[],
        difficulty="professional",
    )
    assert "The Mimic" in candidates


def test_mimic_survives_orb_plus_real_evidence():
    """Confirming orb + one of Mimic's real evidence should keep Mimic."""
    # Mimic's real evidence: uv, freezing, spirit_box
    candidates = narrow_candidates(
        confirmed=["orb", "uv"],
        ruled_out=[],
        eliminated=[],
        difficulty="professional",
    )
    assert "The Mimic" in candidates


def test_mimic_survives_on_nightmare_with_orb():
    """On Nightmare, Mimic with confirmed orb should survive."""
    candidates = narrow_candidates(
        confirmed=["orb", "freezing"],
        ruled_out=[],
        eliminated=[],
        difficulty="nightmare",
    )
    assert "The Mimic" in candidates


def test_mimic_survives_on_insanity_with_orb():
    """On Insanity, Mimic with confirmed orb should survive."""
    candidates = narrow_candidates(
        confirmed=["orb"],
        ruled_out=[],
        eliminated=[],
        difficulty="insanity",
    )
    assert "The Mimic" in candidates


def test_mimic_eliminated_by_real_evidence():
    """Ruling out one of The Mimic's real evidence types SHOULD eliminate it."""
    # The Mimic's real evidence: [uv, freezing, spirit_box]
    for ev in ("uv", "freezing", "spirit_box"):
        candidates = narrow_candidates(
            confirmed=[],
            ruled_out=[ev],
            eliminated=[],
            difficulty="professional",
        )
        assert "The Mimic" not in candidates, (
            f"The Mimic should be eliminated when real evidence '{ev}' is ruled out"
        )


# ---------------------------------------------------------------------------
# 8. test_salt_eliminates_wraith
# ---------------------------------------------------------------------------

def test_salt_eliminates_wraith():
    eliminated = apply_observation_eliminator("ghost_stepped_in_salt")
    assert eliminated == ["Wraith"]


# ---------------------------------------------------------------------------
# 9. test_unknown_key_returns_empty
# ---------------------------------------------------------------------------

def test_unknown_key_returns_empty():
    result = apply_observation_eliminator("ghost_did_a_backflip")
    assert result == []


# ---------------------------------------------------------------------------
# 10. test_nightmare_is_permissive
# ---------------------------------------------------------------------------

def test_nightmare_is_permissive():
    """Nightmare mode should keep more candidates than Professional for
    the same confirmed evidence, because ghosts can hide one evidence."""
    confirmed = ["emf_5", "dots"]
    pro = narrow_candidates(confirmed, [], [], "professional")
    night = narrow_candidates(confirmed, [], [], "nightmare")
    assert len(night) >= len(pro), (
        f"Nightmare ({len(night)}) should keep at least as many as "
        f"Professional ({len(pro)})"
    )
    # Nightmare should actually keep strictly more because some ghosts
    # that lack one of the two types can hide it.
    assert len(night) > len(pro), (
        "Nightmare should keep strictly more candidates than Professional"
    )


# ---------------------------------------------------------------------------
# 11. test_insanity_more_permissive
# ---------------------------------------------------------------------------

def test_insanity_more_permissive():
    """Insanity allows hiding 2 evidence, so it should keep even more
    candidates than Nightmare for the same confirmed evidence."""
    confirmed = ["emf_5", "dots"]
    night = narrow_candidates(confirmed, [], [], "nightmare")
    insanity = narrow_candidates(confirmed, [], [], "insanity")
    assert len(insanity) >= len(night), (
        f"Insanity ({len(insanity)}) should keep at least as many as "
        f"Nightmare ({len(night)})"
    )
    assert len(insanity) > len(night), (
        "Insanity should keep strictly more candidates than Nightmare"
    )


# ---------------------------------------------------------------------------
# 12. test_zero_candidates
# ---------------------------------------------------------------------------

def test_zero_candidates():
    """Conflicting evidence (confirm + rule-out the same type) should
    produce an empty candidate list since no ghost can satisfy both."""
    # Confirm all 7 evidence types — no ghost has all 7
    all_types = ["emf_5", "dots", "uv", "freezing", "orb", "writing", "spirit_box"]
    candidates = narrow_candidates(
        confirmed=all_types,
        ruled_out=[],
        eliminated=[],
        difficulty="professional",
    )
    assert candidates == [], f"Expected no candidates but got {candidates}"


# ---------------------------------------------------------------------------
# 13. test_empty_state_returns_all
# ---------------------------------------------------------------------------

def test_empty_state_returns_all():
    """No evidence, no eliminations should return all 27 ghosts."""
    candidates = narrow_candidates([], [], [], "professional")
    assert len(candidates) == 27


# ---------------------------------------------------------------------------
# 14. test_get_ghost_case_insensitive
# ---------------------------------------------------------------------------

def test_get_ghost_case_insensitive():
    ghost = get_ghost("banshee")
    assert ghost is not None
    assert ghost["name"] == "Banshee"

    ghost2 = get_ghost("BANSHEE")
    assert ghost2 is not None
    assert ghost2["name"] == "Banshee"

    ghost3 = get_ghost("the mimic")
    assert ghost3 is not None
    assert ghost3["name"] == "The Mimic"


# ---------------------------------------------------------------------------
# 15. test_get_ghost_not_found
# ---------------------------------------------------------------------------

def test_get_ghost_not_found():
    assert get_ghost("NotAGhost") is None
    assert get_ghost("") is None


# ---------------------------------------------------------------------------
# Bonus: observation eliminators dict structure
# ---------------------------------------------------------------------------

def test_observation_eliminators_are_dict(db):
    """observation_eliminators must be a dict keyed by name, not a list."""
    elims = db.get("observation_eliminators", {})
    assert isinstance(elims, dict), (
        f"observation_eliminators should be a dict, got {type(elims)}"
    )
    # Each entry should have an 'eliminates' or 'eliminates_all_except' key
    for key, entry in elims.items():
        assert isinstance(entry, dict), f"Entry '{key}' should be a dict"
        has_elim = "eliminates" in entry or "eliminates_all_except" in entry
        assert has_elim, f"Entry '{key}' missing eliminates/eliminates_all_except"


def test_nightmare_does_not_hide_guaranteed_evidence():
    """On Nightmare, a ghost should not survive if its guaranteed evidence
    is missing from the confirmed list AND a conflicting evidence is confirmed.

    Specifically: Goryo has guaranteed_evidence='dots'.  On nightmare, if we
    confirm an evidence type Goryo does NOT have and does NOT include dots,
    Goryo should be eliminated because it cannot hide its guaranteed evidence."""
    # Goryo: [dots, emf_5, uv], guaranteed: dots
    # Confirm spirit_box (Goryo doesn't have it).  On nightmare, Goryo can
    # hide 1 non-guaranteed evidence — but spirit_box is the missing one,
    # and that's only 1 missing, so Goryo would survive if we only confirm
    # spirit_box.  Let's confirm TWO things Goryo lacks: spirit_box + writing.
    candidates = narrow_candidates(
        confirmed=["spirit_box", "writing"],
        ruled_out=[],
        eliminated=[],
        difficulty="nightmare",
    )
    # Goryo lacks both spirit_box and writing — that's 2 missing, but
    # nightmare only allows hiding 1.  So Goryo should be eliminated.
    assert "Goryo" not in candidates

    # But Deogen (dots, writing, spirit_box) has both — should survive.
    assert "Deogen" in candidates


# ---------------------------------------------------------------------------
# Sprint 2: evidence_threshold_reached
# ---------------------------------------------------------------------------

class TestEvidenceThresholdReached:

    def test_threshold_met_exactly(self):
        from graph.deduction import evidence_threshold_reached
        assert evidence_threshold_reached(["emf_5", "dots", "uv"], "professional") is True

    def test_threshold_exceeded(self):
        from graph.deduction import evidence_threshold_reached
        assert evidence_threshold_reached(["a", "b", "c", "d"], "professional") is True

    def test_threshold_not_met(self):
        from graph.deduction import evidence_threshold_reached
        assert evidence_threshold_reached(["emf_5"], "professional") is False

    def test_nightmare_threshold_two(self):
        from graph.deduction import evidence_threshold_reached
        assert evidence_threshold_reached(["emf_5", "dots"], "nightmare") is True
        assert evidence_threshold_reached(["emf_5"], "nightmare") is False

    def test_insanity_threshold_one(self):
        from graph.deduction import evidence_threshold_reached
        assert evidence_threshold_reached(["emf_5"], "insanity") is True
        assert evidence_threshold_reached([], "insanity") is False


# ---------------------------------------------------------------------------
# Sprint 2: eliminate_by_guaranteed_evidence
# ---------------------------------------------------------------------------

class TestEliminateByGuaranteedEvidence:
    from graph.deduction import eliminate_by_guaranteed_evidence

    def test_professional_returns_unchanged(self):
        from graph.deduction import eliminate_by_guaranteed_evidence
        candidates = ["Goryo", "Hantu", "Moroi"]
        result = eliminate_by_guaranteed_evidence(candidates, ["emf_5"], "professional")
        assert result == candidates

    def test_nightmare_keeps_ghost_with_confirmed_guaranteed(self):
        from graph.deduction import eliminate_by_guaranteed_evidence
        # Goryo guaranteed=dots, Hantu guaranteed=freezing
        result = eliminate_by_guaranteed_evidence(
            ["Goryo", "Hantu"], ["dots"], "nightmare"
        )
        assert "Goryo" in result
        assert "Hantu" not in result  # freezing not confirmed

    def test_nightmare_keeps_ghost_without_guaranteed(self):
        from graph.deduction import eliminate_by_guaranteed_evidence
        # Banshee has guaranteed_evidence=null
        result = eliminate_by_guaranteed_evidence(
            ["Banshee", "Goryo"], ["dots"], "nightmare"
        )
        assert "Banshee" in result  # null guaranteed — can't eliminate
        assert "Goryo" in result    # dots confirmed

    def test_insanity_eliminates_missing_guaranteed(self):
        from graph.deduction import eliminate_by_guaranteed_evidence
        # Deogen guaranteed=spirit_box, Moroi guaranteed=spirit_box
        result = eliminate_by_guaranteed_evidence(
            ["Deogen", "Moroi", "Banshee"],
            ["freezing"],  # neither spirit_box confirmed
            "insanity"
        )
        assert "Deogen" not in result
        assert "Moroi" not in result
        assert "Banshee" in result  # null guaranteed

    def test_mimic_survives_guaranteed_check(self):
        from graph.deduction import eliminate_by_guaranteed_evidence
        # The Mimic has guaranteed_evidence=null, fake_evidence=orb
        result = eliminate_by_guaranteed_evidence(
            ["The Mimic", "Goryo"], ["emf_5"], "nightmare"
        )
        assert "The Mimic" in result  # null guaranteed — survives
        assert "Goryo" not in result  # dots not confirmed

    def test_empty_candidates(self):
        from graph.deduction import eliminate_by_guaranteed_evidence
        result = eliminate_by_guaranteed_evidence([], ["dots"], "nightmare")
        assert result == []


# ---------------------------------------------------------------------------
# Sprint 2: rank_discriminating_tests
# ---------------------------------------------------------------------------

class TestRankDiscriminatingTests:

    def test_distinct_tests_ranked(self):
        from graph.deduction import rank_discriminating_tests
        # Goryo and Banshee have different community tests
        result = rank_discriminating_tests(["Goryo", "Banshee"])
        assert len(result) > 0
        # Each test should have a score
        for rt in result:
            assert 0.0 <= rt.score <= 1.0

    def test_single_candidate_returns_its_tests(self):
        from graph.deduction import rank_discriminating_tests
        result = rank_discriminating_tests(["Goryo"])
        assert len(result) > 0
        assert all(rt.ghost_name == "Goryo" for rt in result)

    def test_zero_candidates_returns_empty(self):
        from graph.deduction import rank_discriminating_tests
        result = rank_discriminating_tests([])
        assert result == []

    def test_unique_test_scores_high(self):
        from graph.deduction import rank_discriminating_tests
        result = rank_discriminating_tests(["Goryo", "Banshee"])
        # Tests unique to one ghost should score 1.0
        unique_tests = [rt for rt in result if rt.score == 1.0]
        assert len(unique_tests) > 0


# ---------------------------------------------------------------------------
# Sprint 2: apply_soft_fact_eliminators
# ---------------------------------------------------------------------------

class TestApplySoftFactEliminators:

    def test_male_ghost_eliminates_female_only(self):
        from graph.deduction import apply_soft_fact_eliminators, all_ghost_names
        candidates = all_ghost_names()
        eliminated = apply_soft_fact_eliminators(
            {"model_gender": "male"}, candidates
        )
        assert "Banshee" in eliminated
        assert "Dayan" in eliminated

    def test_unknown_soft_fact_eliminates_nothing(self):
        from graph.deduction import apply_soft_fact_eliminators, all_ghost_names
        candidates = all_ghost_names()
        eliminated = apply_soft_fact_eliminators(
            {"model_gender": "unknown"}, candidates
        )
        assert eliminated == []

    def test_false_soft_fact_eliminates_nothing(self):
        from graph.deduction import apply_soft_fact_eliminators, all_ghost_names
        candidates = all_ghost_names()
        eliminated = apply_soft_fact_eliminators(
            {"favorite_room_changed": False}, candidates
        )
        assert eliminated == []

    def test_favorite_room_changed_eliminates_goryo(self):
        from graph.deduction import apply_soft_fact_eliminators
        eliminated = apply_soft_fact_eliminators(
            {"favorite_room_changed": True}, ["Goryo", "Banshee", "Spirit"]
        )
        assert "Goryo" in eliminated
        assert "Banshee" not in eliminated

    def test_ghost_without_eliminators_survives(self):
        from graph.deduction import apply_soft_fact_eliminators
        eliminated = apply_soft_fact_eliminators(
            {"model_gender": "male"}, ["Spirit"]
        )
        assert eliminated == []
