#!/usr/bin/env python3
"""
Oracle Voice Tester
-------------------
Hear the Kokoro ONNX voices speak lines from Phasmophobia investigation reports.
Type a voice name at the prompt and the Oracle will deliver a random field dispatch.
"""

import os
import random
import sys
from pathlib import Path

import sounddevice as sd
from dotenv import load_dotenv
from kokoro_onnx import Kokoro
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

# ── Config ──────────────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env.local")

AUDIO_DEVICE = os.getenv("AUDIO_DEVICE") or None   # None = system default
MODEL_PATH   = Path(__file__).parent / "kokoro-v0_19.onnx"
VOICES_PATH  = Path(__file__).parent / "voices.bin"

# ── Voice catalogue ──────────────────────────────────────────────────────────

BRITISH = [
    "bf_alice",
    "bf_emma",
    "bf_isabella",
    "bf_lily",
    "bm_daniel",
    "bm_fable",
    "bm_george",
    "bm_lewis",
]

AMERICAN = [
    "af_heart",
    "af_bella",
    "af_sarah",
    "af_sky",
    "af_nova",
    "am_adam",
    "am_eric",
    "am_michael",
    "am_liam",
]

ALL_VOICES = {v: "en-gb" for v in BRITISH} | {v: "en-us" for v in AMERICAN}

# ── Sentence bank ────────────────────────────────────────────────────────────

SENTENCES = [
    "The EMF reader is spiking to level five. Confirmation achieved.",
    "Fingerprints on the light switch — something touched that, and it was not alive.",
    "Ghost orbs detected on camera. I would recommend a tactical retreat.",
    "The spirit box is responding. Ask it something, if you dare.",
    "Freezing temperatures recorded below zero. The thermometer does not lie, unlike your courage.",
    "The ghost has written in the journal. The handwriting is appalling, frankly.",
    "D.O.T.S. projector activated. The silhouette suggests a Phantom.",
    "You have triggered a hunt. Wonderful. Do try not to die in a corner.",
    "Ultraviolet powder reveals footprints leading directly to your location.",
    "The parabolic microphone has detected movement in the basement. Your move, investigator.",
]

# ── Helpers ──────────────────────────────────────────────────────────────────

console = Console()


def build_voice_table() -> Table:
    """Render a two-column table of available voices."""
    table = Table(
        title="[bold cyan]Available Voices[/bold cyan]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
        min_width=44,
    )
    table.add_column("🇬🇧  British", style="cyan", no_wrap=True)
    table.add_column("🇺🇸  American", style="green", no_wrap=True)

    for gb, us in zip(BRITISH, AMERICAN + [""]):
        table.add_row(gb, us)

    # Any overflow American voices (list lengths differ by one)
    for us in AMERICAN[len(BRITISH):]:
        table.add_row("", us)

    return table


def speak(voice: str, text: str, kokoro: Kokoro) -> None:
    lang = ALL_VOICES[voice]
    samples, sample_rate = kokoro.create(text, voice=voice, speed=1.0, lang=lang)

    device_kwargs = {}
    if AUDIO_DEVICE:
        device_kwargs["device"] = AUDIO_DEVICE

    sd.play(samples, samplerate=sample_rate, **device_kwargs)
    sd.wait()


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    # Validate model files exist before loading
    for path, label in [(MODEL_PATH, "kokoro-v0_19.onnx"), (VOICES_PATH, "voices.bin")]:
        if not path.exists():
            console.print(
                f"[bold red]Missing:[/bold red] {label}\n"
                f"[dim]Expected at: {path}[/dim]\n\n"
                "Download both files from [link=https://huggingface.co/hexgrad/Kokoro-82M]"
                "huggingface.co/hexgrad/Kokoro-82M[/link] and place them in voice_test/."
            )
            sys.exit(1)

    console.print(Panel(
        "[bold white]Oracle Voice Tester[/bold white]\n"
        "[dim]Powered by Kokoro ONNX · Phasmophobia Edition[/dim]",
        border_style="cyan",
        expand=False,
    ))

    console.print("\nLoading voice model…", style="dim")
    kokoro = Kokoro(str(MODEL_PATH), str(VOICES_PATH))
    console.print("[green]✓[/green] Model ready.\n")

    console.print(build_voice_table())
    console.print()
    console.print("[dim]Type a voice name to hear it · [bold]q[/bold] to quit[/dim]\n")

    while True:
        try:
            choice = Prompt.ask("[bold cyan]Voice[/bold cyan]").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Signing off.[/dim]")
            break

        if choice in ("q", "quit", "exit"):
            console.print("[dim]Signing off.[/dim]")
            break

        if choice not in ALL_VOICES:
            console.print(
                f"[yellow]Unknown voice:[/yellow] [bold]{choice}[/bold] — "
                "check the table above and try again.\n"
            )
            continue

        sentence = random.choice(SENTENCES)
        console.print(f"[dim italic]{sentence}[/dim italic]")

        try:
            speak(choice, sentence, kokoro)
        except Exception as exc:
            console.print(f"[red]Playback error:[/red] {exc}\n")
            continue

        console.print()


if __name__ == "__main__":
    main()
