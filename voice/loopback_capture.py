"""WASAPI loopback capture for bidirectional mode (Windows only).

Captures what is playing on a specific output device (e.g. Kayden's voice via
Steam voice chat) and feeds it to the Oracle graph as a second speaker.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import numpy as np

logger = logging.getLogger(__name__)


class LoopbackCapture:
    """Captures audio from a loopback device and fires a callback with the audio."""

    def __init__(
        self,
        device_name: str,
        on_audio: Callable[[np.ndarray, int], None],
        tts: object | None = None,
        sample_rate: int = 16000,
    ) -> None:
        self._device_name = device_name
        self._on_audio = on_audio
        self._tts = tts
        self._sample_rate = sample_rate
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("Loopback capture started (device=%s)", self._device_name)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _capture_loop(self) -> None:
        try:
            import sounddevice as sd

            from voice.audio_router import AudioRouter

            device_id = AudioRouter._resolve_output_device(self._device_name)

            def _callback(indata, frames, time_info, status):
                if not self._running:
                    return
                # Self-feedback guard
                if self._tts and getattr(self._tts, "is_speaking", False):
                    return
                audio = indata[:, 0].copy()
                self._on_audio(audio, self._sample_rate)

            with sd.InputStream(
                samplerate=self._sample_rate,
                device=device_id,
                channels=1,
                dtype="float32",
                callback=_callback,
            ):
                while self._running:
                    import time

                    time.sleep(0.1)
        except Exception as exc:
            logger.error("Loopback capture error: %s", exc)
