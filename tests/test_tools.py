"""Comprehensive tests for graph/tools.py — pure Python, no Ollama required."""
from __future__ import annotations

import pytest

from graph.tools import (
    bind_state,
    sync_state_from,
    init_investigation,
    record_evidence,
    record_behavioral_event,
    get_investigation_state,
    query_ghost_database,
    register_players,
    record_theory,
    suggest_next_evidence,
    VALID_EVIDENCE,
    normalize_evidence_id,
    _state,
)
from graph.deduction import all_ghost_names
from graph.state import DEFAULT_SOFT_FACTS


# ── Helpers ─────────────────────────────────────────────────────────────────


def _fresh_state() -> dict:
    """Return a blank state dict with all required keys."""
    return {
        "difficulty": "professional",
        "evidence_confirmed": [],
        "evidence_ruled_out": [],
        "behavioral_observations": [],
        "eliminated_ghosts": [],
        "candidates": all_ghost_names(),
    }


@pytest.fixture(autouse=True)
def reset_state():
    """Bind a clean state before every test and sync back after."""
    state = _fresh_state()
    bind_state(state)
    yield state
    sync_state_from(state)


# ── 1. bind_state / sync_state_from ────────────────────────────────────────


class TestBindSyncState:
    def test_mutations_propagate_back(self):
        """Changes made via tools are visible after sync_state_from."""
        state = _fresh_state()
        bind_state(state)
        init_investigation.invoke({"difficulty": "nightmare"})
        sync_state_from(state)
        assert state["difficulty"] == "nightmare"
        assert state["evidence_confirmed"] == []
        assert len(state["candidates"]) == 27

    def test_bind_replaces_previous_state(self):
        """Calling bind_state a second time replaces the prior state."""
        state_a = _fresh_state()
        state_b = _fresh_state()
        bind_state(state_a)
        init_investigation.invoke({"difficulty": "amateur"})
        bind_state(state_b)
        # state_b should be clean — _state should match state_b, not state_a
        assert _state.get("difficulty") == "professional"


# ── 2. init_investigation ──────────────────────────────────────────────────


class TestInitInvestigation:
    def test_resets_all_fields_and_returns_27_candidates(self):
        # Dirty up state first
        _state["evidence_confirmed"] = ["emf_5", "dots"]
        _state["evidence_ruled_out"] = ["orb"]
        _state["behavioral_observations"] = ["something"]
        _state["eliminated_ghosts"] = ["Wraith"]

        result = init_investigation.invoke({"difficulty": "professional"})

        assert "27" in result
        assert _state["evidence_confirmed"] == []
        assert _state["evidence_ruled_out"] == []
        assert _state["behavioral_observations"] == []
        assert _state["eliminated_ghosts"] == []
        assert len(_state["candidates"]) == 27

    def test_invalid_difficulty_defaults_to_professional(self):
        result = init_investigation.invoke({"difficulty": "hardcore"})
        assert "professional" in result
        assert _state["difficulty"] == "professional"

    @pytest.mark.parametrize("diff", ["amateur", "intermediate", "nightmare", "insanity"])
    def test_valid_difficulties_accepted(self, diff):
        result = init_investigation.invoke({"difficulty": diff})
        assert diff in result
        assert _state["difficulty"] == diff


# ── 3. record_evidence ─────────────────────────────────────────────────────


class TestRecordEvidence:
    def test_confirm_evidence_narrows_candidates(self):
        init_investigation.invoke({"difficulty": "professional"})
        result = record_evidence.invoke({"evidence_id": "emf_5", "status": "confirmed"})
        assert len(_state["candidates"]) < 27
        assert "emf_5" in _state["evidence_confirmed"]
        # Every remaining candidate must have emf_5
        from graph.deduction import get_ghost

        for name in _state["candidates"]:
            ghost = get_ghost(name)
            assert "emf_5" in ghost["evidence"], f"{name} should have emf_5"

    def test_rule_out_evidence_narrows_candidates(self):
        init_investigation.invoke({"difficulty": "professional"})
        result = record_evidence.invoke({"evidence_id": "freezing", "status": "ruled_out"})
        assert len(_state["candidates"]) < 27
        assert "freezing" in _state["evidence_ruled_out"]
        # No remaining candidate should have freezing (except Mimic fake_evidence edge case)
        from graph.deduction import get_ghost

        for name in _state["candidates"]:
            ghost = get_ghost(name)
            if ghost.get("fake_evidence") == "freezing":
                continue
            assert "freezing" not in ghost["evidence"], f"{name} shouldn't have freezing"

    def test_synonym_normalization(self):
        """'ghost_orb' should be normalized to 'orb' before processing."""
        init_investigation.invoke({"difficulty": "professional"})
        result = record_evidence.invoke({"evidence_id": "ghost_orb", "status": "confirmed"})
        assert "orb" in _state["evidence_confirmed"]
        assert "ghost_orb" not in _state["evidence_confirmed"]
        # Should not produce an error
        assert "Unknown evidence type" not in result

    def test_synonym_emf(self):
        """'emf' should normalize to 'emf_5'."""
        init_investigation.invoke({"difficulty": "professional"})
        record_evidence.invoke({"evidence_id": "emf", "status": "confirmed"})
        assert "emf_5" in _state["evidence_confirmed"]

    def test_synonym_ghost_writing(self):
        """'ghost_writing' should normalize to 'writing'."""
        init_investigation.invoke({"difficulty": "professional"})
        record_evidence.invoke({"evidence_id": "ghost_writing", "status": "confirmed"})
        assert "writing" in _state["evidence_confirmed"]

    def test_invalid_evidence_id_returns_error(self):
        init_investigation.invoke({"difficulty": "professional"})
        result = record_evidence.invoke({"evidence_id": "banana", "status": "confirmed"})
        assert "Unknown evidence type" in result
        assert "banana" in result

    def test_invalid_status_returns_error(self):
        init_investigation.invoke({"difficulty": "professional"})
        result = record_evidence.invoke({"evidence_id": "emf_5", "status": "maybe"})
        assert "Invalid status" in result
        assert "maybe" in result

    def test_status_change_feedback_confirm_then_rule_out(self):
        """Changing evidence from confirmed to ruled_out should include feedback."""
        init_investigation.invoke({"difficulty": "professional"})
        record_evidence.invoke({"evidence_id": "emf_5", "status": "confirmed"})
        assert "emf_5" in _state["evidence_confirmed"]

        result = record_evidence.invoke({"evidence_id": "emf_5", "status": "ruled_out"})
        assert "emf_5" not in _state["evidence_confirmed"]
        assert "emf_5" in _state["evidence_ruled_out"]
        assert "previously" in result.lower()
        assert "confirmed" in result.lower()

    def test_status_change_feedback_rule_out_then_confirm(self):
        """Changing evidence from ruled_out to confirmed should include feedback."""
        init_investigation.invoke({"difficulty": "professional"})
        record_evidence.invoke({"evidence_id": "dots", "status": "ruled_out"})
        result = record_evidence.invoke({"evidence_id": "dots", "status": "confirmed"})
        assert "dots" in _state["evidence_confirmed"]
        assert "dots" not in _state["evidence_ruled_out"]
        assert "previously" in result.lower()
        assert "ruled out" in result.lower()

    def test_duplicate_confirm_is_idempotent(self):
        """Confirming the same evidence twice should not duplicate it."""
        init_investigation.invoke({"difficulty": "professional"})
        record_evidence.invoke({"evidence_id": "orb", "status": "confirmed"})
        candidates_after_first = list(_state["candidates"])

        record_evidence.invoke({"evidence_id": "orb", "status": "confirmed"})
        assert _state["evidence_confirmed"].count("orb") == 1
        assert _state["candidates"] == candidates_after_first

    def test_over_proofed_detection_four_evidence(self):
        """4+ confirmed evidence should trigger a warning."""
        init_investigation.invoke({"difficulty": "professional"})
        for ev in ["emf_5", "dots", "uv", "freezing"]:
            record_evidence.invoke({"evidence_id": ev, "status": "confirmed"})

        # The 4th confirmation should have triggered the warning
        result = record_evidence.invoke({"evidence_id": "spirit_box", "status": "confirmed"})
        assert "evidence types confirmed" in result.lower()
        assert "incorrectly" in result.lower()

    def test_over_proofed_mimic_orb_exception(self):
        """3 evidence + orb = 4 total should mention The Mimic."""
        init_investigation.invoke({"difficulty": "professional"})
        for ev in ["uv", "freezing", "spirit_box"]:
            record_evidence.invoke({"evidence_id": ev, "status": "confirmed"})

        result = record_evidence.invoke({"evidence_id": "orb", "status": "confirmed"})
        assert "mimic" in result.lower()

    def test_over_proofed_four_including_orb_but_not_mimic_evidence(self):
        """4 evidence including orb but NOT The Mimic's real evidence set should
        still mention Mimic possibility because the check is purely count-based."""
        init_investigation.invoke({"difficulty": "professional"})
        for ev in ["emf_5", "dots", "writing"]:
            record_evidence.invoke({"evidence_id": ev, "status": "confirmed"})

        result = record_evidence.invoke({"evidence_id": "orb", "status": "confirmed"})
        # Still triggers the Mimic message because len==4 and "orb" in confirmed
        assert "mimic" in result.lower()

    def test_zero_candidates_produces_warning(self):
        """When no ghosts match, the result should warn the user."""
        init_investigation.invoke({"difficulty": "professional"})
        # Confirm and rule out enough evidence to eliminate all ghosts
        record_evidence.invoke({"evidence_id": "emf_5", "status": "confirmed"})
        record_evidence.invoke({"evidence_id": "dots", "status": "confirmed"})
        record_evidence.invoke({"evidence_id": "uv", "status": "confirmed"})
        # Now rule out all three — contradicts the confirms, but rules out everything
        # Actually, let's confirm 3 evidence that no ghost has together after ruling out others
        # Simpler: confirm evidence and rule out evidence that creates an impossible combo
        init_investigation.invoke({"difficulty": "professional"})
        # Confirm emf_5 (must have it) and rule out all other evidence one of those ghosts needs
        record_evidence.invoke({"evidence_id": "emf_5", "status": "confirmed"})
        record_evidence.invoke({"evidence_id": "dots", "status": "confirmed"})
        record_evidence.invoke({"evidence_id": "uv", "status": "confirmed"})
        # Now rule out all three as well — forcing zero via contradictory setup
        # Better approach: rule out all 7 evidence types
        init_investigation.invoke({"difficulty": "professional"})
        for ev in VALID_EVIDENCE:
            record_evidence.invoke({"evidence_id": ev, "status": "ruled_out"})

        assert len(_state["candidates"]) == 0
        # The last result should contain a warning
        result = record_evidence.invoke({"evidence_id": "emf_5", "status": "ruled_out"})
        assert "no ghosts match" in result.lower()


# ── 4. record_behavioral_event ─────────────────────────────────────────────


class TestRecordBehavioralEvent:
    def test_with_eliminator_key(self):
        """ghost_stepped_in_salt should eliminate Wraith."""
        init_investigation.invoke({"difficulty": "professional"})
        result = record_behavioral_event.invoke(
            {
                "observation": "Ghost walked through salt pile",
                "eliminator_key": "ghost_stepped_in_salt",
            }
        )
        assert "Wraith" in result
        assert "Eliminated" in result
        assert "Wraith" in _state["eliminated_ghosts"]
        assert "Wraith" not in _state["candidates"]

    def test_without_eliminator_key(self):
        """Plain observation should just log without eliminating anyone."""
        init_investigation.invoke({"difficulty": "professional"})
        original_candidates = list(_state["candidates"])
        result = record_behavioral_event.invoke(
            {
                "observation": "Ghost threw a plate in the kitchen",
            }
        )
        assert "Observation logged" in result
        assert _state["candidates"] == original_candidates
        assert "Ghost threw a plate in the kitchen" in _state["behavioral_observations"]

    def test_eliminator_key_unknown(self):
        """An unknown eliminator_key should not eliminate anyone."""
        init_investigation.invoke({"difficulty": "professional"})
        original_count = len(_state["candidates"])
        result = record_behavioral_event.invoke(
            {
                "observation": "Something weird happened",
                "eliminator_key": "nonexistent_key",
            }
        )
        assert "Observation logged" in result
        assert len(_state["candidates"]) == original_count

    def test_duplicate_eliminator_is_idempotent(self):
        """Applying the same eliminator twice should not duplicate entries."""
        init_investigation.invoke({"difficulty": "professional"})
        record_behavioral_event.invoke(
            {
                "observation": "Salt disturbed",
                "eliminator_key": "ghost_stepped_in_salt",
            }
        )
        record_behavioral_event.invoke(
            {
                "observation": "Salt disturbed again",
                "eliminator_key": "ghost_stepped_in_salt",
            }
        )
        assert _state["eliminated_ghosts"].count("Wraith") == 1


# ── 5. get_investigation_state ─────────────────────────────────────────────


class TestGetInvestigationState:
    def test_returns_formatted_summary(self):
        init_investigation.invoke({"difficulty": "nightmare"})
        record_evidence.invoke({"evidence_id": "emf_5", "status": "confirmed"})
        record_evidence.invoke({"evidence_id": "orb", "status": "ruled_out"})

        result = get_investigation_state.invoke({})

        assert "Difficulty: nightmare" in result
        assert "emf_5" in result
        assert "orb" in result
        assert "Confirmed evidence (1)" in result
        assert "Ruled out (1)" in result
        assert "Candidates" in result

    def test_empty_state_shows_none(self):
        """A freshly initialized investigation shows 'none' for empty lists."""
        init_investigation.invoke({"difficulty": "professional"})
        result = get_investigation_state.invoke({})
        assert "none" in result
        assert "Eliminated ghosts: none" in result

    def test_behavioral_observations_counted(self):
        init_investigation.invoke({"difficulty": "professional"})
        record_behavioral_event.invoke({"observation": "Event 1"})
        record_behavioral_event.invoke({"observation": "Event 2"})
        result = get_investigation_state.invoke({})
        assert "2 logged" in result


# ── 6. query_ghost_database ────────────────────────────────────────────────


class TestQueryGhostDatabase:
    def test_ghost_found_no_field(self):
        """Full summary returned when no field is specified."""
        result = query_ghost_database.invoke({"ghost_name": "Wraith"})
        assert "Ghost: Wraith" in result
        assert "Evidence:" in result
        assert "Hunt threshold:" in result
        assert "Behavioral tells:" in result

    def test_ghost_found_specific_field(self):
        """Requesting a specific field returns only that field."""
        result = query_ghost_database.invoke(
            {"ghost_name": "Wraith", "field": "evidence"}
        )
        assert "Wraith" in result
        assert "evidence" in result
        # Wraith has dots, emf_5, spirit_box
        assert "dots" in result
        assert "emf_5" in result
        assert "spirit_box" in result

    def test_ghost_not_found_returns_error_with_names(self):
        result = query_ghost_database.invoke({"ghost_name": "Casper"})
        assert "not found" in result
        assert "Casper" in result
        # Should list known ghosts
        assert "Wraith" in result
        assert "Spirit" in result

    def test_ghost_name_case_insensitive(self):
        result = query_ghost_database.invoke({"ghost_name": "wraith"})
        assert "Ghost: Wraith" in result

    def test_invalid_field_returns_error(self):
        result = query_ghost_database.invoke(
            {"ghost_name": "Wraith", "field": "favorite_color"}
        )
        assert "not found" in result.lower()
        assert "favorite_color" in result


# ── 7. normalize_evidence_id (unit-level) ──────────────────────────────────


class TestNormalizeEvidenceId:
    def test_canonical_id_passes_through(self):
        assert normalize_evidence_id("emf_5") == "emf_5"
        assert normalize_evidence_id("orb") == "orb"

    def test_synonym_maps_correctly(self):
        assert normalize_evidence_id("ghost_orb") == "orb"
        assert normalize_evidence_id("ghost_orbs") == "orb"
        assert normalize_evidence_id("fingerprints") == "uv"
        assert normalize_evidence_id("emf") == "emf_5"
        assert normalize_evidence_id("ghost_writing") == "writing"
        assert normalize_evidence_id("spiritbox") == "spirit_box"

    def test_case_insensitive(self):
        assert normalize_evidence_id("Ghost_Orb") == "orb"
        assert normalize_evidence_id("EMF") == "emf_5"

    def test_whitespace_stripped(self):
        assert normalize_evidence_id("  orb  ") == "orb"
        assert normalize_evidence_id(" ghost_orb ") == "orb"

    def test_unknown_passes_through(self):
        assert normalize_evidence_id("banana") == "banana"


# ── Sprint 2: init_investigation resets new fields ────────────────────────


class TestInitInvestigationSprint2:
    def test_resets_investigation_phase(self):
        _state["investigation_phase"] = "behavioral"
        init_investigation.invoke({"difficulty": "professional"})
        assert _state["investigation_phase"] == "evidence"

    def test_resets_soft_facts(self):
        _state["soft_facts"] = {"model_gender": "male"}
        init_investigation.invoke({"difficulty": "professional"})
        assert _state["soft_facts"] == DEFAULT_SOFT_FACTS

    def test_resets_players(self):
        _state["players"] = ["Mike"]
        init_investigation.invoke({"difficulty": "professional"})
        assert _state["players"] == []

    def test_resets_theories(self):
        _state["theories"] = {"Mike": "Wraith"}
        init_investigation.invoke({"difficulty": "professional"})
        assert _state["theories"] == {}

    def test_resets_prev_candidate_count(self):
        _state["prev_candidate_count"] = 5
        init_investigation.invoke({"difficulty": "professional"})
        assert _state["prev_candidate_count"] == 27


# ── Sprint 2: register_players ───────────────────────────────────────────


class TestRegisterPlayers:
    def test_register_single_player(self):
        init_investigation.invoke({"difficulty": "professional"})
        result = register_players.invoke({"player_names": "Mike"})
        assert "Mike" in _state["players"]
        assert "Mike" in _state["theories"]
        assert _state["theories"]["Mike"] is None

    def test_register_multiple_players(self):
        init_investigation.invoke({"difficulty": "professional"})
        result = register_players.invoke({"player_names": "Mike, Kayden"})
        assert "Mike" in _state["players"]
        assert "Kayden" in _state["players"]
        assert len(_state["players"]) == 2

    def test_duplicate_player_ignored(self):
        init_investigation.invoke({"difficulty": "professional"})
        register_players.invoke({"player_names": "Mike"})
        register_players.invoke({"player_names": "Mike"})
        assert _state["players"].count("Mike") == 1

    def test_empty_input(self):
        init_investigation.invoke({"difficulty": "professional"})
        result = register_players.invoke({"player_names": ""})
        assert "No player names" in result


# ── Sprint 2: record_theory ──────────────────────────────────────────────


class TestRecordTheory:
    def test_known_player_valid_ghost(self):
        init_investigation.invoke({"difficulty": "professional"})
        register_players.invoke({"player_names": "Mike"})
        result = record_theory.invoke(
            {"player_name": "Mike", "ghost_name": "Wraith"}
        )
        assert _state["theories"]["Mike"] == "Wraith"
        assert "Mike" in result

    def test_unknown_player_auto_registers(self):
        init_investigation.invoke({"difficulty": "professional"})
        result = record_theory.invoke(
            {"player_name": "Kayden", "ghost_name": "Poltergeist"}
        )
        assert "Kayden" in _state["players"]
        assert _state["theories"]["Kayden"] == "Poltergeist"

    def test_invalid_ghost_returns_error(self):
        init_investigation.invoke({"difficulty": "professional"})
        result = record_theory.invoke(
            {"player_name": "Mike", "ghost_name": "Casper"}
        )
        assert "not found" in result

    def test_overwrite_existing_theory(self):
        init_investigation.invoke({"difficulty": "professional"})
        record_theory.invoke({"player_name": "Mike", "ghost_name": "Wraith"})
        result = record_theory.invoke(
            {"player_name": "Mike", "ghost_name": "Spirit"}
        )
        assert _state["theories"]["Mike"] == "Spirit"
        assert "Previously" in result

    def test_theory_for_eliminated_ghost_warns(self):
        init_investigation.invoke({"difficulty": "professional"})
        # Rule out UV to eliminate Wraith
        record_evidence.invoke({"evidence_id": "dots", "status": "ruled_out"})
        result = record_theory.invoke(
            {"player_name": "Mike", "ghost_name": "Wraith"}
        )
        assert "eliminated" in result.lower()


# ── Sprint 2: phase rollback ─────────────────────────────────────────────


class TestPhaseRollback:
    def test_retracting_evidence_resets_phase(self):
        init_investigation.invoke({"difficulty": "nightmare"})
        # Confirm 2 evidence (meets nightmare threshold)
        record_evidence.invoke({"evidence_id": "emf_5", "status": "confirmed"})
        record_evidence.invoke({"evidence_id": "dots", "status": "confirmed"})
        # Manually set phase to behavioral (simulating phase_shift)
        _state["investigation_phase"] = "behavioral"
        # Retract one evidence — drops below threshold
        record_evidence.invoke({"evidence_id": "dots", "status": "ruled_out"})
        assert _state["investigation_phase"] == "evidence"

    def test_phase_stays_behavioral_if_still_at_threshold(self):
        init_investigation.invoke({"difficulty": "nightmare"})
        record_evidence.invoke({"evidence_id": "emf_5", "status": "confirmed"})
        record_evidence.invoke({"evidence_id": "dots", "status": "confirmed"})
        _state["investigation_phase"] = "behavioral"
        # Confirm another evidence — still above threshold
        record_evidence.invoke({"evidence_id": "uv", "status": "confirmed"})
        assert _state["investigation_phase"] == "behavioral"
