# CLAUDE.md — Oracle Project Guide

**Note:** Always use subagents or agents teams where possible to conserve context and design for isolated work.
**Note:** You have a wealth of skills available to you -- use them.

## Project Overview

Oracle is a Phasmophobia ghost-identification voice assistant. A deterministic regex parser handles ~90% of inputs instantly. A pure Python deduction engine handles all candidate narrowing. Scripted response templates produce all output text. No LLM dependencies in the core pipeline.

**Current sprint:** Sprint 3c — Voice Input (STT + Wake Word + Barge-In)
**Next:** Sprint 3d — GPU Acceleration + Field Test

## Hard Invariants — Never Break These

1. **`oracle/deduction.py` has zero LLM dependencies.** It imports only `yaml`, `pathlib`, and stdlib. Never add imports from `langchain`, `ollama`, or any ML library.
2. **The `InvestigationEngine` class owns all state.** State lives as instance attributes. Methods return typed result dataclasses — never raw strings or dicts.
3. **The deterministic parser handles evidence parsing, not any LLM.** Evidence vocabulary is closed (7 types + synonyms). Confirm/rule_out maps to lexical patterns.
4. **Response templates are pure functions.** `build_response(result) -> str` takes a typed result and returns a string. No side effects, no state mutation.
5. **Rule-out signals take precedence** over confirm signals when both match (e.g., "don't have" contains "have" but is a negation).

## Build / Test / Run

```bash
# Install dependencies (text only)
pip install -e ".[dev]"

# Install with voice output (TTS + radio FX)
pip install -e ".[dev,voice]"

# Install with voice input + output (wake word + STT + TTS)
pip install -e ".[dev,voice-full]"

# Run all tests (voice tests use mocks — no audio hardware needed)
pytest tests/ -v

# Run integration tests that need real Kokoro model
pytest tests/ -v --run-integration

# Start Oracle (text mode)
python -m oracle --text --difficulty professional

# Start Oracle with voice output (CB radio FX)
python -m oracle --text --speak --difficulty professional

# Start Oracle hands-free (wake word + STT + TTS)
python -m oracle --voice --difficulty professional

# Preview radio FX (standalone tuning tool)
python tools/radio_preview.py
```

### Voice Testing Notes

- Voice unit tests mock Kokoro, RealtimeSTT, and sounddevice — they run without audio deps
- Tests marked `@pytest.mark.integration` need real Kokoro model files
- All tests should pass with `pytest tests/ -v` (no voice deps needed)
- Audio invariant: all audio is float32, clipped to [-1.0, 1.0] before playback
- `sd.play()` is non-blocking to allow wake word barge-in to interrupt TTS playback

## Architecture — Deterministic Pipeline

```
user_text → parser.py (regex + fuzzy matching, instant)
                |
                v
         runner.py (DISPATCH table maps action → engine method)
                |
                v
         engine.py (InvestigationEngine — state mutations, deduction)
                |
                v
         responses.py (typed result → scripted string template)
                |
                v
         output (Rich terminal + optional TTS with radio FX)
```

### File responsibilities

- `oracle/parser.py` — Deterministic regex parser. Classifies evidence, init, state queries, ghost lookups, behavioral events, guesses, lock-ins, ghost tests. Returns `ParsedIntent`.
- `oracle/deduction.py` — Pure Python rules engine. No LLM, ever.
- `oracle/engine.py` — `InvestigationEngine` class. All state mutations happen here. Each method returns a typed result dataclass.
- `oracle/responses.py` — Response builder. Pattern-matches result types to string templates.
- `oracle/runner.py` — Main loop with I/O protocols (`InputProvider`/`OutputHandler`). Text mode and voice mode share the same loop.
- `oracle/state.py` — Type definitions for evidence, difficulty, investigation phase.
- `oracle/config/settings.py` — Pydantic settings from `.env.local`.
- `oracle/config/ghost_database.yaml` — 27 ghosts. Source of truth for evidence/eliminators.
- `oracle/config/evidence_synonyms.yaml` — Maps spoken/typed evidence strings to canonical IDs.
- `oracle/config/ghost_tests.yaml` — Deterministic ghost tests (pass/fail).
- `oracle/voice/tts.py` — TTSProvider protocol + Kokoro-onnx wrapper. Swappable TTS backend.
- `oracle/voice/stt.py` — STTProvider protocol + VoiceInput class. RealtimeSTT wrapper with wake word detection and barge-in support.
- `oracle/voice/radio_fx.py` — CB radio FX chain (band-pass, saturation, limiter, noise, assets). Composable stages.
- `oracle/voice/audio_config.py` — Audio pipeline constants, STT config, VB-Cable device discovery. Each FX stage independently toggleable.

## Key Design Decisions

- **Pivot from LangGraph/LLM (2026-04-01)** — LLM narration was buggy and added 2-5s latency. See `INSIGHTS.md` for lessons learned. Archived code in `archive/langgraph-v1/`.
- **Legacy code:** `main.py` and `graph/` at project root are from the pre-pivot LangGraph architecture. Not used — the current entry point is `oracle/runner.py`. Do not modify these files.
- **InvestigationEngine class** replaces the old `_state` dict + `bind_state()`/`sync_state_from()` pattern. State is owned, not borrowed.
- **Typed result dataclasses** as the engine→response contract. One dataclass per action type (EvidenceResult, GhostQueryResult, etc.).
- **I/O Protocols** allow swapping text↔voice without touching the runner loop.
- **STT fuzzy matching** — `_apply_stt_corrections()` in parser.py fixes common speech-to-text mishearings before pattern matching.
- **Evidence synonym normalization** happens at the top of `record_evidence()` before validation.
- **Mimic handling:** orb is observable but not real evidence. 4 confirmed evidence + orb = Mimic lock-in.

## Documentation Index

| Document | Read when... |
|----------|-------------|
| `INSIGHTS.md` | Understanding why we pivoted from LLM to deterministic |
| `BENCHMARK_GUIDE.md` | Measuring Kokoro TTS latency on target hardware |
| `docs/Ghost Identification Guide.md` | Game mechanics reference |
| `docs/Sprint 3b - Voice Pipeline.md` | Voice output sprint spec (complete) |
| `docs/test-audit/` | Hawk + Viper test audit reports from Sprint 3c |
| `archive/langgraph-v1/` | Reference for the old LangGraph implementation |
