"""Wake-word detection using openwakeword."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """Background listener that fires a callback when the wake word is heard.

    The self-feedback guard checks ``tts.is_speaking`` before invoking the
    callback to prevent Oracle from responding to its own voice.
    """

    def __init__(
        self,
        wake_word: str = "oracle",
        on_wake: Callable[[], None] | None = None,
        tts: object | None = None,
    ) -> None:
        self._wake_word = wake_word
        self._on_wake = on_wake
        self._tts = tts
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background detection loop."""
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Wake word detector started (word=%s)", self._wake_word)

    def stop(self) -> None:
        """Stop the detection loop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        try:
            import openwakeword  # type: ignore[import]
            import sounddevice as sd

            oww_model = openwakeword.Model(wakeword_models=[self._wake_word])

            def _audio_callback(indata, frames, time_info, status):
                if not self._running:
                    return
                audio_int16 = (indata[:, 0] * 32768).astype("int16")
                predictions = oww_model.predict(audio_int16)
                if predictions.get(self._wake_word, 0) > 0.5:
                    self.on_wake()

            with sd.InputStream(
                samplerate=16000,
                channels=1,
                dtype="float32",
                blocksize=1280,
                callback=_audio_callback,
            ):
                while self._running:
                    import time

                    time.sleep(0.1)
        except Exception as exc:
            logger.error("Wake word detector error: %s", exc)

    def on_wake(self) -> None:
        """Called when the wake word is detected.  Respects TTS self-feedback guard."""
        if self._tts and getattr(self._tts, "is_speaking", False):
            return
        if self._on_wake:
            self._on_wake()
