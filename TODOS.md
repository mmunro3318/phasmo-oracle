# TODOS

## Kokoro TTS latency — critically slow, needs acceleration
**Priority:** P0 | **Effort:** M (CC: ~30 min) | **Sprint:** 3c

Benchmark results (`docs/benchmarks/results.md`) show CPU-only Kokoro is 6-12x over target:

| Utterance | Laptop (HP OmniBook) | Desktop (RTX 5060 Ti) | Target |
|-----------|---------------------|-----------------------|--------|
| Short (3-10 chars) | ~960ms | ~1330ms | <500ms |
| Medium (36 chars) | ~2300ms | ~3175ms | <500ms |
| Long (116 chars) | ~6000ms | ~7400ms | <1000ms |
| Full pipeline | 3041ms | 3671ms | <500ms |

Neither machine uses GPU — the desktop has an RTX 5060 Ti sitting idle. Three mitigation paths (not mutually exclusive):

1. **GPU acceleration** — `pip install onnxruntime-directml` (Windows) or `onnxruntime-gpu` (CUDA). Re-benchmark. Could drop latency 5-10x.
2. **Chunked streaming** — Start audio playback after first chunk synthesizes, not after the entire response. Perceived latency drops to time-to-first-chunk (~200-400ms) even if total synthesis is 3s. Kokoro supports `create_stream()`.
3. **Shorter voice responses** — Add a voice-mode response variant in responses.py that produces shorter text (e.g., "EMF confirmed. 11 left." instead of "Copy that — EMF Level 5 confirmed. 11 ghosts remain."). Text mode keeps the longer version.

**Where to start:** Try DirectML first (1 line install). If still slow, investigate `create_stream()` for chunked playback. See `BENCHMARK_GUIDE.md`.

---

## CLAUDE.md + docs review with /document-release
**Status:** RESOLVED

Ran `/document-release`. README fully rewritten (removed LangGraph/Ollama references, updated architecture, commands, project structure). CLAUDE.md updated with legacy code note, voice testing docs, doc index. Archived 3 stale docs (REFACTOR.md, Oracle Architecture Design.md, Roadmap.md). Sprint 3b doc marked COMPLETE.

---

## Voice I/O async pattern
**Status:** RESOLVED

Implemented in Sprint 3c. VoiceInput uses RealtimeSTT's blocking `recorder.text()` call — the synchronous run_loop works unchanged. Barge-in uses a simple `_is_speaking` flag + `sd.stop()` callback on wake word detection (no async needed). `sd.play()` stays non-blocking to allow barge-in interruption.

---

## Ghost test completeness audit
**Status:** RESOLVED

Expanded from 15 to 26 of 27 ghosts. Fixed 2 factual errors (Deogen speed direction, Oni fabricated trait). The Mimic has no behavioral test — its identifier is the 4th evidence type, handled by evidence deduction.

---

## Ghost card deep narrative parser
**Priority:** P2 | **Effort:** S (CC: ~20 min) | **Sprint:** Post-3b

The ghost query response builder (`responses.py:_build_ghost_query_response`) handles top-level fields well (evidence, guaranteed, tells, community tests). But ghost_database.yaml has nested structures (behavioral_profile dicts, speed values with units, multi-step procedures) that may leak raw YAML formatting (curly brackets, colons) into spoken output.

**Solution:** Write a recursive `_flatten_to_prose(value)` helper that walks nested dicts/lists and produces natural sentences. For dicts: join "key is value" pairs. For lists: join with commas. For strings: pass through. Apply it in the ghost query builder anywhere raw YAML values are interpolated.

**Where to start:** Run `python -m oracle --text --speak` and query each of the 27 ghosts with "tell me about {ghost}". Flag any responses that read YAML formatting aloud. Fix the deepest offenders first (behavioral_profile, community_tests).

---

## Fix ghost_test_result case mismatch bug
**Priority:** P1 | **Effort:** XS (CC: ~5 min) | **Sprint:** 3c.1

`engine.ghost_test_result()` at line 765 uses `tests.get(true_name, {})` with title-case keys ("Wraith") but `ghost_tests.yaml` uses lowercase ("wraith"). Negative test types (Wraith, Banshee, Oni, Goryo) are never recognized — they always fall back to "positive". The sibling method `ghost_test_lookup()` at line 726 correctly handles this with `tests.get(true_name) or tests.get(true_name.lower())`. Apply the same pattern.

**Found by:** Codex audit + coverage agent during Sprint 3c test overhaul.

---

## Custom "Hey Oracle" wake word
**Priority:** P2 | **Effort:** M (CC: ~1 hour) | **Sprint:** Post-3c

Currently ships with "hey_jarvis" (built-in openWakeWord model). Train a custom "Hey Oracle" wake word model on Google Colab (~1 hour). Follow openWakeWord's fine-tuning guide. Replace the default in `audio_config.py`.

---

## VoiceMeeter Banana dual output
**Priority:** P2 | **Effort:** S (CC: ~20 min) | **Sprint:** Post-3c

V1 routes Oracle TTS to VB-Cable only (Steam voice chat). Local user hears Oracle through Steam like everyone else. For dual output (speakers + VB-Cable simultaneously), VoiceMeeter Banana can handle the routing outside Oracle's code. Document the VoiceMeeter setup and optionally detect VoiceMeeter devices in `find_vb_cable_device()`.

---

## Natural voice change commands
**Priority:** P2 | **Effort:** S (CC: ~15 min) | **Sprint:** 3d

Saying "hey Jarvis, change voice to bf_bella" is unnatural — nobody speaks underscores. Allow natural phrases like "hey Jarvis, put Bella on the line" or "change the voice to Bella". The parser already has a voice change pattern; extend it to match just the display name (e.g., "Bella" → "bf_bella", "Fable" → "bm_fable", "Sarah" → "af_sarah"). Add a reverse lookup from display names to voice IDs in `audio_config.py`.

**Found during:** Sprint 3c field test (2026-04-03).

---

## Parser command tree robustness — test queries and ambiguous intent
**Priority:** P1 | **Effort:** M (CC: ~30 min) | **Sprint:** 3d

Certain voice commands route to the wrong handler. Example: "what tests do we have for Jinn" triggers the ghost card info dump (ghost query) instead of the test lookup. Root cause: the parser checks ghost query patterns before test query patterns, and "for Jinn" matches a ghost name before "tests" is recognized as a test lookup intent. Need to:

1. Audit the parser pattern precedence order — test queries should be checked before generic ghost queries
2. Add explicit test-query patterns: "what tests for {ghost}", "how do we test {ghost}", "test {ghost}"
3. Consider a lightweight intent scoring system where multiple patterns can match and the most specific wins, rather than first-match-wins

**Found during:** Sprint 3c field test (2026-04-03). Also affects: "what info on Jinn" (should be ghost query, works), vs "what tests on Jinn" (should be test lookup, gets ghost query instead).

---

## Echo/self-hearing on laptop speakers
**Priority:** P1 | **Effort:** M (CC: ~30 min) | **Sprint:** 3d

On the HP OmniBook laptop without headphones, Oracle's TTS output from the speakers feeds back into the built-in microphone. Whisper transcribes the TTS audio as garbage commands (observed: "And I'll turn off the break and direct me to overload him..." — a garbled transcription of the Jinn ghost card). This causes:

1. False commands that trigger unwanted responses
2. Potential cascade where each response generates more garbage input
3. App instability (may contribute to unexpected "RealtimeSTT shutting down")

The plan's echo prevention relies on device isolation (TTS → VB-Cable, STT ← physical mic). On the laptop without VB-Cable, there's no isolation. Mitigation options:

1. **Mute STT during TTS playback** — call `recorder.set_microphone(False)` when `is_speaking=True`, re-enable after. Disables barge-in but prevents echo. Simple toggle.
2. **Post-TTS silence buffer** — after TTS finishes, wait 200-500ms before accepting the next wake word. Lets the room echo decay before STT listens again.
3. **Headphone detection** — if no headphones/VB-Cable detected, auto-enable mute-during-TTS mode and warn the user.

Option 1 is the right default for laptop use. Barge-in only matters with headphones/VB-Cable (where echo isn't an issue anyway).

**Found during:** Sprint 3c field test (2026-04-03). Transcript shows Whisper transcribing Oracle's own Jinn ghost card as a command.

---

## Hybrid input mode — voice + keyboard simultaneously
**Priority:** P1 | **Effort:** S (CC: ~15 min) | **Sprint:** 3d

Currently `--voice` replaces keyboard input entirely. There's no way to type a command when voice fails or for debugging during development. Add a hybrid mode where:

1. `--voice` spawns VoiceInput on a background thread
2. Main thread also accepts keyboard input via `input()`
3. Whichever fires first (wake word transcription or keyboard Enter) gets processed
4. Alternatively: simpler approach where `--voice --text` is recognized as "voice primary, keyboard fallback" — keyboard input only checked during the gap between TTS finish and next wake word

The simpler approach: use Python's `select`/`threading` to race VoiceInput.get_command() against a non-blocking stdin check. Or just add a keyboard listener thread that pushes to a shared queue.

**Found during:** Sprint 3c field test (2026-04-03). User wanted to type corrections when voice failed ("ghost names" misheard instead of "ghost orbs").

---

## Sprint 3d outline — GPU Acceleration + Field Test
**Priority:** P0 | **Effort:** L (CC: ~2-3 hours) | **Sprint:** 3d

Sprint 3c delivered voice I/O. Sprint 3d hardens it for real gameplay:

1. **GPU acceleration** — Install CUDA toolkit on desktop (RTX 5060 Ti). Benchmark Kokoro TTS + Whisper STT with GPU. Target: <300ms TTS, <500ms STT. Fallback: DirectML on Intel Arc laptop.
2. **Fix ghost_test_result bug** (P1, see above)
3. **Echo prevention** — Mute STT during TTS playback on non-isolated setups (no headphones/VB-Cable). Re-enable after TTS + 200ms decay buffer.
4. **Parser robustness** — Fix test query vs ghost query precedence. Add natural voice change commands ("put Bella on the line").
5. **Hybrid input** — `--voice --text` enables both voice and keyboard input simultaneously.
6. **Chunked TTS streaming** — Use Kokoro's `create_stream()` to start playback before full synthesis. Perceived latency drops from 3s to ~300ms.
7. **Field test** — Solo Phasmo lobby with `--voice` mode on desktop (headphones + VB-Cable). 10 consecutive commands without crash or echo.
8. **Kayden setup doc** — Write beginner-friendly setup guide for Kayden to install and run Oracle on their machine.

---

*Pre-pivot TODOs archived to `archive/TODOS-pre-pivot.md`*
*Kokoro short-sentence padding: RESOLVED in `oracle/voice/tts.py` (200ms audio-level gate)*
