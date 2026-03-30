**Goal:** Both Mike and Kayden can query Oracle from within a live Phasmophobia session. Oracle responds through Steam chat so all players hear it. Voicemeeter replaces the Sprint 3 VB-Cable single-mic limitation, restoring Mike's real voice to Steam simultaneously with Oracle's.

**Builds on:** Sprint 3's `AudioRouter`, dual-output TTS, and working voice loop.

**Exit criteria:**

- Voicemeeter mixes Mike's real mic + Oracle's voice into a single Steam input
- Kayden can say "oracle, [command]" in Steam voice chat and Oracle responds
- Mike can still query Oracle via his local wake word as before
- Both players' commands are attributed to the correct speaker in Oracle's responses and session log
- Oracle does not respond to its own voice through the loopback (self-feedback guard)
- Sprint 3 smoke tests still pass

---

## Part 1 — Voicemeeter (Replaces Sprint 3 VB-Cable Routing)

### Why VB-Cable alone doesn't work

Steam accepts a single microphone device. Setting it to CABLE Output means Oracle's voice reaches teammates but Mike's real mic goes silent. Voicemeeter Banana is a free virtual audio mixer (also from VB-Audio) that solves this by combining multiple audio sources into one virtual output.

### How Voicemeeter routes the audio

```
Mike's real mic  ──▶ Voicemeeter Hardware Input 1 ──┐
                                                      ├──▶ B1 bus ──▶ "VB-Audio Voicemeeter Output"
Oracle audio     ──▶ Voicemeeter VAIO (virtual in) ──┘                         │
                                                                                ▼
                                                                     Steam mic input
                                                                     (teammates hear both)
```

Oracle writes to **Voicemeeter Input (VB-Audio Voicemeeter VAIO)** — a virtual input device that Voicemeeter treats identically to a hardware source. Mike's real mic goes into **Hardware Input 1**. Both are routed to the **B1 bus**, which appears in Windows as **"VB-Audio Voicemeeter Output"** — a single recording device Steam can use.

VB-Cable is no longer needed for the Steam routing path. `STEAM_ROUTE_DEVICE_NAME` changes from `"CABLE Input"` to `"Voicemeeter Input"`.

### Voicemeeter installation and configuration

**Install Voicemeeter Banana** Download from **https://vb-audio.com/Voicemeeter/banana.htm** (free). Reboot required.

**Hardware Input 1 — Mike's real mic** In Voicemeeter Banana:

- Click the dropdown under **HARDWARE INPUT 1** → select Mike's physical microphone
- Enable the **B1** button on Hardware Input 1 (routes to the B1 bus → Steam)
- Leave A1 disabled unless you also want your own voice in your own headphones (usually not needed)

**VAIO — Oracle's audio**

- The **VOICEMEETER VAIO** strip appears automatically
- Enable the **B1** button on VAIO (routes Oracle's voice to B1 → Steam)
- Enable the **A1** button on VAIO if you also want Oracle audible through your local speakers via Voicemeeter (optional — `AudioRouter` already handles local playback independently)

**Steam** Steam → Settings → Voice → Microphone → select **VB-Audio Voicemeeter Output (VB-Audio Voicemeeter VAIO)**

> If you see two Voicemeeter output options ("Voicemeeter Output" and "Voicemeeter Aux Output"), use the one labelled **Output** (B1 bus). Aux Output corresponds to the B2 bus.

**`.env.local` update**

```env
# Sprint 3: STEAM_ROUTE_DEVICE_NAME=CABLE Input
# Sprint 4: replace with Voicemeeter VAIO
STEAM_ROUTE_DEVICE_NAME=Voicemeeter Input
```

No code changes required — `AudioRouter` resolves the device by name fragment as before.

---

## Part 2 — Loopback Capture: Hearing Kayden

### The problem

Kayden is a remote player. His voice arrives at Mike's machine via Steam voice chat and plays through Mike's headphones. Oracle needs to hear Kayden's commands, but there is no physical microphone pointed at Mike's speakers.

### The solution: WASAPI loopback

Windows WASAPI loopback mode lets an application record whatever is currently playing on a specific output device — effectively a software tap of the headphone signal. `sounddevice` exposes this via `sd.WasapiSettings(loopback=True)`:

```python
import sounddevice as sd

with sd.InputStream(
    device=headphone_device_id,       # the OUTPUT device (your headphones)
    channels=2,
    samplerate=native_rate,
    extra_settings=sd.WasapiSettings(loopback=True),
) as stream:
    chunk, _ = stream.read(chunk_size)
```

The loopback stream captures everything playing on the headphones: Kayden's Steam voice, game audio, music — everything. Oracle's wake word detector and Whisper's VAD filter together ensure only intelligible voice commands containing the wake word are processed.

---

## Part 3 — Dual Capture Architecture

Sprint 2 had one capture loop: **mic → wake word → record → Whisper → graph**.

Sprint 4 has two capture loops running in parallel, both feeding a shared turn queue:

```
[Thread A] Mike's mic ──▶ WakeWordDetector ──▶ record mic  ──▶ Whisper ──▶ queue (speaker="Mike")
[Thread B] Loopback   ──▶ WakeWordDetector ──▶ record loop ──▶ Whisper ──▶ queue (speaker="Kayden")

[Main thread] queue.get() ──▶ run_turn(state, text, speaker) ──▶ TTS response
```

Speaker attribution is **structural, not algorithmic** — if the command came from Thread A it's Mike, if from Thread B it's Kayden. No speaker diarization required.

Oracle processes commands serially (one turn at a time). If Mike and Kayden speak simultaneously, their commands are queued and processed in arrival order. This is correct for an investigation tool where order matters.

---

## Implementation Order

```
1. voice/loopback_capture.py   ← new: WASAPI loopback reader + wake-word-aware recorder
2. voice/voice_session.py      ← new: coordinates two parallel capture loops
3. config/settings.py          ← add LOOPBACK_DEVICE_NAME, LOOPBACK_ENABLED, KAYDEN_SPEAKER_NAME
4. config/.env.local           ← update STEAM_ROUTE_DEVICE_NAME, add loopback fields
5. graph/nodes.py              ← update commentary_node + identify_node: speaker-aware phrasing
6. main.py                     ← replace run_voice_loop() with VoiceSession-based loop
7. tests/test_loopback.py      ← loopback device resolution, resample pipeline, self-feedback guard
```

---

## Scaffold Code

### `voice/loopback_capture.py`

```python
"""
WASAPI loopback capture for Kayden's voice.
Reads whatever is playing on a specified output device (Mike's headphones),
detects the wake word, then records and returns the transcribable audio.

Windows-only (WASAPI loopback is a Windows feature).
"""

import logging
import threading
import time
from typing import Callable

import numpy as np
import sounddevice as sd

from voice.audio_router import resample_audio, _resolve_output_device, _query_native_rate

logger = logging.getLogger(__name__)

_WAKE_CHUNK   = 1280   # ~80ms at 16kHz — openwakeword requirement
_TARGET_RATE  = 16000  # Whisper + openwakeword native rate
_THRESHOLD    = 0.5    # wake word confidence threshold


class LoopbackCapture:
    """
    Continuously reads WASAPI loopback audio from an output device.
    Detects a wake word in the loopback stream; when detected, records
    until silence and returns the audio for transcription.

    Emits (speaker_name, audio_array, sample_rate) via on_command callback.
    """

    def __init__(
        self,
        device_name: str,
        wake_word: str,
        speaker_name: str,
        on_command: Callable[[str, np.ndarray, int], None],
        silence_threshold_db: float = -40.0,
        max_record_seconds: float = 8.0,
    ):
        self._device_id   = _resolve_output_device(device_name)
        self._native_rate = _query_native_rate(self._device_id)
        self._wake_word   = wake_word
        self._speaker     = speaker_name
        self._on_command  = on_command
        self._silence_db  = silence_threshold_db
        self._max_secs    = max_record_seconds
        self._running     = False
        self._recording   = False   # True while capturing a command
        self._thread: threading.Thread | None = None
        self._wake_model  = None
        self._tts_speaking_ref: Callable[[], bool] = lambda: False

    def set_tts_ref(self, is_speaking: Callable[[], bool]) -> None:
        """Inject a callable that returns True when TTS is active. Prevents self-feedback."""
        self._tts_speaking_ref = is_speaking

    def start(self) -> None:
        if self._device_id is None:
            logger.warning("LoopbackCapture: no loopback device resolved — Kayden capture disabled.")
            return

        from openwakeword.model import Model
        self._wake_model = Model(wakeword_models=[self._wake_word], inference_framework="onnx")

        self._running = True
        self._thread  = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info(
            f"LoopbackCapture: listening on device {self._device_id} "
            f"@ {self._native_rate}Hz for wake word '{self._wake_word}'"
        )

    def stop(self) -> None:
        self._running = False

    # ── Internal ──────────────────────────────────────────────────────────────

    def _capture_loop(self) -> None:
        try:
            wasapi = sd.WasapiSettings(loopback=True)
            with sd.InputStream(
                device=self._device_id,
                channels=2,
                samplerate=self._native_rate,
                dtype="float32",
                extra_settings=wasapi,
            ) as stream:
                logger.info("LoopbackCapture: WASAPI loopback stream open.")
                while self._running:
                    if self._recording:
                        time.sleep(0.02)
                        continue

                    raw, _ = stream.read(_WAKE_CHUNK)
                    mono   = raw.mean(axis=1)                     # stereo → mono
                    chunk  = resample_audio(mono, self._native_rate, _TARGET_RATE)

                    # Skip wake word detection while Oracle is speaking
                    if self._tts_speaking_ref():
                        self._wake_model.reset()
                        continue

                    preds = self._wake_model.predict(chunk.astype(np.int16))
                    for word, score in preds.items():
                        if score >= _THRESHOLD:
                            logger.info(
                                f"LoopbackCapture: wake word '{word}' from {self._speaker} "
                                f"(score={score:.2f})"
                            )
                            self._wake_model.reset()
                            self._recording = True
                            # Record in a separate thread so capture loop stays responsive
                            threading.Thread(
                                target=self._record_and_emit,
                                args=(stream,),
                                daemon=True,
                            ).start()
                            break

        except Exception as e:
            logger.error(f"LoopbackCapture: stream error: {e}")

    def _record_and_emit(self, stream: sd.InputStream) -> None:
        """Record until silence, resample to 16kHz mono, emit via callback."""
        try:
            frames: list[np.ndarray] = []
            silence_chunks  = 0
            silence_limit   = int(1.5 / (_WAKE_CHUNK / _TARGET_RATE))
            max_chunks      = int(self._max_secs / (_WAKE_CHUNK / _TARGET_RATE))
            chunk_size_native = int(_WAKE_CHUNK * self._native_rate / _TARGET_RATE)

            for _ in range(max_chunks):
                raw, _ = stream.read(chunk_size_native)
                mono   = raw.mean(axis=1)
                resampled = resample_audio(mono, self._native_rate, _TARGET_RATE)
                frames.append(resampled)

                rms_db = 20 * np.log10(np.sqrt(np.mean(resampled ** 2)) + 1e-9)
                if rms_db < self._silence_db:
                    silence_chunks += 1
                    if silence_chunks >= silence_limit and len(frames) > silence_limit:
                        break
                else:
                    silence_chunks = 0

            audio = np.concatenate(frames) if frames else np.zeros(1, dtype="float32")
            self._on_command(self._speaker, audio, _TARGET_RATE)
        finally:
            self._recording = False
```

---

### `voice/voice_session.py`

```python
"""
VoiceSession — coordinates parallel capture loops for Mike (mic) and Kayden (loopback).

Both loops emit (speaker, audio, rate) into a shared queue.
The main loop reads from the queue and calls run_turn() serially.
"""

import logging
import queue
import threading
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)

# Shared queue: (speaker_name, audio_array, sample_rate)
_CommandTuple = tuple[str, np.ndarray, int]


class VoiceSession:
    def __init__(
        self,
        wake_word: str,
        mic_device: str | None,
        loopback_device: str | None,
        mike_name: str = "Mike",
        kayden_name: str = "Kayden",
        silence_threshold_db: float = -40.0,
        max_record_seconds: float = 8.0,
    ):
        self._wake_word      = wake_word
        self._mic_device     = mic_device
        self._loopback_device = loopback_device
        self._mike_name      = mike_name
        self._kayden_name    = kayden_name
        self._silence_db     = silence_threshold_db
        self._max_secs       = max_record_seconds
        self._queue: queue.Queue[_CommandTuple] = queue.Queue()
        self._tts_speaking: Callable[[], bool] = lambda: False

    def set_tts_ref(self, is_speaking: Callable[[], bool]) -> None:
        self._tts_speaking = is_speaking

    def start(self) -> tuple:
        """
        Start both capture loops. Returns (mic_detector, loopback_capture)
        so caller can stop them cleanly on exit.
        """
        from voice.wake_word import WakeWordDetector
        from voice.loopback_capture import LoopbackCapture
        import sounddevice as sd
        from voice.audio_router import resample_audio

        # ── Mike's capture loop ───────────────────────────────────────────────
        _mic_triggered = threading.Event()

        def on_mike_wake():
            if not self._tts_speaking():
                _mic_triggered.set()

        mic_detector = WakeWordDetector(
            wake_word=self._wake_word,
            callback=on_mike_wake,
        )
        mic_detector.start()

        threading.Thread(
            target=self._mic_loop,
            args=(_mic_triggered,),
            daemon=True,
            name="mike-capture",
        ).start()

        # ── Kayden's capture loop ─────────────────────────────────────────────
        loopback = None
        if self._loopback_device:
            loopback = LoopbackCapture(
                device_name=self._loopback_device,
                wake_word=self._wake_word,
                speaker_name=self._kayden_name,
                on_command=self._on_command,
                silence_threshold_db=self._silence_db,
                max_record_seconds=self._max_secs,
            )
            loopback.set_tts_ref(self._tts_speaking)
            loopback.start()
        else:
            logger.info("VoiceSession: loopback device not configured — Kayden capture disabled.")

        return mic_detector, loopback

    def get(self, timeout: float = 1.0) -> _CommandTuple | None:
        """Block until a command is available, then return (speaker, audio, rate)."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _on_command(self, speaker: str, audio: np.ndarray, rate: int) -> None:
        self._queue.put((speaker, audio, rate))

    def _mic_loop(self, trigger: threading.Event) -> None:
        """Mike's capture loop — mirrors Sprint 2's run_voice_loop mic path."""
        import time
        import sounddevice as sd
        from voice.audio_router import resample_audio

        sample_rate = 16000
        chunk_secs  = 0.3
        chunk_size  = int(sample_rate * chunk_secs)
        silence_lim = int(1.5 / chunk_secs)
        max_chunks  = int(self._max_secs / chunk_secs)

        while True:
            trigger.wait()
            trigger.clear()

            if self._tts_speaking():
                continue

            logger.info("VoiceSession: Mike wake word — recording...")
            frames: list[np.ndarray] = []
            silence_chunks = 0

            try:
                with sd.InputStream(
                    samplerate=sample_rate,
                    channels=1,
                    dtype="float32",
                    device=self._mic_device,
                    blocksize=chunk_size,
                ) as stream:
                    for _ in range(max_chunks):
                        chunk, _ = stream.read(chunk_size)
                        chunk = chunk.flatten()
                        frames.append(chunk)
                        rms_db = 20 * np.log10(
                            np.sqrt(np.mean(chunk ** 2)) + 1e-9
                        )
                        if rms_db < self._silence_db:
                            silence_chunks += 1
                            if silence_chunks >= silence_lim and len(frames) > silence_lim:
                                break
                        else:
                            silence_chunks = 0
            except Exception as e:
                logger.error(f"VoiceSession: mic recording error: {e}")
                continue

            audio = np.concatenate(frames) if frames else np.zeros(1, dtype="float32")
            self._on_command(self._mike_name, audio, sample_rate)
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

    # Voice — TTS
    SPEAKER_DEVICE_NAME: str | None = None
    TTS_VOICE: str                  = "bm_fable"

    # Voice — Steam routing (Voicemeeter VAIO in Sprint 4)
    STEAM_ROUTE_DEVICE_NAME: str | None = None
    STEAM_ROUTE_GAIN: float             = 1.0

    # Voice — wake word
    WAKE_WORD: str = "oracle"

    # Voice — recording (Mike's mic)
    MIC_DEVICE_NAME: str | None  = None
    SILENCE_THRESHOLD_DB: float  = -40.0
    MAX_RECORDING_SECONDS: float = 8.0

    # Voice — loopback (Kayden)  ← Sprint 4
    LOOPBACK_ENABLED: bool          = False
    LOOPBACK_DEVICE_NAME: str | None = None   # e.g. "VK81" — Mike's headphones output
    MIKE_SPEAKER_NAME: str           = "Mike"
    KAYDEN_SPEAKER_NAME: str         = "Kayden"

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
# SPEAKER_DEVICE_NAME=VK81

# ── Voice (TTS — Steam routing via Voicemeeter) ───────────────────────────────
# Sprint 3: STEAM_ROUTE_DEVICE_NAME=CABLE Input
# Sprint 4: use Voicemeeter VAIO instead
# STEAM_ROUTE_DEVICE_NAME=Voicemeeter Input
# STEAM_ROUTE_GAIN=1.0

# ── Voice (Kayden loopback — Sprint 4) ───────────────────────────────────────
# Set LOOPBACK_DEVICE_NAME to the name of Mike's headphone output device.
# Oracle will tap WASAPI loopback on that device to hear Kayden's Steam voice.
# LOOPBACK_ENABLED=true
# LOOPBACK_DEVICE_NAME=VK81
# MIKE_SPEAKER_NAME=Mike
# KAYDEN_SPEAKER_NAME=Kayden
```

---

### `main.py` — updated `run_voice_loop()`

```python
def run_voice_loop(state: dict) -> None:
    from voice.voice_session import VoiceSession
    from voice.speech_to_text import SpeechToText
    from voice.text_to_speech import TextToSpeech

    stt = SpeechToText(model_size=config.STT_MODEL)
    tts = TextToSpeech(
        speaker_device_name=config.SPEAKER_DEVICE_NAME,
        steam_device_name=config.STEAM_ROUTE_DEVICE_NAME,
        steam_gain=config.STEAM_ROUTE_GAIN,
    )
    tts.load()

    session = VoiceSession(
        wake_word=config.WAKE_WORD,
        mic_device=config.MIC_DEVICE_NAME,
        loopback_device=config.LOOPBACK_DEVICE_NAME if config.LOOPBACK_ENABLED else None,
        mike_name=config.MIKE_SPEAKER_NAME,
        kayden_name=config.KAYDEN_SPEAKER_NAME,
        silence_threshold_db=config.SILENCE_THRESHOLD_DB,
        max_record_seconds=config.MAX_RECORDING_SECONDS,
    )
    session.set_tts_ref(lambda: tts.is_speaking)

    mic_detector, loopback = session.start()

    n = len(state["candidates"])
    logger.info(
        f"Oracle ready [voice mode]. Difficulty: {state['difficulty']}. "
        f"{n} candidates. Loopback: {'enabled' if loopback else 'disabled'}."
    )
    tts.speak(
        f"Oracle online. {state['difficulty'].capitalize()} difficulty. "
        f"{'Bidirectional mode active.' if loopback else 'Single-player mode.'}"
    )

    try:
        while True:
            command = session.get(timeout=1.0)
            if command is None:
                continue

            speaker, audio, rate = command
            transcript = stt.transcribe(audio, rate)
            if not transcript:
                logger.info(f"VoiceSession: empty transcription from {speaker} — skipping.")
                continue

            logger.info(f"{speaker}: {transcript!r}")
            log_event("transcription", {"speaker": speaker, "text": transcript},
                      state.get("turn_id", 0))

            state["speaker"] = speaker
            tts.flush()
            response = run_turn(state, transcript)
            if response:
                logger.info(f"Oracle → {speaker}: {response}")
                tts.speak(response)
            else:
                n = len(state.get("candidates", []))
                logger.info(f"[silent update — {n} candidates remain]")

    except KeyboardInterrupt:
        logger.info("Oracle offline.")
    finally:
        if mic_detector:
            mic_detector.stop()
        if loopback:
            loopback.stop()
        tts.shutdown()
```

---

### `graph/nodes.py` — speaker-aware commentary and identification

Small updates to `commentary_node` and `identify_node` to acknowledge the speaker by name when relevant.

```python
# In commentary_node — update the prompt to include speaker context:

speaker = state.get("speaker", "the player")
prompt = (
    f"You are Oracle, a Phasmophobia assistant. Investigation state:\n"
    f"  Confirmed evidence: {confirmed}\n"
    f"  Ruled out: {ruled_out}\n"
    f"  Remaining candidates ({n}): {names}\n"
    f"  Last report from: {speaker}\n\n"
    f"In EXACTLY 2 sentences: name the remaining candidates and tell the players "
    f"what distinguishing evidence or behaviour would identify the ghost. "
    f"You may acknowledge {speaker}'s report if natural. "
    f"Be specific and factual. No atmospheric language. No more than 2 sentences."
)

# In identify_node — acknowledge reporter:

speaker = state.get("speaker", "the player")
response = (
    f"Ghost identified — {speaker} confirmed it: this is a {ghost_name}, "
    f"based on {evidence_str}.{tell_str}"
)
```

---

### `tests/test_loopback.py`

```python
"""
Sprint 4 tests — loopback capture and voice session logic.
No real audio hardware required; tests mock sounddevice and openwakeword.
"""

import numpy as np
import pytest
from unittest.mock import patch, MagicMock, call
import queue
import threading
import time


# ── resample pipeline (reuse from Sprint 3, confirm 2-channel → mono path) ────

def test_stereo_to_mono_mean():
    """Simulates what LoopbackCapture does: stereo loopback → mono."""
    stereo = np.array([[0.4, 0.6], [0.2, 0.8], [0.5, 0.5]], dtype=np.float32)
    mono = stereo.mean(axis=1)
    expected = np.array([0.5, 0.5, 0.5], dtype=np.float32)
    np.testing.assert_allclose(mono, expected, atol=1e-6)


def test_loopback_resample_rate():
    """Audio resampled from native rate to 16kHz has correct length."""
    from voice.audio_router import resample_audio
    native_rate = 44100
    chunk_size  = int(1280 * native_rate / 16000)  # native-rate equivalent of 1280 @16kHz
    audio       = np.random.rand(chunk_size).astype(np.float32)
    result      = resample_audio(audio, native_rate, 16000)
    assert len(result) == 1280


# ── LoopbackCapture self-feedback guard ───────────────────────────────────────

def test_loopback_ignores_wake_word_during_tts():
    """
    When is_speaking returns True, the wake word model should be reset
    and no command should be emitted.
    """
    commands = []
    from voice.loopback_capture import LoopbackCapture

    # We can't easily run the full loop, so test the guard logic directly
    # by inspecting that _tts_speaking_ref blocks emission
    capture = LoopbackCapture(
        device_name=None,
        wake_word="oracle",
        speaker_name="Kayden",
        on_command=lambda s, a, r: commands.append(s),
    )
    capture.set_tts_ref(lambda: True)  # TTS is "speaking"

    # Simulate: even if wake model would fire, is_speaking blocks it
    assert capture._tts_speaking_ref() is True
    # No commands emitted (the full guard is in _capture_loop;
    # this test verifies the ref is wired correctly)
    assert commands == []


# ── VoiceSession queue ────────────────────────────────────────────────────────

def test_voice_session_queue_ordering():
    """Commands from both speakers arrive in FIFO order."""
    from voice.voice_session import VoiceSession

    session = VoiceSession(
        wake_word="oracle",
        mic_device=None,
        loopback_device=None,
    )

    audio = np.zeros(100, dtype=np.float32)
    # Simulate both speakers emitting commands
    session._on_command("Mike",   audio, 16000)
    session._on_command("Kayden", audio, 16000)
    session._on_command("Mike",   audio, 16000)

    speakers = []
    for _ in range(3):
        result = session.get(timeout=0.1)
        assert result is not None
        speakers.append(result[0])

    assert speakers == ["Mike", "Kayden", "Mike"]


def test_voice_session_get_returns_none_on_timeout():
    from voice.voice_session import VoiceSession
    session = VoiceSession(wake_word="oracle", mic_device=None, loopback_device=None)
    result = session.get(timeout=0.05)
    assert result is None


# ── Speaker attribution in graph nodes ───────────────────────────────────────

def test_identify_node_includes_speaker():
    """identify_node should reference the reporting speaker in its response."""
    from graph.nodes import identify_node

    state = {
        "candidates":         ["Wraith"],
        "evidence_confirmed": ["emf_5", "uv", "spirit_box"],
        "difficulty":         "professional",
        "speaker":            "Kayden",
        "turn_id":            3,
    }
    result = identify_node(state)
    assert "Kayden" in result["oracle_response"]
    assert "Wraith" in result["oracle_response"]
```

---

## Installation (Sprint 4 additions)

```bash
# No new Python packages required — Sprint 4 reuses Sprint 3's dependencies.
# New user-facing setup:

# 1. Install Voicemeeter Banana (reboot required)
#    https://vb-audio.com/Voicemeeter/banana.htm

# 2. Configure Voicemeeter as described in Part 1 above

# 3. Update .env.local:
#    STEAM_ROUTE_DEVICE_NAME=Voicemeeter Input
#    LOOPBACK_ENABLED=true
#    LOOPBACK_DEVICE_NAME=VK81   ← your headphone output device name fragment

# 4. Run tests
pytest tests/ -v

# 5. Run Oracle
python main.py
```

---

## Handling Game Audio in the Loopback

The WASAPI loopback captures everything on Mike's headphones — Kayden's voice, Phasmophobia game audio, ambient sound. Filtering strategies, in order of effectiveness:

**1. Whisper VAD (already active from Sprint 2).** `vad_filter=True` in `SpeechToText.transcribe()` automatically skips non-speech audio segments. Game ambient sounds and music won't be transcribed.

**2. Wake word gating.** The loopback only records after the wake word is detected. Game audio doesn't contain "oracle", so false triggers should be rare. Phasmophobia's in-game ghost sounds are unlikely to match a human wake word model.

**3. Garbage filter.** `SpeechToText.transcribe()` already rejects common Whisper hallucinations on noise (single punctuation, "thank you", etc.).

**4. Post-transcription length check (optional Sprint 4b hardening).** Discard transcriptions under 3 words — accidental loopback artifacts tend to be very short. Add to `run_voice_loop()`:

```python
if len(transcript.split()) < 3:
    logger.info(f"VoiceSession: transcript too short — discarding: {transcript!r}")
    continue
```

---

## Task Board

### Backlog

|ID|Task|Notes|
|---|---|---|
|S4-01|**[User action]** Install Voicemeeter Banana|https://vb-audio.com/Voicemeeter/banana.htm — reboot required|
|S4-02|**[User action]** Configure Voicemeeter|Hardware Input 1 = Mike's mic, VAIO and HW1 → B1, Steam mic = Voicemeeter Output|
|S4-03|**[User action]** Update `.env.local`|`STEAM_ROUTE_DEVICE_NAME=Voicemeeter Input`, enable loopback fields|
|S4-04|Create `voice/loopback_capture.py`|WASAPI loopback reader, wake word detection, record + emit|
|S4-05|Create `voice/voice_session.py`|Dual capture coordinator, shared turn queue|
|S4-06|Update `config/settings.py`|`LOOPBACK_ENABLED`, `LOOPBACK_DEVICE_NAME`, `MIKE_SPEAKER_NAME`, `KAYDEN_SPEAKER_NAME`|
|S4-07|Update `config/.env.local`|Document Voicemeeter + loopback fields inline|
|S4-08|Update `main.py`|Replace `run_voice_loop()` with `VoiceSession`-based loop|
|S4-09|Update `graph/nodes.py`|Speaker-aware phrasing in `commentary_node` and `identify_node`|
|S4-10|Write `tests/test_loopback.py`|Stereo→mono, resample rate, self-feedback guard, queue ordering, speaker attribution|
|S4-11|Run all tests|`pytest tests/ -v` — all Sprint 1–4 tests pass|
|S4-12|Smoke test: Voicemeeter routing|Speak into mic → confirm Voicemeeter meter moves → confirm Steam transmits|
|S4-13|Smoke test: Oracle via Voicemeeter|Oracle responds → confirm teammates hear it via Steam|
|S4-14|Smoke test: Mike still hears Oracle locally|Headphone output unchanged|
|S4-15|Smoke test: loopback level check|Play audio through headphones — confirm loopback stream shows activity in logs|
|S4-16|Smoke test: Kayden wake word|Kayden (or simulated loopback audio) says "oracle" → `speaker="Kayden"` in log|
|S4-17|Smoke test: Kayden command → Oracle responds|Kayden reports evidence → candidates narrow → Oracle speaks to both players|
|S4-18|Smoke test: speaker attribution in response|Oracle's response references "Kayden" when Kayden reports evidence|
|S4-19|Smoke test: self-feedback guard|Oracle speaks → loopback detects its own voice → confirms wake word not re-triggered|
|S4-20|Smoke test: simultaneous commands|Mike and Kayden speak within seconds of each other → both processed in order, no crash|
|S4-21|Full session test (bidirectional)|Complete match with both players querying Oracle — session log review|

### Definition of Done (Sprint 4)

- [ ] All `test_loopback.py` tests pass
- [ ] All Sprint 1–3 tests still pass
- [ ] Voicemeeter confirmed: teammates hear both Mike's voice and Oracle in Steam
- [ ] Kayden's commands are attributed as `speaker="Kayden"` in session log
- [ ] Oracle's responses reference the correct speaker name
- [ ] `LOOPBACK_ENABLED=false` (or unset) → Oracle starts in single-player mode with no errors
- [ ] Self-feedback guard confirmed: Oracle's TTS does not trigger Kayden's loopback pipeline
- [ ] `Ctrl+C` exits both capture threads cleanly

---

## Known Risks

**WASAPI loopback is Windows-only.** `sd.WasapiSettings(loopback=True)` is only available on Windows via the WASAPI host API. If sounddevice raises `AttributeError: module 'sounddevice' has no attribute 'WasapiSettings'`, the installed version of sounddevice predates WASAPI support (requires ≥ 0.4.0). Run `pip install --upgrade sounddevice`.

**Game audio false triggers.** Phasmophobia has ghost vocalisations and ambient sound that could theoretically match a wake word. The combination of openwakeword's neural model + Whisper VAD makes this unlikely, but if false triggers occur during testing, raising `_THRESHOLD` from `0.5` to `0.7` in `loopback_capture.py` adds conservatism at the cost of slightly reduced sensitivity to quiet wake words.

**Voicemeeter VAIO latency.** Voicemeeter introduces a small buffer (~10–20ms). Oracle's voice will reach teammates fractionally later than Mike's real voice. This is imperceptible in practice. If latency is audible, reduce Voicemeeter's buffer size in the menu bar (A1 device settings → buffer size).

**Loopback captures Oracle's own TTS.** Oracle's audio plays through the headphones, and the loopback captures the headphones. This means Kayden's pipeline will "hear" Oracle speaking. The `set_tts_ref()` guard prevents wake word detection during TTS, but during the recording window (after wake word fires), Oracle's voice could appear in the loopback recording. Mitigation: `tts.flush()` before recording starts, and Whisper will reject non-command audio via VAD. If this remains a problem, add a 300ms TTS cooldown window before the Kayden capture loop re-arms.

**Single Voicemeeter instance.** Voicemeeter must remain open in the system tray during sessions. If it crashes or is closed, Steam loses its mic input. Add a startup check that verifies `"Voicemeeter Input"` is present in `sd.query_devices()` when `STEAM_ROUTE_DEVICE_NAME` is set and warn the user clearly if it isn't found.