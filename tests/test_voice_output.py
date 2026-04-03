"""Tests for VoiceOutput — the voice-enabled OutputHandler.

All tests mock TTS, radio FX, and sounddevice to run without audio hardware.
"""

from unittest.mock import MagicMock, patch, PropertyMock
import numpy as np
import pytest

from oracle.engine import InvestigationEngine


class TestVoiceOutputProtocol:
    """Verify VoiceOutput satisfies OutputHandler protocol."""

    def test_has_show_response(self):
        from oracle.runner import VoiceOutput
        assert hasattr(VoiceOutput, "show_response")

    def test_has_show_state(self):
        from oracle.runner import VoiceOutput
        assert hasattr(VoiceOutput, "show_state")

    def test_has_show_welcome(self):
        from oracle.runner import VoiceOutput
        assert hasattr(VoiceOutput, "show_welcome")


def _make_voice_output():
    """Create a VoiceOutput with all dependencies mocked."""
    engine = InvestigationEngine()
    engine.new_game("professional")

    # Mock the voice imports
    mock_tts = MagicMock()
    mock_tts.synthesize.return_value = (
        np.random.default_rng(0).normal(0, 0.3, 24000).astype(np.float32),
        24000,
    )

    mock_radio = MagicMock()
    mock_radio.apply.return_value = np.random.default_rng(1).normal(
        0, 0.3, 25000
    ).astype(np.float32)

    mock_sd = MagicMock()

    # Build VoiceOutput bypassing __init__
    from oracle.runner import VoiceOutput, RichOutput
    from oracle.voice.audio_config import get_config

    vo = VoiceOutput.__new__(VoiceOutput)
    vo._text = RichOutput()
    vo._engine = engine
    vo._tts = mock_tts
    vo._radio = mock_radio
    vo._sd = mock_sd
    vo._config = get_config()
    vo._device_sr = 24000
    vo._audio_device = None
    vo._resample = lambda audio, src, tgt: audio

    return vo, engine, mock_tts, mock_radio, mock_sd


class TestShowResponse:
    def test_calls_tts_then_fx_then_play(self):
        """show_response must call TTS, radio FX, and sd.play in order."""
        vo, engine, mock_tts, mock_radio, mock_sd = _make_voice_output()
        vo.show_response("Copy that — EMF 5 confirmed.")

        mock_tts.synthesize.assert_called_once_with("Copy that — EMF 5 confirmed.")
        mock_radio.apply.assert_called_once()
        mock_sd.play.assert_called_once()

    def test_candidate_count_from_engine(self):
        """Radio FX should receive current candidate count from engine."""
        vo, engine, mock_tts, mock_radio, mock_sd = _make_voice_output()
        # Engine starts with 27 candidates
        vo.show_response("Test")
        call_args = mock_radio.apply.call_args
        candidate_count = call_args[0][2]  # 3rd positional arg
        assert candidate_count == 27

    def test_candidate_count_updates_after_evidence(self):
        """After recording evidence, candidate count should decrease."""
        vo, engine, mock_tts, mock_radio, mock_sd = _make_voice_output()
        # Record evidence to narrow candidates
        engine.record_evidence("emf_5", "confirmed")
        vo.show_response("EMF confirmed")
        call_args = mock_radio.apply.call_args
        candidate_count = call_args[0][2]
        assert candidate_count < 27

    def test_audio_failure_still_shows_text(self):
        """If audio playback fails, text should still display."""
        vo, engine, mock_tts, mock_radio, mock_sd = _make_voice_output()
        mock_sd.play.side_effect = RuntimeError("PortAudio error")

        # Patch console to capture output
        with patch.object(vo._text, "show_response") as mock_text:
            vo.show_response("Test response")
            mock_text.assert_called_once_with("Test response")

    def test_no_sounddevice_still_shows_text(self):
        """If sounddevice is None, text should still display."""
        vo, engine, mock_tts, mock_radio, mock_sd = _make_voice_output()
        vo._sd = None

        with patch.object(vo._text, "show_response") as mock_text:
            vo.show_response("Test response")
            mock_text.assert_called_once_with("Test response")
            # TTS should NOT be called if sd is None
            mock_tts.synthesize.assert_not_called()

    def test_stops_previous_audio_before_playing(self):
        """sd.stop() should be called before sd.play() to prevent overlap."""
        vo, engine, mock_tts, mock_radio, mock_sd = _make_voice_output()
        vo.show_response("First")

        # Verify stop was called before play
        calls = mock_sd.method_calls
        stop_idx = next(i for i, c in enumerate(calls) if c[0] == "stop")
        play_idx = next(i for i, c in enumerate(calls) if c[0] == "play")
        assert stop_idx < play_idx


class TestShowStateDelegation:
    def test_delegates_to_rich_output(self):
        vo, engine, _, _, _ = _make_voice_output()
        with patch.object(vo._text, "show_state") as mock:
            vo.show_state(engine)
            mock.assert_called_once_with(engine)


class TestShowWelcomeDelegation:
    def test_delegates_to_rich_output(self):
        vo, engine, _, _, _ = _make_voice_output()
        with patch.object(vo._text, "show_welcome") as mock:
            vo.show_welcome()
            mock.assert_called_once()


class TestDeviceResampling:
    def test_resamples_when_device_rate_differs(self):
        """Audio should be resampled if device rate != pipeline rate."""
        vo, engine, mock_tts, mock_radio, mock_sd = _make_voice_output()
        vo._device_sr = 48000  # Device at 48kHz, pipeline at 24kHz

        resample_called = False
        original_audio = mock_radio.apply.return_value

        def mock_resample(audio, src, tgt):
            nonlocal resample_called
            resample_called = True
            assert src == 24000
            assert tgt == 48000
            return np.zeros(len(audio) * 2, dtype=np.float32)

        vo._resample = mock_resample
        vo.show_response("Test")
        assert resample_called

    def test_no_resample_when_rates_match(self):
        """No resampling when device rate equals pipeline rate."""
        vo, engine, mock_tts, mock_radio, mock_sd = _make_voice_output()
        vo._device_sr = 24000  # Same as pipeline

        resample_called = False

        def mock_resample(audio, src, tgt):
            nonlocal resample_called
            resample_called = True
            return audio

        vo._resample = mock_resample
        vo.show_response("Test")
        assert not resample_called


class TestCLIFlags:
    def test_text_only_no_speak(self):
        """--text without --speak should use RichOutput."""
        from oracle.runner import main
        with patch("sys.argv", ["oracle", "--text"]):
            with patch("oracle.runner.run_loop") as mock_loop:
                with patch("oracle.runner.RichOutput") as mock_rich:
                    main()
                    mock_loop.assert_called_once()
                    # Verify RichOutput instance was passed as the output handler
                    output_arg = mock_loop.call_args[0][2]
                    assert output_arg == mock_rich.return_value



class TestVBCableRouting:
    """Tests for VB-Cable device routing in VoiceOutput."""

    def test_output_device_overrides_config(self):
        """When output_device is provided, it should override config audio_device."""
        vo, engine, mock_tts, mock_radio, mock_sd = _make_voice_output()
        vo._audio_device = "CABLE Input (VB-Audio Virtual Cable)"
        vo.show_response("Test")
        call_kwargs = mock_sd.play.call_args[1]
        assert call_kwargs.get("device") == "CABLE Input (VB-Audio Virtual Cable)"

    def test_no_output_device_uses_config(self):
        """When no output_device, should use config audio_device (None = default)."""
        vo, engine, mock_tts, mock_radio, mock_sd = _make_voice_output()
        assert vo._audio_device is None  # Default from config
        vo.show_response("Test")
        call_kwargs = mock_sd.play.call_args[1]
        # No device kwarg when audio_device is None
        assert "device" not in call_kwargs

    def test_vb_cable_device_name_passed_to_sd_play(self):
        """sd.play should receive the VB-Cable device name."""
        vo, engine, mock_tts, mock_radio, mock_sd = _make_voice_output()
        vo._audio_device = "VoiceMeeter Input"
        vo.show_response("Copy that")
        call_kwargs = mock_sd.play.call_args[1]
        assert call_kwargs["device"] == "VoiceMeeter Input"

    def test_speak_mode_still_works_without_vb_cable(self):
        """--text --speak (no --voice) should still work as before."""
        vo, engine, mock_tts, mock_radio, mock_sd = _make_voice_output()
        # audio_device is None (no VB-Cable)
        vo.show_response("EMF confirmed")
        mock_tts.synthesize.assert_called_once()
        mock_radio.apply.assert_called_once()
        mock_sd.play.assert_called_once()


class TestSpeakingFlag:
    """Tests for is_speaking flag wiring in run_loop."""

    def test_run_loop_calls_show_response(self):
        """run_loop should process commands and call show_response."""
        from oracle.runner import run_loop
        from oracle.engine import InvestigationEngine

        engine = InvestigationEngine()
        engine.new_game("professional")

        # Track is_speaking assignments
        speaking_values = []

        class FakeInput:
            def __init__(self):
                self._calls = iter(["emf confirmed", None])
                self._is_speaking = False

            @property
            def is_speaking(self):
                return self._is_speaking

            @is_speaking.setter
            def is_speaking(self, value):
                speaking_values.append(value)
                self._is_speaking = value

            def get_command(self):
                return next(self._calls)

        mock_output = MagicMock()
        run_loop(engine, FakeInput(), mock_output)

        mock_output.show_response.assert_called()
        # is_speaking should have been set True then False
        assert speaking_values == [True, False]
