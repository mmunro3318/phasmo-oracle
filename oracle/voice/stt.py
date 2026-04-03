"""Speech-to-text provider and voice input for Oracle.

STTProvider is a swappable protocol — RealtimeSTT is the default backend.
VoiceInput implements InputProvider (from runner.py) using STTProvider
with wake word detection and barge-in support.
"""

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class STTProvider(Protocol):
    """Protocol for speech-to-text providers.

    Any STT backend must implement this interface.
    """

    def transcribe(self) -> str | None:
        """Block until speech is captured and transcribed.

        Returns:
            Transcribed text string, or None on timeout/silence.
        """
        ...


class VoiceInput:
    """Voice input using RealtimeSTT with wake word detection.

    Implements the InputProvider protocol (get_command() -> str | None).
    Uses RealtimeSTT's AudioToTextRecorder for wake word + VAD + Whisper STT.

    Lifecycle:
        IDLE (wake word listening) -> LISTENING (STT active) -> text returned
        During SPEAKING: wake word still active for barge-in.
    """

    def __init__(
        self,
        whisper_model: str = "tiny",
        wake_word: str = "hey_jarvis",
        input_device_index: int | None = None,
        vad_aggressiveness: int = 2,
    ):
        """Initialize RealtimeSTT recorder with wake word detection.

        Args:
            whisper_model: Whisper model size (tiny, base, small).
            wake_word: openWakeWord model name for activation.
            input_device_index: PyAudio device index for physical mic.
                None uses system default.

        Raises:
            ImportError: If RealtimeSTT is not installed.
            RuntimeError: If recorder initialization fails.
        """
        self._is_speaking = False
        self._barged_in = False
        self._consecutive_failures = 0
        self._max_failures = 3
        self._recorder = None
        self._sd = None

        try:
            from RealtimeSTT import AudioToTextRecorder
        except ImportError:
            raise ImportError(
                "RealtimeSTT is required for voice input. "
                "Install with: pip install -e '.[voice-full]'"
            )

        try:
            import sounddevice as sd
            self._sd = sd
        except ImportError:
            pass

        recorder_config = {
            "model": whisper_model,
            "language": "en",
            # Whisper initial prompt — biases transcription toward our vocabulary.
            # Ghost names, evidence types, and common commands appear here so
            # Whisper is more likely to transcribe them correctly.
            "initial_prompt": (
                "Phasmophobia ghost investigation. Evidence types: EMF, DOTS, "
                "UV, freezing, orbs, ghost writing, spirit box. "
                "Ghost names: Banshee, Demon, Deogen, Goryo, Hantu, Jinn, Mare, "
                "Moroi, Myling, Obake, Oni, Onryo, Phantom, Poltergeist, Raiju, "
                "Revenant, Shade, Spirit, Thaye, The Mimic, The Twins, Wraith, "
                "Yokai, Yurei, Dayan, Gallu, Obambo."
            ),
            # OpenWakeWord backend — "oww" uses built-in models like hey_jarvis.
            # The "wake_words" param is for pvporcupine only; oww auto-extracts
            # from model files. We pass wake_words anyway for logging clarity.
            "wakeword_backend": "oww",
            "wake_words": wake_word,
            "wake_word_activation_delay": 0.3,
            "wake_word_buffer_duration": 1.0,
            "on_wakeword_detected": self._on_wakeword_detected,
            "spinner": False,
            # Use ONNX Silero VAD to avoid torch.hub trust prompt hanging
            "silero_use_onnx": True,
            "silero_sensitivity": 0.4,
            "webrtc_sensitivity": vad_aggressiveness,
            "post_speech_silence_duration": 0.6,
            "min_length_of_recording": 0.3,
            "pre_recording_buffer_duration": 0.5,
        }

        if input_device_index is not None:
            recorder_config["input_device_index"] = input_device_index

        try:
            self._recorder = AudioToTextRecorder(**recorder_config)
            logger.info(
                "VoiceInput ready: model=%s, wake_word=%s, device=%s",
                whisper_model, wake_word, input_device_index,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize RealtimeSTT: {e}") from e

    def get_command(self) -> str | None:
        """Block until wake word + speech captured, return transcribed text.

        Returns:
            Transcribed text string, empty string if nothing heard (will
            be retried by run_loop), or None only on fatal failure
            (signals run_loop to exit).
        """
        if self._recorder is None:
            return None

        try:
            text = self._recorder.text()
            self._consecutive_failures = 0

            if text and text.strip():
                result = text.strip()
                logger.info("STT transcribed: %r", result)
                print(f"  [heard] {result}")
                return result
            # Empty transcription — return empty string so run_loop retries
            # (not None, which would signal "quit")
            return ""

        except Exception as e:
            self._consecutive_failures += 1
            logger.warning(
                "STT error (%d/%d): %s",
                self._consecutive_failures,
                self._max_failures,
                e,
            )
            if self._consecutive_failures >= self._max_failures:
                logger.error(
                    "STT failed %d times consecutively — voice input unreliable",
                    self._max_failures,
                )
                # Only return None (quit signal) after max failures
                return None
            # Recoverable error — return empty string to retry
            return ""

    @property
    def is_speaking(self) -> bool:
        """Whether Oracle is currently playing TTS audio."""
        return self._is_speaking

    @is_speaking.setter
    def is_speaking(self, value: bool) -> None:
        self._is_speaking = value
        if not value:
            self._barged_in = False

    @property
    def barged_in(self) -> bool:
        """Whether a barge-in interrupted TTS playback."""
        return self._barged_in

    @property
    def failed(self) -> bool:
        """Whether STT has exceeded max consecutive failures."""
        return self._consecutive_failures >= self._max_failures

    def _on_wakeword_detected(self) -> None:
        """Callback when wake word is detected.

        If Oracle is currently speaking (TTS playing), stop playback
        immediately (barge-in) and set flag so the main loop knows.
        """
        logger.info("Wake word detected (speaking=%s)", self._is_speaking)
        if self._is_speaking:
            self._barged_in = True
            self._is_speaking = False
            # Stop TTS playback for barge-in
            if self._sd is not None:
                try:
                    self._sd.stop()
                    logger.info("Barge-in: TTS playback stopped")
                except Exception as e:
                    logger.warning("Failed to stop TTS on barge-in: %s", e)

    def shutdown(self) -> None:
        """Clean up recorder resources."""
        if self._recorder is not None:
            try:
                self._recorder.shutdown()
                logger.info("VoiceInput shut down")
            except Exception as e:
                logger.warning("Error during VoiceInput shutdown: %s", e)
            self._recorder = None
