"""Tests for runner._dispatch() -- the routing layer between parser and engine.

Each test creates a ParsedIntent directly and passes it to _dispatch(engine, intent).
Validates that the correct engine method is called and the correct result type returned.
"""
from __future__ import annotations

import pytest

from oracle.runner import _dispatch
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
    TestResult,
    UnknownCommandResult,
    PlayerRegistrationResult,
    AvailableTestsResult,
    VoiceChangeResult,
)
from oracle.parser import ParsedIntent
from oracle.deduction import reset_db


@pytest.fixture(autouse=True)
def _fresh_db():
    """Reset cached DB before every test so mutations don't leak."""
    reset_db()
    yield
    reset_db()


@pytest.fixture()
def engine() -> InvestigationEngine:
    """Provide a fresh InvestigationEngine."""
    return InvestigationEngine()


@pytest.fixture()
def active_engine(engine) -> InvestigationEngine:
    """Engine with a professional game already started."""
    engine.new_game("professional")
    return engine


# ---------------------------------------------------------------------------
# init_investigation
# ---------------------------------------------------------------------------


class TestInitInvestigation:
    def test_returns_new_game_result(self, engine):
        intent = ParsedIntent(action="init_investigation", difficulty="professional")
        result = _dispatch(engine, intent)
        assert isinstance(result, NewGameResult)
        assert result.difficulty == "professional"
        assert result.candidate_count == 27

    def test_defaults_to_professional(self, engine):
        intent = ParsedIntent(action="init_investigation", difficulty=None)
        result = _dispatch(engine, intent)
        assert isinstance(result, NewGameResult)
        assert result.difficulty == "professional"

    def test_nightmare_difficulty(self, engine):
        intent = ParsedIntent(action="init_investigation", difficulty="nightmare")
        result = _dispatch(engine, intent)
        assert result.difficulty == "nightmare"


# ---------------------------------------------------------------------------
# record_evidence
# ---------------------------------------------------------------------------


class TestRecordEvidence:
    def test_confirmed_evidence(self, active_engine):
        intent = ParsedIntent(
            action="record_evidence", evidence_id="emf_5", status="confirmed"
        )
        result = _dispatch(active_engine, intent)
        assert isinstance(result, EvidenceResult)
        assert result.evidence == "emf_5"
        assert result.status == "confirmed"
        assert result.remaining_count < 27

    def test_ruled_out_evidence(self, active_engine):
        intent = ParsedIntent(
            action="record_evidence", evidence_id="dots", status="ruled_out"
        )
        result = _dispatch(active_engine, intent)
        assert isinstance(result, EvidenceResult)
        assert result.status == "ruled_out"

    def test_extra_evidence_recorded(self, active_engine):
        """When extra_evidence is present, all are recorded."""
        intent = ParsedIntent(
            action="record_evidence",
            evidence_id="emf_5",
            status="confirmed",
            extra_evidence=["dots"],
        )
        result = _dispatch(active_engine, intent)
        assert isinstance(result, EvidenceResult)
        # The primary result is for emf_5
        assert result.evidence == "emf_5"
        # Both should now be confirmed on the engine
        assert "emf_5" in active_engine.evidence_confirmed
        assert "dots" in active_engine.evidence_confirmed

    def test_defaults_status_to_confirmed(self, active_engine):
        intent = ParsedIntent(
            action="record_evidence", evidence_id="uv", status=None
        )
        result = _dispatch(active_engine, intent)
        assert isinstance(result, EvidenceResult)
        assert result.status == "confirmed"


# ---------------------------------------------------------------------------
# record_behavioral_event
# ---------------------------------------------------------------------------


class TestRecordBehavioral:
    def test_returns_behavioral_result(self, active_engine):
        intent = ParsedIntent(
            action="record_behavioral_event",
            observation="ghost stepped in salt",
            eliminator_key="ghost_stepped_in_salt",
            raw_text="ghost stepped in salt",
        )
        result = _dispatch(active_engine, intent)
        assert isinstance(result, BehavioralResult)
        assert result.observation == "ghost stepped in salt"

    def test_falls_back_to_raw_text(self, active_engine):
        intent = ParsedIntent(
            action="record_behavioral_event",
            observation=None,
            raw_text="some weird behavior",
        )
        result = _dispatch(active_engine, intent)
        assert isinstance(result, BehavioralResult)
        assert result.observation == "some weird behavior"


# ---------------------------------------------------------------------------
# get_investigation_state
# ---------------------------------------------------------------------------


class TestGetState:
    def test_returns_state_result(self, active_engine):
        intent = ParsedIntent(action="get_investigation_state")
        result = _dispatch(active_engine, intent)
        assert isinstance(result, StateResult)
        assert result.difficulty == "professional"
        assert len(result.candidates) == 27


# ---------------------------------------------------------------------------
# query_ghost_database
# ---------------------------------------------------------------------------


class TestQueryGhost:
    def test_known_ghost(self, active_engine):
        intent = ParsedIntent(action="query_ghost_database", ghost_name="Spirit")
        result = _dispatch(active_engine, intent)
        assert isinstance(result, GhostQueryResult)
        assert result.found is True
        assert result.ghost_name == "Spirit"

    def test_unknown_ghost(self, active_engine):
        intent = ParsedIntent(action="query_ghost_database", ghost_name="FakeGhost")
        result = _dispatch(active_engine, intent)
        assert isinstance(result, GhostQueryResult)
        assert result.found is False

    def test_empty_ghost_name(self, active_engine):
        intent = ParsedIntent(action="query_ghost_database", ghost_name=None)
        result = _dispatch(active_engine, intent)
        assert isinstance(result, GhostQueryResult)


# ---------------------------------------------------------------------------
# suggest_next_evidence
# ---------------------------------------------------------------------------


class TestSuggestNext:
    def test_returns_suggestion_result(self, active_engine):
        intent = ParsedIntent(action="suggest_next_evidence")
        result = _dispatch(active_engine, intent)
        assert isinstance(result, SuggestionResult)
        assert len(result.evidence_remaining) == 7  # No evidence tested yet


# ---------------------------------------------------------------------------
# record_theory (with player name)
# ---------------------------------------------------------------------------


class TestRecordTheory:
    def test_returns_guess_result(self, active_engine):
        intent = ParsedIntent(
            action="record_theory", ghost_name="Spirit", player_name="Kayden"
        )
        result = _dispatch(active_engine, intent)
        assert isinstance(result, GuessResult)
        assert result.ghost_name == "Spirit"
        assert result.player_name == "Kayden"

    def test_defaults_player_to_me(self, active_engine):
        intent = ParsedIntent(
            action="record_theory", ghost_name="Spirit", player_name=None
        )
        result = _dispatch(active_engine, intent)
        assert isinstance(result, GuessResult)
        assert result.player_name == "me"


# ---------------------------------------------------------------------------
# record_guess (anonymous)
# ---------------------------------------------------------------------------


class TestRecordGuess:
    def test_returns_guess_result(self, active_engine):
        intent = ParsedIntent(action="record_guess", ghost_name="Jinn")
        result = _dispatch(active_engine, intent)
        assert isinstance(result, GuessResult)
        assert result.ghost_name == "Jinn"
        assert result.found is True


# ---------------------------------------------------------------------------
# lock_in
# ---------------------------------------------------------------------------


class TestLockIn:
    def test_returns_lock_in_result(self, active_engine):
        intent = ParsedIntent(action="lock_in", ghost_name="Oni")
        result = _dispatch(active_engine, intent)
        assert isinstance(result, LockInResult)
        assert result.ghost_name == "Oni"
        assert result.found is True


# ---------------------------------------------------------------------------
# confirm_true_ghost
# ---------------------------------------------------------------------------


class TestConfirmTrueGhost:
    def test_returns_end_game_result(self, active_engine):
        intent = ParsedIntent(action="confirm_true_ghost", ghost_name="Wraith")
        result = _dispatch(active_engine, intent)
        assert isinstance(result, EndGameResult)
        assert result.actual_ghost == "Wraith"
        assert result.found is True


# ---------------------------------------------------------------------------
# register_players
# ---------------------------------------------------------------------------


class TestRegisterPlayers:
    def test_returns_player_registration_result(self, active_engine):
        intent = ParsedIntent(
            action="register_players", player_names=["Alice", "Bob"]
        )
        result = _dispatch(active_engine, intent)
        assert isinstance(result, PlayerRegistrationResult)
        assert result.added == ["Alice", "Bob"]
        assert result.total == 2


# ---------------------------------------------------------------------------
# query_tests (with and without ghost name)
# ---------------------------------------------------------------------------


class TestQueryTests:
    def test_with_ghost_name_returns_test_lookup(self, active_engine):
        intent = ParsedIntent(action="query_tests", ghost_name="Wraith")
        result = _dispatch(active_engine, intent)
        assert isinstance(result, TestLookupResult)
        assert result.ghost_name == "Wraith"
        assert result.found is True
        assert result.has_test is True

    def test_without_ghost_name_returns_available_tests(self, active_engine):
        intent = ParsedIntent(action="query_tests", ghost_name=None)
        result = _dispatch(active_engine, intent)
        assert isinstance(result, AvailableTestsResult)
        assert result.total_candidates == 27
        assert len(result.testable) > 0


# ---------------------------------------------------------------------------
# ghost_test_result
# ---------------------------------------------------------------------------


class TestGhostTestResult:
    def test_passed_test(self, active_engine):
        intent = ParsedIntent(
            action="ghost_test_result", ghost_name="Wraith", status="passed"
        )
        result = _dispatch(active_engine, intent)
        assert isinstance(result, TestResult)
        assert result.ghost_name == "Wraith"
        assert result.passed is True

    def test_failed_test(self, active_engine):
        intent = ParsedIntent(
            action="ghost_test_result", ghost_name="Wraith", status="failed"
        )
        result = _dispatch(active_engine, intent)
        assert isinstance(result, TestResult)
        assert result.ghost_name == "Wraith"
        assert result.passed is False


# ---------------------------------------------------------------------------
# change_voice
# ---------------------------------------------------------------------------


class TestChangeVoice:
    def test_valid_voice(self, engine):
        from oracle.voice.audio_config import ALL_VOICES

        valid_voice = next(iter(ALL_VOICES.keys()))
        intent = ParsedIntent(action="change_voice", voice_name=valid_voice)
        result = _dispatch(engine, intent)
        assert isinstance(result, VoiceChangeResult)
        assert result.success is True
        assert result.voice_name == valid_voice

    def test_invalid_voice(self, engine):
        intent = ParsedIntent(action="change_voice", voice_name="nonexistent_voice_99")
        result = _dispatch(engine, intent)
        assert isinstance(result, VoiceChangeResult)
        assert result.success is False

    def test_empty_voice_name(self, engine):
        intent = ParsedIntent(action="change_voice", voice_name=None)
        result = _dispatch(engine, intent)
        assert isinstance(result, VoiceChangeResult)
        assert result.success is False


# ---------------------------------------------------------------------------
# unknown / unrecognized
# ---------------------------------------------------------------------------


class TestUnknown:
    def test_unknown_action(self, engine):
        intent = ParsedIntent(action="unknown", raw_text="gibberish input")
        result = _dispatch(engine, intent)
        assert isinstance(result, UnknownCommandResult)
        assert result.raw_text == "gibberish input"

    def test_completely_unrecognized_action(self, engine):
        intent = ParsedIntent(action="not_a_real_action", raw_text="foo")
        result = _dispatch(engine, intent)
        assert isinstance(result, UnknownCommandResult)

    def test_query_behavior_with_ghost(self, active_engine):
        """query_behavior with a ghost name delegates to query_ghost."""
        intent = ParsedIntent(action="query_behavior", ghost_name="Jinn")
        result = _dispatch(active_engine, intent)
        assert isinstance(result, GhostQueryResult)
        assert result.found is True

    def test_query_behavior_without_ghost(self, active_engine):
        """query_behavior without ghost name falls through to unknown."""
        intent = ParsedIntent(
            action="query_behavior", ghost_name=None, raw_text="what does it do"
        )
        result = _dispatch(active_engine, intent)
        assert isinstance(result, UnknownCommandResult)
