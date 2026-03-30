**Goal:** Oracle's spoken responses are audible to all players in a Steam voice session, not just the local player. Oracle continues to play through local headphones simultaneously.

**Builds on:** Sprint 2's working voice loop — wake word, Whisper, graph, Kokoro TTS.

**Windows only.** VB-Cable is a Windows virtual audio driver. Since Phasmophobia is Windows-exclusive, this is not a constraint in practice.

**Exit criteria:**

- Oracle's audio plays through both local headphones AND VB-Cable simultaneously
- Steam teammates hear Oracle in-game voice chat
- Mike's real microphone is unaffected
- No audible sync gap between local and Steam outputs
- `STEAM_ROUTE_DEVICE_NAME` in `.env.local` can be blanked to disable Steam routing with no code changes
- Sprint 2 voice loop regression: Oracle still responds correctly to voice commands

---

## How VB-Cable Works

VB-Cable installs two virtual audio devices:

|Windows device name|Role|
|---|---|
|`CABLE Input (VB-Audio Virtual Cable)`|Virtual speaker — apps **play into** this|
|`CABLE Output (VB-Audio Virtual Cable)`|Virtual microphone — apps **record from** this|

The cable internally loops everything written to CABLE Input back out through CABLE Output. This means:

- **Oracle writes audio → CABLE Input** (treats it as a speaker)
- **Steam reads audio ← CABLE Output** (treats it as a microphone)
- Teammates in Steam hear whatever Oracle writes

Oracle simultaneously writes the same audio to real headphones via its existing `SPEAKER_DEVICE_NAME` path. The two writes run in parallel threads so there is no sequential delay.

```
                     ┌─ CABLE Input ──────────────────┐
Kokoro audio ──────▶ │  (virtual speaker)              │──▶ CABLE Output ──▶ Steam mic
                     └────────────────────────────────┘

                     ┌─ Headphones (VK81 / real device) ┐
Kokoro audio ──────▶ │  (physical speaker)              │──▶ Mike's ears
                     └──────────────────────────────────┘
```

---

## Sample Rate Resampling

Kokoro TTS outputs at **24,000 Hz**. VB-Cable's default native rate is **44,100 Hz** (sometimes 48,000 Hz — depends on Windows settings). PortAudio/sounddevice requires audio data at the device's native rate; it does not resample automatically.

Oracle must resample before writing to VB-Cable. The approach:

1. Query VB-Cable's native sample rate at startup via `sd.query_devices()`
2. Resample from 24,000 Hz to the device's native rate using `scipy.signal.resample_poly`
3. Write resampled audio to VB-Cable; write original 24,000 Hz audio to headphones (which already work at that rate from Sprint 2)

---

## New Architecture: `AudioRouter`

Sprint 2's TTS module called `sd.play()` directly. Sprint 3 introduces `voice/audio_router.py` — a dedicated routing layer that sits between TTS synthesis and device playback. `TextToSpeech` now calls `router.play(samples, rate)` instead of `sd.play()`.

Benefits:

- TTS module stays focused on synthesis; routing is a separate concern
- Sprint 4 can extend `AudioRouter` without touching TTS
- `AudioRouter` is testable without audio synthesis

```
TextToSpeech._synthesize()  →  AudioRouter.play()  →  primary device (headphones)
                                                    →  secondary device (VB-Cable) [if configured]
```

---

## Implementation Order

```
1. voice/audio_router.py       ← new: dual output, resampling, gain control
2. voice/text_to_speech.py     ← updated: use AudioRouter instead of sd.play()
3. config/settings.py          ← add STEAM_ROUTE_DEVICE_NAME, STEAM_ROUTE_GAIN
4. config/.env.local           ← document VB-Cable setup
5. main.py                     ← pass steam config to AudioRouter
6. tests/test_audio_router.py  ← resampling math, device resolution, dual-output logic
```

---

## Scaffold Code

### `voice/audio_router.py`

```python
"""
AudioRouter — routes synthesized audio to one or two output devices in parallel.

Primary device:   local headphones (always plays)
Secondary device: VB-Cable Input (optional, routes to Steam)

Both devices are written simultaneously in background threads. play() blocks
until both outputs have finished, which keeps the TTS _speaking flag accurate.
"""

import logging
import math
import threading
from typing import Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


def resample_audio(
    audio: np.ndarray,
    src_rate: int,
    dst_rate: int,
) -> np.ndarray:
    """
    Resample float32 audio from src_rate to dst_rate using polyphase filtering.
    Returns a new float32 array. No-op if rates are equal.
    """
    if src_rate == dst_rate:
        return audio
    from scipy.signal import resample_poly
    g = math.gcd(src_rate, dst_rate)
    resampled = resample_poly(audio, dst_rate // g, src_rate // g)
    return resampled.astype(np.float32)


def _query_native_rate(device_id: int | None) -> int:
    """Return the default sample rate reported by the device, or 44100 as fallback."""
    if device_id is None:
        return 44100
    try:
        info = sd.query_devices(device_id)
        return int(info["default_samplerate"])
    except Exception:
        return 44100


def _resolve_output_device(name_hint: str | None) -> int | None:
    """
    Find a sounddevice output device ID by partial name match.
    Returns None if hint is empty or no match is found.
    """
    if not name_hint:
        return None
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if name_hint.lower() in d["name"].lower() and d["max_output_channels"] > 0:
            logger.info(f"AudioRouter: resolved '{name_hint}' → [{i}] {d['name']}")
            return i
    logger.warning(
        f"AudioRouter: device '{name_hint}' not found — "
        "check STEAM_ROUTE_DEVICE_NAME or SPEAKER_DEVICE_NAME in .env.local"
    )
    return None


class AudioRouter:
    """
    Routes audio to one (local only) or two (local + Steam) output devices.

    Usage:
        router = AudioRouter(
            primary_device="VK81",         # headphones
            secondary_device="CABLE Input", # VB-Cable → Steam
            secondary_gain=0.9,
        )
        router.play(samples_float32, src_rate=24000)
    """

    def __init__(
        self,
        primary_device: str | None = None,
        secondary_device: str | None = None,
        secondary_gain: float = 1.0,
    ):
        self._primary_id   = _resolve_output_device(primary_device)
        self._secondary_id = _resolve_output_device(secondary_device)

        self._primary_rate   = _query_native_rate(self._primary_id)
        self._secondary_rate = _query_native_rate(self._secondary_id)
        self._secondary_gain = float(np.clip(secondary_gain, 0.0, 2.0))

        logger.info(
            f"AudioRouter ready. "
            f"Primary: device={self._primary_id} @ {self._primary_rate}Hz | "
            f"Secondary: device={self._secondary_id} @ {self._secondary_rate}Hz "
            f"(gain={self._secondary_gain:.2f})"
        )

    @property
    def steam_enabled(self) -> bool:
        return self._secondary_id is not None

    def play(self, samples: np.ndarray, src_rate: int) -> None:
        """
        Write audio to primary (and secondary if configured) device.
        Blocks until all outputs complete.
        Resamples as needed for each device's native rate.
        """
        samples = np.nan_to_num(samples, nan=0.0, posinf=1.0, neginf=-1.0)
        samples = np.clip(samples.astype(np.float32), -1.0, 1.0)

        threads: list[threading.Thread] = []

        # Primary (headphones)
        primary_audio = resample_audio(samples, src_rate, self._primary_rate)
        threads.append(threading.Thread(
            target=self._play_device,
            args=(primary_audio, self._primary_rate, self._primary_id),
            daemon=True,
        ))

        # Secondary (VB-Cable → Steam)
        if self._secondary_id is not None:
            secondary_audio = resample_audio(samples, src_rate, self._secondary_rate)
            if self._secondary_gain != 1.0:
                secondary_audio = np.clip(
                    secondary_audio * self._secondary_gain, -1.0, 1.0
                )
            threads.append(threading.Thread(
                target=self._play_device,
                args=(secondary_audio, self._secondary_rate, self._secondary_id),
                daemon=True,
            ))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

    @staticmethod
    def _play_device(
        audio: np.ndarray,
        rate: int,
        device_id: int | None,
    ) -> None:
        try:
            sd.play(audio, samplerate=rate, device=device_id, blocking=True)
        except sd.PortAudioError as e:
            logger.error(f"AudioRouter: PortAudio error on device {device_id}: {e}")
            if device_id is not None:
                # Last-resort fallback to system default
                try:
                    sd.play(audio, samplerate=rate, device=None, blocking=True)
                except Exception:
                    pass
```

---

### `voice/text_to_speech.py` (updated)

Replace the `sd.play()` call in `_synthesize_and_play()` with `self._router.play()`. The rest of the module stays the same.

```python
"""kokoro-onnx TTS wrapper — Sprint 3: uses AudioRouter for dual output."""

import logging
import queue
import threading

import numpy as np

logger = logging.getLogger(__name__)

_KOKORO_RATE = 24000


class TextToSpeech:
    def __init__(
        self,
        speaker_device_name: str | None = None,
        steam_device_name: str | None = None,
        steam_gain: float = 1.0,
        voice: str = "bm_fable",
    ):
        self._speaker_device = speaker_device_name
        self._steam_device   = steam_device_name
        self._steam_gain     = steam_gain
        self._voice          = voice
        self._pipeline       = None
        self._router         = None
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._speaking = False

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def load(self) -> None:
        from kokoro_onnx import Kokoro
        from voice.audio_router import AudioRouter

        self._pipeline = Kokoro("kokoro-v0_19.onnx", "voices-v1_0.bin")
        self._router   = AudioRouter(
            primary_device=self._speaker_device,
            secondary_device=self._steam_device,
            secondary_gain=self._steam_gain,
        )

        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        logger.info(
            f"TTS ready. Voice: {self._voice}. "
            f"Steam routing: {'enabled' if self._router.steam_enabled else 'disabled'}."
        )

    def speak(self, text: str) -> None:
        if text and text.strip():
            self._queue.put(text.strip())

    def flush(self) -> None:
        discarded = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                discarded += 1
            except queue.Empty:
                break
        if discarded:
            logger.debug(f"TTS queue flushed: {discarded} phrase(s) discarded.")

    def shutdown(self) -> None:
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=5)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            try:
                self._speaking = True
                self._synthesize_and_play(item)
            except Exception as e:
                logger.error(f"TTS synthesis error: {e}")
            finally:
                self._speaking = False

    def _synthesize_and_play(self, text: str) -> None:
        samples, rate = self._pipeline.create(
            text, voice=self._voice, speed=1.0, lang="en-us"
        )
        # AudioRouter handles resampling, dual output, and PortAudio fallback
        self._router.play(samples, src_rate=rate)
```

---

### `config/settings.py` (updated)

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env.local", extra="ignore")

    # LLM
    OLLAMA_MODEL: str    = "phi4-mini"
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # Game
    DIFFICULTY: str = "professional"
    DB_PATH: str    = "config/ghost_database.yaml"

    # Voice — STT
    STT_MODEL: str = "base.en"

    # Voice — TTS (local)
    SPEAKER_DEVICE_NAME: str | None = None
    TTS_VOICE: str                  = "bm_fable"

    # Voice — TTS (Steam routing)  ← Sprint 3
    STEAM_ROUTE_DEVICE_NAME: str | None = None   # e.g. "CABLE Input"
    STEAM_ROUTE_GAIN: float             = 1.0    # 0.0–2.0; scale Steam volume independently

    # Voice — wake word
    WAKE_WORD: str = "oracle"

    # Voice — recording
    MIC_DEVICE_NAME: str | None  = None
    SILENCE_THRESHOLD_DB: float  = -40.0
    MAX_RECORDING_SECONDS: float = 8.0

config = Settings()
```

---

### `config/.env.local` (updated template)

```env
# ── LLM ──────────────────────────────────────────────────────────────────────
OLLAMA_MODEL=phi4-mini
OLLAMA_BASE_URL=http://localhost:11434
DIFFICULTY=professional

# ── Voice (STT) ───────────────────────────────────────────────────────────────
STT_MODEL=base.en
WAKE_WORD=oracle
# MIC_DEVICE_NAME=Blue Yeti
SILENCE_THRESHOLD_DB=-40.0
MAX_RECORDING_SECONDS=8.0

# ── Voice (TTS — local playback) ─────────────────────────────────────────────
TTS_VOICE=bm_fable
# SPEAKER_DEVICE_NAME=VK81       # fragment of your headphones device name

# ── Voice (TTS — Steam routing via VB-Cable) ─────────────────────────────────
# Requires VB-Cable installed: https://vb-audio.com/Cable/
# Set Steam's voice input device to: CABLE Output (VB-Audio Virtual Cable)
# Then uncomment the line below to enable Oracle routing to Steam:
# STEAM_ROUTE_DEVICE_NAME=CABLE Input
# STEAM_ROUTE_GAIN=1.0           # reduce if Oracle is too loud in Steam (e.g. 0.7)
```

---

### `main.py` — `run_voice_loop()` update (diff only)

The `TextToSpeech` constructor gains two new params. One line change in `run_voice_loop()`:

```python
# Before (Sprint 2):
tts = TextToSpeech(speaker_device_name=config.SPEAKER_DEVICE_NAME)

# After (Sprint 3):
tts = TextToSpeech(
    speaker_device_name=config.SPEAKER_DEVICE_NAME,
    steam_device_name=config.STEAM_ROUTE_DEVICE_NAME,   # None = disabled
    steam_gain=config.STEAM_ROUTE_GAIN,
)
```

No other changes to `main.py`.

---

### `tests/test_audio_router.py`

```python
"""
AudioRouter unit tests.
No real audio hardware required — tests use mock devices and mathematical verification.
"""

import math
import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from voice.audio_router import resample_audio, _query_native_rate, AudioRouter


# ── resample_audio ────────────────────────────────────────────────────────────

def test_resample_noop_same_rate():
    audio = np.random.rand(24000).astype(np.float32)
    result = resample_audio(audio, 24000, 24000)
    np.testing.assert_array_equal(result, audio)


def test_resample_length_correct_upsample():
    """24000 → 44100 should produce ~1.8375x more samples."""
    audio = np.random.rand(24000).astype(np.float32)
    result = resample_audio(audio, 24000, 44100)
    expected_len = int(round(24000 * 44100 / 24000))  # = 44100
    assert len(result) == expected_len


def test_resample_length_correct_downsample():
    """48000 → 16000 should produce 1/3 the samples."""
    audio = np.random.rand(48000).astype(np.float32)
    result = resample_audio(audio, 48000, 16000)
    assert len(result) == 16000


def test_resample_output_dtype():
    audio = np.random.rand(1000).astype(np.float32)
    result = resample_audio(audio, 24000, 44100)
    assert result.dtype == np.float32


def test_resample_preserves_dc():
    """A constant signal should remain constant after resampling (within tolerance)."""
    audio = np.ones(24000, dtype=np.float32) * 0.5
    result = resample_audio(audio, 24000, 44100)
    # Interior samples should be close to 0.5; ignore edge effects
    interior = result[100:-100]
    assert np.allclose(interior, 0.5, atol=1e-3)


# ── AudioRouter device resolution ────────────────────────────────────────────

def test_resolve_device_returns_none_for_empty():
    from voice.audio_router import _resolve_output_device
    assert _resolve_output_device(None) is None
    assert _resolve_output_device("") is None


@patch("voice.audio_router.sd.query_devices")
def test_resolve_device_matches_fragment(mock_query):
    from voice.audio_router import _resolve_output_device
    mock_query.return_value = [
        {"name": "Realtek Audio", "max_output_channels": 2},
        {"name": "CABLE Input (VB-Audio Virtual Cable)", "max_output_channels": 2},
        {"name": "VK81 Headset", "max_output_channels": 2},
    ]
    assert _resolve_output_device("CABLE Input") == 1
    assert _resolve_output_device("VK81") == 2
    assert _resolve_output_device("nonexistent") is None


# ── AudioRouter.play dual output ─────────────────────────────────────────────

@patch("voice.audio_router.sd.play")
@patch("voice.audio_router._resolve_output_device")
@patch("voice.audio_router._query_native_rate")
def test_play_calls_both_devices(mock_rate, mock_resolve, mock_play):
    mock_resolve.side_effect = [0, 1]   # primary=0, secondary=1
    mock_rate.side_effect    = [24000, 44100]

    router = AudioRouter(primary_device="VK81", secondary_device="CABLE Input")
    audio  = np.random.rand(24000).astype(np.float32)
    router.play(audio, src_rate=24000)

    # sd.play should have been called twice (once per device thread)
    assert mock_play.call_count == 2


@patch("voice.audio_router.sd.play")
@patch("voice.audio_router._resolve_output_device")
@patch("voice.audio_router._query_native_rate")
def test_play_calls_only_primary_when_no_secondary(mock_rate, mock_resolve, mock_play):
    mock_resolve.side_effect = [0, None]  # primary only
    mock_rate.side_effect    = [24000, 44100]

    router = AudioRouter(primary_device="VK81", secondary_device=None)
    router.play(np.random.rand(100).astype(np.float32), src_rate=24000)

    assert mock_play.call_count == 1


@patch("voice.audio_router.sd.play")
@patch("voice.audio_router._resolve_output_device")
@patch("voice.audio_router._query_native_rate")
def test_gain_applied_to_secondary(mock_rate, mock_resolve, mock_play):
    mock_resolve.side_effect = [0, 1]
    mock_rate.side_effect    = [24000, 24000]  # same rate, no resample needed

    router = AudioRouter(
        primary_device="VK81",
        secondary_device="CABLE Input",
        secondary_gain=0.5,
    )
    audio = np.ones(1000, dtype=np.float32) * 0.8
    router.play(audio, src_rate=24000)

    # Second sd.play call's audio should be ~0.4 (0.8 * 0.5)
    secondary_call_audio = mock_play.call_args_list[1][0][0]
    assert np.allclose(secondary_call_audio.mean(), 0.4, atol=0.01)
```

---

## VB-Cable Setup Guide

### 1. Download and install VB-Cable

Download from **https://vb-audio.com/Cable/** (free). Run `VBCABLE_Setup_x64.exe` as Administrator. **A reboot is required** — VB-Cable installs a kernel audio driver.

After reboot, two new audio devices will appear in Windows Sound settings:

- **Playback:** `CABLE Input (VB-Audio Virtual Cable)`
- **Recording:** `CABLE Output (VB-Audio Virtual Cable)`

### 2. Set VB-Cable sample rate

Open Windows Sound settings → Playback → right-click **CABLE Input** → Properties → Advanced. Set the default format to **44100 Hz, 16-bit** (or 48000 Hz if you prefer — just note it in `.env.local` if debugging). Click OK.

Repeat for Recording → **CABLE Output** → same rate.

> **Why this matters:** VB-Cable's internal buffer uses a fixed rate. If Oracle writes at 24000 Hz and VB-Cable expects 44100 Hz without the resampling step, you get chipmunk voices or silence. `AudioRouter` handles this automatically, but the device needs a consistent rate to query.

### 3. Configure Steam

Steam → Settings → Voice → **Microphone** → select **CABLE Output (VB-Audio Virtual Cable)**

This tells Steam to use VB-Cable's output as its microphone input. Whatever Oracle writes to CABLE Input will appear to Steam as a live mic signal.

> **Push-to-talk vs always-on:** For Oracle routing, set Steam voice to **always transmit** on the CABLE Output device. Oracle manages its own gating (it only writes when it has a response). You won't hear dead air because VB-Cable passes silence when Oracle isn't writing.

### 4. Mike's real microphone

Steam only supports one voice input device. For Sprint 3, Oracle's voice occupies the CABLE Output slot. Mike's real microphone should be handled one of two ways:

- **Voicemeeter** (recommended for Sprint 4): Voicemeeter can mix Mike's real mic + Oracle's VB-Cable output into a single virtual input that Steam sees. Sprint 4 covers this.
- **Discord as a secondary channel**: Mike uses Discord for his own voice communications; Oracle broadcasts to Steam. Simple and effective if the team is on Discord anyway.
- **VB-Cable A+B**: VB-Audio offers a free second VB-Cable pair (VB-Cable A+B). One cable for Oracle, one for Mike's mic. Requires a mixer or additional configuration to combine them into Steam.

For Sprint 3, the simplest path is option 2 — Oracle speaks via Steam, Mike speaks via his real mic on a separate channel.

### 5. Enable Oracle routing

Uncomment in `.env.local`:

```env
STEAM_ROUTE_DEVICE_NAME=CABLE Input
```

Start Oracle: `python main.py`

Oracle will log:

```
AudioRouter ready. Primary: device=X @ 44100Hz | Secondary: device=Y @ 44100Hz (gain=1.00)
TTS ready. Voice: bm_fable. Steam routing: enabled.
```

---

## Volume Balancing

Oracle's volume may land differently in headphones vs Steam. Adjust independently:

- **Local headphones**: Windows volume mixer → adjust Oracle's process, or use your headphone hardware volume
- **Steam level**: Set `STEAM_ROUTE_GAIN=0.7` (or similar) in `.env.local` to scale Oracle's Steam output down without affecting local volume. The `AudioRouter` applies the gain only to the secondary (VB-Cable) audio path.

Teammates should hear Oracle at roughly the same volume as a normal in-game voice. If Oracle is too dominant, lower `STEAM_ROUTE_GAIN`. If teammates can't hear it, raise toward `2.0` (clipped to prevent distortion).

---

## Echo / Feedback Risk

Phasmophobia's voice chat is push-to-talk by default, which eliminates loopback. If teammates are on always-on voice, their audio output could contain Oracle's voice playing through their speakers, looping back through their mics, and reaching Oracle's wake word detector.

Mitigations already in place from Sprint 2:

1. `is_speaking` guard in `on_wake()` — ignores wake word during active TTS
2. Whisper `vad_filter` — rejects non-speech energy
3. Garbage filter in `SpeechToText.transcribe()` — rejects hallucination artifacts

If echo remains a problem after Sprint 3 testing, add a post-TTS cooldown window (e.g. 500ms after `is_speaking` drops) before the wake word detector re-arms.

---

## Task Board

### Backlog

|ID|Task|Notes|
|---|---|---|
|S3-01|Create `voice/audio_router.py`|`AudioRouter` class, `resample_audio`, `_resolve_output_device`, `_query_native_rate`|
|S3-02|Update `voice/text_to_speech.py`|Replace `sd.play()` with `self._router.play()`, add `steam_device_name` / `steam_gain` params|
|S3-03|Update `config/settings.py`|Add `STEAM_ROUTE_DEVICE_NAME`, `STEAM_ROUTE_GAIN`|
|S3-04|Update `config/.env.local`|Document VB-Cable setup inline, add new fields commented out|
|S3-05|Update `main.py`|Pass `steam_device_name` + `steam_gain` to `TextToSpeech`|
|S3-06|Write `tests/test_audio_router.py`|Resampling math, device resolution, dual-output mock, gain application|
|S3-07|**[User action]** Install VB-Cable|https://vb-audio.com/Cable/ — requires reboot|
|S3-08|**[User action]** Set VB-Cable sample rate|44100 Hz in Windows Sound → CABLE Input & Output properties|
|S3-09|**[User action]** Configure Steam voice input|Microphone → CABLE Output (VB-Audio Virtual Cable)|
|S3-10|**[User action]** Uncomment `STEAM_ROUTE_DEVICE_NAME=CABLE Input` in `.env.local`||
|S3-11|Run tests|`pytest tests/ -v` — all Sprint 1, 2, 3 tests pass|
|S3-12|Smoke test: local audio unaffected|`python main.py`, confirm Oracle still speaks through headphones|
|S3-13|Smoke test: VB-Cable level|Open Windows volume mixer while Oracle speaks — confirm CABLE Input shows activity|
|S3-14|Smoke test: Steam routing|Start Phasmophobia, enter lobby, confirm teammate hears Oracle|
|S3-15|Smoke test: STEAM_ROUTE_GAIN|Set `STEAM_ROUTE_GAIN=0.5`, confirm local volume unchanged, Steam volume halved|
|S3-16|Smoke test: routing disabled|Clear `STEAM_ROUTE_DEVICE_NAME=`, confirm `steam_enabled=False` logged, no errors|
|S3-17|Echo test|Oracle speaks, confirm wake word does not re-trigger via Steam loopback|
|S3-18|Full session test|Complete Phasmophobia match with Oracle routing enabled — log review|

### Definition of Done (Sprint 3)

- [ ] All `test_audio_router.py` tests pass
- [ ] All Sprint 1 and Sprint 2 tests still pass
- [ ] Oracle audio visible in Windows volume mixer on CABLE Input during speech
- [ ] Teammate confirms Oracle audible in Steam voice chat
- [ ] Local headphone playback unaffected (same volume, no artefacts)
- [ ] `STEAM_ROUTE_DEVICE_NAME` blank → Oracle starts normally, logs `steam routing: disabled`
- [ ] No self-feedback loops detected during full session test
- [ ] `Ctrl+C` exits cleanly

---

## Known Risks

**VB-Cable sample rate mismatch.** If Windows reports CABLE Input's native rate as 48000 Hz but `_query_native_rate()` returns 44100 Hz (or vice versa), Oracle's resampling target will be wrong. Symptom: chipmunk-voice or slowed audio in Steam. Fix: check `sd.query_devices()` output at startup and log `native_rate` clearly so it can be verified against Windows Sound settings.

**`scipy` not in Sprint 1/2 requirements.** `resample_poly` requires `scipy`. Add `scipy` to the pip install line. On some machines `scipy` is large — `resampy` is a lighter alternative with the same API if install size becomes a concern.

**PortAudio WASAPI exclusive mode.** On Windows, some audio devices default to exclusive mode, which means only one application can open them at a time. If sounddevice raises `paUnanticipatedHostError` when opening CABLE Input, open Windows Sound → Playback → CABLE Input → Properties → Advanced and **uncheck "Allow applications to take exclusive control"**.

**`sd.play()` global stream conflict.** `AudioRouter._play_device()` calls `sd.play()` in two threads. `sd.play()` is not thread-safe — it sets a global active stream. Switch to `sd.OutputStream` (context manager) in `_play_device()` if threading conflicts arise during testing. The `sd.OutputStream` API supports per-instance streams with no global state.

**Reboot requirement for VB-Cable.** VB-Cable installs a kernel driver; a reboot is mandatory. If Oracle fails to find the device after installation but before reboot, it will log a warning and continue with local-only output. Sprint 3 smoke tests cannot be completed until after the reboot.

**VB-Cable override.** Steam Chat only allows a single input device to stream audio to the voice chat, so Sprint 3 will replace the player's mic input with the VB-Cable stream. To fix this, and allow both the player and the Oracle to be heard in Voice Chat, The fix is **Voicemeeter Banana** (free, also from VB-Audio — same company as VB-Cable). It's a virtual audio mixer that sits between your devices and Steam, combining both sources into one virtual output Steam can use. Oracle skips VB-Cable entirely in this setup and writes directly to **Voicemeeter Input (VAIO)**, which Voicemeeter treats as a software audio source. Your real mic goes into Voicemeeter Hardware Input 1. Both get routed to the B1 bus, which appears as a single recording device ("VB-Audio Voicemeeter Output") that Steam sees as its microphone. Teammates hear both of you.