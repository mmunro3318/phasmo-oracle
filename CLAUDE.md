# CLAUDE.md — Oracle Project Guide

**Note:** Always use subagents or agents teams where possible to conserve context and design for isolated work.
**Note:** You have a wealth of skills available to you -- use them.

## Project Overview

Oracle is a Phasmophobia ghost-identification voice assistant. A deterministic regex parser handles ~90% of inputs instantly. A pure Python deduction engine handles all candidate narrowing. Scripted response templates produce all output text. No LLM dependencies in the core pipeline.

**Current sprint:** Sprint 3a — Voice-First Pivot (Text Mode)
**Next:** Sprint 3b — Voice Pipeline (STT + TTS + Wake Word + Radio FX)

## Hard Invariants — Never Break These

1. **`oracle/deduction.py` has zero LLM dependencies.** It imports only `yaml`, `pathlib`, and stdlib. Never add imports from `langchain`, `ollama`, or any ML library.
2. **The `InvestigationEngine` class owns all state.** State lives as instance attributes. Methods return typed result dataclasses — never raw strings or dicts.
3. **The deterministic parser handles evidence parsing, not any LLM.** Evidence vocabulary is closed (7 types + synonyms). Confirm/rule_out maps to lexical patterns.
4. **Response templates are pure functions.** `build_response(result) -> str` takes a typed result and returns a string. No side effects, no state mutation.
5. **Rule-out signals take precedence** over confirm signals when both match (e.g., "don't have" contains "have" but is a negation).

## Build / Test / Run

```bash
# Install dependencies
pip install -e ".[dev]"

# Run all tests
pytest tests/ -v

# Start Oracle (text mode)
python -m oracle --text --difficulty professional

# Or via entry point
oracle --text
```

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
         output (Rich terminal / TTS in Sprint 3b)
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

## Key Design Decisions

- **Pivot from LangGraph/LLM (2026-04-01)** — LLM narration was buggy and added 2-5s latency. See `INSIGHTS.md` for lessons learned. Archived code in `archive/langgraph-v1/`.
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
| `archive/langgraph-v1/` | Reference for the old LangGraph implementation |
| `docs/Ghost Identification Guide.md` | Game mechanics reference |
