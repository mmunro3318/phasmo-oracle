"""Audio pipeline configuration for Oracle voice output.

All FX parameters live here. Each stage of the radio FX chain can be
independently enabled/disabled for debugging and tuning.

Audio device is configurable via AUDIO_DEVICE in .env.local.
Voice is configurable via KOKORO_VOICE in .env.local (default: bm_fable).
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

# ── Voice catalogue ────────────────────────────────────────────────────────

BRITISH_VOICES = [
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
]

AMERICAN_VOICES = [
    "af_heart", "af_bella", "af_sarah", "af_sky", "af_nova",
    "am_adam", "am_eric", "am_michael", "am_liam",
]

ALL_VOICES: dict[str, str] = {
    v: "en-gb" for v in BRITISH_VOICES
} | {
    v: "en-us" for v in AMERICAN_VOICES
}

DEFAULT_VOICE = "bm_fable"


def _load_env() -> None:
    """Load .env.local once if python-dotenv is available."""
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).parent.parent.parent / ".env.local"
        if env_path.exists():
            load_dotenv(env_path)
    except ImportError:
        pass


def _load_audio_device() -> str | None:
    """Load AUDIO_DEVICE from .env.local."""
    _load_env()
    device = os.getenv("AUDIO_DEVICE")
    return device if device else None


def _load_voice() -> str:
    """Load KOKORO_VOICE from .env.local, default to bm_fable."""
    _load_env()
    voice = os.getenv("KOKORO_VOICE", DEFAULT_VOICE)
    if voice not in ALL_VOICES:
        voice = DEFAULT_VOICE
    return voice


def _load_stt_input_device() -> str | None:
    """Load STT_INPUT_DEVICE from .env.local."""
    _load_env()
    device = os.getenv("STT_INPUT_DEVICE")
    return device if device else None


def _load_vb_cable_device() -> str | None:
    """Load VB_CABLE_DEVICE from .env.local."""
    _load_env()
    device = os.getenv("VB_CABLE_DEVICE")
    return device if device else None


@dataclass
class AudioConfig:
    """Audio pipeline constants.

    Audio device can be set via AUDIO_DEVICE in .env.local.
    Default: system output device (None).
    """

    # Audio device (None = system default, or device name/index from .env.local)
    audio_device: str | None = field(default_factory=_load_audio_device)

    # Kokoro voice (from .env.local KOKORO_VOICE, default: bm_fable)
    voice: str = field(default_factory=_load_voice)

    # Pipeline sample rate (Kokoro output rate)
    sample_rate: int = 24_000

    # ── Band-pass filter ──────────────────────────────────────────────
    bandpass_enabled: bool = True
    bandpass_low: float = 300.0    # Hz — high-pass cutoff
    bandpass_high: float = 4500.0  # Hz — low-pass cutoff (wider than military for CB warmth)
    bandpass_order: int = 4        # Butterworth filter order

    # ── Tanh saturation ───────────────────────────────────────────────
    saturation_enabled: bool = True
    saturation_drive: float = 1.5  # Mild warm crunch. Higher = more distortion.

    # ── Hard-knee peak limiter ────────────────────────────────────────
    limiter_enabled: bool = True
    limiter_threshold: float = 0.3  # Signal above this is attenuated
    limiter_ratio: float = 0.5      # Slope above threshold (0.5 = 2:1 ratio)

    # ── Confidence-coded noise ────────────────────────────────────────
    noise_enabled: bool = True
    noise_sigma_min: float = 0.003  # At 1 candidate (near-clean, confident)
    noise_sigma_max: float = 0.020  # At 27 candidates (heavy static, uncertain)

    # ── Asset mixing ──────────────────────────────────────────────────
    assets_enabled: bool = True
    crossfade_ms: float = 5.0  # Crossfade between assets and speech

    # ── Squelch tail duration (confidence-coded) ──────────────────────
    squelch_duration_min_ms: float = 80.0    # At 1 candidate (crisp)
    squelch_duration_max_ms: float = 300.0   # At 27 candidates (long)

    # ── Short-sentence padding ────────────────────────────────────────
    min_audio_duration_ms: float = 200.0  # Minimum TTS output before padding

    # ── STT / Voice Input (Sprint 3c) ────────────────────────────────
    whisper_model: str = "base"  # Whisper model size: tiny, base, small
    wake_word: str = "hey_jarvis"  # openWakeWord model name
    vad_aggressiveness: int = 2  # WebRTC VAD aggressiveness (0-3, higher = more aggressive)
    stt_input_device: str | None = field(default_factory=_load_stt_input_device)
    vb_cable_device: str | None = field(default_factory=_load_vb_cable_device)


def get_config() -> AudioConfig:
    """Return default audio config.

    Future: load overrides from .env.local or CLI flags.
    """
    return AudioConfig()


# Known VB-Audio device name patterns (output devices that Oracle sends TTS to)
_VB_CABLE_PATTERNS = [
    "CABLE Input",
    "CABLE-A",
    "CABLE-B",
    "VoiceMeeter Input",
    "VoiceMeeter Aux Input",
]


def find_vb_cable_device() -> str | None:
    """Scan sounddevice output devices for a VB-Audio virtual cable.

    Searches for known VB-Cable device name patterns. Returns the first
    match, or None if no VB-Cable device is found.

    The returned name can be passed to sd.play(device=...) to route
    Oracle's TTS audio through VB-Cable into Steam Voice Chat.
    """
    try:
        import sounddevice as sd
    except ImportError:
        return None

    devices = sd.query_devices()
    for device in devices:
        name = device["name"]
        # Only check output devices (max_output_channels > 0)
        if device["max_output_channels"] <= 0:
            continue
        for pattern in _VB_CABLE_PATTERNS:
            if pattern.lower() in name.lower():
                return name
    return None
