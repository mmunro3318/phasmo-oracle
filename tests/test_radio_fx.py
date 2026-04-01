"""Tests for the CB radio FX chain.

Tests verify DSP correctness, confidence-coded parameter mapping,
asset mixing, edge cases, and graceful fallbacks.
"""

import time

import numpy as np
import pytest

from oracle.voice.audio_config import AudioConfig, get_config
from oracle.voice.radio_fx import (
    RadioFX,
    _generate_ptt_click,
    _generate_squelch_tail,
    resample_for_device,
)


@pytest.fixture()
def config() -> AudioConfig:
    return get_config()


@pytest.fixture()
def fx(config) -> RadioFX:
    return RadioFX(config)


@pytest.fixture()
def tone_1k(config) -> np.ndarray:
    """Generate a 1-second 1kHz sine wave at pipeline sample rate."""
    sr = config.sample_rate
    t = np.linspace(0, 1.0, sr, dtype=np.float32)
    return (np.sin(2 * np.pi * 1000 * t) * 0.5).astype(np.float32)


@pytest.fixture()
def short_audio(config) -> np.ndarray:
    """Generate 0.3s of audio (typical Oracle response length for short commands)."""
    sr = config.sample_rate
    n = int(sr * 0.3)
    t = np.linspace(0, 0.3, n, dtype=np.float32)
    return (np.sin(2 * np.pi * 800 * t) * 0.4).astype(np.float32)


class TestBandPassFilter:
    def test_passes_midrange_frequencies(self, fx, config):
        """1kHz tone (within 300-4500Hz) should pass through with minimal loss."""
        sr = config.sample_rate
        t = np.linspace(0, 0.5, int(sr * 0.5), dtype=np.float32)
        tone = (np.sin(2 * np.pi * 1000 * t) * 0.5).astype(np.float32)

        # Apply only band-pass (disable other stages)
        bp_config = AudioConfig(
            bandpass_enabled=True,
            saturation_enabled=False,
            limiter_enabled=False,
            noise_enabled=False,
            assets_enabled=False,
        )
        bp_fx = RadioFX(bp_config)
        result = bp_fx.apply(tone, sr)

        # Mid-band energy should be preserved (allow for filter transient)
        mid = len(result) // 2
        chunk = 1000  # ~42ms at 24kHz
        input_rms = np.sqrt(np.mean(tone[mid : mid + chunk] ** 2))
        output_rms = np.sqrt(np.mean(result[mid : mid + chunk] ** 2))
        # Should retain at least 70% of energy at 1kHz
        assert output_rms > input_rms * 0.7

    def test_attenuates_low_frequencies(self, config):
        """100Hz tone (below 300Hz cutoff) should be significantly attenuated."""
        sr = config.sample_rate
        t = np.linspace(0, 0.5, int(sr * 0.5), dtype=np.float32)
        tone = (np.sin(2 * np.pi * 100 * t) * 0.5).astype(np.float32)

        bp_config = AudioConfig(
            bandpass_enabled=True,
            saturation_enabled=False,
            limiter_enabled=False,
            noise_enabled=False,
            assets_enabled=False,
        )
        bp_fx = RadioFX(bp_config)
        result = bp_fx.apply(tone, sr)

        mid = len(result) // 2
        chunk = 1000
        input_rms = np.sqrt(np.mean(tone[mid : mid + chunk] ** 2))
        output_rms = np.sqrt(np.mean(result[mid : mid + chunk] ** 2))
        # Should lose at least 70% of energy at 100Hz
        assert output_rms < input_rms * 0.3


class TestTanhSaturation:
    def test_output_stays_in_valid_range(self, config):
        """Saturation output must be in [-1, 1] for any input."""
        sr = config.sample_rate
        # Hot signal that would clip without saturation
        t = np.linspace(0, 0.1, int(sr * 0.1), dtype=np.float32)
        hot = (np.sin(2 * np.pi * 1000 * t) * 2.0).astype(np.float32)

        sat_config = AudioConfig(
            bandpass_enabled=False,
            saturation_enabled=True,
            limiter_enabled=False,
            noise_enabled=False,
            assets_enabled=False,
        )
        sat_fx = RadioFX(sat_config)
        result = sat_fx.apply(hot, sr)
        assert np.all(result >= -1.0)
        assert np.all(result <= 1.0)

    def test_preserves_sign(self, config):
        """Positive input stays positive, negative stays negative."""
        sr = config.sample_rate
        audio = np.array([0.5, -0.5, 0.9, -0.9], dtype=np.float32)
        sat_config = AudioConfig(
            bandpass_enabled=False,
            saturation_enabled=True,
            limiter_enabled=False,
            noise_enabled=False,
            assets_enabled=False,
        )
        sat_fx = RadioFX(sat_config)
        result = sat_fx.apply(audio, sr)
        assert result[0] > 0
        assert result[1] < 0
        assert result[2] > 0
        assert result[3] < 0


class TestConfidenceCodedNoise:
    @pytest.mark.parametrize(
        "candidates,expected_sigma",
        [
            (27, 0.020),
            (1, 0.003),
            (0, 0.003),
            (14, pytest.approx(0.0115, abs=0.002)),
        ],
    )
    def test_noise_sigma_mapping(self, fx, candidates, expected_sigma):
        """Noise sigma maps correctly from candidate count."""
        sigma = fx._noise_sigma(candidates)
        assert sigma == pytest.approx(expected_sigma, abs=0.001)

    def test_more_candidates_means_more_noise(self, config):
        """27 candidates should produce more noise energy than 1 candidate."""
        sr = config.sample_rate
        silence = np.zeros(sr, dtype=np.float32)

        noise_config = AudioConfig(
            bandpass_enabled=False,
            saturation_enabled=False,
            limiter_enabled=False,
            noise_enabled=True,
            assets_enabled=False,
        )
        noise_fx = RadioFX(noise_config)

        result_27 = noise_fx.apply(silence.copy(), sr, candidate_count=27)
        result_1 = noise_fx.apply(silence.copy(), sr, candidate_count=1)

        rms_27 = np.sqrt(np.mean(result_27**2))
        rms_1 = np.sqrt(np.mean(result_1**2))
        assert rms_27 > rms_1 * 2  # 27 candidates should have much more noise


class TestEmptyAudio:
    def test_empty_array_returns_empty(self, fx):
        """Empty input should produce empty output without error."""
        empty = np.array([], dtype=np.float32)
        result = fx.apply(empty, 24000)
        assert len(result) == 0
        assert result.dtype == np.float32

    def test_zero_length_array(self, fx):
        """Zero-length array should not crash."""
        zeros = np.zeros(0, dtype=np.float32)
        result = fx.apply(zeros, 24000)
        assert result.size == 0


class TestOutputProperties:
    def test_handles_2d_input(self, fx, config):
        """Some TTS backends return (N, 1) shaped arrays. FX chain should handle it."""
        sr = config.sample_rate
        audio_2d = np.random.default_rng(0).normal(0, 0.3, (sr, 1)).astype(np.float32)
        result = fx.apply(audio_2d, sr)
        assert result.ndim == 1
        assert result.dtype == np.float32

    def test_output_is_float32(self, fx, tone_1k, config):
        result = fx.apply(tone_1k, config.sample_rate)
        assert result.dtype == np.float32

    def test_output_clipped_to_valid_range(self, fx, config):
        """Output must always be in [-1.0, 1.0] regardless of input."""
        sr = config.sample_rate
        # Extreme input
        extreme = np.full(sr, 5.0, dtype=np.float32)
        result = fx.apply(extreme, sr)
        assert np.all(result >= -1.0)
        assert np.all(result <= 1.0)

    def test_no_nan_in_output(self, fx, config):
        """Output should never contain NaN values."""
        sr = config.sample_rate
        # Input with NaN
        bad_input = np.array([0.5, np.nan, -0.5, np.inf, -np.inf], dtype=np.float32)
        result = fx.apply(bad_input, sr)
        assert not np.any(np.isnan(result))
        assert not np.any(np.isinf(result))


class TestProcessingLatency:
    def test_fx_processing_under_50ms(self, fx, short_audio, config):
        """FX processing for a typical response should be fast.

        Target: < 50ms for 0.3s of audio (generous — design target is <10ms).
        Using 50ms to avoid flaky tests on slow CI.
        """
        start = time.perf_counter()
        fx.apply(short_audio, config.sample_rate, candidate_count=10)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 50, f"FX took {elapsed_ms:.1f}ms, expected < 50ms"


class TestAssetGeneration:
    def test_ptt_click_valid(self, config):
        click = _generate_ptt_click(config.sample_rate)
        assert len(click) > 0
        assert click.dtype == np.float32
        assert np.all(click >= -1.0)
        assert np.all(click <= 1.0)

    def test_squelch_tail_valid(self, config):
        squelch = _generate_squelch_tail(config.sample_rate, 300.0)
        assert len(squelch) > 0
        assert squelch.dtype == np.float32
        assert np.all(squelch >= -1.0)
        assert np.all(squelch <= 1.0)

    def test_squelch_decays(self, config):
        """Squelch tail should decay — end is quieter than start."""
        squelch = _generate_squelch_tail(config.sample_rate, 300.0)
        chunk = len(squelch) // 10
        start_rms = np.sqrt(np.mean(squelch[:chunk] ** 2))
        end_rms = np.sqrt(np.mean(squelch[-chunk:] ** 2))
        assert end_rms < start_rms


class TestAssetMixing:
    def test_output_includes_ptt_and_squelch(self, fx, short_audio, config):
        """Output with assets enabled should be longer than input (PTT + squelch added)."""
        result = fx.apply(short_audio, config.sample_rate, candidate_count=10)
        assert len(result) > len(short_audio)

    def test_assets_disabled_preserves_length(self, config, short_audio):
        """With assets disabled, output length matches processing (no PTT/squelch)."""
        no_asset_config = AudioConfig(assets_enabled=False)
        no_asset_fx = RadioFX(no_asset_config)
        result = no_asset_fx.apply(short_audio, config.sample_rate)
        assert len(result) == len(short_audio)

    def test_squelch_duration_varies_with_candidates(self, fx, short_audio, config):
        """More candidates → longer output (longer squelch tail)."""
        result_27 = fx.apply(short_audio.copy(), config.sample_rate, candidate_count=27)
        result_1 = fx.apply(short_audio.copy(), config.sample_rate, candidate_count=1)
        assert len(result_27) > len(result_1)


class TestResampleForDevice:
    def test_same_rate_returns_unchanged(self):
        audio = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        result = resample_for_device(audio, 24000, 24000)
        np.testing.assert_array_equal(result, audio)

    def test_upsample_to_48k(self):
        """24kHz → 48kHz should roughly double the sample count."""
        sr = 24000
        audio = np.random.default_rng(0).normal(0, 0.5, sr).astype(np.float32)
        result = resample_for_device(audio, 24000, 48000)
        assert len(result) == pytest.approx(len(audio) * 2, abs=5)
        assert result.dtype == np.float32

    def test_upsample_to_44100(self):
        """24kHz → 44.1kHz resampling should produce correct length."""
        sr = 24000
        audio = np.random.default_rng(0).normal(0, 0.5, sr).astype(np.float32)
        result = resample_for_device(audio, 24000, 44100)
        expected_len = int(len(audio) * 44100 / 24000)
        assert len(result) == pytest.approx(expected_len, abs=5)

    def test_empty_audio(self):
        empty = np.array([], dtype=np.float32)
        result = resample_for_device(empty, 24000, 48000)
        assert result.size == 0
