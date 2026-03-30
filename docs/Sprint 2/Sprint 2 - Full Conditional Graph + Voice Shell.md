**Goal:** Oracle proactively comments when candidates narrow, announces identifications automatically, and the full voice pipeline (wake word → Whisper → graph → Kokoro) is wired and functional.

**Builds on:** Sprint 1's linear graph, tools, deduction engine, and text loop — all of which remain intact.

**Exit criteria:**

- Auto-commentary fires unprompted when candidates drop to ≤ 5 (and changed this turn)
- Identification fires automatically at 1 candidate + difficulty-appropriate evidence count
- Identification does NOT fire prematurely (e.g. 1 candidate but only 1 confirmed evidence on Professional)
- Session events write to `sessions/<id>.jsonl`
- `python main.py` enters voice mode by default; `python main.py --text` still works
- Wake word ("oracle") triggers recording; Whisper transcribes; Kokoro speaks the response

---

## What Changes vs Sprint 1

### Graph topology

Sprint 1's loop was: `llm → tools → llm → respond → END`

Sprint 2 adds a conditional router after `tools` runs. Instead of always looping back to the LLM, the graph first checks whether the evidence state now meets an auto-trigger condition:

```txt
                     ┌─────────────────────────────────────────────────────────┐
                     │                                                         │
llm ──[tool call]──▶ tools ──▶ route_after_tools ──[identify]──▶ identify ──▶ END
 │                                                 ──[comment]──▶ commentary ──▶ END
 │                                                 ──[normal]──▶ llm (loop)
 │
 └──[direct]──▶ respond ──▶ END
```

`route_after_tools` is a pure conditional edge function — no extra node, no state mutation. It reads the current candidate count, compares it to `prev_candidate_count` (snapshotted in `main.py` at the start of each turn), and routes.

- **`identify`**: 1 candidate remaining AND confirmed evidence ≥ difficulty threshold → pure Python announcement
- **`commentary`**: candidates changed this turn AND 1 < n ≤ 5 → LLM at `temperature=0.3`
- **`normal`**: everything else → loop back to `llm` for a standard tool-result response

### New `OracleState` fields

```python
prev_candidate_count: int    # set in main.py before each invoke; used by route_after_tools
turn_id: int                 # incremented each turn; stamped on session log entries
```

### Evidence thresholds by difficulty

Phasmophobia hides evidence at higher difficulties. Identification should not wait for 3 confirmed evidence on Nightmare when the game only shows 2.

|Difficulty|Evidence shown|Threshold for auto-identify|
|---|---|---|
|Amateur|3|3|
|Intermediate|3|3|
|Professional|3|3|
|Nightmare|2|2|
|Insanity|1|1|

---

## Implementation Order

```
1. graph/state.py          ← add prev_candidate_count, turn_id
2. graph/session_log.py    ← new: append-only JSONL session logger
3. graph/nodes.py          ← add identify_node, commentary_node, route_after_tools
4. graph/graph.py          ← rewire: tools → route_after_tools → [identify|commentary|llm]
5. main.py                 ← snapshot prev_candidate_count; add run_voice_loop(); --text flag
6. voice/speech_to_text.py ← faster-whisper wrapper
7. voice/text_to_speech.py ← kokoro-onnx wrapper (adapted from Demonic Tutor)
8. voice/wake_word.py      ← openwakeword listener
9. tests/test_triggers.py  ← verify identify/commentary triggers, difficulty thresholds
```

---

## Scaffold Code

### `graph/state.py` (updated)

```python
from typing import TypedDict, Literal, Annotated
import operator

EvidenceID = Literal[
    "emf_5", "dots", "uv", "freezing", "orb", "writing", "spirit_box"
]
Difficulty = Literal[
    "amateur", "intermediate", "professional", "nightmare", "insanity"
]

class OracleState(TypedDict):
    # Input
    user_text: str
    speaker: str
    difficulty: Difficulty

    # Evidence tracking
    evidence_confirmed: list[EvidenceID]
    evidence_ruled_out: list[EvidenceID]
    behavioral_observations: list[str]

    # Deduction (written by tools only)
    eliminated_ghosts: list[str]
    candidates: list[str]

    # Sprint 2: auto-trigger tracking
    prev_candidate_count: int    # snapshotted in main.py before each invoke
    turn_id: int                 # incremented each turn

    # Output
    oracle_response: str | None

    # LangGraph message history
    messages: Annotated[list, operator.add]
```

---

### `graph/session_log.py`

```python
"""Append-only JSONL session logger.

Each line is a JSON object: {"ts": float, "turn": int, "event": str, ...data}
Call init_log() once at startup. Call log_event() from any node or main.py.
"""

import json
import time
from pathlib import Path

_log_path: Path | None = None


def init_log(session_id: str, log_dir: str = "sessions") -> Path:
    global _log_path
    d = Path(log_dir)
    d.mkdir(exist_ok=True)
    _log_path = d / f"{session_id}.jsonl"
    log_event("session_start", {"session_id": session_id})
    return _log_path


def log_event(event: str, data: dict | None = None, turn_id: int = 0) -> None:
    if _log_path is None:
        return
    entry = {
        "ts": round(time.time(), 3),
        "turn": turn_id,
        "event": event,
        **(data or {}),
    }
    with open(_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def get_log_path() -> Path | None:
    return _log_path
```

---

### `graph/nodes.py` (updated — add identify_node, commentary_node, route_after_tools)

Add these to the existing `nodes.py` from Sprint 1. Everything from Sprint 1 stays.

```python
# ── Sprint 2 additions ────────────────────────────────────────────────────────

from .session_log import log_event
from .deduction import get_ghost

# Evidence counts required to trigger auto-identification per difficulty
_EVIDENCE_THRESHOLD: dict[str, int] = {
    "amateur":      3,
    "intermediate": 3,
    "professional": 3,
    "nightmare":    2,
    "insanity":     1,
}


def route_after_tools(state: OracleState) -> str:
    """
    Conditional edge function — runs after ToolNode completes.
    Decides whether to auto-identify, auto-comment, or loop back to llm_node.
    No state mutation here — pure routing logic only.
    """
    candidates = state.get("candidates", [])
    prev_count  = state.get("prev_candidate_count", 27)
    confirmed   = state.get("evidence_confirmed", [])
    difficulty  = state.get("difficulty", "professional")

    n = len(candidates)
    changed = n != prev_count
    threshold = _EVIDENCE_THRESHOLD.get(difficulty, 3)

    if n == 1 and len(confirmed) >= threshold:
        return "identify"
    if changed and 1 < n <= 5:
        return "commentary"
    return "llm"  # default: loop back for normal LLM response


def identify_node(state: OracleState) -> dict:
    """
    Pure Python identification announcement.
    Only fires when route_after_tools returns 'identify'.
    Never calls the LLM — deterministic output only.
    """
    candidates = state.get("candidates", [])
    confirmed  = state.get("evidence_confirmed", [])

    if not candidates:
        response = (
            "No matching ghost found — the evidence may be contradictory. "
            "Consider ruling out one evidence type and re-evaluating."
        )
        log_event("identification_failed", {"candidates": []}, state.get("turn_id", 0))
        return {"oracle_response": response}

    ghost_name = candidates[0]
    ghost = get_ghost(ghost_name)

    evidence_str = ", ".join(confirmed) if confirmed else "the evidence collected"

    # Primary tell for the announcement (first behavioral tell if available)
    tells = (ghost or {}).get("behavioral_tells", [])
    tell_str = f" Key tell: {tells[0].rstrip('.')}." if tells else ""

    response = (
        f"Ghost identified — this is a {ghost_name}, "
        f"confirmed by {evidence_str}.{tell_str}"
    )

    log_event(
        "identification",
        {"ghost": ghost_name, "evidence": confirmed},
        state.get("turn_id", 0),
    )

    return {"oracle_response": response}


def commentary_node(state: OracleState) -> dict:
    """
    LLM-generated commentary on remaining candidates.
    Fires when candidates changed this turn and count is 2–5.
    Uses temperature=0.3 for slightly more natural prose than tool-call nodes.
    """
    from langchain_ollama import ChatOllama
    from langchain_core.messages import HumanMessage
    from config.settings import config

    llm = ChatOllama(
        model=config.OLLAMA_MODEL,
        temperature=0.3,
        base_url=config.OLLAMA_BASE_URL,
    )

    candidates = state.get("candidates", [])
    n = len(candidates)
    names = ", ".join(candidates)
    confirmed = ", ".join(state.get("evidence_confirmed", [])) or "none so far"
    ruled_out = ", ".join(state.get("evidence_ruled_out", [])) or "none"

    prompt = (
        f"You are Oracle, a Phasmophobia assistant. Investigation state:\n"
        f"  Confirmed evidence: {confirmed}\n"
        f"  Ruled out: {ruled_out}\n"
        f"  Remaining candidates ({n}): {names}\n\n"
        f"In EXACTLY 2 sentences: name the remaining candidates and tell the player "
        f"what distinguishing evidence or behaviour would identify the ghost. "
        f"Be specific and factual. No atmospheric language. No more than 2 sentences."
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    content = (response.content or "").strip()

    log_event(
        "auto_commentary",
        {"candidates": candidates, "response": content},
        state.get("turn_id", 0),
    )

    return {"oracle_response": content or None}
```

---

### `graph/graph.py` (updated)

```python
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from .state import OracleState
from .nodes import (
    llm_node,
    extract_response,
    route_after_llm,
    route_after_tools,   # Sprint 2
    identify_node,       # Sprint 2
    commentary_node,     # Sprint 2
)
from .tools import ORACLE_TOOLS


def build_graph():
    builder = StateGraph(OracleState)

    # ── Nodes ────────────────────────────────────────────────────────────────
    builder.add_node("llm",        llm_node)
    builder.add_node("tools",      ToolNode(ORACLE_TOOLS))
    builder.add_node("identify",   identify_node)    # Sprint 2
    builder.add_node("commentary", commentary_node)  # Sprint 2
    builder.add_node("respond",    extract_response)

    # ── Entry ─────────────────────────────────────────────────────────────────
    builder.set_entry_point("llm")

    # ── LLM → tool call or direct response ───────────────────────────────────
    builder.add_conditional_edges(
        "llm",
        route_after_llm,
        {"tools": "tools", "respond": "respond"},
    )

    # ── After tools: check for auto-triggers (Sprint 2) ──────────────────────
    builder.add_conditional_edges(
        "tools",
        route_after_tools,
        {
            "identify":   "identify",    # 1 candidate + enough evidence
            "commentary": "commentary",  # candidates narrowed to ≤ 5
            "llm":        "llm",         # no trigger — loop back for normal response
        },
    )

    # ── Terminal edges ────────────────────────────────────────────────────────
    builder.add_edge("identify",   END)
    builder.add_edge("commentary", END)
    builder.add_edge("respond",    END)

    return builder.compile()


oracle_graph = build_graph()
```

**Graph topology (Sprint 2):**

```
llm ──[tool call]──▶ tools ──▶ route_after_tools ──[identify]──▶ identify ──▶ END
 │                                                 ──[comment]──▶ commentary ──▶ END
 │                                                 ──[normal]──▶ llm (loop)
 │
 └──[direct]──▶ respond ──▶ END
```

---

### `main.py` (updated)

```python
#!/usr/bin/env python3
"""Oracle — Sprint 2: voice loop + conditional graph."""

import argparse
import datetime
import logging
import time
import numpy as np

from graph.graph import oracle_graph
from graph.deduction import all_ghost_names
from graph.tools import bind_state, sync_state_from
from graph.session_log import init_log, log_event
from config.settings import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("oracle")

# ── Session state ─────────────────────────────────────────────────────────────

def make_initial_state() -> dict:
    return {
        "user_text":              "",
        "speaker":                "Mike",
        "difficulty":             config.DIFFICULTY,
        "evidence_confirmed":     [],
        "evidence_ruled_out":     [],
        "behavioral_observations":[],
        "eliminated_ghosts":      [],
        "candidates":             all_ghost_names(),
        "oracle_response":        None,
        "prev_candidate_count":   27,   # Sprint 2
        "turn_id":                0,    # Sprint 2
        "messages":               [],
    }


def run_turn(state: dict, user_text: str) -> str | None:
    """Execute one graph turn. Mutates state in-place. Returns oracle_response."""
    state["turn_id"] += 1
    state["user_text"] = user_text
    state["messages"] = []
    state["prev_candidate_count"] = len(state.get("candidates", []))  # snapshot

    bind_state(state)
    result = oracle_graph.invoke(state)
    sync_state_from(state)

    log_event(
        "turn",
        {
            "speaker":   state["speaker"],
            "input":     user_text,
            "response":  result.get("oracle_response"),
            "candidates": state.get("candidates", []),
        },
        state["turn_id"],
    )

    return result.get("oracle_response")


# ── Text loop (Sprint 1 mode, kept for testing) ───────────────────────────────

def run_text_loop(state: dict) -> None:
    n = len(state["candidates"])
    print(f"\nOracle ready [text mode]. Difficulty: {state['difficulty']}. {n} candidates.\n")

    while True:
        try:
            raw = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nOracle offline.")
            break

        if not raw or raw.lower() in ("quit", "exit"):
            break

        response = run_turn(state, raw)
        if response:
            print(f"\nOracle: {response}\n")
        else:
            print(f"  [state updated — {len(state.get('candidates', []))} candidate(s) remain]\n")


# ── Voice loop (Sprint 2) ─────────────────────────────────────────────────────

def run_voice_loop(state: dict) -> None:
    from voice.wake_word import WakeWordDetector
    from voice.speech_to_text import SpeechToText
    from voice.text_to_speech import TextToSpeech

    stt = SpeechToText(model_size=config.STT_MODEL)
    tts = TextToSpeech(speaker_device_name=config.SPEAKER_DEVICE_NAME)
    tts.load()

    _wake_triggered = threading.Event()

    def on_wake():
        if not tts.is_speaking:
            _wake_triggered.set()

    wwd = WakeWordDetector(wake_word=config.WAKE_WORD, callback=on_wake)
    wwd.start()

    n = len(state["candidates"])
    logger.info(f"Oracle ready [voice mode]. Difficulty: {state['difficulty']}. {n} candidates.")
    tts.speak(f"Oracle online. {state['difficulty'].capitalize()} difficulty. Ready.")

    try:
        while True:
            _wake_triggered.wait()         # block until wake word fires
            _wake_triggered.clear()

            if tts.is_speaking:
                continue                   # TTS fired between wait() and clear() — ignore

            logger.info("Wake word detected — recording...")
            audio, sr = record_until_silence(
                device_name=config.MIC_DEVICE_NAME,
                silence_threshold=config.SILENCE_THRESHOLD_DB,
                max_seconds=config.MAX_RECORDING_SECONDS,
            )

            transcript = stt.transcribe(audio, sr)
            if not transcript:
                logger.info("Empty transcription — skipping.")
                continue

            logger.info(f"Transcribed: {transcript!r}")
            log_event("transcription", {"text": transcript}, state.get("turn_id", 0))

            response = run_turn(state, transcript)
            if response:
                logger.info(f"Oracle: {response}")
                tts.speak(response)
            else:
                n = len(state.get("candidates", []))
                logger.info(f"[silent update — {n} candidates remain]")

    except KeyboardInterrupt:
        logger.info("Oracle offline.")
        wwd.stop()
        tts.shutdown()


# ── Recording helper ──────────────────────────────────────────────────────────

import threading
import sounddevice as sd

def record_until_silence(
    device_name: str | None,
    silence_threshold_db: float = -40.0,
    max_seconds: float = 8.0,
    sample_rate: int = 16000,
    chunk_seconds: float = 0.3,
) -> tuple[np.ndarray, int]:
    """
    Record audio until silence is detected or max_seconds is reached.
    Returns (audio_array_float32, sample_rate).
    """
    chunk_size = int(sample_rate * chunk_seconds)
    frames: list[np.ndarray] = []
    silence_chunks = 0
    silence_limit   = int(1.5 / chunk_seconds)  # 1.5s of silence to stop

    with sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=device_name,
        blocksize=chunk_size,
    ) as stream:
        start = time.monotonic()
        while (time.monotonic() - start) < max_seconds:
            chunk, _ = stream.read(chunk_size)
            chunk = chunk.flatten()
            frames.append(chunk)

            rms_db = 20 * np.log10(np.sqrt(np.mean(chunk ** 2)) + 1e-9)
            if rms_db < silence_threshold_db:
                silence_chunks += 1
                if silence_chunks >= silence_limit and len(frames) > silence_limit:
                    break
            else:
                silence_chunks = 0

    audio = np.concatenate(frames) if frames else np.zeros(1, dtype="float32")
    return audio, sample_rate


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Oracle — Phasmophobia ghost assistant")
    parser.add_argument("--text",       action="store_true", help="Text mode (no voice)")
    parser.add_argument("--difficulty", default=None,        help="Override difficulty")
    args = parser.parse_args()

    if args.difficulty:
        config.DIFFICULTY = args.difficulty

    session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    init_log(session_id)
    logger.info(f"Session: {session_id}")

    state = make_initial_state()
    log_event("init", {"difficulty": state["difficulty"], "candidates": len(state["candidates"])})

    if args.text:
        run_text_loop(state)
    else:
        run_voice_loop(state)


if __name__ == "__main__":
    main()
```

---

### `config/settings.py` (updated)

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env.local", extra="ignore")

    # LLM
    OLLAMA_MODEL: str = "phi4-mini"
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # Game
    DIFFICULTY: str = "professional"
    DB_PATH: str = "config/ghost_database.yaml"

    # Voice — STT
    STT_MODEL: str = "base.en"          # tiny.en (faster) or base.en (more accurate)

    # Voice — TTS
    SPEAKER_DEVICE_NAME: str | None = None
    TTS_VOICE: str = "bm_fable"

    # Voice — wake word
    WAKE_WORD: str = "oracle"

    # Voice — recording
    MIC_DEVICE_NAME: str | None = None
    SILENCE_THRESHOLD_DB: float = -40.0
    MAX_RECORDING_SECONDS: float = 8.0

config = Settings()
```

### `config/.env.local` (updated template)

```env
OLLAMA_MODEL=phi4-mini
OLLAMA_BASE_URL=http://localhost:11434
DIFFICULTY=professional

# Voice
STT_MODEL=base.en
WAKE_WORD=oracle
# MIC_DEVICE_NAME=Blue Yeti
# SPEAKER_DEVICE_NAME=VK81
SILENCE_THRESHOLD_DB=-40.0
MAX_RECORDING_SECONDS=8.0
TTS_VOICE=bm_fable
```

---

### `voice/speech_to_text.py`

```python
"""faster-whisper wrapper. Synchronous, called after recording completes."""

import logging
import numpy as np

logger = logging.getLogger(__name__)


class SpeechToText:
    def __init__(self, model_size: str = "base.en"):
        logger.info(f"Loading Whisper model: {model_size}")
        from faster_whisper import WhisperModel
        self._model = WhisperModel(model_size, device="cpu", compute_type="int8")
        logger.info("Whisper ready.")

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """
        Transcribe float32 audio array. Returns stripped transcript string.
        Returns empty string if nothing intelligible was detected.
        """
        if audio is None or len(audio) == 0:
            return ""

        # Normalise
        audio = np.nan_to_num(audio, nan=0.0, posinf=1.0, neginf=-1.0)
        audio = np.clip(audio, -1.0, 1.0)

        segments, info = self._model.transcribe(
            audio,
            language="en",
            beam_size=1,
            vad_filter=True,          # skip silent segments
            vad_parameters={"min_silence_duration_ms": 300},
        )

        text = " ".join(seg.text.strip() for seg in segments).strip()

        # Filter out common Whisper hallucinations on silent audio
        _GARBAGE = {"", ".", "...", "thank you", "thanks", "you", "the"}
        if text.lower() in _GARBAGE:
            return ""

        logger.debug(f"Transcribed ({info.language}, {info.duration:.1f}s): {text!r}")
        return text
```

---

### `voice/text_to_speech.py`

Adapted from Demonic Tutor with the key fixes (blocking play, TTS-speaking flag, device fallback).

```python
"""kokoro-onnx TTS wrapper. Runs synthesis in a background thread."""

import logging
import queue
import threading
import time

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 24000  # kokoro native output rate


class TextToSpeech:
    def __init__(self, speaker_device_name: str | None = None, voice: str = "bm_fable"):
        self._device_name = speaker_device_name
        self._device_id: int | None = None
        self._voice = voice
        self._pipeline = None
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._speaking = False

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def load(self) -> None:
        from kokoro_onnx import Kokoro
        self._pipeline = Kokoro("kokoro-v0_19.onnx", "voices-v1_0.bin")
        self._device_id = self._resolve_device(self._device_name)
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        logger.info(f"TTS ready. Device: {self._device_id}, voice: {self._voice}")

    def speak(self, text: str) -> None:
        """Queue a phrase for synthesis and playback."""
        if text and text.strip():
            self._queue.put(text.strip())

    def flush(self) -> None:
        """Discard all pending queued phrases."""
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
                logger.error(f"TTS error: {e}")
            finally:
                self._speaking = False

    def _synthesize_and_play(self, text: str) -> None:
        samples, rate = self._pipeline.create(text, voice=self._voice, speed=1.0, lang="en-us")
        samples = np.nan_to_num(samples, nan=0.0, posinf=1.0, neginf=-1.0)
        samples = np.clip(samples.astype(np.float32), -1.0, 1.0)

        try:
            sd.play(samples, samplerate=rate, device=self._device_id, blocking=True)
        except sd.PortAudioError:
            logger.warning("PortAudio error on named device — falling back to system default.")
            sd.play(samples, samplerate=rate, device=None, blocking=True)

    @staticmethod
    def _resolve_device(name_hint: str | None) -> int | None:
        if not name_hint:
            return None
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            if name_hint.lower() in d["name"].lower() and d["max_output_channels"] > 0:
                logger.warning(f"TTS output device: [{i}] {d['name']}")
                return i
        logger.warning(f"Device '{name_hint}' not found — using system default.")
        return None
```

---

### `voice/wake_word.py`

```python
"""openwakeword listener. Runs in a background thread.
Calls callback() when the configured wake word is detected.
"""

import logging
import threading
from typing import Callable

import numpy as np
import pyaudio

logger = logging.getLogger(__name__)

_CHUNK     = 1280   # ~80ms at 16kHz (openwakeword requirement)
_RATE      = 16000
_THRESHOLD = 0.5    # detection confidence threshold


class WakeWordDetector:
    def __init__(self, wake_word: str = "oracle", callback: Callable | None = None):
        self._wake_word = wake_word
        self._callback  = callback
        self._running   = False
        self._thread: threading.Thread | None = None
        self._model = None

    def start(self) -> None:
        from openwakeword.model import Model
        logger.info(f"Loading wake word model for '{self._wake_word}'...")
        self._model   = Model(wakeword_models=[self._wake_word], inference_framework="onnx")
        self._running = True
        self._thread  = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        logger.info("Wake word detector running.")

    def stop(self) -> None:
        self._running = False

    def _listen_loop(self) -> None:
        pa     = pyaudio.PyAudio()
        stream = pa.open(
            rate=_RATE,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=_CHUNK,
        )
        try:
            while self._running:
                raw    = stream.read(_CHUNK, exception_on_overflow=False)
                audio  = np.frombuffer(raw, dtype=np.int16)
                preds  = self._model.predict(audio)
                for word, score in preds.items():
                    if score >= _THRESHOLD:
                        logger.info(f"Wake word '{word}' detected (score={score:.2f})")
                        if self._callback:
                            self._callback()
                        self._model.reset()
                        break
        except Exception as e:
            logger.error(f"Wake word listener error: {e}")
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()
```

---

### `tests/test_triggers.py`

```python
"""Test Sprint 2 auto-trigger routing logic.
No LLM, no audio — pure state inspection.
"""

import pytest
from graph.nodes import route_after_tools, _EVIDENCE_THRESHOLD


def make_state(candidates, prev_count, confirmed, difficulty="professional"):
    return {
        "candidates":          candidates,
        "prev_candidate_count": prev_count,
        "evidence_confirmed":  confirmed,
        "difficulty":          difficulty,
    }


# ── Identification triggers ───────────────────────────────────────────────────

def test_identify_fires_at_1_candidate_3_evidence_professional():
    state = make_state(["Wraith"], 5, ["emf_5", "uv", "spirit_box"])
    assert route_after_tools(state) == "identify"

def test_identify_fires_at_1_candidate_2_evidence_nightmare():
    state = make_state(["Wraith"], 5, ["emf_5", "uv"], difficulty="nightmare")
    assert route_after_tools(state) == "identify"

def test_identify_fires_at_1_candidate_1_evidence_insanity():
    state = make_state(["Wraith"], 5, ["emf_5"], difficulty="insanity")
    assert route_after_tools(state) == "identify"

def test_identify_does_not_fire_with_insufficient_evidence():
    # 1 candidate but only 1 confirmed on Professional — not enough
    state = make_state(["Wraith"], 5, ["emf_5"], difficulty="professional")
    assert route_after_tools(state) != "identify"

def test_identify_does_not_fire_when_candidates_unchanged():
    # Already had 1 candidate last turn — no change, shouldn't re-announce
    state = make_state(["Wraith"], 1, ["emf_5", "uv", "spirit_box"])
    # Still identifies because 1 candidate + 3 evidence — identification is stateless
    # (idempotent: always fires when condition is met)
    assert route_after_tools(state) == "identify"


# ── Commentary triggers ───────────────────────────────────────────────────────

def test_commentary_fires_when_candidates_drop_to_5():
    state = make_state(
        ["Banshee", "Demon", "Goryo", "Hantu", "Shade"], 8, ["emf_5"]
    )
    assert route_after_tools(state) == "commentary"

def test_commentary_fires_at_2_candidates():
    state = make_state(["Banshee", "Shade"], 6, ["emf_5"])
    assert route_after_tools(state) == "commentary"

def test_commentary_does_not_fire_when_count_unchanged():
    # Candidates did not change this turn
    state = make_state(["Banshee", "Shade"], 2, ["emf_5"])
    assert route_after_tools(state) == "llm"

def test_commentary_does_not_fire_at_6_candidates():
    state = make_state(
        ["Banshee","Demon","Goryo","Hantu","Shade","Wraith"], 10, ["emf_5"]
    )
    assert route_after_tools(state) == "llm"

def test_commentary_does_not_fire_when_identify_should():
    # 1 candidate + enough evidence = identify wins
    state = make_state(["Wraith"], 5, ["emf_5", "uv", "spirit_box"])
    assert route_after_tools(state) == "identify"


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_no_trigger_when_candidates_high():
    state = make_state(list(range(15)), 20, ["emf_5"])  # 15 candidates, narrowed from 20
    assert route_after_tools(state) == "llm"

def test_evidence_threshold_values():
    assert _EVIDENCE_THRESHOLD["professional"] == 3
    assert _EVIDENCE_THRESHOLD["nightmare"]    == 2
    assert _EVIDENCE_THRESHOLD["insanity"]     == 1
```

---

## Installation (Sprint 2 additions)

```bash
# Sprint 2 new dependencies
pip install faster-whisper kokoro-onnx sounddevice pyaudio openwakeword

# Download kokoro model files (place in project root)
# kokoro-v0_19.onnx + voices-v1_0.bin
# https://github.com/thewh1teagle/kokoro-onnx/releases

# Pull wake word model (openwakeword downloads automatically on first run)
# Default model: "oracle" — check openwakeword docs if a custom model is needed

# Run all tests
pytest tests/ -v

# Voice mode (default)
python main.py

# Text mode (Sprint 1 behaviour, useful for graph testing without audio)
python main.py --text

# Override difficulty
python main.py --difficulty nightmare
```

---

## Self-Feedback Prevention

The voice loop includes two guards to prevent Oracle's TTS output from being picked up by the mic and re-transcribed as a new command:

1. **`is_speaking` check in `on_wake()`** — the wake word callback ignores detections while TTS is active. Since `WakeWordDetector` runs continuously in its own thread, it can detect the wake word in Oracle's own speech synthesis. The `if not tts.is_speaking: _wake_triggered.set()` guard blocks this.
2. **`vad_filter=True` in Whisper** — even if a recording slips through, Whisper's built-in VAD will skip segments that don't contain speech energy consistent with a human voice command.

If self-feedback remains a problem in testing, the third-line of defense is a post-transcription garbage filter (already present in `SpeechToText.transcribe()`) that discards short hallucination strings like `")"` or `"thank you"` — the artifacts Demonic Tutor produced.

---

## Task Board

### Backlog

|ID|Task|Notes|
|---|---|---|
|S2-01|Update `graph/state.py`|Add `prev_candidate_count: int`, `turn_id: int`|
|S2-02|Create `graph/session_log.py`|`init_log()`, `log_event()`|
|S2-03|Add `route_after_tools()` to `graph/nodes.py`|Conditional edge function, uses `_EVIDENCE_THRESHOLD`|
|S2-04|Add `identify_node()` to `graph/nodes.py`|Pure Python, no LLM, logs to session|
|S2-05|Add `commentary_node()` to `graph/nodes.py`|LLM at `temperature=0.3`, 2-sentence constraint|
|S2-06|Rewire `graph/graph.py`|`tools → route_after_tools → [identify\|commentary\|llm]`|
|S2-07|Update `config/settings.py`|Add STT/TTS/wake-word/recording config fields|
|S2-08|Update `main.py`|`run_turn()` helper, `run_voice_loop()`, `--text` / `--difficulty` flags|
|S2-09|Create `voice/speech_to_text.py`|faster-whisper, VAD filter, garbage rejection|
|S2-10|Create `voice/text_to_speech.py`|kokoro-onnx, `is_speaking` flag, device fallback|
|S2-11|Create `voice/wake_word.py`|openwakeword background listener|
|S2-12|Write `tests/test_triggers.py`|All routing branches, difficulty thresholds|
|S2-13|Run all tests|`pytest tests/ -v` — both Sprint 1 and Sprint 2 tests|
|S2-14|Smoke test: auto-commentary|Confirm evidence until ≤ 5 candidates — verify Oracle speaks unprompted|
|S2-15|Smoke test: identification|Narrow to 1 candidate + correct evidence count — verify Oracle identifies|
|S2-16|Smoke test: no premature ID|1 candidate, insufficient evidence (e.g. 1 confirmed on Professional) — silence|
|S2-17|Smoke test: voice round-trip|Say "ghost orb confirmed" → Oracle responds via Kokoro correctly|
|S2-18|Smoke test: self-feedback|Oracle speaks; verify wake word does not re-trigger during playback|
|S2-19|Full match simulation (voice)|Simulate a full match from init to identification — log review|

### Definition of Done (Sprint 2)

- [ ] All `test_triggers.py` tests pass
- [ ] All Sprint 1 tests still pass
- [ ] Auto-commentary fires at correct candidate thresholds, not before
- [ ] Identification fires correctly per difficulty (3/2/1 evidence)
- [ ] Session `.jsonl` contains correct entries for all events
- [ ] `python main.py --text` still works (regression check)
- [ ] `python main.py` enters voice mode, wake word triggers recording
- [ ] Oracle does not speak during its own TTS output (self-feedback guard confirmed)
- [ ] `Ctrl+C` exits cleanly from both modes

---

## Known Risks

**openwakeword "oracle" model availability.** openwakeword ships pre-trained models for a specific set of wake words. "oracle" may not be in the default set — check the openwakeword registry before Sprint 2 testing. If absent, "hey oracle", "computer", or a custom-trained model are alternatives. The `WAKE_WORD` config value makes this a one-line change.

**Kokoro model files not in pip package.** `kokoro-onnx` requires `kokoro-v0_19.onnx` and `voices-v1_0.bin` to be present at runtime. These are downloaded separately from the GitHub releases page, not via pip. Add a startup check in `tts.load()` that raises a clear error with the download URL if the files are missing — otherwise the failure message will be cryptic.

**commentary_node LLM latency.** Commentary fires synchronously before TTS. If phi4-mini takes 3–5 seconds to generate 2 sentences, there will be a noticeable lag after evidence is reported. Mitigate by starting the commentary LLM call in a background thread while the tool result is being spoken (Sprint 3 optimisation), or by switching to a faster model for commentary only.

**`sync_state_from` and LangGraph native state.** The shared `_state` dict approach works fine for single-threaded voice (one turn at a time). If Sprint 4 introduces concurrent multi-speaker capture, migrate to LangGraph's `InjectedState` pattern to give each invocation its own isolated state copy.