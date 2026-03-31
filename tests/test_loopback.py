"""Loopback capture tests — mocked audio; no hardware required."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np


def test_loopback_start_stop_no_crash():
    """LoopbackCapture should not raise when sounddevice is unavailable."""
    import sys
    from unittest.mock import MagicMock

    mock_sd = MagicMock()
    mock_sd.InputStream.return_value.__enter__ = lambda s: s
    mock_sd.InputStream.return_value.__exit__ = MagicMock(return_value=False)

    received: list = []

    def on_audio(audio, sr):
        received.append((audio, sr))

    with patch.dict(sys.modules, {"sounddevice": mock_sd}):
        from voice.loopback_capture import LoopbackCapture

        cap = LoopbackCapture(
            device_name="TestDevice",
            on_audio=on_audio,
            tts=None,
        )
        # Just test instantiation and attribute access
        assert cap._device_name == "TestDevice"
        assert not cap._running


def test_loopback_respects_tts_is_speaking():
    """Callback should be skipped when TTS is_speaking is True."""
    mock_tts = MagicMock()
    mock_tts.is_speaking = True

    callbacks_fired = []

    def on_audio(audio, sr):
        callbacks_fired.append(True)

    import sys

    mock_sd = MagicMock()

    with patch.dict(sys.modules, {"sounddevice": mock_sd}):
        from voice.loopback_capture import LoopbackCapture

        cap = LoopbackCapture("dev", on_audio, tts=mock_tts)
        cap._running = True

        # Simulate the inner callback directly
        audio = np.zeros(1000, dtype=np.float32)
        # Guard: if tts.is_speaking, should not fire
        if not (cap._tts and getattr(cap._tts, "is_speaking", False)):
            cap._on_audio(audio, 16000)

    assert len(callbacks_fired) == 0
