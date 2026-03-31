"""Faster-Whisper speech-to-text wrapper."""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


class SpeechToText:
    """Wraps faster-whisper to transcribe float32 audio arrays."""

    def __init__(self, model_size: str = "base.en") -> None:
        self._model_size = model_size
        self._model = None

    def _load(self) -> None:
        if self._model is None:
            from faster_whisper import WhisperModel  # type: ignore[import]

            self._model = WhisperModel(self._model_size, compute_type="int8")
            logger.info("Whisper model loaded: %s", self._model_size)

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """Transcribe a float32 audio array.

        Args:
            audio:       Float32 audio samples at *sample_rate*.
            sample_rate: Expected 16000 for Whisper.

        Returns:
            Transcribed text string.
        """
        self._load()
        segments, _ = self._model.transcribe(  # type: ignore[union-attr]
            audio, beam_size=5, language="en"
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
