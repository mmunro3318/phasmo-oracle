"""InvestigationEngine — pure Python ghost identification engine.

Replaces the old LangChain @tool-based tools.py. All state lives as
instance attributes on InvestigationEngine. Each public method returns
a typed result dataclass. Zero LLM dependencies.
"""
from __future__ import annotations

import json
import yaml
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from pathlib import Path
from typing import Optional

from oracle.deduction import (
    narrow_candidates,
    all_ghost_names,
    apply_observation_eliminator,
    get_ghost,
    load_db,
    EVIDENCE_THRESHOLDS,
    evidence_threshold_reached,
    rank_discriminating_tests,
    eliminate_by_guaranteed_evidence,
)
from oracle.state import DEFAULT_SOFT_FACTS
from oracle.config.settings import config


# ── Canonical evidence IDs ──────────────────────────────────────────────────

VALID_EVIDENCE = {"emf_5", "dots", "uv", "freezing", "orb", "writing", "spirit_box"}

EVIDENCE_LABELS = {
    "emf_5": "EMF Level 5",
    "dots": "D.O.T.S. Projector",
    "uv": "Ultraviolet",
    "freezing": "Freezing Temperatures",
    "orb": "Ghost Orb",
    "writing": "Ghost Writing",
    "spirit_box": "Spirit Box",
}


# ── Evidence synonym loading ────────────────────────────────────────────────

_SYNONYMS: dict[str, str] | None = None


def _load_synonyms() -> dict[str, str]:
    """Load and cache evidence synonym map from YAML."""
    global _SYNONYMS
    if _SYNONYMS is None:
        p = Path(config.SYNONYMS_PATH)
        if p.exists():
            with open(p) as f:
                raw = yaml.safe_load(f) or {}
            _SYNONYMS = {k.lower(): v for k, v in raw.items()}
        else:
            _SYNONYMS = {}
    return _SYNONYMS


def normalize_evidence_id(evidence_id: str) -> str:
    """Normalize an evidence ID using the synonym map.

    Returns the canonical ID if a synonym is found, otherwise
    returns the input unchanged (validation happens downstream).
    """
    synonyms = _load_synonyms()
    key = evidence_id.lower().strip()
    return synonyms.get(key, key)


# ── Ghost test loading ──────────────────────────────────────────────────────

_GHOST_TESTS: dict[str, dict] | None = None


def _load_ghost_tests() -> dict[str, dict]:
    """Load and cache ghost tests from YAML.

    Expected format per ghost:
        GhostName:
            description: "..."
            test_type: "positive" | "negative"
    """
    global _GHOST_TESTS
    if _GHOST_TESTS is None:
        p = Path(config.GHOST_TESTS_PATH)
        if p.exists():
            with open(p) as f:
                _GHOST_TESTS = yaml.safe_load(f) or {}
        else:
            _GHOST_TESTS = {}
    return _GHOST_TESTS


# ── Result dataclasses ──────────────────────────────────────────────────────


@dataclass
class NewGameResult:
    """Returned by new_game()."""
    difficulty: str
    candidate_count: int


@dataclass
class EvidenceResult:
    """Returned by record_evidence()."""
    evidence: str
    evidence_label: str
    status: str
    remaining_count: int
    candidates: list[str]
    threshold_reached: bool
    mimic_detected: bool
    identified_ghost: Optional[str]
    status_changed: bool
    old_status: Optional[str]
    zero_candidates: bool
    over_proofed: bool
    # Trigger flags for downstream routing
    identification_triggered: bool
    phase_shifted: bool
    commentary_needed: bool
    # Ghosts eliminated by guaranteed evidence at threshold
    guaranteed_eliminated: list[str] = dc_field(default_factory=list)


@dataclass
class BehavioralResult:
    """Returned by record_behavioral()."""
    observation: str
    newly_eliminated: list[str]
    remaining_count: int
    candidates: list[str]


@dataclass
class StateResult:
    """Returned by get_state()."""
    difficulty: str
    evidence_confirmed: list[str]
    evidence_ruled_out: list[str]
    observations_count: int
    eliminated: list[str]
    candidates: list[str]


@dataclass
class GhostQueryResult:
    """Returned by query_ghost()."""
    ghost_name: str
    found: bool
    evidence_list: list[str] = dc_field(default_factory=list)
    evidence_status: dict[str, str] = dc_field(default_factory=dict)
    guaranteed_evidence: Optional[str] = None
    tells: list[str] = dc_field(default_factory=list)
    community_tests: list[dict] = dc_field(default_factory=list)
    fake_evidence: Optional[str] = None
    all_ghost_names: list[str] = dc_field(default_factory=list)


@dataclass
class SuggestionResult:
    """Returned by suggest_next()."""
    suggestion_text: str
    evidence_remaining: list[str]
    best_evidence: Optional[str]
    best_evidence_label: Optional[str]
    threshold_reached: bool
    candidates: list[str]


@dataclass
class GuessResult:
    """Returned by record_guess()."""
    ghost_name: str
    found: bool
    old_guess: Optional[str]
    is_candidate: bool
    player_name: Optional[str]


@dataclass
class LockInResult:
    """Returned by lock_in()."""
    ghost_name: str
    found: bool
    is_candidate: bool


@dataclass
class EndGameResult:
    """Returned by end_game()."""
    actual_ghost: str
    found: bool
    guess: Optional[str]
    correct: bool
    identified_ghost: Optional[str]
    was_candidate: bool
    evidence_count: int
    difficulty: str


@dataclass
class TestLookupResult:
    """Returned by ghost_test_lookup()."""
    ghost_name: str
    found: bool
    has_test: bool
    test_description: Optional[str]
    test_type: Optional[str]


@dataclass
class TestResult:
    """Returned by ghost_test_result()."""
    ghost_name: str
    passed: bool
    eliminated_ghosts: list[str]
    remaining_count: int
    identified_ghost: Optional[str] = None


@dataclass
class UnknownCommandResult:
    """Returned when the engine cannot interpret a command."""
    raw_text: str


@dataclass
class PlayerRegistrationResult:
    """Returned by register_players()."""
    added: list[str]
    total: int


@dataclass
class AvailableTestsResult:
    """Returned when player asks which remaining ghosts have tests."""
    testable: list[tuple[str, str]]  # (ghost_name, test_description)
    untestable: list[str]            # ghosts with no test
    total_candidates: int


@dataclass
class VoiceChangeResult:
    """Returned when the player changes Oracle's voice."""
    voice_name: str
    success: bool
    available_voices: list[str] = dc_field(default_factory=list)


# ── InvestigationEngine ─────────────────────────────────────────────────────


class InvestigationEngine:
    """Core investigation engine. Owns all game state as instance attributes.

    Each public method returns a typed result dataclass. The engine has
    zero LLM dependencies — all deduction is pure Python.
    """

    def __init__(self) -> None:
        """Initialize engine and load the ghost database."""
        self._db: dict = load_db()

        # Investigation state — reset by new_game()
        self.difficulty: str = "professional"
        self.evidence_confirmed: list[str] = []
        self.evidence_ruled_out: list[str] = []
        self.behavioral_observations: list[str] = []
        self.eliminated_ghosts: list[str] = []
        self.candidates: list[str] = []
        self.investigation_active: bool = False
        self.identified_ghost: Optional[str] = None
        self.true_ghost: Optional[str] = None

        # Sprint 2 fields
        self.investigation_phase: str = "evidence"
        self.soft_facts: dict = dict(DEFAULT_SOFT_FACTS)
        self.players: list[str] = []
        self.theories: dict[str, Optional[str]] = {}
        self.prev_candidate_count: int = 0
        self.locked_in_ghost: Optional[str] = None

    @property
    def state(self) -> dict:
        """Return a dict snapshot of current investigation state (for display)."""
        return {
            "difficulty": self.difficulty,
            "evidence_confirmed": self.evidence_confirmed,
            "evidence_ruled_out": self.evidence_ruled_out,
            "candidates": self.candidates,
            "eliminated_ghosts": self.eliminated_ghosts,
            "investigation_active": self.investigation_active,
            "identified_ghost": self.identified_ghost,
            "investigation_phase": self.investigation_phase,
            "guess": self.locked_in_ghost or (
                next(iter(self.theories.values()), None)
                if self.theories else None
            ),
            "locked_in": self.locked_in_ghost is not None,
            "players": self.players,
            "theories": self.theories,
        }

    # ── Public methods ──────────────────────────────────────────────────

    def new_game(self, difficulty: str = "professional") -> NewGameResult:
        """Start a new investigation. Resets all state."""
        valid = {"amateur", "intermediate", "professional", "nightmare", "insanity"}
        if difficulty not in valid:
            difficulty = "professional"

        self.difficulty = difficulty
        self.evidence_confirmed = []
        self.evidence_ruled_out = []
        self.behavioral_observations = []
        self.eliminated_ghosts = []
        self.candidates = all_ghost_names()
        self.investigation_active = True
        self.identified_ghost = None
        self.true_ghost = None

        # Sprint 2 fields
        self.investigation_phase = "evidence"
        self.soft_facts = dict(DEFAULT_SOFT_FACTS)
        self.players = []
        self.theories = {}
        self.prev_candidate_count = len(self.candidates)
        self.locked_in_ghost = None

        return NewGameResult(
            difficulty=self.difficulty,
            candidate_count=len(self.candidates),
        )

    def record_evidence(self, evidence_id: str, status: str) -> EvidenceResult:
        """Record a confirmed or ruled-out evidence type.

        Handles synonym normalization, status change tracking, Mimic
        detection, over-proofed warnings, threshold detection, phase
        shifts, and auto-identification.
        """
        evidence_id = normalize_evidence_id(evidence_id)

        if evidence_id not in VALID_EVIDENCE:
            return self._invalid_evidence_result(evidence_id, status)

        if status not in ("confirmed", "ruled_out"):
            return self._invalid_evidence_result(evidence_id, status)

        # Track status changes
        status_changed, old_status = self._apply_evidence_status(evidence_id, status)

        # Re-run deduction
        self.candidates = narrow_candidates(
            self.evidence_confirmed,
            self.evidence_ruled_out,
            self.eliminated_ghosts,
            self.difficulty,
        )

        # Detect edge cases
        threshold_reached = evidence_threshold_reached(
            self.evidence_confirmed, self.difficulty
        )

        # At threshold, eliminate ghosts whose guaranteed evidence wasn't found
        guaranteed_eliminated: list[str] = []
        if threshold_reached:
            before = set(self.candidates)
            self.candidates = eliminate_by_guaranteed_evidence(
                self.candidates, self.evidence_confirmed, self.difficulty
            )
            guaranteed_eliminated = sorted(before - set(self.candidates))

        mimic_detected = self._check_mimic(evidence_id, status)
        over_proofed = self._check_over_proofed(status)
        zero_candidates = len(self.candidates) == 0

        # Phase rollback: if evidence retracted below threshold, reset phase
        phase_shifted = self._check_phase_shift(threshold_reached)

        # Auto-identification
        identified_ghost = self._check_identification()

        # Track candidate changes for commentary routing
        n = len(self.candidates)
        commentary_needed = (
            n != self.prev_candidate_count
            and 1 < n <= 5
        )
        self.prev_candidate_count = n

        # Identification trigger: exactly 1 candidate + threshold reached
        identification_triggered = (
            n == 1
            and threshold_reached
            and self.identified_ghost is not None
        )

        return EvidenceResult(
            evidence=evidence_id,
            evidence_label=EVIDENCE_LABELS.get(evidence_id, evidence_id),
            status=status,
            remaining_count=n,
            candidates=list(self.candidates),
            threshold_reached=threshold_reached,
            mimic_detected=mimic_detected,
            identified_ghost=self.identified_ghost,
            status_changed=status_changed,
            old_status=old_status,
            zero_candidates=zero_candidates,
            over_proofed=over_proofed,
            identification_triggered=identification_triggered,
            phase_shifted=phase_shifted,
            commentary_needed=commentary_needed,
            guaranteed_eliminated=guaranteed_eliminated,
        )

    def record_behavioral(
        self, observation: str, eliminator_key: str = ""
    ) -> BehavioralResult:
        """Log a behavioral observation. Optionally apply an eliminator."""
        self.behavioral_observations.append(observation)

        newly_eliminated: list[str] = []
        if eliminator_key:
            to_eliminate = apply_observation_eliminator(eliminator_key)
            for ghost_name in to_eliminate:
                if ghost_name not in self.eliminated_ghosts:
                    self.eliminated_ghosts.append(ghost_name)
                    newly_eliminated.append(ghost_name)

            if newly_eliminated:
                self.candidates = narrow_candidates(
                    self.evidence_confirmed,
                    self.evidence_ruled_out,
                    self.eliminated_ghosts,
                    self.difficulty,
                )

        return BehavioralResult(
            observation=observation,
            newly_eliminated=newly_eliminated,
            remaining_count=len(self.candidates),
            candidates=list(self.candidates),
        )

    def get_state(self) -> StateResult:
        """Return a full summary of the current investigation state."""
        return StateResult(
            difficulty=self.difficulty,
            evidence_confirmed=list(self.evidence_confirmed),
            evidence_ruled_out=list(self.evidence_ruled_out),
            observations_count=len(self.behavioral_observations),
            eliminated=list(self.eliminated_ghosts),
            candidates=list(self.candidates),
        )

    def query_ghost(self, ghost_name: str) -> GhostQueryResult:
        """Look up a ghost in the database by name."""
        ghost = get_ghost(ghost_name)
        if not ghost:
            return GhostQueryResult(
                ghost_name=ghost_name,
                found=False,
                all_ghost_names=[g["name"] for g in self._db["ghosts"]],
            )

        # Build evidence status relative to current investigation
        ghost_evidence = ghost.get("evidence", [])
        confirmed_set = set(self.evidence_confirmed)
        ruled_out_set = set(self.evidence_ruled_out)

        evidence_status: dict[str, str] = {}
        for e in ghost_evidence:
            if e in confirmed_set:
                evidence_status[e] = "confirmed"
            elif e in ruled_out_set:
                evidence_status[e] = "ruled_out"
            else:
                evidence_status[e] = "untested"

        fake = ghost.get("fake_evidence")
        if fake:
            evidence_status[fake] = "fake"

        return GhostQueryResult(
            ghost_name=ghost["name"],
            found=True,
            evidence_list=ghost_evidence,
            evidence_status=evidence_status,
            guaranteed_evidence=ghost.get("guaranteed_evidence"),
            tells=ghost.get("behavioral_tells", []),
            community_tests=ghost.get("community_tests", []),
            fake_evidence=fake,
        )

    def suggest_next(self) -> SuggestionResult:
        """Suggest which evidence type to test next."""
        confirmed = set(self.evidence_confirmed)
        ruled_out = set(self.evidence_ruled_out)
        tested = confirmed | ruled_out
        remaining = sorted(VALID_EVIDENCE - tested)

        threshold = EVIDENCE_THRESHOLDS.get(self.difficulty, 3)
        n_confirmed = len(confirmed)
        threshold_reached = n_confirmed >= threshold

        best_evidence: Optional[str] = None
        best_evidence_label: Optional[str] = None
        suggestion_text: str

        if threshold_reached:
            suggestion_text = (
                f"You've confirmed {n_confirmed} evidence type(s) — the maximum "
                f"observable on {self.difficulty} difficulty."
            )
            if len(self.candidates) == 1:
                suggestion_text += f" The ghost is {self.candidates[0]}."
            elif len(self.candidates) <= 5:
                suggestion_text += (
                    f" Remaining candidates: {', '.join(self.candidates)}."
                    " Use behavioral observations or rule out evidence to narrow further."
                )
            else:
                suggestion_text += (
                    f" {len(self.candidates)} candidates remain."
                    " Rule out evidence to narrow the field."
                )
        elif remaining:
            remaining_labels = [EVIDENCE_LABELS.get(e, e) for e in remaining]
            suggestion_text = f"Evidence not yet tested: {', '.join(remaining_labels)}."

            # Find most discriminating evidence among candidates
            if 1 < len(self.candidates) <= 8:
                best_evidence = self._find_best_discriminator(remaining)
                if best_evidence:
                    best_evidence_label = EVIDENCE_LABELS.get(best_evidence, best_evidence)
                    suggestion_text += (
                        f" Try {best_evidence_label} next — "
                        "it will narrow the field most effectively."
                    )

            suggestion_text += f" {len(self.candidates)} candidate(s) remain."
        else:
            suggestion_text = (
                f"All evidence types have been tested."
                f" {len(self.candidates)} candidate(s) remain."
            )

        return SuggestionResult(
            suggestion_text=suggestion_text,
            evidence_remaining=remaining,
            best_evidence=best_evidence,
            best_evidence_label=best_evidence_label,
            threshold_reached=threshold_reached,
            candidates=list(self.candidates),
        )

    def record_guess(
        self, ghost_name: str, player_name: Optional[str] = None
    ) -> GuessResult:
        """Log a player's guess about the ghost type.

        If player_name is provided, tracks per-player. Auto-registers
        unknown players.
        """
        ghost = get_ghost(ghost_name)
        if not ghost:
            return GuessResult(
                ghost_name=ghost_name,
                found=False,
                old_guess=None,
                is_candidate=False,
                player_name=player_name,
            )

        true_name = ghost["name"]
        old_guess: Optional[str] = None

        if player_name:
            # Auto-register unknown players
            if player_name not in self.players:
                self.players.append(player_name)

            old_guess = self.theories.get(player_name)
            self.theories[player_name] = true_name
        else:
            # No player specified — store as anonymous theory
            old_guess = self.theories.get("_anonymous")
            self.theories["_anonymous"] = true_name

        is_candidate = true_name in self.candidates

        return GuessResult(
            ghost_name=true_name,
            found=True,
            old_guess=old_guess if old_guess != true_name else None,
            is_candidate=is_candidate,
            player_name=player_name,
        )

    def lock_in(self, ghost_name: str) -> LockInResult:
        """Lock in a final answer for the ghost."""
        ghost = get_ghost(ghost_name)
        if not ghost:
            return LockInResult(
                ghost_name=ghost_name,
                found=False,
                is_candidate=False,
            )

        true_name = ghost["name"]
        self.locked_in_ghost = true_name
        is_candidate = true_name in self.candidates

        return LockInResult(
            ghost_name=true_name,
            found=True,
            is_candidate=is_candidate,
        )

    def end_game(self, actual_ghost: str) -> EndGameResult:
        """End the investigation by confirming the actual ghost.

        Persists the session to sessions/history.json.
        """
        ghost = get_ghost(actual_ghost)
        if not ghost:
            return EndGameResult(
                actual_ghost=actual_ghost,
                found=False,
                guess=self.locked_in_ghost,
                correct=False,
                identified_ghost=self.identified_ghost,
                was_candidate=False,
                evidence_count=len(self.evidence_confirmed),
                difficulty=self.difficulty,
            )

        true_name = ghost["name"]
        self.true_ghost = true_name
        self.investigation_active = False

        guess = self.locked_in_ghost or self.identified_ghost
        correct = guess == true_name if guess else False
        was_candidate = true_name in self.candidates

        result = EndGameResult(
            actual_ghost=true_name,
            found=True,
            guess=guess,
            correct=correct,
            identified_ghost=self.identified_ghost,
            was_candidate=was_candidate,
            evidence_count=len(self.evidence_confirmed),
            difficulty=self.difficulty,
        )

        # Persist session history
        self._save_session(result)

        return result

    def register_players(self, player_names: list[str]) -> PlayerRegistrationResult:
        """Register one or more players for this investigation."""
        added: list[str] = []
        for name in player_names:
            name = name.strip()
            if name and name not in self.players:
                self.players.append(name)
                added.append(name)

        # Initialize theories for new players
        for name in added:
            if name not in self.theories:
                self.theories[name] = None

        return PlayerRegistrationResult(
            added=added,
            total=len(self.players),
        )

    def available_tests(self) -> AvailableTestsResult:
        """List which remaining candidates have deterministic tests."""
        tests = _load_ghost_tests()
        testable = []
        untestable = []

        for name in self.candidates:
            entry = tests.get(name) or tests.get(name.lower())
            if entry and entry.get("description"):
                testable.append((name, entry["description"]))
            else:
                untestable.append(name)

        return AvailableTestsResult(
            testable=testable,
            untestable=untestable,
            total_candidates=len(self.candidates),
        )

    def ghost_test_lookup(self, ghost_name: str) -> TestLookupResult:
        """Look up a deterministic ghost test from ghost_tests.yaml."""
        ghost = get_ghost(ghost_name)
        if not ghost:
            return TestLookupResult(
                ghost_name=ghost_name,
                found=False,
                has_test=False,
                test_description=None,
                test_type=None,
            )

        true_name = ghost["name"]
        tests = _load_ghost_tests()
        # YAML keys are lowercase; ghost DB names are title case
        test_entry = tests.get(true_name) or tests.get(true_name.lower())

        if not test_entry:
            return TestLookupResult(
                ghost_name=true_name,
                found=True,
                has_test=False,
                test_description=None,
                test_type=None,
            )

        return TestLookupResult(
            ghost_name=true_name,
            found=True,
            has_test=True,
            test_description=test_entry.get("description"),
            test_type=test_entry.get("test_type"),
        )

    def ghost_test_result(self, ghost_name: str, passed: bool) -> TestResult:
        """Record the result of a ghost test.

        If the test failed (passed=False for a positive test, or
        passed=True for a negative test), the ghost is eliminated.
        """
        ghost = get_ghost(ghost_name)
        if not ghost:
            return TestResult(
                ghost_name=ghost_name,
                passed=passed,
                eliminated_ghosts=[],
                remaining_count=len(self.candidates),
            )

        true_name = ghost["name"]
        eliminated: list[str] = []

        # Look up test type to determine elimination logic
        tests = _load_ghost_tests()
        # YAML keys are lowercase; ghost DB names are title case
        test_entry = tests.get(true_name) or tests.get(true_name.lower()) or {}
        test_type = test_entry.get("test_type", "positive")

        should_eliminate = False
        if test_type == "positive" and not passed:
            # Positive test failed — ghost doesn't exhibit expected behavior
            should_eliminate = True
        elif test_type == "negative" and passed:
            # Negative test passed — ghost exhibits behavior it shouldn't
            should_eliminate = True

        if should_eliminate and true_name not in self.eliminated_ghosts:
            self.eliminated_ghosts.append(true_name)
            eliminated.append(true_name)
            self.candidates = narrow_candidates(
                self.evidence_confirmed,
                self.evidence_ruled_out,
                self.eliminated_ghosts,
                self.difficulty,
            )

        # A passed test that CONFIRMS the ghost's behavior is an identification
        # signal — if this ghost is a current candidate, lock it in.
        identified = None
        should_identify = False
        if test_type == "positive" and passed:
            should_identify = True
        elif test_type == "negative" and not passed:
            should_identify = True

        if should_identify and true_name in self.candidates:
            self.identified_ghost = true_name
            identified = true_name

        return TestResult(
            ghost_name=true_name,
            passed=passed,
            eliminated_ghosts=eliminated,
            remaining_count=len(self.candidates),
            identified_ghost=identified,
        )

    # ── Private helpers ─────────────────────────────────────────────────

    def _apply_evidence_status(
        self, evidence_id: str, status: str
    ) -> tuple[bool, Optional[str]]:
        """Move evidence between confirmed/ruled_out lists.

        Returns (status_changed, old_status) for tracking flips.
        """
        status_changed = False
        old_status: Optional[str] = None

        if status == "confirmed":
            if evidence_id in self.evidence_ruled_out:
                self.evidence_ruled_out.remove(evidence_id)
                status_changed = True
                old_status = "ruled_out"
            if evidence_id not in self.evidence_confirmed:
                self.evidence_confirmed.append(evidence_id)
        elif status == "ruled_out":
            if evidence_id in self.evidence_confirmed:
                self.evidence_confirmed.remove(evidence_id)
                status_changed = True
                old_status = "confirmed"
            if evidence_id not in self.evidence_ruled_out:
                self.evidence_ruled_out.append(evidence_id)

        return status_changed, old_status

    def _check_mimic(self, evidence_id: str, status: str) -> bool:
        """Detect Mimic: orbs confirmed + more evidence than threshold allows.

        The Mimic has 3 real evidence types + orb (fake). The tell is that
        the player has confirmed MORE evidence than the difficulty allows —
        the extra piece is the fake orb. On Professional (threshold=3),
        this means 4 confirmed. On Nightmare (threshold=2), 3 confirmed.
        """
        if status != "confirmed" or "orb" not in self.evidence_confirmed:
            return False
        if "The Mimic" not in self.candidates:
            return False

        threshold = EVIDENCE_THRESHOLDS.get(self.difficulty, 3)
        return len(self.evidence_confirmed) > threshold

    def _check_over_proofed(self, status: str) -> bool:
        """Detect over-proofed: more confirmed evidence than threshold allows."""
        if status != "confirmed":
            return False
        threshold = EVIDENCE_THRESHOLDS.get(self.difficulty, 3)
        return len(self.evidence_confirmed) > threshold

    def _check_phase_shift(self, threshold_reached: bool) -> bool:
        """Handle phase transitions between evidence and behavioral phases.

        Returns True if a phase shift occurred this turn.
        """
        if threshold_reached and self.investigation_phase == "evidence":
            self.investigation_phase = "behavioral"
            return True

        # Phase rollback: evidence retracted below threshold
        if (
            self.investigation_phase == "behavioral"
            and not evidence_threshold_reached(
                self.evidence_confirmed, self.difficulty
            )
        ):
            self.investigation_phase = "evidence"
            # Return False — this is a rollback, not a forward phase shift.
            # The response should NOT say "time for behavioral tests."

        return False

    def _check_identification(self) -> Optional[str]:
        """Auto-identify when exactly one candidate remains."""
        if len(self.candidates) == 1:
            self.identified_ghost = self.candidates[0]
            return self.identified_ghost
        return None

    def _find_best_discriminator(self, remaining: list[str]) -> Optional[str]:
        """Find the evidence type that best splits candidates in half."""
        if not remaining or not self.candidates:
            return None

        half = len(self.candidates) / 2
        best: Optional[str] = None
        best_distance = float("inf")

        for e in remaining:
            count = sum(
                1
                for c in self.candidates
                if (ghost := get_ghost(c)) and e in ghost.get("evidence", [])
            )
            distance = abs(count - half)
            if distance < best_distance:
                best_distance = distance
                best = e

        return best

    def _invalid_evidence_result(
        self, evidence_id: str, status: str
    ) -> EvidenceResult:
        """Return an EvidenceResult for invalid input."""
        return EvidenceResult(
            evidence=evidence_id,
            evidence_label=EVIDENCE_LABELS.get(evidence_id, evidence_id),
            status=status,
            remaining_count=len(self.candidates),
            candidates=list(self.candidates),
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

    def _save_session(self, result: EndGameResult) -> None:
        """Append game result to sessions/history.json."""
        sessions_dir = Path(config.SESSIONS_DIR)
        sessions_dir.mkdir(parents=True, exist_ok=True)

        history_path = sessions_dir / "history.json"

        # Load existing history
        history: list[dict] = []
        if history_path.exists():
            try:
                with open(history_path) as f:
                    history = json.load(f)
            except (json.JSONDecodeError, ValueError):
                history = []

        # Append new session
        history.append({
            "date": datetime.now().isoformat(),
            "difficulty": result.difficulty,
            "ghost": result.actual_ghost,
            "guess": result.guess,
            "correct": result.correct,
            "evidence_count": result.evidence_count,
        })

        with open(history_path, "w") as f:
            json.dump(history, f, indent=2)
