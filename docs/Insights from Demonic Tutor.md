*A technical handoff for the Oracle project — distilled from the Demonic Tutor prototype.*

---

## What We Were Building

Demonic Tutor was a Python overlay + voice assistant for Phasmophobia. It did too much at once: screen capture, OCR journal reading, a ghost deduction engine, an overlay rendered on top of the game, a two-brain LLM advisor (Brain 1 = ambient banter, Brain 2 = evidence analysis), Supabase sync, and a full voice pipeline (wake word → STT → LLM → TTS). The result worked, but several subsystems were fighting each other and the Oracle went "rogue" — generating atmospheric prose rather than useful gameplay advice.

Oracle strips this back to the core value: **a voice-queryable Phasmophobia rules engine**. No screen capture. No overlay. Just: player speaks → evidence is logged → Oracle reasons from the rules and responds.

---

## Voice Pipeline — What We Learned

### Wake Word
- **Library**: `openwakeword` with the built-in `hey_jarvis` model. Works well offline, no cloud dependency.
- **The `paInvalidDevice (-9996)` error**: WASAPI on Windows rejects device format mismatches. When `sounddevice.rec()` is called with `samplerate=16000, channels=1` but the device's native format is `44100 Hz / stereo`, PortAudio throws `-9996`.
  - **Fix**: Always query the device's native sample rate and channel count first, open the stream at native params, and resample in software (numpy linear interpolation to 16kHz mono for Whisper). Never ask sounddevice to do the conversion on WASAPI.
- **Device resolution**: Don't rely on `sd.default.device`. Build a fallback chain: (1) name fragment match, (2) PortAudio default, (3) first non-virtual device. See `voice/audio_devices.py::resolve_input_device()`.
- **Virtual devices** (VB-Cable, "Mapper", "Primary Sound Capture Driver") show up in `sd.query_devices()` but reject PCM streams — skip them in the fallback chain.

### Recording
- `sd.rec()` opens and closes a PortAudio stream on every call. On Windows WASAPI this is expensive and error-prone. **Prefer `sd.InputStream` as a context manager** — open once, read in a loop, close once.
- For the post-wake-word recording pass, `sd.rec()` for a fixed `MAX_RECORD_SECS` window (8s) is fine because it only runs once per activation.
- **NaN / overflow guard**: sounddevice can return NaN or very large finite float32 values during device initialization. `np.nan_to_num(audio, nan=0.0, posinf=1.0, neginf=-1.0)` alone is not enough — large *finite* values still overflow during `x**2`. Always follow with `np.clip(audio, -1.0, 1.0)` before any RMS energy calculation.

### STT — Whisper
- **Library**: `faster-whisper` (CTranslate2 backend). Significantly faster than `openai-whisper` on CPU.
- **Model**: `base.en` is the sweet spot for English-only, low-latency use. `small.en` is worth it if you have ~4s to spare.
- **TTS self-feedback**: The microphone picks up Oracle's own TTS output through the speakers. Whisper transcribes this as garbage (`))))`, repeated characters, etc.).
  - **Fix**: Track a `_tts_speaking` boolean flag. Set it True in `on_speak_start`, False in `on_speak_end`. In `_on_wake_word`, return early if `_tts_speaking` is True — don't even start recording. The user just says the wake word again when Oracle finishes.

### TTS — Kokoro-ONNX
- **Library**: `kokoro-onnx` — 82M parameter model, ~300MB download, runs on CPU.
- **Preferred voice**: `bm_fable` (British male, warm and dry — good for an "Oracle" persona).
- **Latency note**: Synthesis on CPU takes 3–8 seconds per phrase. Not suitable for real-time back-and-forth — design Oracle responses to be at most 2 sentences so synthesis time is tolerable.
- **`sd.play(blocking=False)` + `sd.wait()` race condition**: This pattern interacts badly with a concurrently running `sd.InputStream` (for the loopback capture). Use `sd.play(blocking=True)` instead — the TTS thread blocks until playback finishes, which is fine since it's a daemon thread.
- **Device resolution**: `sd.default.device[1]` frequently returns the wrong device (or -1) on Windows. Build the same fallback chain as for input: name fragment → PortAudio default → first non-virtual output. Log at WARNING level so the device is visible in startup logs.
- **Queue delay bug**: Any phrase queued before the player speaks will play *before* their query's response — making it sound one-message delayed. Fix: call `tts_queue.flush()` (drain all pending items) immediately before queuing a direct player response. Don't queue startup announcements at all — they cause the same delay on first activation.

### Threading Model
- **Qt event loop must own the main thread.** All other work (game loop, voice pipeline) runs on daemon background threads.
- **`os._exit()` not `sys.exit()`** for shutdown on Windows. `sys.exit()` raises `SystemExit` and waits for non-daemon threads (ONNX, sounddevice) before the process terminates. `os._exit()` is immediate. Pattern: `app.exec()` → `shutdown_event.set()` → `game_thread.join(timeout=6)` → `os._exit(exit_code)`.

---

## LLM / Oracle Brain — What We Learned

### The "Going Rogue" Problem
The oracle was generating atmospheric prose ("the shadows flicker", "air feels heavy with anticipation") because Brain 1 (ambient banter) was:
1. Firing every 30 seconds automatically via a poll loop
2. Being sent the default prompt: `"Give a brief, atmospheric observation about the investigation so far."`

This is exactly what the model does when given that instruction. The fix is structural, not prompt-tweaking:
- **Don't fire ambient observations unless there is meaningful game-state context to pass.** Trigger Brain 1 only on events (new evidence, hunt started, player death) — not on a timer with no context.
- **Default prompt must be NULL-biased**: `"If you have a SPECIFIC, evidence-grounded observation, state it. Otherwise reply NULL."` NULL-biased defaults are far more effective than hoping the model self-censors.
- **Repeat the constraint in the user prompt**, not just the system prompt. Models respond much more consistently to constraints that appear immediately before their response slot: `[Oracle: respond in exactly 2 sentences. No more.]`.

### Grounding with Game Knowledge
Without explicit game rules in the context, the model invents plausible-sounding but wrong Phasmophobia facts. The fix: inject a structured reference document (evidence types, ghost hunt thresholds, key behavioural tells) directly into every prompt. The model stops inventing when it has facts to cite.

For Oracle, maintain `config/phasmophobia_guide.md` as the authoritative source. Inject it into every Brain 2 prompt. Keep a condensed quick-reference version in the system prompt so it's always in context even on long conversations.

### Models — Current Setup and Recommendations

**What we used in Demonic Tutor:**
| Brain | Model | Role | Notes |
|---|---|---|---|
| Brain 1 | `llama3.2:3b` via Ollama | Ambient banter | Fast, but poor at self-censoring |
| Brain 2 | `llama3.1:8b` via Ollama | Evidence analysis | Solid reasoning, but ~24s on CPU |
| Brain 2 (API) | `claude-haiku-4-5` via Anthropic | Evidence analysis | Fast, excellent structured output |
| Vision | `qwen2.5vl:7b` via Ollama | Screen-capture analysis | Not relevant to Oracle |

**Better options for Oracle's single-brain architecture:**

> Oracle doesn't need two brains — it has one job: receive evidence claims, reason against the rules, give a concise answer. The two-brain split was solving a latency problem (Brain 1 fills silence while Brain 2 thinks). Since Oracle doesn't fill silence, one good model is cleaner.

| Model | Why it's better for Oracle | Ollama? | Notes |
|---|---|---|---|
| **`phi4-mini`** | Explicitly trained for constrained, structured outputs. Follows JSON schemas and strict length rules. Best "stick to the script" behaviour at small size. | ✅ | ~3.8B params. Top recommendation for local inference. |
| **`qwen2.5:7b`** | Trained on 1M+ high-quality instruction samples. Excellent RAG behaviour — cites provided context rather than training data. 128k context window. | ✅ | Good alternative if phi4-mini is too terse. |
| **`mistral-nemo`** | Built-in JSON mode. Good instruction adherence. 128k context. More capable than 7B models. | ✅ | 12B params — heavier, but better reasoning. |
| **`claude-haiku-4-5` (API)** | Near-instant, never hallucinates structure, follows 2-sentence constraint reliably. | API only | Best quality. Use as production target once local is proven. |

**Practical recommendation for Oracle sprint 1:** Start with `phi4-mini` locally (fast, obedient), with `claude-haiku-4-5` as the API fallback for when you want best-quality responses. Skip the two-brain architecture entirely — just one model, one role.

**Temperature**: Always set to `0.0` or `0.1` for Oracle. Structured factual output should be deterministic. Higher temperature is what causes the "going rogue" behaviour.

### Ollama setup notes
- Run Ollama on a local machine or LAN IP: `LLM_HOST=http://192.168.1.50:11434`
- Pull models: `ollama pull phi4-mini`, `ollama pull qwen2.5:7b`
- Ollama `/api/generate` supports a `format: "json"` field — use it for evidence responses to get structured output that's easy to parse.
- CPU inference timing: `llama3.1:8b` = ~24s per response on CPU. `phi4-mini` = ~8–12s. For real-time feel, keep response < 2 sentences and use API mode for faster turnaround.

---

## Evidence Tracking — Design Notes

Demonic Tutor's evidence system (in `deduction/engine.py`) was too complex for the first sprint — it tried to be a full deduction engine that automatically narrowed ghost candidates. For Oracle, keep it simple:

### Recommended minimal schema
```python
@dataclass
class EvidenceState:
    confirmed: set[str]   # e.g. {"Ghost Orb", "Freezing Temperatures"}
    ruled_out: set[str]   # e.g. {"EMF Level 5"}
    behavioral: list[str] # e.g. ["ghost manifests frequently but doesn't hunt"]
```

**Distinguish explicitly:**
- **Hard evidence** (observed via equipment): confirms/rules out a ghost type definitively per the rules
- **Behavioral observations** (player reports): soft signals — useful for narrowing but never conclusive. The model must use language like "consistent with" rather than "proves". This distinction should be in the system prompt and reinforced in the evidence schema injected into each prompt.

**Inject evidence state as a structured block at the top of every user prompt:**
```
== CURRENT EVIDENCE ==
Confirmed (equipment): Ghost Orb, Freezing Temperatures
Ruled out: EMF Level 5
Behavioral observations (soft signals): ghost manifests frequently but doesn't initiate hunt
Ghost candidates (based on confirmed evidence): Hantu, Mimic, Moroi, Thaye, Yokai, Raiju
```

The model reasons from this block. It doesn't remember between turns unless the block is re-injected.

---

## Steam Chat TTS Routing (Sprint 2 Goal)

The goal: Oracle's TTS voice plays into the Steam voice chat so a second player (Kayden) can hear Oracle even without a copy of the app running.

**How it works**: VB-Audio Virtual Cable creates a virtual audio device. Any audio played to "CABLE Input" appears as a microphone source to other applications. Steam voice chat (and Discord) can be configured to use "CABLE Output" as their input microphone.

**Implementation:**
1. Install [VB-Cable](https://vb-audio.com/Cable/) — free.
2. In Steam voice settings: set input to "CABLE Output (VB-Audio Virtual Cable)".
3. In Oracle: set `VBCABLE_DEVICE_NAME=CABLE Input (VB-Audio Virtual Cable)` in `.env.local`.
4. In `TextToSpeech._synthesize_and_play()`: play to BOTH the headset AND VB-Cable simultaneously. Note: `sd.play()` can only have one active stream per device — play to each device with a separate blocking call in sequence (not truly simultaneous, but the delay between them is inaudible for speech).
5. `use_vbcable=True` flag in `VoiceController` / config enables the second playback call.

**Known issue from Demonic Tutor**: Two sequential `sd.play(blocking=True)` calls mean the VB-Cable audio plays slightly after the headset audio. For speech this is acceptable. If it becomes an issue, use `sd.OutputStream` with a separate thread per device.

**Sprint 3 goal** (bidirectional): Second player can speak to Oracle too, via their own microphone through Steam. This requires capturing the loopback of Steam's incoming voice audio — `Stereo Mix` or `WASAPI loopback` — running it through Whisper, attributing it to the second player by speaker tag, and feeding it to the evidence tracker. This is the loopback capture subsystem from Demonic Tutor (`_LoopbackCapture` in `core/game_loop.py`).

---

## TTS Voice Options

**Current favourite**: `bm_fable` (Kokoro British male, warm and dry). Good for an authoritative Oracle tone.

**Kokoro-ONNX** (82M params, ~300MB):
- Best local TTS for edge/CPU use. #1 ranked open-weight TTS as of early 2026.
- Synthesis: ~3–8s on CPU for 2-sentence response. Acceptable for Oracle's use pattern.
- Runs fully offline after the one-time model download.

**Mistral Voxtral** (released March 26, 2026):
- A full speech suite: Voxtral TTS (4B params) + Voxtral STT (3B / 24B).
- TTS latency: 70ms model latency, 90ms time-to-first-audio — significantly faster than Kokoro on equivalent hardware.
- **BUT**: requires ~16GB VRAM for comfortable inference. CPU inference is impractical.
- Not yet available in Ollama (pending as of mid-2026).
- Integration: `pip install transformers>=5.2.0` + HuggingFace model weights, or via vLLM-Omni.
- **Verdict for Oracle sprint 1**: Stick with Kokoro. Consider Voxtral for sprint 2/3 if you have GPU headroom and want faster synthesis + voice cloning capability.

---

## Project Structure Recommendation for Oracle

```
oracle/
├── main.py                  # entry point: start voice loop
├── core/
│   ├── config.py            # pydantic-settings, .env.local
│   └── oracle_loop.py       # main loop: wake word → record → transcribe → LLM → TTS
├── voice/
│   ├── audio_devices.py     # device resolution (reuse from DT)
│   ├── wake_word.py         # openwakeword listener (reuse from DT)
│   ├── speech_recognition.py # faster-whisper wrapper (reuse from DT)
│   └── text_to_speech.py    # kokoro-onnx wrapper (reuse from DT)
├── evidence/
│   ├── tracker.py           # EvidenceState dataclass + update methods
│   └── deduction.py         # ghost candidate filtering from evidence
├── ai/
│   ├── oracle.py            # single-brain LLM call (no Brain 1/2 split)
│   └── prompts.py           # system prompt + evidence block builder
├── config/
│   ├── phasmophobia_guide.md # game rules reference (reuse from DT)
│   └── ghost_database.yaml  # ghost evidence requirements (reuse from DT)
├── .env.local               # user config (gitignored)
└── .env.local.example
```

Key simplifications vs Demonic Tutor:
- No overlay, no Qt, no screen capture, no dxcam
- No two-brain split — one `oracle.py` module, one LLM call per query
- No `SessionMemory` / `CrossSessionMemory` complexity in sprint 1
- No Supabase sync
- Evidence tracker is a plain Python dataclass, not a deduction engine

---

## Key Config Values Learned

```
# .env.local — essential settings

LLM_BACKEND=ollama
LLM_HOST=http://localhost:11434        # or LAN IP of mini-PC
LLM_TEXT_MODEL=phi4-mini              # recommended replacement for llama3.1:8b

WHISPER_MODEL=base.en                 # fast enough, accurate for gaming context
MIC_DEVICE_NAME=default               # or exact fragment e.g. "Headset Microphone"
SPEAKER_DEVICE_NAME=VK81              # fragment of headset name
VBCABLE_DEVICE_NAME=CABLE Input       # set for Steam routing (sprint 2)

ORACLE_VOICE=bm_fable                 # Kokoro voice
TTS_SPEED=1.1
WAKE_WORD=hey tutor                   # or hey jarvis — openwakeword supports both

ADVISOR_AMBIENT_COOLDOWN_SECONDS=999  # effectively disable auto-ambient in Oracle
                                      # (no unprompted observations — query only)
LOG_LEVEL=INFO
```

---

## What to Carry Forward (Code Reuse)

These modules from Demonic Tutor are solid and can be copied directly into Oracle with minimal changes:

| Module | Status | Notes |
|---|---|---|
| `voice/audio_devices.py` | ✅ Reuse as-is | All device resolution logic is here |
| `voice/wake_word.py` | ✅ Reuse as-is | openwakeword wrapper, device fallback wired |
| `voice/speech_recognition.py` | ✅ Reuse as-is | faster-whisper wrapper |
| `voice/text_to_speech.py` | ✅ Reuse as-is | Kokoro + `flush_pending()` + `blocking=True` fix |
| `voice/voice_controller.py` | ✅ Reuse, simplify | Remove `_tts_speaking` complexity if no ambient brain |
| `config/phasmophobia_guide.md` | ✅ Reuse as-is | Full game reference |
| `config/ghost_database.yaml` | ✅ Reuse as-is | Ghost evidence requirements |
| `deduction/engine.py` | ⚠️ Too complex for sprint 1 | Replace with simple `EvidenceState` dataclass |
| `ai/prompts.py` | ⚠️ Simplify | Remove two-brain structure, keep game knowledge injection |
| `core/game_loop.py` | ❌ Don't reuse | Too coupled to overlay/screen-capture — start fresh |
| `overlay/` | ❌ Drop entirely | No overlay in Oracle |
| `capture/` | ❌ Drop entirely | No screen capture in Oracle |

---

*Written: March 2026 — after the Demonic Tutor prototype sprint.*
