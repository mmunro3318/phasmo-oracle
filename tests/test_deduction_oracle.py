"""Tests for oracle.deduction -- the production deduction module.

Covers: load_db, all_ghost_names, get_ghost, narrow_candidates (confirmed,
ruled_out, nightmare/insanity permissiveness, Mimic fake evidence),
evidence_threshold_reached, reset_db, and eliminate_by_guaranteed_evidence.

All imports are from oracle.deduction, NOT from graph.deduction.
"""
from __future__ import annotations

import pytest

from oracle.deduction import (
    load_db,
    reset_db,
    all_ghost_names,
    get_ghost,
    narrow_candidates,
    evidence_threshold_reached,
    eliminate_by_guaranteed_evidence,
    EVIDENCE_THRESHOLDS,
)


@pytest.fixture(autouse=True)
def _fresh_db():
    reset_db()
    yield
    reset_db()


# ---------------------------------------------------------------------------
# load_db
# ---------------------------------------------------------------------------


class TestLoadDb:
    def test_returns_dict_with_ghosts_key(self):
        db = load_db()
        assert isinstance(db, dict)
        assert "ghosts" in db

    def test_ghosts_is_list(self):
        db = load_db()
        assert isinstance(db["ghosts"], list)
        assert len(db["ghosts"]) > 0

    def test_each_ghost_has_name_and_evidence(self):
        db = load_db()
        for ghost in db["ghosts"]:
            assert "name" in ghost
            assert "evidence" in ghost
            assert isinstance(ghost["evidence"], list)


# ---------------------------------------------------------------------------
# all_ghost_names
# ---------------------------------------------------------------------------


class TestAllGhostNames:
    def test_returns_27_ghosts(self):
        names = all_ghost_names()
        assert len(names) == 27

    def test_known_ghosts_present(self):
        names = all_ghost_names()
        for ghost in ["Spirit", "Wraith", "Banshee", "Jinn", "The Mimic", "Oni"]:
            assert ghost in names

    def test_no_duplicates(self):
        names = all_ghost_names()
        assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# get_ghost
# ---------------------------------------------------------------------------


class TestGetGhost:
    def test_exact_name(self):
        ghost = get_ghost("Spirit")
        assert ghost is not None
        assert ghost["name"] == "Spirit"

    def test_case_insensitive(self):
        ghost = get_ghost("spirit")
        assert ghost is not None
        assert ghost["name"] == "Spirit"

    def test_returns_correct_evidence(self):
        ghost = get_ghost("Spirit")
        assert ghost is not None
        # Spirit has writing, emf_5, spirit_box
        assert set(ghost["evidence"]) == {"writing", "emf_5", "spirit_box"}

    def test_mimic_has_fake_evidence(self):
        ghost = get_ghost("The Mimic")
        assert ghost is not None
        assert ghost["fake_evidence"] == "orb"

    def test_nonexistent_ghost(self):
        assert get_ghost("NotARealGhost") is None


# ---------------------------------------------------------------------------
# narrow_candidates — confirmed evidence
# ---------------------------------------------------------------------------


class TestNarrowByConfirmed:
    def test_no_evidence_returns_all(self):
        result = narrow_candidates([], [], [], "professional")
        assert len(result) == 27

    def test_single_confirmed_narrows(self):
        result = narrow_candidates(["emf_5"], [], [], "professional")
        assert len(result) < 27
        # Every remaining ghost must have emf_5
        for name in result:
            ghost = get_ghost(name)
            observable = set(ghost["evidence"])
            if ghost.get("fake_evidence"):
                observable.add(ghost["fake_evidence"])
            assert "emf_5" in observable

    def test_two_confirmed_narrows_further(self):
        one = narrow_candidates(["emf_5"], [], [], "professional")
        two = narrow_candidates(["emf_5", "spirit_box"], [], [], "professional")
        assert len(two) <= len(one)

    def test_impossible_combo_returns_empty(self):
        """All 7 evidence types confirmed -- no ghost has all 7."""
        all_ev = ["emf_5", "dots", "uv", "freezing", "orb", "writing", "spirit_box"]
        result = narrow_candidates(all_ev, [], [], "professional")
        assert len(result) == 0


# ---------------------------------------------------------------------------
# narrow_candidates — ruled-out evidence (standard difficulties)
# ---------------------------------------------------------------------------


class TestNarrowByRuledOut:
    def test_ruled_out_eliminates_on_professional(self):
        all_ghosts = narrow_candidates([], [], [], "professional")
        result = narrow_candidates([], ["emf_5"], [], "professional")
        assert len(result) < len(all_ghosts)
        # No remaining ghost should have emf_5 in its observable set
        for name in result:
            ghost = get_ghost(name)
            observable = set(ghost["evidence"])
            if ghost.get("fake_evidence"):
                observable.add(ghost["fake_evidence"])
            assert "emf_5" not in observable

    def test_ruled_out_eliminates_on_amateur(self):
        result_pro = narrow_candidates([], ["dots"], [], "professional")
        result_ama = narrow_candidates([], ["dots"], [], "amateur")
        # Standard difficulties should behave identically for ruled-out
        assert set(result_pro) == set(result_ama)


# ---------------------------------------------------------------------------
# narrow_candidates — nightmare/insanity permissiveness
# ---------------------------------------------------------------------------


class TestNightmareInsanity:
    def test_nightmare_ignores_ruled_out(self):
        """On nightmare, ruling out evidence does NOT eliminate ghosts."""
        all_ghosts = narrow_candidates([], [], [], "nightmare")
        result = narrow_candidates([], ["emf_5"], [], "nightmare")
        # Should keep ghosts that have emf_5 (it could be hidden)
        assert len(result) >= len(all_ghosts) - 1  # At most lose Mimic fake edge case

    def test_insanity_ignores_ruled_out(self):
        """Insanity behaves same as nightmare for ruled-out evidence."""
        nightmare_result = narrow_candidates([], ["emf_5"], [], "nightmare")
        insanity_result = narrow_candidates([], ["emf_5"], [], "insanity")
        assert set(nightmare_result) == set(insanity_result)

    def test_nightmare_still_respects_confirmed(self):
        """Even on nightmare, confirmed evidence must match."""
        result = narrow_candidates(["emf_5"], [], [], "nightmare")
        for name in result:
            ghost = get_ghost(name)
            observable = set(ghost["evidence"])
            if ghost.get("fake_evidence"):
                observable.add(ghost["fake_evidence"])
            assert "emf_5" in observable

    def test_mimic_orb_ruled_out_eliminates_on_nightmare(self):
        """Exception: Mimic's fake evidence (orb) is never hidden.
        Ruling out orbs should eliminate The Mimic even on nightmare."""
        result = narrow_candidates([], ["orb"], [], "nightmare")
        assert "The Mimic" not in result


# ---------------------------------------------------------------------------
# narrow_candidates — eliminated ghosts
# ---------------------------------------------------------------------------


class TestNarrowByEliminated:
    def test_eliminated_ghost_removed(self):
        result = narrow_candidates([], [], ["Spirit"], "professional")
        assert "Spirit" not in result
        assert len(result) == 26

    def test_multiple_eliminations(self):
        result = narrow_candidates([], [], ["Spirit", "Wraith", "Jinn"], "professional")
        assert "Spirit" not in result
        assert "Wraith" not in result
        assert "Jinn" not in result
        assert len(result) == 24


# ---------------------------------------------------------------------------
# Mimic handling
# ---------------------------------------------------------------------------


class TestMimicHandling:
    def test_mimic_survives_orb_confirmed(self):
        """The Mimic has fake_evidence=orb, so confirming orb should keep it."""
        result = narrow_candidates(["orb"], [], [], "professional")
        assert "The Mimic" in result

    def test_mimic_eliminated_by_orb_ruled_out_standard(self):
        """Ruling out orb on standard should eliminate The Mimic."""
        result = narrow_candidates([], ["orb"], [], "professional")
        assert "The Mimic" not in result

    def test_mimic_four_evidence(self):
        """The Mimic can have 4 observable evidence (3 real + orb fake).
        Confirming all 4 should narrow to just The Mimic."""
        # Mimic evidence: uv, freezing, spirit_box + fake orb
        result = narrow_candidates(
            ["uv", "freezing", "spirit_box", "orb"], [], [], "professional"
        )
        assert "The Mimic" in result


# ---------------------------------------------------------------------------
# evidence_threshold_reached
# ---------------------------------------------------------------------------


class TestEvidenceThreshold:
    @pytest.mark.parametrize(
        "difficulty, threshold",
        [
            ("amateur", 3),
            ("intermediate", 3),
            ("professional", 3),
            ("nightmare", 2),
            ("insanity", 1),
        ],
    )
    def test_threshold_values(self, difficulty, threshold):
        assert EVIDENCE_THRESHOLDS[difficulty] == threshold

    @pytest.mark.parametrize(
        "difficulty, count, expected",
        [
            ("professional", 2, False),
            ("professional", 3, True),
            ("professional", 4, True),
            ("nightmare", 1, False),
            ("nightmare", 2, True),
            ("insanity", 0, False),
            ("insanity", 1, True),
            ("amateur", 3, True),
        ],
    )
    def test_threshold_reached(self, difficulty, count, expected):
        confirmed = [f"ev_{i}" for i in range(count)]
        assert evidence_threshold_reached(confirmed, difficulty) is expected


# ---------------------------------------------------------------------------
# reset_db
# ---------------------------------------------------------------------------


class TestResetDb:
    def test_clears_cache(self):
        # Load the db to populate cache
        db1 = load_db()
        assert db1 is not None
        # Reset
        reset_db()
        # Load again -- should get a fresh copy (same content, but re-loaded)
        db2 = load_db()
        assert db2 is not None
        assert len(db2["ghosts"]) == 27


# ---------------------------------------------------------------------------
# eliminate_by_guaranteed_evidence
# ---------------------------------------------------------------------------


class TestEliminateByGuaranteed:
    def test_no_effect_on_professional(self):
        """Guaranteed evidence elimination only applies on nightmare/insanity."""
        candidates = all_ghost_names()
        result = eliminate_by_guaranteed_evidence(candidates, ["emf_5"], "professional")
        assert result == candidates

    def test_eliminates_on_nightmare(self):
        """On nightmare, ghosts with guaranteed evidence that wasn't confirmed get eliminated."""
        candidates = all_ghost_names()
        # Confirm emf_5 only -- ghosts whose guaranteed evidence is NOT emf_5
        # (and IS something else) should be eliminated
        result = eliminate_by_guaranteed_evidence(candidates, ["emf_5"], "nightmare")
        # Result should be shorter (some ghosts with non-emf_5 guaranteed evidence removed)
        # But ghosts with no guaranteed evidence survive
        for name in result:
            ghost = get_ghost(name)
            ge = ghost.get("guaranteed_evidence")
            # Either no guaranteed evidence, or guaranteed evidence was confirmed
            assert ge is None or ge in ["emf_5"]

    def test_mimic_survives_guaranteed_check(self):
        """The Mimic has guaranteed_evidence=null, so it always survives."""
        candidates = all_ghost_names()
        result = eliminate_by_guaranteed_evidence(candidates, ["dots"], "nightmare")
        assert "The Mimic" in result

    def test_no_effect_on_amateur(self):
        candidates = all_ghost_names()
        result = eliminate_by_guaranteed_evidence(candidates, ["dots"], "amateur")
        assert result == candidates
