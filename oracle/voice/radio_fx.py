"""CB radio FX chain for Oracle voice output.

Applies a walkie-talkie / CB radio effect to TTS audio. Each stage of the
chain can be independently enabled/disabled via AudioConfig for debugging.

FX chain order:
  1. Band-pass filter (300-4500Hz, Butterworth)
  2. Tanh saturation (warm analog crunch)
  3. Hard-knee peak limiter
  4. Gaussian noise (confidence-coded intensity)
  5. nan_to_num + clip [-1.0, 1.0]
  6. Asset mixing (PTT click + speech + squelch tail)
  7. Resample to device sample rate (if needed)
"""

import logging
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt, resample_poly
from math import gcd

from oracle.voice.audio_config import AudioConfig, get_config

logger = logging.getLogger(__name__)

# Canonical asset directory
_ASSET_DIR = Path(__file__).parent / "assets"


def _generate_ptt_click(sr: int) -> np.ndarray:
    """Generate a synthetic PTT click: short sine burst + noise burst.

    ~50ms total. Sharp attack, fast decay.
    """
    duration_s = 0.05
    n_samples = int(sr * duration_s)
    t = np.linspace(0, duration_s, n_samples, dtype=np.float32)

    # 1kHz sine burst with sharp attack envelope
    sine = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    envelope = np.exp(-t * 60).astype(np.float32)  # fast exponential decay
    click = sine * envelope * 0.6

    # Add a tiny noise burst at the start
    noise_len = min(int(sr * 0.01), n_samples)  # 10ms noise
    noise = np.random.default_rng(42).normal(0, 0.15, noise_len).astype(np.float32)
    click[:noise_len] += noise

    return np.clip(click, -1.0, 1.0)


def _generate_squelch_tail(sr: int, max_duration_ms: float = 300.0) -> np.ndarray:
    """Generate a synthetic squelch tail: filtered noise with exponential decay.

    Generated at max duration; trimmed per-call based on confidence.
    """
    duration_s = max_duration_ms / 1000.0
    n_samples = int(sr * duration_s)

    rng = np.random.default_rng(123)
    noise = rng.normal(0, 0.3, n_samples).astype(np.float32)

    # Exponential decay envelope
    t = np.linspace(0, duration_s, n_samples, dtype=np.float32)
    envelope = np.exp(-t * 8).astype(np.float32)
    squelch = noise * envelope

    # Band-limit the squelch to radio bandwidth
    sos = butter(2, [300, 3000], btype="bandpass", fs=sr, output="sos")
    squelch = sosfilt(sos, squelch).astype(np.float32)

    return np.clip(squelch, -1.0, 1.0)


class RadioFX:
    """CB radio FX processor.

    Applies a composable effects chain to TTS audio. Each stage can be
    individually toggled via AudioConfig for debugging/tuning.

    Assets (PTT click, squelch tail) are generated synthetically on init
    and cached as numpy arrays.
    """

    def __init__(self, config: AudioConfig | None = None):
        self._config = config or get_config()
        sr = self._config.sample_rate

        # Pre-generate and cache assets at pipeline sample rate
        self._ptt_click = _generate_ptt_click(sr)
        self._squelch_tail = _generate_squelch_tail(
            sr, self._config.squelch_duration_max_ms
        )

        # Pre-compute band-pass filter coefficients
        if self._config.bandpass_enabled:
            self._bandpass_sos = butter(
                self._config.bandpass_order,
                [self._config.bandpass_low, self._config.bandpass_high],
                btype="bandpass",
                fs=sr,
                output="sos",
            )

    def _noise_sigma(self, candidate_count: int) -> float:
        """Map candidate count to noise sigma (linear interpolation)."""
        cfg = self._config
        # Clamp to valid range
        count = max(0, min(candidate_count, 27))
        # Linear interpolation: 1 candidate → min, 27 candidates → max
        if count <= 1:
            return cfg.noise_sigma_min
        t = (count - 1) / 26.0
        return cfg.noise_sigma_min + t * (cfg.noise_sigma_max - cfg.noise_sigma_min)

    def _squelch_duration_samples(self, candidate_count: int) -> int:
        """Map candidate count to squelch tail duration in samples."""
        cfg = self._config
        count = max(0, min(candidate_count, 27))
        if count <= 1:
            duration_ms = cfg.squelch_duration_min_ms
        else:
            t = (count - 1) / 26.0
            duration_ms = (
                cfg.squelch_duration_min_ms
                + t * (cfg.squelch_duration_max_ms - cfg.squelch_duration_min_ms)
            )
        return int(cfg.sample_rate * duration_ms / 1000.0)

    def apply(
        self, audio: np.ndarray, sr: int, candidate_count: int = 27
    ) -> np.ndarray:
        """Apply the full CB radio FX chain to audio.

        Args:
            audio: Input audio as float32 array.
            sr: Sample rate of input audio.
            candidate_count: Number of remaining ghost candidates (for
                confidence-coded noise intensity and squelch duration).

        Returns:
            Processed audio as float32 array, at the pipeline sample rate.
        """
        if audio.size == 0:
            return audio.astype(np.float32)

        # Ensure 1D — some TTS backends return (N, 1) shaped arrays
        processed = audio.astype(np.float32).squeeze()
        if processed.ndim != 1:
            processed = processed.flatten()
        cfg = self._config

        # Stage 1: Band-pass filter
        if cfg.bandpass_enabled:
            processed = sosfilt(self._bandpass_sos, processed).astype(np.float32)

        # Stage 2: Tanh saturation
        if cfg.saturation_enabled:
            drive = cfg.saturation_drive
            # Normalize so output stays in [-1, 1] range
            processed = (np.tanh(processed * drive) / np.tanh(drive)).astype(
                np.float32
            )

        # Stage 3: Hard-knee peak limiter
        if cfg.limiter_enabled:
            threshold = cfg.limiter_threshold
            ratio = cfg.limiter_ratio
            above = np.abs(processed) > threshold
            processed[above] = np.sign(processed[above]) * (
                threshold + (np.abs(processed[above]) - threshold) * ratio
            )
            processed = processed.astype(np.float32)

        # Stage 4: Gaussian noise
        if cfg.noise_enabled:
            sigma = self._noise_sigma(candidate_count)
            noise = np.random.default_rng().normal(0, sigma, len(processed))
            processed = (processed + noise).astype(np.float32)

        # Stage 5: Clean up — remove NaN/Inf, clip to valid range
        processed = np.nan_to_num(processed, nan=0.0, posinf=1.0, neginf=-1.0)
        processed = np.clip(processed, -1.0, 1.0).astype(np.float32)

        # Stage 6: Asset mixing
        if cfg.assets_enabled:
            processed = self._mix_assets(processed, candidate_count)

        return processed

    def _mix_assets(
        self, speech: np.ndarray, candidate_count: int
    ) -> np.ndarray:
        """Mix PTT click and squelch tail with speech audio.

        Layout: [PTT click] + [crossfade] + [speech] + [crossfade] + [squelch tail]
        Crossfade length is capped at min(cfg crossfade samples, asset_length // 2).
        """
        sr = self._config.sample_rate
        crossfade_samples = int(sr * self._config.crossfade_ms / 1000.0)

        ptt = self._ptt_click.copy()
        squelch_len = self._squelch_duration_samples(candidate_count)
        squelch = self._squelch_tail[:squelch_len].copy()

        # Apply fade-out to squelch tail
        if len(squelch) > 0:
            fade_len = min(int(sr * 0.005), len(squelch))  # 5ms fade
            if fade_len > 0:
                fade = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
                squelch[-fade_len:] *= fade

        # Guard crossfade length
        cf_ptt = min(crossfade_samples, len(ptt) // 2) if len(ptt) > 0 else 0
        cf_squelch = (
            min(crossfade_samples, len(squelch) // 2) if len(squelch) > 0 else 0
        )

        # Build output: concatenate with crossfades
        parts = []

        if len(ptt) > 0:
            # PTT without the crossfade tail
            parts.append(ptt[: len(ptt) - cf_ptt])
            # Crossfade region: blend PTT tail with speech start
            if cf_ptt > 0 and len(speech) >= cf_ptt:
                blend = np.linspace(1.0, 0.0, cf_ptt, dtype=np.float32)
                crossfade = ptt[-cf_ptt:] * blend + speech[:cf_ptt] * (1 - blend)
                parts.append(crossfade)
                speech = speech[cf_ptt:]

        parts.append(speech)

        if len(squelch) > 0 and cf_squelch > 0 and len(parts) > 0:
            # Get the tail of speech for crossfade
            combined = np.concatenate(parts)
            if len(combined) >= cf_squelch:
                # Blend speech tail with squelch start
                blend = np.linspace(0.0, 1.0, cf_squelch, dtype=np.float32)
                combined[-cf_squelch:] = (
                    combined[-cf_squelch:] * (1 - blend)
                    + squelch[:cf_squelch] * blend
                )
                result = np.concatenate([combined, squelch[cf_squelch:]])
            else:
                result = np.concatenate([combined, squelch])
        else:
            result = np.concatenate(parts) if parts else speech

        return np.clip(result, -1.0, 1.0).astype(np.float32)


def get_device_sample_rate(audio_device: str | None = None) -> int:
    """Query the output device's sample rate.

    Args:
        audio_device: Device name/index from config, or None for system default.

    Returns the device rate, or 24000 if sounddevice is unavailable.
    """
    try:
        import sounddevice as sd

        if audio_device:
            device_info = sd.query_devices(audio_device, "output")
        else:
            device_info = sd.query_devices(kind="output")
        return int(device_info["default_samplerate"])
    except Exception:
        return 24_000


def resample_for_device(
    audio: np.ndarray, source_rate: int, target_rate: int
) -> np.ndarray:
    """Resample audio to match device sample rate.

    Uses scipy.signal.resample_poly for clean resampling without aliasing.
    Returns input unchanged if rates already match.
    """
    if source_rate == target_rate:
        return audio
    if audio.size == 0:
        return audio

    # Compute up/down factors
    divisor = gcd(source_rate, target_rate)
    up = target_rate // divisor
    down = source_rate // divisor

    return resample_poly(audio, up, down).astype(np.float32)
