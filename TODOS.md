# TODOS

## Kokoro TTS latency benchmark
**Priority:** P1 | **Effort:** S (CC: ~15 min) | **Sprint:** Post-3b

Kokoro-onnx (82M params) CPU latency is unvalidated on target hardware. Estimated 200ms but could be 400-600ms. Need real measurements to decide if DirectML acceleration or a different TTS backend is needed.

**Where to start:** See `BENCHMARK_GUIDE.md` for step-by-step instructions and the benchmark script. Test both CPU and DirectML (if available). Measure across short (10-50 char) and long (100+ char) utterances.

---

## CLAUDE.md + docs review with /document-release
**Priority:** P2 | **Effort:** S (CC: ~15 min) | **Sprint:** Post-3b

After Sprint 3b ships, run `/document-release` to fully review and update CLAUDE.md, README, and other docs. AGENTS.md was archived — CLAUDE.md needs to be the definitive project guide with voice-specific guidance for future sessions.

**Where to start:** Run `/document-release` in a fresh session.

---

## Voice I/O async pattern
**Priority:** P1 | **Effort:** M (CC: ~30 min) | **Sprint:** 3c (voice input)

The current `InputProvider`/`OutputHandler` protocols are synchronous (text mode). Voice mode involves async operations: wake word listening (continuous), streaming STT, TTS playback. Sprint 3c's `VoiceInput` will likely need `async get_command()` or a callback pattern. The runner loop may need an async variant.

**Where to start:** Design the voice state machine (IDLE -> LISTENING -> PROCESSING) and decide whether to use asyncio, threading, or callback pattern. Note: `sd.play()` must switch to `blocking=True` when InputStream (STT) is added.

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

*Pre-pivot TODOs archived to `archive/TODOS-pre-pivot.md`*
*Kokoro short-sentence padding: RESOLVED in `oracle/voice/tts.py` (200ms audio-level gate)*
