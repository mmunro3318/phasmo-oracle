"""Dual-capture loop coordinator.

Manages two audio sources:
  1. Primary mic (wake word → STT → Oracle)
  2. Loopback capture (Kayden's voice via Steam, optional)

Both paths share the same Oracle graph instance and turn queue.
"""
from __future__ import annotations

import logging
import queue
from collections.abc import Callable

import numpy as np

logger = logging.getLogger(__name__)


class VoiceSession:
    """Coordinates wake-word detection, STT, and turn dispatch."""

    def __init__(
        self,
        stt,  # SpeechToText instance
        tts,  # TextToSpeech instance
        on_turn: Callable[[str, str], None],  # (speaker, text) → None
        wake_word: str = "oracle",
        mic_device: str | None = None,
        loopback_device: str | None = None,
    ) -> None:
        self._stt = stt
        self._tts = tts
        self._on_turn = on_turn
        self._wake_word = wake_word
        self._mic_device = mic_device
        self._loopback_device = loopback_device
        self._turn_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._running = False

    def start(self) -> None:
        """Start all background capture threads."""
        from voice.wake_word import WakeWordDetector

        self._detector = WakeWordDetector(
            wake_word=self._wake_word,
            on_wake=self._on_primary_wake,
            tts=self._tts,
        )
        self._detector.start()

        if self._loopback_device:
            from voice.loopback_capture import LoopbackCapture

            self._loopback = LoopbackCapture(
                device_name=self._loopback_device,
                on_audio=self._on_loopback_audio,
                tts=self._tts,
            )
            self._loopback.start()

        self._running = True
        logger.info("VoiceSession started")

    def stop(self) -> None:
        self._running = False
        if hasattr(self, "_detector"):
            self._detector.stop()
        if hasattr(self, "_loopback"):
            self._loopback.stop()

    def get_turn(self, timeout: float = 0.1) -> tuple[str, str] | None:
        """Non-blocking poll for the next (speaker, text) turn."""
        try:
            return self._turn_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    # ── Internal callbacks ─────────────────────────────────────────────────────

    def _on_primary_wake(self) -> None:
        """Record mic audio after wake word and transcribe it."""
        import sounddevice as sd

        audio = sd.rec(
            (5 * 16000), samplerate=16000, channels=1, dtype="float32"
        )
        sd.wait()
        text = self._stt.transcribe(audio[:, 0])
        if text.strip():
            self._turn_queue.put(("Mike", text))

    def _on_loopback_audio(self, audio: np.ndarray, sample_rate: int) -> None:
        """Transcribe loopback audio and queue as Kayden's turn."""
        text = self._stt.transcribe(audio)
        if text.strip():
            self._turn_queue.put(("Kayden", text))
