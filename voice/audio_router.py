"""AudioRouter — all sounddevice output goes through here.

Hard invariants (see AGENTS.md):
- ``sd.play()`` is ALWAYS called with ``blocking=True``.
- All audio arrays are float32, clipped to [-1.0, 1.0] before playback.
- Do not bypass this class to call sd.play() elsewhere.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class AudioRouter:
    """Routes audio to one or two output devices simultaneously."""

    def __init__(
        self,
        primary_device: str | None = None,
        secondary_device: str | None = None,
        sample_rate: int = 24000,
    ) -> None:
        self._primary = primary_device
        self._secondary = secondary_device
        self._sample_rate = sample_rate

    # ── Public API ─────────────────────────────────────────────────────────────

    def play(self, audio: np.ndarray, sample_rate: int | None = None) -> None:
        """Play *audio* on all configured output devices.

        Sanitises the array (nan→0, clip to [-1, 1]) before playback.

        Args:
            audio:       Float32 audio samples.
            sample_rate: Override sample rate; defaults to router's sample rate.
        """
        rate = sample_rate or self._sample_rate
        audio = self._sanitise(audio)

        if self._secondary:
            t = threading.Thread(
                target=self._play_device,
                args=(audio, rate, self._secondary),
                daemon=True,
            )
            t.start()

        self._play_device(audio, rate, self._primary)

        if self._secondary:
            t.join()  # type: ignore[possibly-undefined]

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _sanitise(audio: np.ndarray) -> np.ndarray:
        audio = np.nan_to_num(audio, nan=0.0, posinf=1.0, neginf=-1.0)
        return np.clip(audio, -1.0, 1.0).astype(np.float32)

    def _play_device(self, audio: np.ndarray, rate: int, device: Any) -> None:
        """Play audio on a single device, always blocking."""
        try:
            import sounddevice as sd

            device_id = self._resolve_output_device(device) if isinstance(device, str) else device
            sd.play(audio, samplerate=rate, device=device_id, blocking=True)
        except Exception as exc:
            logger.warning("AudioRouter playback error (device=%s): %s", device, exc)

    @staticmethod
    def _resolve_output_device(name_fragment: str) -> int | None:
        """Find an output device whose name contains *name_fragment*."""
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            for idx, dev in enumerate(devices):
                if name_fragment.lower() in dev["name"].lower() and dev["max_output_channels"] > 0:
                    return idx
        except Exception:
            pass
        return None

    @staticmethod
    def resample_audio(audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
        """Resample *audio* from *from_rate* to *to_rate* using scipy.

        Uses ``scipy.signal.resample_poly`` for clean arbitrary-ratio resampling.
        """
        if from_rate == to_rate:
            return audio
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(from_rate, to_rate)
        return resample_poly(audio, to_rate // g, from_rate // g).astype(np.float32)
