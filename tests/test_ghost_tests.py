"""Tests for engine.ghost_test_result() and engine.available_tests().

These methods had zero test coverage. Tests cover positive/negative test types,
elimination logic, identification logic, ghost-not-found, and available_tests().
"""
from __future__ import annotations

import pytest

from oracle.engine import (
    InvestigationEngine,
    TestResult,
    AvailableTestsResult,
)
from oracle.deduction import reset_db


@pytest.fixture(autouse=True)
def _fresh_db():
    reset_db()
    yield
    reset_db()


@pytest.fixture()
def engine() -> InvestigationEngine:
    eng = InvestigationEngine()
    eng.new_game("professional")
    return eng


# ---------------------------------------------------------------------------
# ghost_test_result — positive tests
# ---------------------------------------------------------------------------


class TestPositiveTests:
    """Positive tests: passed=True means the ghost exhibited expected behavior."""

    def test_positive_passed_identifies_ghost(self, engine):
        """A positive test that passes should identify the ghost (if candidate)."""
        # Hantu has test_type=positive
        result = engine.ghost_test_result("Hantu", passed=True)
        assert isinstance(result, TestResult)
        assert result.ghost_name == "Hantu"
        assert result.passed is True
        assert result.identified_ghost == "Hantu"
        assert result.eliminated_ghosts == []

    def test_positive_failed_eliminates_ghost(self, engine):
        """A positive test that fails means the ghost doesn't match -- eliminate."""
        result = engine.ghost_test_result("Hantu", passed=False)
        assert isinstance(result, TestResult)
        assert result.passed is False
        assert "Hantu" in result.eliminated_ghosts
        assert "Hantu" not in engine.candidates
        assert result.remaining_count == 26

    def test_positive_failed_recalculates_candidates(self, engine):
        """After elimination, candidate list is recalculated via narrow_candidates."""
        engine.ghost_test_result("Hantu", passed=False)
        assert "Hantu" not in engine.candidates
        assert "Hantu" in engine.eliminated_ghosts


# ---------------------------------------------------------------------------
# ghost_test_result — negative tests
# ---------------------------------------------------------------------------


class TestNegativeTests:
    """Negative tests: passed=True means the ghost DID exhibit disqualifying behavior.

    For negative test_type ghosts (e.g. Banshee, Goryo, Wraith):
    - passed=True means the ghost exhibited the behavior -> ELIMINATE (it's not that ghost)
    - passed=False means the ghost did NOT exhibit the behavior -> IDENTIFY (consistent)
    """

    def test_negative_passed_eliminates_ghost(self, engine):
        """Banshee has test_type=negative. passed=True means the ghost targeted
        multiple players (disqualifying behavior) -> eliminate."""
        result = engine.ghost_test_result("Banshee", passed=True)
        assert isinstance(result, TestResult)
        assert "Banshee" in result.eliminated_ghosts
        assert result.identified_ghost is None

    def test_negative_failed_identifies_ghost(self, engine):
        """Banshee has test_type=negative. passed=False means the ghost did NOT
        exhibit disqualifying behavior -> identifies as Banshee."""
        result = engine.ghost_test_result("Banshee", passed=False)
        assert isinstance(result, TestResult)
        assert result.identified_ghost == "Banshee"
        assert result.eliminated_ghosts == []

    def test_goryo_negative_passed_eliminates(self, engine):
        """Goryo has test_type=negative. passed=True (ghost changed rooms) -> eliminate."""
        result = engine.ghost_test_result("Goryo", passed=True)
        assert "Goryo" in result.eliminated_ghosts
        assert result.identified_ghost is None

    def test_goryo_negative_failed_identifies(self, engine):
        """Goryo has test_type=negative. passed=False (ghost didn't change rooms) -> identify."""
        result = engine.ghost_test_result("Goryo", passed=False)
        assert result.identified_ghost == "Goryo"
        assert result.eliminated_ghosts == []


# ---------------------------------------------------------------------------
# ghost_test_result — edge cases
# ---------------------------------------------------------------------------


class TestGhostTestEdgeCases:
    def test_ghost_not_found(self, engine):
        """A nonexistent ghost returns a result with no eliminations."""
        result = engine.ghost_test_result("NotARealGhost", passed=True)
        assert isinstance(result, TestResult)
        assert result.ghost_name == "NotARealGhost"
        assert result.eliminated_ghosts == []
        assert result.identified_ghost is None
        assert result.remaining_count == 27

    def test_ghost_not_candidate_still_identifies(self, engine):
        """If the ghost is not a current candidate, it should not be identified."""
        # First eliminate Hantu
        engine.eliminated_ghosts.append("Hantu")
        engine.candidates = [c for c in engine.candidates if c != "Hantu"]
        # Now pass the test -- Hantu is not a candidate
        result = engine.ghost_test_result("Hantu", passed=True)
        # Should NOT identify since Hantu is not a candidate
        assert result.identified_ghost is None

    def test_double_elimination_is_idempotent(self, engine):
        """Eliminating the same ghost twice does not add duplicate entries."""
        engine.ghost_test_result("Hantu", passed=False)
        result2 = engine.ghost_test_result("Hantu", passed=False)
        assert result2.eliminated_ghosts == []  # Already eliminated
        assert engine.eliminated_ghosts.count("Hantu") == 1

    def test_elimination_updates_remaining_count(self, engine):
        """remaining_count reflects the new candidate count after elimination."""
        initial = len(engine.candidates)
        result = engine.ghost_test_result("Hantu", passed=False)
        assert result.remaining_count == initial - 1


# ---------------------------------------------------------------------------
# available_tests
# ---------------------------------------------------------------------------


class TestAvailableTests:
    def test_returns_all_testable_candidates(self, engine):
        """With all 27 candidates, available_tests lists ghosts that have tests."""
        result = engine.available_tests()
        assert isinstance(result, AvailableTestsResult)
        assert result.total_candidates == 27
        # ghost_tests.yaml has 26 ghosts covered (Mimic has no test)
        assert len(result.testable) >= 20  # Broad check -- most ghosts have tests
        # Each testable entry is a (name, description) tuple
        for name, desc in result.testable:
            assert isinstance(name, str)
            assert isinstance(desc, str)
            assert len(desc) > 0

    def test_untestable_includes_mimic(self, engine):
        """The Mimic has no behavioral test -- should be in untestable."""
        result = engine.available_tests()
        assert "The Mimic" in result.untestable

    def test_eliminated_ghost_not_in_results(self, engine):
        """After eliminating a ghost, it should not appear in available_tests."""
        # Hantu has test_type=positive; passed=False eliminates it
        engine.ghost_test_result("Hantu", passed=False)
        result = engine.available_tests()
        testable_names = [name for name, _ in result.testable]
        assert "Hantu" not in testable_names
        assert "Hantu" not in result.untestable
        assert result.total_candidates == 26

    def test_testable_descriptions_are_nonempty(self, engine):
        """Every testable ghost should have a non-empty description."""
        result = engine.available_tests()
        for _, desc in result.testable:
            assert desc.strip() != ""
