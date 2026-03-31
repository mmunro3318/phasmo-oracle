# Memory: Initial Scaffold Design

**Date:** 2026-03-31
**Sprint:** Sprint 0 (Scaffold)
**Author:** GitHub Copilot

---

## Problem

The repository had extensive documentation but no code.  Multiple AI frameworks
would work in parallel on isolated branches.  The scaffold needed to support
all seven sprint milestones without prescribing implementation details.

---

## Investigation

Reviewed all context documentation:
- `AGENTS.md` — hard invariants and architectural rules
- `Oracle Architecture Design.md` — LangGraph tool-calling rationale
- `Roadmap.md` and all six Sprint docs — implementation order and exit criteria
- `docs/ghost_database.yaml` — 27 ghosts, evidence types, observation eliminators

---

## Solution

Created a complete Python package scaffold in this order:

1. `config/settings.py` — pydantic-settings, reads `config/.env.local`
2. `config/ghost_database.yaml` — copied from docs, single source of truth
3. `graph/state.py` — `OracleState` TypedDict with `make_initial_state()`
4. `graph/deduction.py` — pure Python, zero LLM dependencies
5. `graph/tools.py` — 8 LangChain `@tool` wrappers; all write to module-level `_state`
6. `graph/nodes.py` — `llm_node`, `identify_node`, `commentary_node`, `respond_node`, routing functions
7. `graph/graph.py` — `StateGraph` assembly with `build_graph()` and module-level `oracle_graph`
8. `graph/llm.py` — Ollama → Anthropic fallback factory
9. `graph/session_log.py` — append-only JSONL
10. `db/database.py` — SQLite CRUD
11. `db/queries.py` — read-only analytics
12. `voice/` — all voice pipeline stubs (audio_router, stt, tts, wake_word, loopback, session)
13. `ui/` — display, diagnostics, stats, replay
14. `main.py` — CLI entry point with all five modes
15. `tests/` — full test suite for deduction, triggers, DB, UI, LLM, audio

---

## Key Design Decisions

### ghost_database.yaml location
Placed in `config/` (not `docs/`) because it is a runtime dependency, not just
documentation.  The `docs/` version remains as the canonical reference; `config/`
is the live copy read by `deduction.py`.

### `bind_state` / `sync_state_from` pattern
Tools write to the module-level `_state` dict bound before each `oracle_graph.invoke()`.
After the graph returns, `sync_state_from()` copies mutations back to the caller's
live dict.  This bridges LangGraph's copy-of-state semantics with our requirement
for persistent evidence across turns.

### Observation eliminators — dict vs list
The YAML uses a `dict` structure for `observation_eliminators` (key → entry),
not a list.  `apply_observation_eliminator()` uses `dict.get(key)` for O(1) lookup.

### Nightmare difficulty — permissive
On Nightmare, `_ghost_missing_confirmed_evidence` always returns `False`, keeping
all ghosts that pass the ruled-out check as candidates.  This is intentionally
over-inclusive; see the Sprint 1 docs for the rationale.

---

## Why This Matters

The scaffold must let Sprints 1–7 proceed without rearchitecting.  All the hard
invariants in `AGENTS.md` are baked into the module boundaries:
- `deduction.py` has zero LLM imports ✓
- All state mutations go through `tools.py` ✓
- `route_after_tools` has no side effects ✓
- All `sd.play()` calls go through `AudioRouter` ✓

---

## Related Files

- `AGENTS.md` — all hard invariants
- `graph/deduction.py` — the rules engine this scaffold protects
- `tests/test_deduction.py` — must always pass
- `tests/test_triggers.py` — must always pass

---

## Follow-up

- Sprint 1: wire deduction tests and verify `python main.py --text` works end-to-end
- Sprint 7: add `behavioral_profile` to `ghost_database.yaml` and behavioral reasoning layer
