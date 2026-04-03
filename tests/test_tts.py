"""Tests for the TTS provider interface and Kokoro wrapper.

Unit tests mock kokoro-onnx. Integration tests (marked @pytest.mark.integration)
use the real model and require kokoro-onnx to be installed with model files.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from oracle.voice.audio_config import AudioConfig
from oracle.voice.tts import KokoroTTS, TTSProvider


class TestTTSProviderProtocol:
    def test_kokoro_satisfies_protocol(self):
        """KokoroTTS must satisfy the TTSProvider protocol."""
        # Verify the class has the synthesize method with correct signature.
        # Can't use isinstance() without instantiation (needs kokoro-onnx),
        # but we can verify the method exists and is callable.
        assert callable(getattr(KokoroTTS, "synthesize", None))
        # Verify return type annotation matches protocol
        import inspect
        sig = inspect.signature(KokoroTTS.synthesize)
        assert "text" in sig.parameters

    def test_custom_provider_satisfies_protocol(self):
        """A custom class with synthesize() should satisfy TTSProvider."""

        class DummyTTS:
            def synthesize(self, text: str) -> tuple[np.ndarray, int]:
                return np.zeros(100, dtype=np.float32), 24000

        assert isinstance(DummyTTS(), TTSProvider)


def _make_mock_tts(audio_len: int = 24000) -> KokoroTTS:
    """Create a KokoroTTS instance with a mocked Kokoro model.

    Bypasses __init__ (which tries to import kokoro-onnx) and injects
    a mock model that returns deterministic audio.
    """
    tts = KokoroTTS.__new__(KokoroTTS)
    tts._voice = "af_heart"
    tts._speed = 1.0
    tts._config = AudioConfig()

    mock_model = MagicMock()
    audio = np.random.default_rng(0).normal(0, 0.3, audio_len).astype(np.float32)
    mock_model.create.return_value = (audio, 24000)
    tts._model = mock_model

    return tts


class TestKokoroTTSSynthesize:
    def test_returns_float32_tuple(self):
        """synthesize() must return (float32 array, int sample rate)."""
        tts = _make_mock_tts()
        audio, sr = tts.synthesize("Hello world")
        assert audio.dtype == np.float32
        assert isinstance(sr, int)
        assert sr == 24000

    def test_returns_non_empty_audio(self):
        """Normal text should produce non-empty audio."""
        tts = _make_mock_tts(audio_len=24000)
        audio, sr = tts.synthesize("Copy that, spirit box confirmed.")
        assert len(audio) > 0

    def test_model_create_called_with_text(self):
        """synthesize() must pass text and voice params to model.create()."""
        tts = _make_mock_tts()
        tts.synthesize("test phrase")
        tts._model.create.assert_called_once_with(
            "test phrase", voice="af_heart", speed=1.0, lang="en-us"
        )

    def test_short_audio_gets_padded(self):
        """Audio shorter than 200ms (4800 samples at 24kHz) should be padded."""
        tts = _make_mock_tts(audio_len=2400)  # 100ms — too short
        audio, sr = tts.synthesize("OK")
        min_samples = int(24000 * 0.2)  # 200ms = 4800 samples
        assert len(audio) >= min_samples

    def test_long_audio_not_padded(self):
        """Audio longer than 200ms should not be padded."""
        tts = _make_mock_tts(audio_len=24000)  # 1 second
        audio, sr = tts.synthesize("A longer response text")
        assert len(audio) == 24000  # unchanged

    def test_padding_has_lower_energy_than_original(self):
        """Padded section should have lower energy than original (fade applied)."""
        tts = _make_mock_tts(audio_len=2400)  # 100ms — needs padding
        audio, sr = tts.synthesize("Hi")
        original_section = audio[:2400]
        padded_section = audio[2400:]
        assert len(padded_section) > 0

        original_rms = np.sqrt(np.mean(original_section ** 2))
        padded_rms = np.sqrt(np.mean(padded_section ** 2))
        assert padded_rms < original_rms, (
            "Padded tail should have lower energy than original audio "
            "(fade-out was applied to the seed)"
        )


class TestKokoroImportError:
    def test_missing_kokoro_raises_import_error(self):
        """If kokoro-onnx is not installed, KokoroTTS.__init__ raises ImportError."""
        with patch.dict("sys.modules", {"kokoro_onnx": None}):
            with pytest.raises((ImportError, ModuleNotFoundError)):
                KokoroTTS()


class TestPaddingEdgeCases:
    def test_empty_audio_not_padded(self):
        """Empty audio should not be padded (nothing to extend)."""
        tts = KokoroTTS.__new__(KokoroTTS)
        tts._config = AudioConfig()
        empty = np.array([], dtype=np.float32)
        result = tts._pad_short_audio(empty, 24000)
        assert len(result) == 0

    def test_very_short_audio_padded(self):
        """Even very short audio (10 samples) should be padded to minimum."""
        tts = KokoroTTS.__new__(KokoroTTS)
        tts._config = AudioConfig()
        tiny = np.ones(10, dtype=np.float32) * 0.5
        result = tts._pad_short_audio(tiny, 24000)
        min_samples = int(24000 * 0.2)
        assert len(result) >= min_samples
        assert result.dtype == np.float32

    def test_exact_minimum_not_padded(self):
        """Audio exactly at minimum duration should not be padded."""
        tts = KokoroTTS.__new__(KokoroTTS)
        tts._config = AudioConfig()
        min_samples = int(24000 * 0.2)
        exact = np.ones(min_samples, dtype=np.float32) * 0.3
        result = tts._pad_short_audio(exact, 24000)
        assert len(result) == min_samples
