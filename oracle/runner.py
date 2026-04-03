"""Oracle runner — main loop with I/O protocols.

Supports text mode (--text) and voice output (--speak).
The I/O protocols allow swapping input/output without touching the loop.
"""
from __future__ import annotations

import argparse
import logging
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
    VoiceChangeResult,
    AvailableTestsResult,
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

    def _show_voice_table(self, current_voice: str) -> None:
        """Display available Kokoro voices in a table."""
        from rich.table import Table
        from oracle.voice.audio_config import BRITISH_VOICES, AMERICAN_VOICES

        table = Table(
            title="[bold cyan]The Team[/bold cyan]",
            show_header=True,
            header_style="bold magenta",
            min_width=44,
        )
        table.add_column("British", style="cyan", no_wrap=True)
        table.add_column("American", style="green", no_wrap=True)

        max_rows = max(len(BRITISH_VOICES), len(AMERICAN_VOICES))
        for i in range(max_rows):
            gb = BRITISH_VOICES[i] if i < len(BRITISH_VOICES) else ""
            us = AMERICAN_VOICES[i] if i < len(AMERICAN_VOICES) else ""
            # Mark current voice
            if gb == current_voice:
                gb = f"[bold yellow]> {gb}[/bold yellow]"
            if us == current_voice:
                us = f"[bold yellow]> {us}[/bold yellow]"
            table.add_row(gb, us)

        self._console.print(table)
        self._console.print(
            "[dim]Change voice: [cyan]'change voice to bm_george'[/cyan][/dim]\n"
        )


logger = logging.getLogger(__name__)


# ── Voice Output ──────────────────────────────────────────────────────────


class VoiceOutput:
    """OutputHandler that adds TTS + radio FX to text responses.

    Wraps RichOutput via composition. Only show_response() adds audio —
    show_state() and show_welcome() delegate directly to text display.
    """

    def __init__(self, engine: InvestigationEngine, output_device: str | None = None):
        self._text = RichOutput()
        self._engine = engine
        self._sd = None  # Lazy import of sounddevice
        self._device_sr = None
        self._audio_device = None

        # Import voice dependencies (may raise ImportError)
        from oracle.voice.tts import KokoroTTS
        from oracle.voice.radio_fx import RadioFX, get_device_sample_rate, resample_for_device
        from oracle.voice.audio_config import get_config

        self._config = get_config()
        self._audio_device = self._config.audio_device
        # Override with explicit output device (e.g. VB-Cable) if provided
        if output_device is not None:
            self._audio_device = output_device
        self._tts = KokoroTTS()
        self._radio = RadioFX()
        self._resample = resample_for_device

        # Query device sample rate once at startup
        self._device_sr = get_device_sample_rate(self._audio_device)
        if self._device_sr != self._config.sample_rate:
            logger.info(
                f"Device sample rate ({self._device_sr}Hz) differs from pipeline "
                f"({self._config.sample_rate}Hz) — audio will be resampled."
            )

        try:
            import sounddevice as sd
            self._sd = sd
        except ImportError:
            logger.warning("sounddevice not available — voice output disabled")

    def show_response(self, text: str) -> None:
        """Speak the response through radio FX, then display as text."""
        if self._sd is not None:
            try:
                candidate_count = len(self._engine.candidates)
                audio, sr = self._tts.synthesize(text)
                processed = self._radio.apply(audio, sr, candidate_count)

                # Resample to device rate if needed (prevents paInvalidSampleRate)
                if self._device_sr and self._device_sr != sr:
                    processed = self._resample(processed, sr, self._device_sr)
                    sr = self._device_sr

                # Stop any currently playing audio to prevent overlap
                self._sd.stop()
                # Non-blocking: allows wake word barge-in to interrupt playback.
                device_kwargs = {"device": self._audio_device} if self._audio_device else {}
                self._sd.play(processed, sr, **device_kwargs)
            except Exception as e:
                logger.warning(f"Audio playback failed, falling back to text: {e}")

        self._text.show_response(text)

    def show_state(self, engine: InvestigationEngine) -> None:
        self._text.show_state(engine)

    def show_welcome(self) -> None:
        self._text.show_welcome()
        self._text._show_voice_table(self._tts.voice)


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
        return engine.query_ghost(intent.ghost_name or "")

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
        if intent.ghost_name:
            return engine.ghost_test_lookup(intent.ghost_name)
        # No specific ghost — list available tests among remaining candidates
        return engine.available_tests()

    if action == "ghost_test_result":
        passed = intent.status == "passed"
        return engine.ghost_test_result(intent.ghost_name or "", passed)

    if action == "query_behavior":
        # For now, treat as a ghost query if a ghost name is found
        if intent.ghost_name:
            return engine.query_ghost(intent.ghost_name)
        return UnknownCommandResult(raw_text=intent.raw_text)

    if action == "change_voice":
        from oracle.voice.audio_config import ALL_VOICES
        voice = intent.voice_name or ""
        return VoiceChangeResult(
            voice_name=voice,
            success=voice in ALL_VOICES,
            available_voices=sorted(ALL_VOICES.keys()),
        )

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

        # Handle voice change — apply to VoiceOutput's TTS if available
        if isinstance(result, VoiceChangeResult) and result.success:
            if isinstance(output, VoiceOutput):
                output._tts.set_voice(result.voice_name)

        response = build_response(result)

        # Set speaking flag for barge-in awareness
        if hasattr(input_provider, 'is_speaking'):
            input_provider.is_speaking = True

        output.show_response(response)

        if hasattr(input_provider, 'is_speaking'):
            input_provider.is_speaking = False

        # Show state panel after evidence changes
        if isinstance(result, (EvidenceResult, BehavioralResult, NewGameResult)):
            output.show_state(engine)


# ── CLI Entry Point ─────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Oracle — Phasmophobia Ghost ID Assistant")
    parser.add_argument(
        "--text", action="store_true", default=True,
        help="Run in text mode (default)",
    )
    parser.add_argument(
        "--speak", action="store_true", default=False,
        help="Enable voice output with CB radio FX (requires --text, voice deps)",
    )
    parser.add_argument(
        "--voice", action="store_true", default=False,
        help="Enable voice input (wake word + STT) and voice output (implies --speak)",
    )
    parser.add_argument(
        "--difficulty",
        choices=["amateur", "intermediate", "professional", "nightmare", "insanity"],
        default=None,
        help="Start with a specific difficulty (auto-starts a new game)",
    )
    args = parser.parse_args()

    # --voice implies --speak
    if args.voice:
        args.speak = True

    # --speak without --text is invalid (unless --voice provides STT input)
    if args.speak and not args.text and not args.voice:
        print(
            "Error: --speak requires --text or --voice.\n"
            "Usage: oracle --text --speak  OR  oracle --voice",
            file=sys.stderr,
        )
        sys.exit(1)

    engine = InvestigationEngine()

    if args.difficulty:
        result = engine.new_game(args.difficulty)
        print(f"Auto-started: {result.difficulty} difficulty, {result.candidate_count} ghosts.")

    # ── Input provider ───────────────────────────────────────────────
    voice_input = None
    if args.voice:
        try:
            from oracle.voice.stt import VoiceInput
            from oracle.voice.audio_config import get_config

            config = get_config()

            # Parse device index (must be integer for PyAudio)
            device_index = None
            if config.stt_input_device:
                try:
                    device_index = int(config.stt_input_device)
                except ValueError:
                    print(
                        f"Error: STT_INPUT_DEVICE must be an integer device index, "
                        f"got '{config.stt_input_device}'.\n"
                        "Run: python -c \"import pyaudio; p=pyaudio.PyAudio(); "
                        "[print(i, p.get_device_info_by_index(i)['name']) "
                        "for i in range(p.get_device_count())]\"",
                        file=sys.stderr,
                    )
                    sys.exit(1)

            voice_input = VoiceInput(
                whisper_model=config.whisper_model,
                wake_word=config.wake_word,
                input_device_index=device_index,
                vad_aggressiveness=config.vad_aggressiveness,
            )
            input_provider: InputProvider = voice_input
            print("Voice input enabled — say the wake word to activate.")
        except ImportError as e:
            print(
                f"Voice input dependencies not installed: {e}\n"
                "Install with: pip install -e '.[voice-full]'",
                file=sys.stderr,
            )
            sys.exit(1)
        except Exception as e:
            print(f"Voice input initialization failed: {e}", file=sys.stderr)
            print("Falling back to keyboard input.")
            input_provider = TextInput()
    else:
        input_provider = TextInput()

    # ── Output handler ───────────────────────────────────────────────
    if args.speak:
        try:
            from oracle.voice.audio_config import find_vb_cable_device

            output_device = None
            if args.voice:
                output_device = find_vb_cable_device()
                if output_device:
                    print(f"VB-Cable found: routing TTS to '{output_device}' for Steam.")
                else:
                    print("VB-Cable not found — using default speakers.")

            output: OutputHandler = VoiceOutput(engine, output_device=output_device)
            if not output_device:
                print("Voice output enabled — Oracle will speak through your speakers.")
        except ImportError as e:
            print(
                f"Voice dependencies not installed: {e}\n"
                "Install with: pip install -e '.[voice]'",
                file=sys.stderr,
            )
            sys.exit(1)
        except Exception as e:
            print(f"Voice output initialization failed: {e}", file=sys.stderr)
            print("Falling back to text-only mode.")
            output = RichOutput()
    else:
        output = RichOutput()

    # ── Pre-warm announcement ────────────────────────────────────────
    if args.voice and voice_input and not voice_input.failed:
        output.show_response("Oracle online.")

    run_loop(engine, input_provider, output)

    # Clean up voice input
    if voice_input is not None:
        voice_input.shutdown()


if __name__ == "__main__":
    main()
