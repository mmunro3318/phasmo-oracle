#!/usr/bin/env python3
"""
Oracle Voice Tester
-------------------
Hear the Kokoro ONNX voices speak lines from Phasmophobia investigation reports.
Type a voice name at the prompt and the Oracle will deliver a random field dispatch.

Model files are downloaded automatically on first run (~90 MB, int8 quantised).
"""

import os
import random
import sys
import urllib.request
from pathlib import Path

import scipy.signal as sps
import sounddevice as sd
from dotenv import load_dotenv
from kokoro_onnx import Kokoro
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, DownloadColumn, Progress, TransferSpeedColumn
from rich.prompt import Prompt
from rich.table import Table

# ── Config ──────────────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env.local")

AUDIO_DEVICE = os.getenv("AUDIO_DEVICE") or None   # None = system default
DIR          = Path(__file__).parent
MODEL_PATH   = DIR / "kokoro-v1.0.int8.onnx"       # ~88 MB — smallest full-quality build
VOICES_PATH  = DIR / "voices-v1.0.bin"

_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
DOWNLOADS = {
    MODEL_PATH:  f"{_RELEASE}/kokoro-v1.0.int8.onnx",
    VOICES_PATH: f"{_RELEASE}/voices-v1.0.bin",
}

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


def download_models() -> None:
    """Download missing model files with a Rich progress bar."""
    missing = {p: url for p, url in DOWNLOADS.items() if not p.exists()}
    if not missing:
        return

    console.print("[yellow]Model files not found — downloading now…[/yellow]")
    for path, url in missing.items():
        console.print(f"  [dim]{path.name}[/dim]  ← {url}")

    console.print()
    with Progress(
        "[progress.description]{task.description}",
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        console=console,
    ) as progress:
        for path, url in missing.items():
            task = progress.add_task(path.name, total=None)

            def _hook(block_num, block_size, total_size, _task=task):
                if total_size > 0:
                    progress.update(_task, total=total_size,
                                    completed=min(block_num * block_size, total_size))

            try:
                urllib.request.urlretrieve(url, path, reporthook=_hook)
                progress.update(task, completed=progress._tasks[task].total)
            except Exception as exc:
                console.print(f"\n[red]Download failed:[/red] {exc}")
                path.unlink(missing_ok=True)
                sys.exit(1)

    console.print("[green]✓[/green] Downloads complete.\n")


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

    for gb, us in zip(BRITISH, AMERICAN):
        table.add_row(gb, us)
    for us in AMERICAN[len(BRITISH):]:
        table.add_row("", us)

    return table


def speak(voice: str, text: str, kokoro: Kokoro) -> None:
    lang = ALL_VOICES[voice]
    samples, sample_rate = kokoro.create(text, voice=voice, speed=1.0, lang=lang)

    # WASAPI (and some other drivers) require audio at the device's native sample
    # rate. Kokoro outputs 24 kHz; query the target device and resample if needed.
    device_info = (
        sd.query_devices(AUDIO_DEVICE, "output")
        if AUDIO_DEVICE
        else sd.query_devices(kind="output")
    )
    target_rate = int(device_info["default_samplerate"])
    if target_rate != sample_rate:
        samples = sps.resample_poly(samples, target_rate, sample_rate)

    device_kwargs = {"device": AUDIO_DEVICE} if AUDIO_DEVICE else {}
    sd.play(samples, samplerate=target_rate, **device_kwargs)
    sd.wait()


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    console.print(Panel(
        "[bold white]Oracle Voice Tester[/bold white]\n"
        "[dim]Powered by Kokoro ONNX · Phasmophobia Edition[/dim]",
        border_style="cyan",
        expand=False,
    ))
    console.print()

    download_models()

    console.print("Loading voice model…", style="dim")
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
