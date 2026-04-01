# TODOS

## Kokoro short-sentence padding
**Priority:** P1 | **Effort:** S (CC: ~10 min) | **Sprint:** 3b (voice)

kokoro-onnx produces poor audio quality for very short sentences (<8 phonemes). The response builder already has `_ensure_minimum_length()` which pads responses under 40 characters. When integrating TTS in Sprint 3b, verify this padding is sufficient for natural-sounding audio. May need to tune the threshold or add prosody hints.

**Where to start:** Test all response templates through kokoro-onnx and flag any that sound bad. Adjust padding or rewrite templates as needed.

---

## Voice I/O async pattern
**Priority:** P1 | **Effort:** M (CC: ~30 min) | **Sprint:** 3b (voice)

The current `InputProvider`/`OutputHandler` protocols are synchronous (text mode). Voice mode involves async operations: wake word listening (continuous), streaming STT, TTS playback. Sprint 3b's `VoiceInput` will likely need `async get_command()` or a callback pattern. The runner loop may need an async variant.

**Where to start:** Design the voice state machine (IDLE -> LISTENING -> PROCESSING) and decide whether to use asyncio, threading, or callback pattern.

---

## Ghost test completeness audit
**Priority:** P2 | **Effort:** S (CC: ~15 min) | **Sprint:** 3b+

`ghost_tests.yaml` currently covers 15 of 27 ghosts. Audit the Ghost ID Guide for all testable behaviors and add missing entries. Some ghosts may not have reliable deterministic tests.

**Where to start:** Read `docs/Ghost Identification Guide.md` and cross-reference with existing entries in `oracle/config/ghost_tests.yaml`.

---

*Pre-pivot TODOs archived to `archive/TODOS-pre-pivot.md`*
