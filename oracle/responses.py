"""Response builder — typed engine results in, human-readable strings out.

Pattern-matches on result type and dispatches to a specific builder function.
Multiple template variants per response type provide variety for TTS output.
All builders are pure functions: result in, string out.

Minimum response length enforcement ensures kokoro-onnx TTS gets enough
phonemes (>8) to produce clean audio.
"""
from __future__ import annotations

import random

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
)

# ── Minimum length enforcement ──────────────────────────────────────────────

_MIN_LENGTH = 40
_FILLER = " Say a command when you're ready."


def _ensure_minimum_length(response: str) -> str:
    """Pad short responses so TTS has enough phonemes to work with."""
    if len(response) < _MIN_LENGTH:
        response = response.rstrip() + _FILLER
    return response


# ── Helper formatting ───────────────────────────────────────────────────────

def _ghost_list(names: list[str]) -> str:
    """Format a list of ghost names as a comma-separated string."""
    if not names:
        return "none"
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def _evidence_list(evidence: list[str]) -> str:
    """Format a list of evidence IDs as a readable string."""
    if not evidence:
        return "none"
    return ", ".join(evidence)


# ── Evidence result builder ─────────────────────────────────────────────────

def _build_evidence_response(result: EvidenceResult) -> str:
    parts: list[str] = []

    # Status change notification
    if result.status_changed:
        parts.append(
            f"{result.evidence_label} was previously {result.old_status.replace('_', ' ')}. "
            f"Updated to {result.status.replace('_', ' ')}."
        )

    # Zero candidates
    if result.zero_candidates:
        parts.append(
            "No ghosts match this evidence combination. "
            "Something may be recorded incorrectly."
        )
        return " ".join(parts)

    # Mimic detection
    if result.mimic_detected:
        parts.append(
            "Four pieces of evidence with orbs — that's a Mimic. "
            "The orb is fake evidence. Locking it in."
        )
        return " ".join(parts)

    # Over-proofed (not Mimic)
    if result.over_proofed:
        parts.append(
            "More evidence confirmed than expected for this difficulty. "
            "You may have recorded something incorrectly."
        )
        return " ".join(parts)

    # Identification triggered — single candidate
    if result.identification_triggered and result.remaining_count == 1:
        parts.append(
            f"That's it — we've identified the ghost as a {result.candidates[0]}."
        )
        return " ".join(parts)

    # Threshold reached with multiple candidates + phase shifted
    if result.phase_shifted:
        templates = [
            (
                f"That's our evidence limit. "
                f"Remaining options: {_ghost_list(result.candidates)}. "
                f"Time for behavioral tests."
            ),
            (
                f"That's it for evidence. Our options are "
                f"{_ghost_list(result.candidates)}. Time for behavioral tests."
            ),
        ]
        parts.append(random.choice(templates))
        return " ".join(parts)

    # Normal confirm / rule-out
    if result.status == "confirmed":
        templates = [
            f"Copy that — {result.evidence} confirmed. {result.remaining_count} ghosts remain.",
            f"Got it. {result.evidence} is in. Down to {result.remaining_count}.",
        ]
    else:
        templates = [
            f"Noted — {result.evidence} ruled out. {result.remaining_count} remain.",
            f"Roger. Crossing off {result.evidence}. {result.remaining_count} remain.",
        ]

    response = random.choice(templates)

    # Append candidate list when few remain
    if result.remaining_count < 5:
        response += f" Current options: {_ghost_list(result.candidates)}."

    # Commentary for narrowing
    if result.commentary_needed and not result.identification_triggered:
        response += f" Narrowing it down — {result.remaining_count} options left."

    parts.append(response)
    return " ".join(parts)


# ── Behavioral result builder ───────────────────────────────────────────────

def _build_behavioral_response(result: BehavioralResult) -> str:
    if result.newly_eliminated:
        return (
            f"Observation logged. Eliminated: {_ghost_list(result.newly_eliminated)}. "
            f"{result.remaining_count} candidates remain."
        )
    return f"Observation logged. {result.remaining_count} candidates remain."


# ── State query builder ─────────────────────────────────────────────────────

def _build_state_response(result: StateResult) -> str:
    n = len(result.candidates)
    lines = [
        f"Difficulty: {result.difficulty}",
        f"Confirmed: {_evidence_list(result.evidence_confirmed)}",
        f"Ruled out: {_evidence_list(result.evidence_ruled_out)}",
        f"Candidates ({n}): {_ghost_list(result.candidates)}",
    ]
    return "\n".join(lines)


# ── Ghost query builder ────────────────────────────────────────────────────

def _build_ghost_query_response(result: GhostQueryResult) -> str:
    if not result.found:
        if result.all_ghost_names:
            return f"Ghost '{result.ghost_name}' not found. Known ghosts: {_ghost_list(result.all_ghost_names)}"
        return f"Ghost '{result.ghost_name}' not found."

    # Full card
    lines = [f"Ghost: {result.ghost_name}"]

    if result.evidence_list:
        lines.append(f"Evidence: {_evidence_list(result.evidence_list)}")
    if result.evidence_status:
        status_parts = [f"  {ev}: {st}" for ev, st in result.evidence_status.items()]
        lines.append("Evidence status:\n" + "\n".join(status_parts))
    if result.guaranteed_evidence:
        lines.append(f"Guaranteed evidence: {result.guaranteed_evidence}")
    if result.tells:
        lines.append(f"Tells: {_evidence_list(result.tells)}")
    if result.community_tests:
        lines.append("Community tests:")
        for test in result.community_tests:
            lines.append(f"  - {test}")

    return "\n".join(lines)


# ── Suggestion builder ──────────────────────────────────────────────────────

def _build_suggestion_response(result: SuggestionResult) -> str:
    if result.threshold_reached:
        response = "Evidence threshold reached — that's the max for this difficulty."
        if result.candidates:
            response += f" Remaining candidates: {_ghost_list(result.candidates)}."
        return response

    parts: list[str] = []
    if result.evidence_remaining:
        parts.append(
            f"Evidence not yet tested: {_evidence_list(result.evidence_remaining)}."
        )
    if result.best_evidence_label:
        parts.append(
            f"Try {result.best_evidence_label} next — it narrows the field most."
        )
    return " ".join(parts) if parts else "No suggestion available at this time."


# ── Guess builder ───────────────────────────────────────────────────────────

def _build_guess_response(result: GuessResult) -> str:
    if result.old_guess:
        response = (
            f"Got it — changing your guess from {result.old_guess} "
            f"to {result.ghost_name}."
        )
    else:
        response = (
            f"Tracking your guess as {result.ghost_name}. "
            "Say 'lock in' when you're sure."
        )

    if not result.is_candidate:
        response += (
            f" Note: {result.ghost_name} has been eliminated "
            "based on current evidence."
        )

    return response


# ── Lock-in builder ─────────────────────────────────────────────────────────

def _build_lockin_response(result: LockInResult) -> str:
    if result.is_candidate:
        return f"Locked in on {result.ghost_name}. Good luck."
    return (
        f"Locking in {result.ghost_name}, though it's been eliminated "
        "by current evidence. Bold move."
    )


# ── End game builder ───────────────────────────────────────────────────────

def _build_endgame_response(result: EndGameResult) -> str:
    if not result.guess:
        return f"Game over. It was a {result.actual_ghost}. No guess was locked in."
    if result.correct:
        return (
            f"Nice call — recording the win. "
            f"{result.actual_ghost} identified correctly."
        )
    return (
        f"Tough break. It was a {result.actual_ghost}, "
        f"not a {result.guess}. Recording for next time."
    )


# ── Test lookup builder ────────────────────────────────────────────────────

def _build_test_lookup_response(result: TestLookupResult) -> str:
    if not result.found:
        return f"I don't have a ghost called '{result.ghost_name}' in the database."
    if result.has_test:
        return (
            f"The {result.ghost_name} test: {result.test_description}. "
            "Let me know if it passes or fails."
        )
    return (
        f"No known test for {result.ghost_name} yet. "
        "We'll have to rely on evidence and behavior."
    )


# ── Test result builder ────────────────────────────────────────────────────

def _build_test_result_response(result: TestResult) -> str:
    if result.passed and result.eliminated_ghosts:
        return (
            f"Test passed. Eliminated: {_ghost_list(result.eliminated_ghosts)}. "
            f"{result.remaining_count} candidates remain."
        )
    if result.passed:
        return f"Test passed. {result.remaining_count} candidates remain."
    return f"Test failed. {result.remaining_count} candidates remain."


# ── New game builder ───────────────────────────────────────────────────────

def _build_new_game_response(result: NewGameResult) -> str:
    return (
        f"New investigation started on {result.difficulty}. "
        f"{result.candidate_count} ghost candidates active. Good hunting."
    )


# ── Unknown command builder ─────────────────────────────────────────────────

def _build_unknown_command_response(result: UnknownCommandResult) -> str:
    return "I didn't catch that. Try a command like 'confirm EMF 5' or 'what's left?'"


# ── Player registration builder ────────────────────────────────────────────

def _build_player_registration_response(result: PlayerRegistrationResult) -> str:
    return (
        f"Registered: {_ghost_list(result.names)}. "
        f"{result.total} players total."
    )


# ── Dispatch table ──────────────────────────────────────────────────────────

_BUILDERS = {
    NewGameResult: _build_new_game_response,
    EvidenceResult: _build_evidence_response,
    BehavioralResult: _build_behavioral_response,
    StateResult: _build_state_response,
    GhostQueryResult: _build_ghost_query_response,
    SuggestionResult: _build_suggestion_response,
    GuessResult: _build_guess_response,
    LockInResult: _build_lockin_response,
    EndGameResult: _build_endgame_response,
    TestLookupResult: _build_test_lookup_response,
    TestResult: _build_test_result_response,
    UnknownCommandResult: _build_unknown_command_response,
    PlayerRegistrationResult: _build_player_registration_response,
}


# ── Main entry point ───────────────────────────────────────────────────────

def build_response(result) -> str:
    """Build a response string from a typed engine result."""
    builder = _BUILDERS.get(type(result))
    if builder is None:
        return (
            f"I'm not sure how to respond to that. "
            f"(Unhandled: {type(result).__name__})"
        )
    response = builder(result)
    return _ensure_minimum_length(response)
