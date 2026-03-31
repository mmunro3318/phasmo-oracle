"""Oracle — entry point.

Usage:
    python main.py                              # voice mode
    python main.py --text                       # text mode (no microphone)
    python main.py --difficulty nightmare       # override difficulty
    python main.py --check                      # run startup diagnostics only
    python main.py --stats                      # display game statistics
    python main.py --replay sessions/ID.jsonl   # replay a past session
    python main.py --replay sessions/ID.jsonl --speed 1.0
    python main.py --replay sessions/ID.jsonl --re-run
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from pathlib import Path

from rich.console import Console

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
console = Console()


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_initial_state(difficulty: str, speaker: str = "Mike"):
    from graph.deduction import all_ghost_names
    from graph.state import OracleState

    return OracleState(
        user_text="",
        speaker=speaker,
        difficulty=difficulty,  # type: ignore[arg-type]
        evidence_confirmed=[],
        evidence_ruled_out=[],
        behavioral_observations=[],
        eliminated_ghosts=[],
        candidates=all_ghost_names(),
        session_id=str(uuid.uuid4()),
        session_start_time=time.time(),
        prev_candidate_count=27,
        oracle_response=None,
        messages=[],
    )


def run_turn(state: dict, user_text: str, tts=None) -> str:
    """Execute one turn of the Oracle graph and return oracle_response."""
    from graph.graph import oracle_graph
    from graph.tools import bind_state, sync_state_from

    state["prev_candidate_count"] = len(state.get("candidates", []))
    state["messages"] = []
    state["user_text"] = user_text

    bind_state(state)
    if tts:
        tts.flush()

    result = oracle_graph.invoke(state)
    sync_state_from(state)

    response = result.get("oracle_response") or ""
    return response


# ── CLI modes ─────────────────────────────────────────────────────────────────


def text_mode(difficulty: str) -> None:
    """Interactive text loop — no microphone required."""
    from graph.llm import current_backend, init_llm

    console.print("[bold cyan]Oracle[/bold cyan] — text mode (type 'quit' to exit)")

    try:
        init_llm()
        console.print(f"LLM backend: [green]{current_backend()}[/green]")
    except RuntimeError as exc:
        console.print(f"[red]LLM init failed:[/red] {exc}")
        sys.exit(1)

    state = make_initial_state(difficulty)
    console.print(f"Difficulty: [yellow]{difficulty}[/yellow] | {len(state['candidates'])} candidates")

    while True:
        try:
            user_text = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if user_text.lower() in {"quit", "exit", "q"}:
            break
        if not user_text:
            continue

        response = run_turn(state, user_text)
        if response:
            console.print(f"[magenta]Oracle:[/magenta] {response}")

        from ui.display import render_state

        render_state(state)


def voice_mode(difficulty: str) -> None:
    """Full voice pipeline mode."""
    from config.settings import config
    from graph.llm import current_backend, init_llm
    from voice.audio_router import AudioRouter
    from voice.speech_to_text import SpeechToText
    from voice.text_to_speech import TextToSpeech
    from voice.voice_session import VoiceSession

    try:
        init_llm()
        console.print(f"LLM backend: [green]{current_backend()}[/green]")
    except RuntimeError as exc:
        console.print(f"[red]LLM init failed:[/red] {exc}")
        sys.exit(1)

    router = AudioRouter(
        primary_device=config.SPEAKER_DEVICE_NAME,
        secondary_device=config.STEAM_ROUTE_DEVICE_NAME,
    )
    tts = TextToSpeech(router, voice=config.TTS_VOICE)
    stt = SpeechToText(model_size=config.STT_MODEL)

    state = make_initial_state(difficulty)

    def on_turn(speaker: str, text: str) -> None:
        state["speaker"] = speaker
        response = run_turn(state, text, tts=tts)
        if response:
            tts.speak(response)

    session = VoiceSession(
        stt=stt,
        tts=tts,
        on_turn=on_turn,
        wake_word=config.WAKE_WORD,
        mic_device=config.MIC_DEVICE_NAME,
        loopback_device=config.LOOPBACK_DEVICE_NAME if config.LOOPBACK_ENABLED else None,
    )
    session.start()
    console.print("[bold cyan]Oracle[/bold cyan] listening... (Ctrl-C to quit)")

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        session.stop()


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Oracle — Phasmophobia ghost-identification assistant")
    parser.add_argument("--text", action="store_true", help="Text mode (no microphone)")
    parser.add_argument("--difficulty", default=None, help="Override difficulty for this session")
    parser.add_argument("--check", action="store_true", help="Run startup diagnostics only")
    parser.add_argument("--stats", action="store_true", help="Display game statistics")
    parser.add_argument("--replay", metavar="SESSION", help="Replay a past session JSONL file")
    parser.add_argument("--speed", type=float, default=None, help="Replay speed multiplier")
    parser.add_argument("--re-run", action="store_true", help="Re-execute session through current graph")
    args = parser.parse_args()

    from config.settings import config
    from db.database import init_db

    init_db()
    difficulty = args.difficulty or config.DIFFICULTY

    if args.check:
        from ui.diagnostics import print_diagnostics

        ok = print_diagnostics()
        sys.exit(0 if ok else 1)

    if args.stats:
        from ui.stats import print_stats

        print_stats()
        return

    if args.replay:
        session_id = Path(args.replay).stem
        if args.re_run:
            from ui.replay import rerun_session

            rerun_session(session_id)
        else:
            from ui.replay import replay_session

            replay_session(session_id, speed=args.speed)
        return

    if args.text:
        text_mode(difficulty)
    else:
        voice_mode(difficulty)


if __name__ == "__main__":
    main()
