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
    EVIDENCE_LABELS,
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
        count = len([e for e in result.candidates]) + 1  # approximate
        parts.append(
            "More evidence than expected, and orbs are confirmed — that's a Mimic. "
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
        msg = (
            f"That's our evidence limit. "
            f"Remaining options: {_ghost_list(result.candidates)}. "
        )
        if result.guaranteed_eliminated:
            msg += (
                f"Eliminated {len(result.guaranteed_eliminated)} based on missing "
                f"guaranteed evidence: {_ghost_list(result.guaranteed_eliminated)}. "
            )
        msg += "Time for behavioral tests."
        parts.append(msg)
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
            return f"I don't have a file on '{result.ghost_name}'. Check the name and try again."
        return f"I don't have a file on '{result.ghost_name}'."

    parts: list[str] = []

    # Opening — name + evidence
    evidence_str = _evidence_list(result.evidence_list) if result.evidence_list else "unknown"
    parts.append(f"The {result.ghost_name}. Evidence: {evidence_str}.")

    # Guaranteed evidence
    if result.guaranteed_evidence:
        ge_label = EVIDENCE_LABELS.get(result.guaranteed_evidence, result.guaranteed_evidence)
        parts.append(f"{ge_label} is guaranteed — it always shows up.")

    # Evidence status in current investigation
    if result.evidence_status:
        confirmed = [ev for ev, st in result.evidence_status.items() if st == "confirmed"]
        untested = [ev for ev, st in result.evidence_status.items() if st == "untested"]
        if confirmed:
            parts.append(f"We've already confirmed {_evidence_list(confirmed)}.")
        if untested:
            parts.append(f"Still need to check {_evidence_list(untested)}.")

    # Behavioral tells — conversational summary (not a raw dump)
    if result.tells:
        # Take the first 2-3 tells for voice brevity, skip deeply technical ones
        clean_tells = []
        for tell in result.tells[:3]:
            # Strip dict-like formatting if a tell somehow contains it
            t = str(tell).strip()
            if t.startswith("{") or t.startswith("["):
                continue
            clean_tells.append(t)
        if len(clean_tells) == 1:
            parts.append(f"Key behavior: {clean_tells[0]}.")
        elif clean_tells:
            joined = ". ".join(clean_tells)
            parts.append(f"Key behaviors: {joined}.")

    # Community tests — narrative (unwrap dict fields into prose)
    if result.community_tests:
        for test in result.community_tests:
            if isinstance(test, dict):
                name = test.get("name", "")
                procedure = test.get("procedure", test.get("description", ""))
                confidence = test.get("confidence", "")
                line = f"Community test"
                if name:
                    line += f" — {name}"
                if procedure:
                    line += f": {procedure}"
                if confidence:
                    line += f" Confidence: {confidence}."
                parts.append(line)
            else:
                parts.append(f"Community test: {test}")

    # Fake evidence (Mimic)
    if result.fake_evidence:
        fe_label = EVIDENCE_LABELS.get(result.fake_evidence, result.fake_evidence)
        parts.append(f"Watch out — it fakes {fe_label} as extra evidence.")

    return " ".join(parts)


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
    if result.identified_ghost:
        return (
            f"Test confirmed — the ghost is a {result.identified_ghost}. "
            "Lock it in on the whiteboard."
        )
    if result.passed and result.eliminated_ghosts:
        return (
            f"Test passed. Eliminated: {_ghost_list(result.eliminated_ghosts)}. "
            f"{result.remaining_count} candidates remain."
        )
    if not result.passed and result.eliminated_ghosts:
        return (
            f"Test failed. Eliminated: {_ghost_list(result.eliminated_ghosts)}. "
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
        f"Registered: {_ghost_list(result.added)}. "
        f"{result.total} players total."
    )


# ── Available tests builder ────────────────────────────────────────────────

def _build_available_tests_response(result: AvailableTestsResult) -> str:
    if not result.testable:
        return "None of the remaining candidates have known tests. Focus on evidence and behavioral observations."

    parts = [f"{len(result.testable)} of {result.total_candidates} remaining ghosts have tests."]
    for name, desc in result.testable:
        parts.append(f"{name}: {desc}")

    if result.untestable:
        parts.append(f"No tests for: {_ghost_list(result.untestable)}.")

    return " ".join(parts)


# ── Voice change builder ───────────────────────────────────────────────────

def _build_voice_change_response(result: VoiceChangeResult) -> str:
    if result.success:
        # Extract the display name (e.g. "bm_fable" → "Fable")
        name = result.voice_name.split("_", 1)[-1].capitalize()
        return f"This is {name}, taking over. Ready when you are."
    return (
        f"Unknown voice: {result.voice_name}. "
        f"Available voices: {', '.join(result.available_voices)}."
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
    VoiceChangeResult: _build_voice_change_response,
    AvailableTestsResult: _build_available_tests_response,
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
