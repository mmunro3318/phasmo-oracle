"""Tests for VoiceInput — the voice-enabled InputProvider.

All tests mock RealtimeSTT and sounddevice to run without audio hardware.
"""

from unittest.mock import MagicMock, patch, PropertyMock
import pytest


def _make_voice_input():
    """Create a VoiceInput with RealtimeSTT mocked."""
    mock_recorder = MagicMock()
    mock_sd = MagicMock()

    with patch("oracle.voice.stt.AudioToTextRecorder", create=True) as mock_cls:
        # Patch the import inside VoiceInput.__init__
        with patch.dict("sys.modules", {"RealtimeSTT": MagicMock()}):
            from oracle.voice.stt import VoiceInput
            # Build VoiceInput bypassing __init__ to avoid real RealtimeSTT
            vi = VoiceInput.__new__(VoiceInput)
            vi._is_speaking = False
            vi._barged_in = False
            vi._consecutive_failures = 0
            vi._max_failures = 3
            vi._recorder = mock_recorder
            vi._sd = mock_sd
    return vi, mock_recorder, mock_sd


class TestVoiceInputProtocol:
    """Verify VoiceInput satisfies InputProvider protocol."""

    def test_has_get_command(self):
        vi, _, _ = _make_voice_input()
        assert hasattr(vi, "get_command")
        assert callable(vi.get_command)


class TestGetCommand:
    def test_returns_transcribed_text(self):
        vi, mock_recorder, _ = _make_voice_input()
        mock_recorder.text.return_value = "EMF confirmed"
        result = vi.get_command()
        assert result == "EMF confirmed"

    def test_strips_whitespace(self):
        vi, mock_recorder, _ = _make_voice_input()
        mock_recorder.text.return_value = "  spirit box confirmed  "
        result = vi.get_command()
        assert result == "spirit box confirmed"

    def test_returns_empty_on_empty(self):
        """Empty transcription returns empty string (retry), not None (quit)."""
        vi, mock_recorder, _ = _make_voice_input()
        mock_recorder.text.return_value = ""
        assert vi.get_command() == ""

    def test_returns_empty_on_whitespace_only(self):
        vi, mock_recorder, _ = _make_voice_input()
        mock_recorder.text.return_value = "   "
        assert vi.get_command() == ""

    def test_returns_empty_on_none_transcription(self):
        """None from recorder means nothing heard, not fatal — return empty."""
        vi, mock_recorder, _ = _make_voice_input()
        mock_recorder.text.return_value = None
        assert vi.get_command() == ""

    def test_returns_none_when_recorder_is_none(self):
        vi, _, _ = _make_voice_input()
        vi._recorder = None
        assert vi.get_command() is None

    def test_resets_failure_count_on_success(self):
        vi, mock_recorder, _ = _make_voice_input()
        vi._consecutive_failures = 2
        mock_recorder.text.return_value = "orbs confirmed"
        vi.get_command()
        assert vi._consecutive_failures == 0


class TestErrorHandling:
    def test_increments_failure_on_exception(self):
        vi, mock_recorder, _ = _make_voice_input()
        mock_recorder.text.side_effect = RuntimeError("audio error")
        vi.get_command()
        assert vi._consecutive_failures == 1

    def test_returns_empty_on_recoverable_exception(self):
        """Single error returns empty string (retry), not None (quit)."""
        vi, mock_recorder, _ = _make_voice_input()
        mock_recorder.text.side_effect = RuntimeError("audio error")
        assert vi.get_command() == ""

    def test_failed_after_three_consecutive_errors(self):
        vi, mock_recorder, _ = _make_voice_input()
        mock_recorder.text.side_effect = RuntimeError("audio error")
        vi.get_command()  # returns ""
        vi.get_command()  # returns ""
        result = vi.get_command()  # 3rd failure — returns None (quit signal)
        assert vi.failed is True
        assert result is None

    def test_not_failed_after_two_errors(self):
        vi, mock_recorder, _ = _make_voice_input()
        mock_recorder.text.side_effect = RuntimeError("audio error")
        vi.get_command()
        vi.get_command()
        assert vi.failed is False

    def test_failure_resets_on_success(self):
        vi, mock_recorder, _ = _make_voice_input()
        mock_recorder.text.side_effect = RuntimeError("audio error")
        vi.get_command()
        vi.get_command()
        # Now succeed
        mock_recorder.text.side_effect = None
        mock_recorder.text.return_value = "freezing confirmed"
        vi.get_command()
        assert vi._consecutive_failures == 0
        assert vi.failed is False


class TestBargeIn:
    def test_wakeword_during_speaking_stops_tts(self):
        vi, _, mock_sd = _make_voice_input()
        vi._is_speaking = True
        vi._on_wakeword_detected()
        mock_sd.stop.assert_called_once()

    def test_wakeword_during_speaking_sets_barged_in(self):
        vi, _, mock_sd = _make_voice_input()
        vi._is_speaking = True
        vi._on_wakeword_detected()
        assert vi.barged_in is True

    def test_wakeword_during_speaking_clears_speaking(self):
        vi, _, mock_sd = _make_voice_input()
        vi._is_speaking = True
        vi._on_wakeword_detected()
        assert vi.is_speaking is False

    def test_wakeword_while_idle_no_stop(self):
        vi, _, mock_sd = _make_voice_input()
        vi._is_speaking = False
        vi._on_wakeword_detected()
        mock_sd.stop.assert_not_called()
        assert vi.barged_in is False

    def test_barged_in_resets_when_speaking_cleared(self):
        vi, _, mock_sd = _make_voice_input()
        vi._is_speaking = True
        vi._on_wakeword_detected()
        assert vi.barged_in is True
        vi.is_speaking = False
        assert vi.barged_in is False

    def test_barge_in_survives_sd_stop_failure(self):
        vi, _, mock_sd = _make_voice_input()
        vi._is_speaking = True
        mock_sd.stop.side_effect = RuntimeError("PortAudio error")
        vi._on_wakeword_detected()
        assert vi.barged_in is True
        assert vi.is_speaking is False


class TestShutdown:
    def test_calls_recorder_shutdown(self):
        vi, mock_recorder, _ = _make_voice_input()
        vi.shutdown()
        mock_recorder.shutdown.assert_called_once()

    def test_sets_recorder_to_none(self):
        vi, mock_recorder, _ = _make_voice_input()
        vi.shutdown()
        assert vi._recorder is None

    def test_handles_shutdown_error(self):
        vi, mock_recorder, _ = _make_voice_input()
        mock_recorder.shutdown.side_effect = RuntimeError("cleanup error")
        vi.shutdown()  # Should not raise
        assert vi._recorder is None

    def test_shutdown_when_no_recorder(self):
        vi, _, _ = _make_voice_input()
        vi._recorder = None
        vi.shutdown()  # Should not raise


