"""Tests for oracle/parser.py — deterministic intent parser.

Tests cover: evidence confirm/rule-out for all 7 types, rule-out precedence,
init patterns, endgame patterns, state queries, advice patterns, guess,
lock_in, ghost_test_result, journal, everything, STT corrections,
empty/unrecognized input.
"""
from __future__ import annotations

import pytest

from oracle.parser import parse_intent


# ---------------------------------------------------------------------------
# Evidence CONFIRMED
# ---------------------------------------------------------------------------


class TestEvidenceConfirmed:
    """Player says they FOUND evidence -> status must be 'confirmed'."""

    @pytest.mark.parametrize("text,expected_evidence", [
        # Ghost Orb
        ("we found ghost orbs", "orb"),
        ("ghost orb confirmed", "orb"),
        ("orbs on camera", "orb"),
        # Freezing Temperatures
        ("we found freezing temps", "freezing"),
        ("freezing temperatures confirmed", "freezing"),
        ("it's freezing in here", "freezing"),
        ("confirmed freezing", "freezing"),
        # EMF Level 5
        ("we have EMF 5", "emf_5"),
        ("EMF went to 5", "emf_5"),
        ("got EMF 5", "emf_5"),
        ("EMF 5 confirmed", "emf_5"),
        # D.O.T.S.
        ("we found DOTS", "dots"),
        ("D.O.T.S. confirmed", "dots"),
        ("got dots projector", "dots"),
        # Ultraviolet / Fingerprints
        ("found fingerprints", "uv"),
        ("we have UV", "uv"),
        ("ultraviolet confirmed", "uv"),
        ("got handprints", "uv"),
        # Ghost Writing
        ("we found ghost writing", "writing"),
        ("writing confirmed", "writing"),
        # Spirit Box
        ("spirit box confirmed", "spirit_box"),
        ("we got spirit box", "spirit_box"),
    ])
    def test_confirm_evidence(self, text, expected_evidence):
        intent = parse_intent(text)
        assert intent.action == "record_evidence", (
            f"Expected record_evidence, got {intent.action} for: {text}"
        )
        assert intent.evidence_id == expected_evidence
        assert intent.status == "confirmed"


# ---------------------------------------------------------------------------
# Evidence RULED OUT
# ---------------------------------------------------------------------------


class TestEvidenceRuledOut:
    """Player says they DON'T have evidence -> status must be 'ruled_out'."""

    @pytest.mark.parametrize("text,expected_evidence", [
        ("no EMF 5", "emf_5"),
        ("rule out spirit box", "spirit_box"),
        ("ruled out ghost writing", "writing"),
        ("we don't have freezing", "freezing"),
        ("no ghost orbs", "orb"),
        ("eliminated DOTS", "dots"),
        ("crossed off UV", "uv"),
        ("can't find spirit box", "spirit_box"),
        ("EMF never hit 5", "emf_5"),
        ("doesn't have ghost writing", "writing"),
    ])
    def test_rule_out_evidence(self, text, expected_evidence):
        intent = parse_intent(text)
        assert intent.action == "record_evidence"
        assert intent.evidence_id == expected_evidence
        assert intent.status == "ruled_out"


# ---------------------------------------------------------------------------
# Rule-out precedence over confirm
# ---------------------------------------------------------------------------


class TestRuleOutPrecedence:
    def test_dont_have_emf(self):
        """'don't have emf' contains 'have' (confirm) AND 'don't' (rule-out).
        Rule-out must win."""
        intent = parse_intent("don't have emf")
        assert intent.action == "record_evidence"
        assert intent.status == "ruled_out"

    def test_we_do_not_have_orb(self):
        intent = parse_intent("we do not have ghost orbs")
        assert intent.status == "ruled_out"

    def test_no_freezing(self):
        intent = parse_intent("no freezing temperatures")
        assert intent.status == "ruled_out"


# ---------------------------------------------------------------------------
# Init patterns
# ---------------------------------------------------------------------------


class TestInitPatterns:
    @pytest.mark.parametrize("text,expected_diff", [
        ("new game professional", "professional"),
        ("start investigation on nightmare", "nightmare"),
        ("new investigation amateur", "amateur"),
        ("begin new game insanity", "insanity"),
        ("start fresh game", "professional"),
        ("reset the investigation", "professional"),
    ])
    def test_init_investigation(self, text, expected_diff):
        intent = parse_intent(text)
        assert intent.action == "init_investigation"
        assert intent.difficulty == expected_diff


# ---------------------------------------------------------------------------
# Endgame patterns
# ---------------------------------------------------------------------------


class TestEndgamePatterns:
    @pytest.mark.parametrize("text,expected_ghost", [
        ("it was a Wraith", "Wraith"),
        ("the ghost was a Demon", "Demon"),
        ("turned out to be a Banshee", "Banshee"),
        ("game over it was a Spirit", "Spirit"),
    ])
    def test_endgame_with_ghost(self, text, expected_ghost):
        intent = parse_intent(text)
        assert intent.action == "confirm_true_ghost"
        assert intent.ghost_name == expected_ghost

    def test_endgame_without_ghost(self):
        intent = parse_intent("game over")
        assert intent.action == "confirm_true_ghost"
        assert intent.ghost_name is None


# ---------------------------------------------------------------------------
# State query patterns
# ---------------------------------------------------------------------------


class TestStateQueries:
    @pytest.mark.parametrize("text", [
        "what's left?",
        "what do we have?",
        "how many ghosts remain?",
        "which ghosts are still candidates?",
        "where are we?",
        "what do we know?",
        "what have we collected?",
    ])
    def test_state_queries(self, text):
        intent = parse_intent(text)
        assert intent.action == "get_investigation_state", (
            f"Expected get_investigation_state for: {text}"
        )


# ---------------------------------------------------------------------------
# Advice patterns
# ---------------------------------------------------------------------------


class TestAdvicePatterns:
    @pytest.mark.parametrize("text", [
        "what should we check next?",
        "what should we do next?",
        "what's next?",
        "suggest something",
        "what else can we try?",
        "what evidence should we look for?",
    ])
    def test_advice_queries(self, text):
        intent = parse_intent(text)
        assert intent.action == "suggest_next_evidence", (
            f"Expected suggest_next_evidence for: {text}"
        )


# ---------------------------------------------------------------------------
# Guess patterns
# ---------------------------------------------------------------------------


class TestGuessPatterns:
    def test_we_think_its_a_ghost(self):
        """'we think it's a X' matches theory pattern (player='me'), not guess."""
        intent = parse_intent("we think it's a Wraith")
        # Theory patterns fire before guess patterns for "think" phrasing
        assert intent.action == "record_theory"
        assert intent.ghost_name == "Wraith"

    def test_my_guess_is(self):
        intent = parse_intent("my guess is Banshee")
        assert intent.action == "record_guess"
        assert intent.ghost_name == "Banshee"

    def test_guessing(self):
        intent = parse_intent("guessing Demon")
        assert intent.action == "record_guess"
        assert intent.ghost_name == "Demon"

    def test_betting_on(self):
        intent = parse_intent("betting on Wraith")
        assert intent.action == "record_guess"
        assert intent.ghost_name == "Wraith"


# ---------------------------------------------------------------------------
# Lock-in patterns
# ---------------------------------------------------------------------------


class TestLockInPatterns:
    def test_lock_in_with_ghost(self):
        intent = parse_intent("lock in Wraith")
        assert intent.action == "lock_in"
        assert intent.ghost_name == "Wraith"

    def test_lock_in_without_ghost(self):
        intent = parse_intent("lock in")
        assert intent.action == "lock_in"
        assert intent.ghost_name is None

    def test_final_answer(self):
        intent = parse_intent("final answer is Banshee")
        assert intent.action == "lock_in"
        assert intent.ghost_name == "Banshee"


# ---------------------------------------------------------------------------
# Ghost test result patterns
# ---------------------------------------------------------------------------


class TestGhostTestResultPatterns:
    def test_test_passed(self):
        intent = parse_intent("Goryo test passed")
        assert intent.action == "ghost_test_result"
        assert intent.ghost_name == "Goryo"
        assert intent.status == "passed"

    def test_test_failed(self):
        intent = parse_intent("Goryo test failed")
        assert intent.action == "ghost_test_result"
        assert intent.ghost_name == "Goryo"
        assert intent.status == "failed"


# ---------------------------------------------------------------------------
# Journal / everything patterns
# ---------------------------------------------------------------------------


class TestJournalPatterns:
    def test_tell_me_about(self):
        intent = parse_intent("tell me about the Banshee")
        assert intent.action == "query_ghost_database"
        assert intent.ghost_name == "Banshee"

    def test_everything_about(self):
        intent = parse_intent("everything on Wraith")
        assert intent.action == "query_ghost_database"
        assert intent.ghost_name == "Wraith"
        assert intent.query_field == "full"


# ---------------------------------------------------------------------------
# STT corrections
# ---------------------------------------------------------------------------


class TestSTTCorrections:
    def test_herbs_becomes_orb(self):
        """STT mishearing 'herbs' should correct to 'orbs'."""
        intent = parse_intent("we found herbs")
        assert intent.action == "record_evidence"
        assert intent.evidence_id == "orb"

    def test_spirit_bucks_becomes_spirit_box(self):
        """STT mishearing 'spirit bucks' should correct to 'spirit box'."""
        intent = parse_intent("we got spirit bucks")
        assert intent.action == "record_evidence"
        assert intent.evidence_id == "spirit_box"


# ---------------------------------------------------------------------------
# Empty / unrecognized input
# ---------------------------------------------------------------------------


class TestEmptyAndUnrecognized:
    def test_empty_input(self):
        intent = parse_intent("")
        assert intent.action == "unknown"
        assert intent.confidence == 0.0

    def test_whitespace_only(self):
        intent = parse_intent("   ")
        assert intent.action == "unknown"
        assert intent.confidence == 0.0

    def test_unrecognized_input(self):
        intent = parse_intent("I'm scared")
        assert intent.action == "unknown"
        assert intent.confidence == 0.0

    def test_nonsense_input(self):
        intent = parse_intent("asdfghjkl")
        assert intent.action == "unknown"
        assert intent.confidence == 0.0
