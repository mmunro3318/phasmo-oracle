"""Tests for deterministic intent router — no Ollama required.

These tests verify that natural language inputs are correctly classified
into structured intents by the regex/keyword-based parser. This is the
most critical test file — if the router misclassifies, the wrong tool runs.
"""
import pytest

from graph.intent_router import parse_intent


# ── Evidence CONFIRMED ───────────────────────────────────────────────────────

class TestEvidenceConfirmed:
    """Player says they FOUND evidence → status must be 'confirmed'."""

    @pytest.mark.parametrize("text,expected_evidence", [
        # Ghost Orb
        ("we found ghost orbs", "orb"),
        ("ghost orb confirmed", "orb"),
        ("we've got ghost orbs", "orb"),
        ("there's ghost orbs in the kitchen", "orb"),
        ("detected ghost orbs", "orb"),
        ("orbs on camera", "orb"),
        # Freezing Temperatures
        ("we found freezing temps", "freezing"),
        ("freezing temperatures confirmed", "freezing"),
        ("we've got freezing temps", "freezing"),
        ("it's freezing in here", "freezing"),
        ("temperatures are freezing", "freezing"),
        ("confirmed freezing", "freezing"),
        # EMF Level 5
        ("we have EMF 5", "emf_5"),
        ("EMF went to 5", "emf_5"),
        ("got EMF 5", "emf_5"),
        ("picked up EMF 5", "emf_5"),
        ("EMF 5 confirmed", "emf_5"),
        # D.O.T.S.
        ("we found DOTS", "dots"),
        ("D.O.T.S. confirmed", "dots"),
        ("got dots projector", "dots"),
        ("DOTS is showing", "dots"),
        # Ultraviolet / Fingerprints
        ("found fingerprints", "uv"),
        ("we have UV", "uv"),
        ("ultraviolet confirmed", "uv"),
        ("got handprints", "uv"),
        ("there's fingerprints", "uv"),
        # Ghost Writing
        ("we found ghost writing", "writing"),
        ("writing confirmed", "writing"),
        ("got writing in the book", "writing"),
        # Spirit Box
        ("spirit box confirmed", "spirit_box"),
        ("we got spirit box", "spirit_box"),
        ("spirit box is responding", "spirit_box"),
    ])
    def test_confirm_evidence(self, text, expected_evidence):
        intent = parse_intent(text)
        assert intent.action == "record_evidence", f"Expected record_evidence, got {intent.action} for: {text}"
        assert intent.evidence_id == expected_evidence, f"Expected {expected_evidence}, got {intent.evidence_id} for: {text}"
        assert intent.status == "confirmed", f"Expected confirmed, got {intent.status} for: {text}"


# ── Evidence RULED OUT ───────────────────────────────────────────────────────

class TestEvidenceRuledOut:
    """Player says they DON'T have evidence → status must be 'ruled_out'."""

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
        ("no freezing temperatures", "freezing"),
        ("doesn't have ghost writing", "writing"),
    ])
    def test_rule_out_evidence(self, text, expected_evidence):
        intent = parse_intent(text)
        assert intent.action == "record_evidence", f"Expected record_evidence, got {intent.action} for: {text}"
        assert intent.evidence_id == expected_evidence, f"Expected {expected_evidence}, got {intent.evidence_id} for: {text}"
        assert intent.status == "ruled_out", f"Expected ruled_out, got {intent.status} for: {text}"


# ── CRITICAL: Evidence misidentification prevention ──────────────────────────

class TestEvidenceMisidentification:
    """These are the exact failures from the phi4-mini test run.
    The router must get these right or the same bugs recur."""

    def test_freezing_temps_is_freezing_not_emf(self):
        """'freezing temps' was misidentified as emf_5 by phi4-mini."""
        intent = parse_intent("we found freezing temps")
        assert intent.evidence_id == "freezing"
        assert intent.status == "confirmed"

    def test_temperatures_are_freezing_is_confirm(self):
        """'temperatures are freezing' was misidentified as ruled_out by phi4-mini."""
        intent = parse_intent("temperatures are freezing")
        assert intent.evidence_id == "freezing"
        assert intent.status == "confirmed"

    def test_its_freezing_is_confirm(self):
        intent = parse_intent("it's freezing in the basement")
        assert intent.evidence_id == "freezing"
        assert intent.status == "confirmed"

    def test_we_got_freezing_is_confirm(self):
        intent = parse_intent("we've got freezing temps")
        assert intent.evidence_id == "freezing"
        assert intent.status == "confirmed"


# ── Investigation management ─────────────────────────────────────────────────

class TestInvestigationInit:
    @pytest.mark.parametrize("text,expected_diff", [
        ("new game professional", "professional"),
        ("start investigation on nightmare", "nightmare"),
        ("new investigation amateur", "amateur"),
        ("begin new game insanity", "insanity"),
        ("start fresh game", "professional"),  # no difficulty → default
        ("reset the investigation", "professional"),
    ])
    def test_init_investigation(self, text, expected_diff):
        intent = parse_intent(text)
        assert intent.action == "init_investigation"
        assert intent.difficulty == expected_diff


# ── State queries ────────────────────────────────────────────────────────────

class TestStateQueries:
    @pytest.mark.parametrize("text", [
        "what ghosts are left?",
        "what's left?",
        "what do we have?",
        "what evidence have we collected?",
        "how many ghosts remain?",
        "which ghosts are still candidates?",
        "where are we?",
        "what do we know?",
    ])
    def test_state_queries(self, text):
        intent = parse_intent(text)
        assert intent.action == "get_investigation_state", f"Expected get_investigation_state for: {text}"


# ── Ghost database queries ───────────────────────────────────────────────────

class TestGhostQueries:
    @pytest.mark.parametrize("text,expected_ghost", [
        ("what does the Banshee do?", "Banshee"),
        ("tell me about the Spirit", "Spirit"),
        ("Wraith info", "Wraith"),
    ])
    def test_ghost_queries(self, text, expected_ghost):
        intent = parse_intent(text)
        assert intent.action == "query_ghost_database"
        assert intent.ghost_name == expected_ghost


# ── Behavioral observations ──────────────────────────────────────────────────

class TestBehavioralEvents:
    def test_ghost_stepped_in_salt(self):
        intent = parse_intent("the ghost stepped in salt")
        assert intent.action == "record_behavioral_event"
        assert intent.eliminator_key == "ghost_stepped_in_salt"

    def test_airball(self):
        intent = parse_intent("we saw an airball event")
        assert intent.action == "record_behavioral_event"
        assert intent.eliminator_key == "airball_event_observed"


# ── Advice / suggest next evidence ───────────────────────────────────────────

class TestAdviceQueries:
    @pytest.mark.parametrize("text", [
        "what should we do next?",
        "what should we test?",
        "what evidence should we look for?",
        "what should I check next?",
        "suggest something",
        "what's next?",
        "what else can we try?",
    ])
    def test_advice_queries(self, text):
        intent = parse_intent(text)
        assert intent.action == "suggest_next_evidence", f"Expected suggest_next_evidence for: {text}"


# ── Ghost evidence queries ──────────────────────────────────────────────────

class TestGhostEvidenceQueries:
    def test_what_evidence_does_ghost_have(self):
        intent = parse_intent("what evidence does the Banshee have?")
        assert intent.action == "query_ghost_database"
        assert intent.ghost_name == "Banshee"

    def test_what_evidence_does_ghost_need(self):
        intent = parse_intent("what evidence does the Spirit need?")
        assert intent.action == "query_ghost_database"
        assert intent.ghost_name == "Spirit"


# ── LLM fallback ────────────────────────────────────────────────────────────

class TestLLMFallback:
    @pytest.mark.parametrize("text", [
        "I'm scared",
        "this is creepy",
        "thanks oracle",
        "hello",
    ])
    def test_ambiguous_inputs_fall_back(self, text):
        intent = parse_intent(text)
        assert intent.action == "llm_fallback", f"Expected llm_fallback for: {text}"
        assert intent.confidence == 0.0


# ── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_input(self):
        intent = parse_intent("")
        assert intent.action == "null"

    def test_whitespace_only(self):
        intent = parse_intent("   ")
        assert intent.action == "null"

    def test_multiple_evidence_returns_first(self):
        """When multiple evidence types are mentioned, return the first one."""
        intent = parse_intent("we found ghost orbs and freezing temps")
        assert intent.action == "record_evidence"
        assert intent.evidence_id in ("orb", "freezing")
        # Extra evidence should be noted for follow-up
        assert len(intent.extra_evidence) >= 1
