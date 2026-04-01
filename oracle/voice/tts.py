"""TTS provider interface and Kokoro-onnx implementation.

TTSProvider is a swappable protocol — Kokoro is the default backend but can
be replaced with any TTS engine that produces (float32 array, sample rate).

Model files are downloaded automatically on first run (~90MB int8 quantised).
"""

import logging
import sys
import urllib.request
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from oracle.voice.audio_config import AudioConfig, get_config

logger = logging.getLogger(__name__)


@runtime_checkable
class TTSProvider(Protocol):
    """Protocol for text-to-speech providers.

    Any TTS backend must implement this interface. The returned audio
    must be a float32 numpy array with values in [-1.0, 1.0].
    """

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Convert text to speech audio.

        Args:
            text: The text to synthesize.

        Returns:
            Tuple of (audio_array, sample_rate).
            audio_array: float32 numpy array in [-1.0, 1.0].
            sample_rate: integer sample rate (e.g. 24000).
        """
        ...


# ── Model file management ─────────────────────────────────────────────────

_MODEL_FILENAME = "kokoro-v1.0.int8.onnx"  # ~88MB — smallest full-quality build
_VOICES_FILENAME = "voices-v1.0.bin"
_RELEASE_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0"
)
_DOWNLOADS = {
    _MODEL_FILENAME: f"{_RELEASE_URL}/{_MODEL_FILENAME}",
    _VOICES_FILENAME: f"{_RELEASE_URL}/{_VOICES_FILENAME}",
}

# Models are stored next to this file (oracle/voice/)
_MODEL_DIR = Path(__file__).parent


def download_models() -> None:
    """Download missing Kokoro model files with a Rich progress bar.

    Files are saved to oracle/voice/ (next to this module). Automatically
    called on first KokoroTTS init if files are missing.
    """
    from rich.console import Console
    from rich.progress import (
        BarColumn,
        DownloadColumn,
        Progress,
        TransferSpeedColumn,
    )

    console = Console()
    missing = {
        name: url
        for name, url in _DOWNLOADS.items()
        if not (_MODEL_DIR / name).exists()
    }

    if not missing:
        return

    console.print("[yellow]Kokoro model files not found — downloading now...[/yellow]")
    for name, url in missing.items():
        console.print(f"  [dim]{name}[/dim]  <- {url}")
    console.print()

    with Progress(
        "[progress.description]{task.description}",
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        console=console,
    ) as progress:
        for name, url in missing.items():
            dest = _MODEL_DIR / name
            task = progress.add_task(name, total=None)

            def _hook(block_num, block_size, total_size, _task=task):
                if total_size > 0:
                    progress.update(
                        _task,
                        total=total_size,
                        completed=min(block_num * block_size, total_size),
                    )

            try:
                urllib.request.urlretrieve(url, dest, reporthook=_hook)
                progress.update(task, completed=progress._tasks[task].total)
            except Exception as exc:
                console.print(f"\n[red]Download failed:[/red] {exc}")
                dest.unlink(missing_ok=True)
                raise RuntimeError(
                    f"Failed to download {name}: {exc}"
                ) from exc

    console.print("[green]Downloads complete.[/green]\n")


class KokoroTTS:
    """Kokoro-onnx TTS wrapper.

    Loads the Kokoro model on init (1-5s cold start). Model files are
    downloaded automatically on first run (~90MB total).

    All subsequent synthesize() calls use the pre-loaded model.
    """

    def __init__(self, voice: str | None = None, speed: float = 1.0):
        """Initialize Kokoro TTS.

        Args:
            voice: Kokoro voice name. If None, uses KOKORO_VOICE from
                .env.local (default: bm_fable).
            speed: Speech speed multiplier. Default 1.0.

        Raises:
            ImportError: If kokoro-onnx is not installed.
            RuntimeError: If model download or loading fails.
        """
        self._config = get_config()
        self._voice = voice or self._config.voice
        self._speed = speed

        try:
            from kokoro_onnx import Kokoro
        except ImportError:
            raise ImportError(
                "kokoro-onnx is required for voice output. "
                "Install with: pip install -e '.[voice]'"
            )

        # Auto-download model files if missing
        download_models()

        model_path = str(_MODEL_DIR / _MODEL_FILENAME)
        voices_path = str(_MODEL_DIR / _VOICES_FILENAME)

        try:
            self._model = Kokoro(model_path, voices_path)
            logger.info("Kokoro TTS model loaded from %s", model_path)
        except Exception as e:
            raise RuntimeError(f"Failed to load Kokoro TTS model: {e}") from e

    @property
    def voice(self) -> str:
        """Current voice name."""
        return self._voice

    def set_voice(self, voice: str) -> bool:
        """Change the active voice at runtime.

        Args:
            voice: Voice name (e.g. 'bm_fable', 'af_sarah').

        Returns:
            True if voice was changed, False if unknown voice name.
        """
        from oracle.voice.audio_config import ALL_VOICES

        if voice not in ALL_VOICES:
            return False
        self._voice = voice
        return True

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Synthesize text to speech audio.

        Returns padded audio if the output is shorter than the minimum
        duration threshold (200ms by default).
        """
        from oracle.voice.audio_config import ALL_VOICES

        lang = ALL_VOICES.get(self._voice, "en-us")
        audio, sr = self._model.create(
            text, voice=self._voice, speed=self._speed, lang=lang
        )
        audio = np.asarray(audio, dtype=np.float32)

        # Pad short audio to avoid Kokoro quality issues with <8 phonemes
        audio = self._pad_short_audio(audio, sr)

        return audio, sr

    def _pad_short_audio(
        self, audio: np.ndarray, sr: int
    ) -> np.ndarray:
        """Extend short audio by repeating the tail with a fade-out.

        If synthesized audio is shorter than min_audio_duration_ms, take
        the last 20ms, apply a linear fade-out, and append until the
        minimum duration is reached.
        """
        min_samples = int(sr * self._config.min_audio_duration_ms / 1000.0)

        if len(audio) >= min_samples or len(audio) == 0:
            return audio

        # Take the last 20ms of audio as the extension seed
        tail_len = min(int(sr * 0.02), len(audio))
        tail = audio[-tail_len:].copy()

        # Apply fade-out envelope to the tail
        fade = np.linspace(1.0, 0.0, tail_len, dtype=np.float32)
        tail *= fade

        # Repeat the faded tail until we reach minimum duration
        parts = [audio]
        current_len = len(audio)
        while current_len < min_samples:
            remaining = min_samples - current_len
            chunk = tail[:remaining]
            parts.append(chunk)
            current_len += len(chunk)

        return np.concatenate(parts).astype(np.float32)
