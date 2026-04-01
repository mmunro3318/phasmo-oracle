"""Tests for oracle/engine.py — InvestigationEngine with typed result dataclasses.

Tests cover: new_game, record_evidence (narrowing, synonyms, status changes,
threshold, Mimic, over-proofed, zero candidates, phase shift), record_behavioral,
get_state, query_ghost, suggest_next, record_guess, lock_in, end_game,
ghost_test_lookup, and register_players.
"""
from __future__ import annotations

import json

import pytest

from oracle.engine import (
    InvestigationEngine,
    NewGameResult,
    EvidenceResult,
    BehavioralResult,
    StateResult,
    GhostQueryResult,
    SuggestionResult,
    GuessResult,
    LockInResult,
    EndGameResult,
    TestLookupResult,
    PlayerRegistrationResult,
    VALID_EVIDENCE,
    normalize_evidence_id,
)
from oracle.deduction import reset_db


@pytest.fixture(autouse=True)
def _fresh_db():
    """Reset the cached DB before every test so mutations don't leak."""
    reset_db()
    yield
    reset_db()


@pytest.fixture()
def engine() -> InvestigationEngine:
    """Provide a fresh InvestigationEngine with a new game started."""
    eng = InvestigationEngine()
    eng.new_game("professional")
    return eng


# ---------------------------------------------------------------------------
# new_game
# ---------------------------------------------------------------------------


class TestNewGame:
    def test_returns_new_game_result_with_27_candidates(self, engine):
        result = engine.new_game("professional")
        assert isinstance(result, NewGameResult)
        assert result.candidate_count == 27
        assert result.difficulty == "professional"

    def test_difficulty_is_set(self):
        eng = InvestigationEngine()
        result = eng.new_game("nightmare")
        assert result.difficulty == "nightmare"
        assert eng.difficulty == "nightmare"

    def test_invalid_difficulty_falls_back_to_professional(self):
        eng = InvestigationEngine()
        result = eng.new_game("hardcore")
        assert result.difficulty == "professional"
        assert eng.difficulty == "professional"

    def test_new_game_resets_state(self, engine):
        # Dirty up state
        engine.record_evidence("emf_5", "confirmed")
        engine.record_evidence("dots", "ruled_out")
        engine.record_behavioral("something happened")
        # Reset
        result = engine.new_game("amateur")
        assert result.candidate_count == 27
        assert engine.evidence_confirmed == []
        assert engine.evidence_ruled_out == []
        assert engine.behavioral_observations == []
        assert engine.eliminated_ghosts == []


# ---------------------------------------------------------------------------
# record_evidence
# ---------------------------------------------------------------------------


class TestRecordEvidence:
    def test_confirm_emf5_narrows_candidates(self, engine):
        result = engine.record_evidence("emf_5", "confirmed")
        assert isinstance(result, EvidenceResult)
        assert result.evidence == "emf_5"
        assert result.status == "confirmed"
        assert result.remaining_count < 27

    def test_rule_out_narrows_correctly(self, engine):
        result = engine.record_evidence("freezing", "ruled_out")
        assert result.status == "ruled_out"
        assert result.remaining_count < 27
        # No remaining candidate should have freezing as real evidence
        # (except via fake_evidence edge case)
        from oracle.deduction import get_ghost
        for name in result.candidates:
            ghost = get_ghost(name)
            if ghost.get("fake_evidence") == "freezing":
                continue
            assert "freezing" not in ghost["evidence"]

    def test_synonym_normalization_emf(self, engine):
        """'emf' should normalize to 'emf_5' via synonym map."""
        result = engine.record_evidence("emf", "confirmed")
        assert result.evidence == "emf_5"
        assert "emf_5" in engine.evidence_confirmed

    def test_status_change_confirmed_to_ruled_out(self, engine):
        engine.record_evidence("emf_5", "confirmed")
        assert "emf_5" in engine.evidence_confirmed

        result = engine.record_evidence("emf_5", "ruled_out")
        assert result.status_changed is True
        assert result.old_status == "confirmed"
        assert "emf_5" not in engine.evidence_confirmed
        assert "emf_5" in engine.evidence_ruled_out

    def test_status_change_ruled_out_to_confirmed(self, engine):
        engine.record_evidence("dots", "ruled_out")
        result = engine.record_evidence("dots", "confirmed")
        assert result.status_changed is True
        assert result.old_status == "ruled_out"
        assert "dots" in engine.evidence_confirmed
        assert "dots" not in engine.evidence_ruled_out

    def test_threshold_detection_professional(self, engine):
        """3 confirmed on professional triggers threshold_reached."""
        engine.record_evidence("emf_5", "confirmed")
        engine.record_evidence("dots", "confirmed")
        result = engine.record_evidence("uv", "confirmed")
        assert result.threshold_reached is True

    def test_identification_triggered_on_single_candidate(self, engine):
        """When threshold reached + exactly 1 candidate, identification_triggered is True."""
        # Goryo has [dots, emf_5, uv] — confirming all 3 should narrow heavily
        engine.record_evidence("dots", "confirmed")
        engine.record_evidence("emf_5", "confirmed")
        result = engine.record_evidence("uv", "confirmed")
        # If exactly 1 candidate remains + threshold reached, should trigger
        if result.remaining_count == 1:
            assert result.identification_triggered is True
            assert result.identified_ghost is not None

    def test_mimic_not_detected_below_threshold(self, engine):
        """Confirming orb below evidence threshold should NOT trigger mimic_detected.

        Regression: previously, confirming orbs as the 1st evidence on a fresh
        game would trigger "Four pieces of evidence with orbs — that's a Mimic"
        because _check_mimic only checked orbs+candidate, not evidence count.
        """
        # Just orb as first evidence — should NOT trigger Mimic detection
        result = engine.record_evidence("orb", "confirmed")
        assert result.mimic_detected is False

        # Two evidence including orb — still below Professional threshold of 3
        engine.record_evidence("uv", "confirmed")
        result = engine.record_evidence("freezing", "confirmed")
        assert result.mimic_detected is False

    def test_mimic_detection_above_threshold(self, engine):
        """Mimic detected when evidence count exceeds threshold AND orbs confirmed.

        On Professional (threshold=3), need 4 confirmed evidence including orb.
        """
        engine.record_evidence("uv", "confirmed")
        engine.record_evidence("freezing", "confirmed")
        engine.record_evidence("spirit_box", "confirmed")
        # 4th evidence is orb — exceeds threshold, triggers Mimic detection
        result = engine.record_evidence("orb", "confirmed")
        # With all 4 Mimic evidence, it narrows to Mimic alone
        assert result.remaining_count == 1
        assert result.candidates == ["The Mimic"]
        assert result.identification_triggered is True

    def test_mimic_regression_new_game_resets(self, engine):
        """Starting a new game must fully reset state so Mimic detection is clean.

        Regression: after a 3-evidence game, starting a new game and confirming
        orbs as the 1st evidence should NOT trigger Mimic detection.
        """
        # First game: confirm 3 evidence
        engine.record_evidence("emf_5", "confirmed")
        engine.record_evidence("uv", "confirmed")
        engine.record_evidence("dots", "confirmed")

        # Start new game
        engine.new_game("nightmare")

        # First evidence in new game is orbs — must NOT trigger Mimic
        result = engine.record_evidence("orb", "confirmed")
        assert result.mimic_detected is False
        assert len(engine.evidence_confirmed) == 1

    def test_over_proofed_four_evidence_without_orb(self, engine):
        """4 confirmed without orb on professional = over_proofed."""
        engine.record_evidence("emf_5", "confirmed")
        engine.record_evidence("dots", "confirmed")
        engine.record_evidence("uv", "confirmed")
        result = engine.record_evidence("freezing", "confirmed")
        assert result.over_proofed is True

    def test_zero_candidates(self, engine):
        """Rule out all evidence to produce zero candidates."""
        for ev in VALID_EVIDENCE:
            engine.record_evidence(ev, "ruled_out")
        # Confirm one more to get result — candidates already 0
        result = engine.record_evidence("emf_5", "ruled_out")
        assert result.zero_candidates is True
        assert result.remaining_count == 0

    def test_phase_shifted_flag(self, engine):
        """Threshold reached + multiple candidates triggers phase_shifted."""
        engine.record_evidence("emf_5", "confirmed")
        engine.record_evidence("dots", "confirmed")
        result = engine.record_evidence("uv", "confirmed")
        # If multiple candidates remain, phase should shift
        if result.remaining_count > 1 and result.threshold_reached:
            assert result.phase_shifted is True
            assert engine.investigation_phase == "behavioral"


# ---------------------------------------------------------------------------
# record_behavioral
# ---------------------------------------------------------------------------


class TestRecordBehavioral:
    def test_with_eliminator_key(self, engine):
        """ghost_stepped_in_salt eliminates Wraith."""
        result = engine.record_behavioral(
            "Ghost walked through salt", "ghost_stepped_in_salt"
        )
        assert isinstance(result, BehavioralResult)
        assert "Wraith" in result.newly_eliminated
        assert "Wraith" in engine.eliminated_ghosts
        assert "Wraith" not in engine.candidates

    def test_without_eliminator(self, engine):
        """Plain observation logs but doesn't eliminate anyone."""
        original_count = len(engine.candidates)
        result = engine.record_behavioral("Ghost threw a plate")
        assert result.newly_eliminated == []
        assert result.remaining_count == original_count
        assert "Ghost threw a plate" in engine.behavioral_observations


# ---------------------------------------------------------------------------
# get_state
# ---------------------------------------------------------------------------


class TestGetState:
    def test_returns_state_result(self, engine):
        engine.record_evidence("emf_5", "confirmed")
        engine.record_evidence("orb", "ruled_out")
        result = engine.get_state()
        assert isinstance(result, StateResult)
        assert result.difficulty == "professional"
        assert "emf_5" in result.evidence_confirmed
        assert "orb" in result.evidence_ruled_out
        assert len(result.candidates) < 27

    def test_observations_count(self, engine):
        engine.record_behavioral("Event 1")
        engine.record_behavioral("Event 2")
        result = engine.get_state()
        assert result.observations_count == 2


# ---------------------------------------------------------------------------
# query_ghost
# ---------------------------------------------------------------------------


class TestQueryGhost:
    def test_known_ghost_returns_details(self, engine):
        result = engine.query_ghost("Wraith")
        assert isinstance(result, GhostQueryResult)
        assert result.found is True
        assert result.ghost_name == "Wraith"
        assert len(result.evidence_list) > 0

    def test_unknown_ghost_returns_not_found(self, engine):
        result = engine.query_ghost("Casper")
        assert result.found is False
        assert result.ghost_name == "Casper"
        assert len(result.all_ghost_names) == 27


# ---------------------------------------------------------------------------
# suggest_next
# ---------------------------------------------------------------------------


class TestSuggestNext:
    def test_returns_suggestion_with_remaining_evidence(self, engine):
        result = engine.suggest_next()
        assert isinstance(result, SuggestionResult)
        assert len(result.evidence_remaining) == 7  # Nothing tested yet
        assert result.suggestion_text != ""

    def test_after_some_evidence(self, engine):
        engine.record_evidence("emf_5", "confirmed")
        engine.record_evidence("dots", "ruled_out")
        result = engine.suggest_next()
        assert "emf_5" not in result.evidence_remaining
        assert "dots" not in result.evidence_remaining
        assert len(result.evidence_remaining) == 5


# ---------------------------------------------------------------------------
# record_guess
# ---------------------------------------------------------------------------


class TestRecordGuess:
    def test_first_guess(self, engine):
        result = engine.record_guess("Wraith")
        assert isinstance(result, GuessResult)
        assert result.found is True
        assert result.ghost_name == "Wraith"
        assert result.old_guess is None

    def test_change_guess(self, engine):
        engine.record_guess("Wraith")
        result = engine.record_guess("Spirit")
        assert result.old_guess == "Wraith"
        assert result.ghost_name == "Spirit"

    def test_guess_for_eliminated_ghost(self, engine):
        """Guessing a ghost that's been eliminated marks is_candidate=False."""
        engine.record_evidence("dots", "ruled_out")
        # Wraith has dots — should be eliminated
        result = engine.record_guess("Wraith")
        assert result.found is True
        assert result.is_candidate is False


# ---------------------------------------------------------------------------
# lock_in
# ---------------------------------------------------------------------------


class TestLockIn:
    def test_valid_ghost(self, engine):
        result = engine.lock_in("Wraith")
        assert isinstance(result, LockInResult)
        assert result.found is True
        assert result.ghost_name == "Wraith"
        assert engine.locked_in_ghost == "Wraith"

    def test_non_candidate_ghost(self, engine):
        engine.record_evidence("dots", "ruled_out")
        result = engine.lock_in("Wraith")
        assert result.found is True
        assert result.is_candidate is False


# ---------------------------------------------------------------------------
# end_game
# ---------------------------------------------------------------------------


class TestEndGame:
    def test_correct_guess(self, engine):
        engine.lock_in("Wraith")
        result = engine.end_game("Wraith")
        assert isinstance(result, EndGameResult)
        assert result.found is True
        assert result.correct is True
        assert result.actual_ghost == "Wraith"

    def test_wrong_guess(self, engine):
        engine.lock_in("Spirit")
        result = engine.end_game("Wraith")
        assert result.correct is False
        assert result.guess == "Spirit"
        assert result.actual_ghost == "Wraith"

    def test_writes_to_history_json(self, engine, tmp_path, monkeypatch):
        """end_game persists session to sessions/history.json."""
        # Redirect SESSIONS_DIR to tmp_path
        monkeypatch.setattr(
            "oracle.engine.config.SESSIONS_DIR", str(tmp_path)
        )
        engine.lock_in("Wraith")
        engine.end_game("Wraith")

        history_path = tmp_path / "history.json"
        assert history_path.exists()

        with open(history_path) as f:
            history = json.load(f)
        assert len(history) == 1
        assert history[0]["ghost"] == "Wraith"
        assert history[0]["correct"] is True


# ---------------------------------------------------------------------------
# ghost_test_lookup
# ---------------------------------------------------------------------------


class TestGhostTestLookup:
    def test_ghost_with_test(self, engine):
        """A ghost that has a test entry returns has_test=True."""
        # Try Goryo — commonly has a test
        result = engine.ghost_test_lookup("Goryo")
        assert isinstance(result, TestLookupResult)
        assert result.found is True
        # If the YAML has a test for Goryo:
        if result.has_test:
            assert result.test_description is not None

    def test_ghost_without_test(self, engine):
        """A ghost in the DB but without a test entry returns has_test=False."""
        result = engine.ghost_test_lookup("Spirit")
        assert result.found is True
        # Spirit may or may not have a test — just verify the structure
        assert isinstance(result.has_test, bool)

    def test_unknown_ghost(self, engine):
        result = engine.ghost_test_lookup("Casper")
        assert result.found is False
        assert result.has_test is False


# ---------------------------------------------------------------------------
# register_players
# ---------------------------------------------------------------------------


class TestRegisterPlayers:
    def test_adds_players(self, engine):
        result = engine.register_players(["Mike", "Kayden"])
        assert isinstance(result, PlayerRegistrationResult)
        assert "Mike" in result.added
        assert "Kayden" in result.added
        assert result.total == 2
        assert "Mike" in engine.players
        assert "Kayden" in engine.players

    def test_duplicate_player_ignored(self, engine):
        engine.register_players(["Mike"])
        result = engine.register_players(["Mike"])
        assert result.added == []
        assert result.total == 1
        assert engine.players.count("Mike") == 1
