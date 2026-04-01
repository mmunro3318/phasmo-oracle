"""Oracle runner — main loop with I/O protocols.

Supports text mode (--text) now and voice mode (Sprint 3b) later.
The I/O protocols allow swapping input/output without touching the loop.
"""
from __future__ import annotations

import argparse
import sys
from typing import Protocol

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from oracle.engine import (
    InvestigationEngine,
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
    NewGameResult,
    UnknownCommandResult,
    PlayerRegistrationResult,
)
from oracle.parser import parse_intent, ParsedIntent
from oracle.responses import build_response


# ── I/O Protocols ───────────────────────────────────────────────────────────


class InputProvider(Protocol):
    """Protocol for getting player commands."""

    def get_command(self) -> str | None: ...


class OutputHandler(Protocol):
    """Protocol for displaying Oracle's responses."""

    def show_response(self, text: str) -> None: ...
    def show_state(self, engine: InvestigationEngine) -> None: ...
    def show_welcome(self) -> None: ...


# ── Text Mode Implementations ───────────────────────────────────────────────


class TextInput:
    """Read commands from stdin."""

    def __init__(self, prompt: str = "You > "):
        self._prompt = prompt

    def get_command(self) -> str | None:
        try:
            return input(self._prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return None


class RichOutput:
    """Display responses using Rich panels."""

    def __init__(self):
        self._console = Console()

    def show_response(self, text: str) -> None:
        panel = Panel(
            Text(text, style="bold cyan"),
            title="[bold green]Oracle[/bold green]",
            border_style="green",
            padding=(0, 1),
        )
        self._console.print(panel)

    def show_state(self, engine: InvestigationEngine) -> None:
        state = engine.state
        candidates = state.get("candidates", [])
        n = len(candidates)
        confirmed = state.get("evidence_confirmed", [])
        ruled_out = state.get("evidence_ruled_out", [])
        difficulty = state.get("difficulty", "?")

        lines = [
            f"Difficulty: {difficulty}",
            f"Confirmed ({len(confirmed)}): {', '.join(confirmed) or 'none'}",
            f"Ruled out ({len(ruled_out)}): {', '.join(ruled_out) or 'none'}",
            f"Candidates ({n}): {', '.join(candidates) if n <= 10 else f'{n} ghosts'}",
        ]

        guess = state.get("guess")
        if guess:
            locked = " (LOCKED IN)" if state.get("locked_in") else ""
            lines.append(f"Current guess: {guess}{locked}")

        panel = Panel(
            "\n".join(lines),
            title="[bold yellow]Investigation[/bold yellow]",
            border_style="yellow",
            padding=(0, 1),
        )
        self._console.print(panel)

    def show_welcome(self) -> None:
        self._console.print(
            Panel(
                "[bold]Oracle[/bold] — Phasmophobia Ghost Identification Assistant\n"
                "Say [cyan]'new game professional'[/cyan] to start.\n"
                "Type [cyan]'quit'[/cyan] or press Ctrl+C to exit.",
                border_style="blue",
                padding=(0, 1),
            )
        )


# ── Dispatch ────────────────────────────────────────────────────────────────


def _dispatch(engine: InvestigationEngine, intent: ParsedIntent):
    """Map a parsed intent to an engine method call. Returns a result dataclass."""
    action = intent.action

    if action == "init_investigation":
        return engine.new_game(intent.difficulty or "professional")

    if action == "record_evidence":
        result = engine.record_evidence(intent.evidence_id, intent.status or "confirmed")
        # Handle extra evidence mentions in the same utterance
        for extra_ev in intent.extra_evidence:
            engine.record_evidence(extra_ev, intent.status or "confirmed")
        return result

    if action == "record_behavioral_event":
        return engine.record_behavioral(
            intent.observation or intent.raw_text,
            intent.eliminator_key or "",
        )

    if action == "get_investigation_state":
        return engine.get_state()

    if action == "query_ghost_database":
        return engine.query_ghost(
            intent.ghost_name or "",
            full=(intent.query_field == "full"),
        )

    if action == "suggest_next_evidence":
        return engine.suggest_next()

    if action == "record_theory":
        return engine.record_guess(
            intent.ghost_name or "",
            player_name=intent.player_name or "me",
        )

    if action == "record_guess":
        return engine.record_guess(intent.ghost_name or "")

    if action == "lock_in":
        return engine.lock_in(intent.ghost_name or "")

    if action == "confirm_true_ghost":
        return engine.end_game(intent.ghost_name or "")

    if action == "register_players":
        return engine.register_players(intent.player_names)

    if action == "query_tests":
        return engine.ghost_test_lookup(intent.ghost_name or "")

    if action == "ghost_test_result":
        passed = intent.status == "passed"
        return engine.ghost_test_result(intent.ghost_name or "", passed)

    if action == "query_behavior":
        # For now, treat as a ghost query if a ghost name is found
        if intent.ghost_name:
            return engine.query_ghost(intent.ghost_name)
        return UnknownCommandResult(raw_text=intent.raw_text)

    # Unknown / null / unrecognized
    return UnknownCommandResult(raw_text=intent.raw_text)


# ── Main Loop ───────────────────────────────────────────────────────────────


def run_loop(
    engine: InvestigationEngine,
    input_provider: InputProvider,
    output: OutputHandler,
) -> None:
    """Main investigation loop — works identically for text and voice."""
    output.show_welcome()

    while True:
        text = input_provider.get_command()
        if text is None:
            break
        if not text:
            continue
        if text.lower() in ("quit", "exit", "bye", "q"):
            break

        intent = parse_intent(text)
        result = _dispatch(engine, intent)
        response = build_response(result)
        output.show_response(response)

        # Show state panel after evidence changes
        if isinstance(result, (EvidenceResult, BehavioralResult, NewGameResult)):
            output.show_state(engine)


# ── CLI Entry Point ─────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Oracle — Phasmophobia Ghost ID Assistant")
    parser.add_argument(
        "--text", action="store_true", default=True,
        help="Run in text mode (default, voice mode coming in Sprint 3b)",
    )
    parser.add_argument(
        "--difficulty",
        choices=["amateur", "intermediate", "professional", "nightmare", "insanity"],
        default=None,
        help="Start with a specific difficulty (auto-starts a new game)",
    )
    args = parser.parse_args()

    engine = InvestigationEngine()

    if args.difficulty:
        result = engine.new_game(args.difficulty)
        print(f"Auto-started: {result.difficulty} difficulty, {result.candidate_count} ghosts.")

    input_provider = TextInput()
    output = RichOutput()
    run_loop(engine, input_provider, output)


if __name__ == "__main__":
    main()
