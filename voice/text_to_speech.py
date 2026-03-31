"""Kokoro-ONNX text-to-speech wrapper with AudioRouter output."""
from __future__ import annotations

import logging
import threading

import numpy as np

from voice.audio_router import AudioRouter

logger = logging.getLogger(__name__)


class TextToSpeech:
    """Synthesises speech via kokoro-onnx and plays it through AudioRouter."""

    def __init__(
        self,
        router: AudioRouter,
        voice: str = "bm_fable",
        speed: float = 1.0,
        model_path: str = "kokoro-v0_19.onnx",
        voices_path: str = "voices-v1_0.bin",
    ) -> None:
        self._router = router
        self._voice = voice
        self._speed = speed
        self._model_path = model_path
        self._voices_path = voices_path
        self._kokoro = None
        self._lock = threading.Lock()
        self.is_speaking: bool = False

    def _load(self) -> None:
        if self._kokoro is None:
            from kokoro_onnx import Kokoro  # type: ignore[import]

            self._kokoro = Kokoro(self._model_path, self._voices_path)
            logger.info("Kokoro TTS loaded (voice=%s)", self._voice)

    def speak(self, text: str) -> None:
        """Synthesise *text* and play it via the AudioRouter.

        Sets ``is_speaking`` for the duration of synthesis + playback.
        """
        if not text.strip():
            return
        self._load()
        with self._lock:
            self.is_speaking = True
            try:
                samples, sr = self._kokoro.create(  # type: ignore[union-attr]
                    text, voice=self._voice, speed=self._speed
                )
                audio = np.array(samples, dtype=np.float32)
                self._router.play(audio, sample_rate=sr)
            except Exception as exc:
                logger.error("TTS error: %s", exc)
            finally:
                self.is_speaking = False

    def flush(self) -> None:
        """No-op placeholder — reserved for future queue flushing."""
