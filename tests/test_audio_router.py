"""AudioRouter tests — mocked sounddevice; no audio hardware required."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


@pytest.fixture
def router():
    from voice.audio_router import AudioRouter

    return AudioRouter(primary_device=None, secondary_device=None)


def test_sanitise_clips_values(router):
    audio = np.array([2.0, -3.0, 0.5, float("nan")], dtype=np.float32)
    result = router._sanitise(audio)
    assert np.all(result <= 1.0)
    assert np.all(result >= -1.0)
    assert not np.any(np.isnan(result))


def test_sanitise_returns_float32(router):
    audio = np.array([0.1, 0.2], dtype=np.float64)
    result = router._sanitise(audio)
    assert result.dtype == np.float32


def test_play_calls_sd_play(router):
    audio = np.zeros(100, dtype=np.float32)
    mock_sd = MagicMock()
    with patch.dict("sys.modules", {"sounddevice": mock_sd}):
        router._play_device(audio, 24000, None)
    mock_sd.play.assert_called_once()
    _, kwargs = mock_sd.play.call_args
    assert kwargs.get("blocking") is True


def test_resolve_output_device_returns_none_on_no_match():
    mock_sd = MagicMock()
    mock_sd.query_devices.return_value = [
        {"name": "Built-in Output", "max_output_channels": 2},
    ]
    with patch.dict("sys.modules", {"sounddevice": mock_sd}):
        from voice.audio_router import AudioRouter

        result = AudioRouter._resolve_output_device("XYZ_NOT_PRESENT")
    assert result is None


def test_resample_no_op_when_rates_equal(router):
    audio = np.random.rand(1000).astype(np.float32)
    result = router.resample_audio(audio, 16000, 16000)
    np.testing.assert_array_equal(audio, result)
