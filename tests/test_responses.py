"""Tests for oracle/responses.py — build_response with typed result objects.

Tests cover: all result types dispatched through build_response, minimum
length enforcement, and correct keyword presence in generated strings.
"""
from __future__ import annotations

import pytest

from oracle.engine import (
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
    TestResult,
    UnknownCommandResult,
    PlayerRegistrationResult,
    VoiceChangeResult,
    AvailableTestsResult,
)
from oracle.responses import build_response, _MIN_LENGTH, _FILLER


# ---------------------------------------------------------------------------
# Helpers — construct result objects directly
# ---------------------------------------------------------------------------


def _evidence_result(**overrides) -> EvidenceResult:
    """Build an EvidenceResult with sensible defaults, overriding as needed."""
    defaults = dict(
        evidence="emf_5",
        evidence_label="EMF Level 5",
        status="confirmed",
        remaining_count=10,
        candidates=["Spirit", "Wraith", "Demon"],
        threshold_reached=False,
        mimic_detected=False,
        identified_ghost=None,
        status_changed=False,
        old_status=None,
        zero_candidates=False,
        over_proofed=False,
        identification_triggered=False,
        phase_shifted=False,
        commentary_needed=False,
    )
    defaults.update(overrides)
    return EvidenceResult(**defaults)


# ---------------------------------------------------------------------------
# NewGameResult
# ---------------------------------------------------------------------------


class TestNewGameResponse:
    def test_includes_difficulty_and_count(self):
        result = NewGameResult(difficulty="professional", candidate_count=27)
        response = build_response(result)
        assert "professional" in response
        assert "27" in response


# ---------------------------------------------------------------------------
# EvidenceResult
# ---------------------------------------------------------------------------


class TestEvidenceResponse:
    def test_confirmed_includes_confirmed(self):
        result = _evidence_result(status="confirmed")
        response = build_response(result)
        assert "confirmed" in response.lower() or "is in" in response.lower()

    def test_ruled_out_includes_ruled_out(self):
        result = _evidence_result(status="ruled_out")
        response = build_response(result)
        assert "ruled out" in response.lower() or "crossing off" in response.lower()

    def test_identification_triggered_includes_ghost_name(self):
        result = _evidence_result(
            identification_triggered=True,
            remaining_count=1,
            candidates=["Goryo"],
            identified_ghost="Goryo",
            threshold_reached=True,
        )
        response = build_response(result)
        assert "Goryo" in response

    def test_mimic_detected_includes_mimic(self):
        result = _evidence_result(
            mimic_detected=True,
            evidence="orb",
        )
        response = build_response(result)
        assert "Mimic" in response

    def test_zero_candidates_includes_no_ghosts_match(self):
        result = _evidence_result(
            zero_candidates=True,
            remaining_count=0,
            candidates=[],
        )
        response = build_response(result)
        assert "no ghosts match" in response.lower() or "no ghost" in response.lower()

    def test_over_proofed_includes_warning(self):
        result = _evidence_result(
            over_proofed=True,
        )
        response = build_response(result)
        assert "evidence" in response.lower()
        assert "incorrectly" in response.lower()


# ---------------------------------------------------------------------------
# GhostQueryResult
# ---------------------------------------------------------------------------


class TestGhostQueryResponse:
    def test_not_found_includes_not_found(self):
        result = GhostQueryResult(
            ghost_name="Casper",
            found=False,
            all_ghost_names=["Wraith", "Spirit"],
        )
        response = build_response(result)
        assert "casper" in response.lower()

    def test_found_includes_ghost_name(self):
        result = GhostQueryResult(
            ghost_name="Wraith",
            found=True,
            evidence_list=["dots", "emf_5", "spirit_box"],
        )
        response = build_response(result)
        assert "Wraith" in response


# ---------------------------------------------------------------------------
# GuessResult
# ---------------------------------------------------------------------------


class TestGuessResponse:
    def test_new_guess_includes_tracking(self):
        result = GuessResult(
            ghost_name="Wraith",
            found=True,
            old_guess=None,
            is_candidate=True,
            player_name=None,
        )
        response = build_response(result)
        assert "tracking" in response.lower() or "Tracking" in response

    def test_changed_guess_includes_changing(self):
        result = GuessResult(
            ghost_name="Spirit",
            found=True,
            old_guess="Wraith",
            is_candidate=True,
            player_name=None,
        )
        response = build_response(result)
        assert "changing" in response.lower()


# ---------------------------------------------------------------------------
# LockInResult
# ---------------------------------------------------------------------------


class TestLockInResponse:
    def test_locked_in_includes_locked_in(self):
        result = LockInResult(
            ghost_name="Wraith",
            found=True,
            is_candidate=True,
        )
        response = build_response(result)
        assert "locked in" in response.lower() or "Locked in" in response


# ---------------------------------------------------------------------------
# EndGameResult
# ---------------------------------------------------------------------------


class TestEndGameResponse:
    def test_win_includes_win_language(self):
        result = EndGameResult(
            actual_ghost="Wraith",
            found=True,
            guess="Wraith",
            correct=True,
            identified_ghost="Wraith",
            was_candidate=True,
            evidence_count=3,
            difficulty="professional",
        )
        response = build_response(result)
        # The response uses "Nice call" / "recording the win"
        assert "win" in response.lower() or "nice call" in response.lower()

    def test_loss_includes_tough_break(self):
        result = EndGameResult(
            actual_ghost="Wraith",
            found=True,
            guess="Spirit",
            correct=False,
            identified_ghost=None,
            was_candidate=True,
            evidence_count=2,
            difficulty="professional",
        )
        response = build_response(result)
        assert "tough break" in response.lower()


# ---------------------------------------------------------------------------
# TestLookupResult
# ---------------------------------------------------------------------------


class TestTestLookupResponse:
    def test_with_test_includes_description(self):
        result = TestLookupResult(
            ghost_name="Goryo",
            found=True,
            has_test=True,
            test_description="Check D.O.T.S. on camera only",
            test_type="positive",
        )
        response = build_response(result)
        assert "Check D.O.T.S. on camera only" in response

    def test_no_test_includes_no_known_test(self):
        result = TestLookupResult(
            ghost_name="Spirit",
            found=True,
            has_test=False,
            test_description=None,
            test_type=None,
        )
        response = build_response(result)
        assert "no known test" in response.lower()


# ---------------------------------------------------------------------------
# UnknownCommandResult
# ---------------------------------------------------------------------------


class TestUnknownCommandResponse:
    def test_includes_didnt_catch_that(self):
        result = UnknownCommandResult(raw_text="asdfghjkl")
        response = build_response(result)
        assert "didn't catch that" in response.lower()


# ---------------------------------------------------------------------------
# Minimum length enforcement
# ---------------------------------------------------------------------------


class TestMinimumLength:
    def test_short_response_gets_padded(self):
        """Any response shorter than _MIN_LENGTH gets padded with filler."""
        # UnknownCommandResult always produces a response > 40 chars,
        # so test with a result type that can produce a short string.
        # BehavioralResult with no eliminations and small count could be short.
        result = BehavioralResult(
            observation="ok",
            newly_eliminated=[],
            remaining_count=5,
            candidates=["A", "B", "C", "D", "E"],
        )
        response = build_response(result)
        assert len(response) >= _MIN_LENGTH

    def test_long_response_not_padded(self):
        """A response already above _MIN_LENGTH should not get filler appended."""
        result = NewGameResult(difficulty="professional", candidate_count=27)
        response = build_response(result)
        assert len(response) >= _MIN_LENGTH
        assert _FILLER not in response


# ---------------------------------------------------------------------------
# PlayerRegistrationResult (regression: was using result.names instead of result.added)
# ---------------------------------------------------------------------------


class TestPlayerRegistrationResponse:
    def test_renders_added_players(self):
        result = PlayerRegistrationResult(added=["Mike", "Kayden"], total=2)
        response = build_response(result)
        assert "Mike" in response
        assert "Kayden" in response
        assert "2" in response

    def test_single_player(self):
        result = PlayerRegistrationResult(added=["Mike"], total=1)
        response = build_response(result)
        assert "Mike" in response

    def test_three_players_uses_oxford_comma(self):
        result = PlayerRegistrationResult(added=["Mike", "Kayden", "Alex"], total=3)
        response = build_response(result)
        assert "Mike" in response and "Kayden" in response and "Alex" in response


# ---------------------------------------------------------------------------
# GhostQueryResult confirmed evidence display
# (regression: was checking "CONFIRMED" uppercase instead of "confirmed")
# ---------------------------------------------------------------------------


class TestGhostQueryConfirmedEvidence:
    def test_confirmed_evidence_shown(self):
        result = GhostQueryResult(
            ghost_name="Wraith",
            found=True,
            evidence_list=["dots", "emf_5", "spirit_box"],
            evidence_status={"dots": "confirmed", "emf_5": "untested", "spirit_box": "untested"},
            guaranteed_evidence=None,
            tells=[],
            community_tests=[],
            fake_evidence=None,
            all_ghost_names=["Wraith"],
        )
        response = build_response(result)
        assert "confirmed" in response.lower()
        assert "dots" in response

    def test_untested_evidence_shown(self):
        result = GhostQueryResult(
            ghost_name="Spirit",
            found=True,
            evidence_list=["emf_5", "spirit_box", "writing"],
            evidence_status={"emf_5": "untested", "spirit_box": "untested", "writing": "untested"},
            guaranteed_evidence=None,
            tells=[],
            community_tests=[],
            fake_evidence=None,
            all_ghost_names=["Spirit"],
        )
        response = build_response(result)
        assert "check" in response.lower() or "untested" in response.lower()

    def test_mixed_status_shows_both(self):
        result = GhostQueryResult(
            ghost_name="Demon",
            found=True,
            evidence_list=["freezing", "writing", "uv"],
            evidence_status={"freezing": "confirmed", "writing": "confirmed", "uv": "untested"},
            guaranteed_evidence=None,
            tells=[],
            community_tests=[],
            fake_evidence=None,
            all_ghost_names=["Demon"],
        )
        response = build_response(result)
        assert "confirmed" in response.lower()
        assert "uv" in response


# ---------------------------------------------------------------------------
# TestResult response builder
# ---------------------------------------------------------------------------


class TestTestResultResponse:
    def test_identified_ghost(self):
        result = TestResult(
            ghost_name="Hantu",
            passed=True,
            eliminated_ghosts=[],
            remaining_count=1,
            identified_ghost="Hantu",
        )
        response = build_response(result)
        assert "Hantu" in response
        assert "confirmed" in response.lower() or "lock" in response.lower()

    def test_passed_with_elimination(self):
        result = TestResult(
            ghost_name="Banshee",
            passed=True,
            eliminated_ghosts=["Banshee"],
            remaining_count=26,
        )
        response = build_response(result)
        assert "passed" in response.lower()
        assert "Banshee" in response
        assert "26" in response

    def test_failed_with_elimination(self):
        result = TestResult(
            ghost_name="Hantu",
            passed=False,
            eliminated_ghosts=["Hantu"],
            remaining_count=26,
        )
        response = build_response(result)
        assert "failed" in response.lower()
        assert "Hantu" in response

    def test_passed_no_elimination(self):
        result = TestResult(
            ghost_name="Hantu",
            passed=True,
            eliminated_ghosts=[],
            remaining_count=27,
        )
        response = build_response(result)
        assert "passed" in response.lower()
        assert "27" in response

    def test_failed_no_elimination(self):
        result = TestResult(
            ghost_name="Hantu",
            passed=False,
            eliminated_ghosts=[],
            remaining_count=27,
        )
        response = build_response(result)
        assert "failed" in response.lower()


# ---------------------------------------------------------------------------
# VoiceChangeResult response builder
# ---------------------------------------------------------------------------


class TestVoiceChangeResponse:
    def test_successful_voice_change(self):
        result = VoiceChangeResult(
            voice_name="bm_fable",
            success=True,
        )
        response = build_response(result)
        assert "Fable" in response
        assert "taking over" in response.lower() or "ready" in response.lower()

    def test_unknown_voice(self):
        result = VoiceChangeResult(
            voice_name="xx_unknown",
            success=False,
            available_voices=["af_sarah", "bm_fable", "bf_bella"],
        )
        response = build_response(result)
        assert "unknown" in response.lower() or "Unknown" in response
        assert "af_sarah" in response


# ---------------------------------------------------------------------------
# AvailableTestsResult response builder
# ---------------------------------------------------------------------------


class TestAvailableTestsResponse:
    def test_with_testable_ghosts(self):
        result = AvailableTestsResult(
            testable=[("Goryo", "Check D.O.T.S. on camera only"), ("Hantu", "Watch for freezing breath")],
            untestable=["The Mimic"],
            total_candidates=3,
        )
        response = build_response(result)
        assert "2 of 3" in response
        assert "Goryo" in response
        assert "Mimic" in response

    def test_no_testable_ghosts(self):
        result = AvailableTestsResult(
            testable=[],
            untestable=["Ghost A", "Ghost B"],
            total_candidates=2,
        )
        response = build_response(result)
        assert "none" in response.lower()
