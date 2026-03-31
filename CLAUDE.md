# CLAUDE.md — Oracle Project Guide

## Project Overview

Oracle is a voice-driven Phasmophobia ghost-identification assistant built as a LangGraph tool-calling agent. The LLM handles intent parsing only; a pure Python deduction engine handles all candidate narrowing. The LLM never reasons about ghost identity.

**Current sprint:** Sprint 1 — Core Agent Loop (Text-First)

## Hard Invariants — Never Break These

1. **The LLM never writes to `OracleState` directly.** All state mutations happen inside tool functions in `graph/tools.py` via the shared `_state` dict.
2. **`graph/deduction.py` has zero LLM dependencies.** It imports only `yaml`, `pathlib`, and stdlib. Never add imports from `langchain`, `ollama`, or `graph.llm`.
3. **Tools write to `_state`, never to a local copy.** Every tool function uses the module-level `_state` dict bound by `bind_state()`. Never create a `new_state = {}` inside a tool.
4. **`oracle_correct` has three states: `1`, `0`, and `None`.** Never coerce `None` to `False` or `0`.

## Build / Test / Run

```bash
# Install dependencies
pip install -e ".[dev]"

# Pull the LLM model (requires Ollama running)
ollama pull qwen2.5:7b

# Run tests (no Ollama needed)
pytest tests/test_deduction.py tests/test_tools.py tests/test_synonyms.py tests/test_nodes.py -v

# Run LLM-dependent tests (requires Ollama with qwen2.5:7b)
pytest tests/test_intent_parsing.py tests/test_e2e.py -v

# Run all tests
pytest tests/ -v

# Start Oracle (text mode, requires Ollama)
python main.py

# Startup diagnostics
python main.py --check
```

## Architecture

```
main.py → graph/graph.py → graph/nodes.py → graph/tools.py → graph/deduction.py → ghost_database.yaml
                                ↓
                          graph/llm.py (LLM factory)
```

- `graph/deduction.py` — Pure Python rules engine. No LLM, ever.
- `graph/tools.py` — LangChain `@tool` functions. All state mutations here.
- `graph/nodes.py` — Graph nodes: `llm_node`, `extract_response`, `route_after_llm`.
- `graph/graph.py` — `StateGraph` wiring.
- `graph/llm.py` — LLM factory. Call `init_llm()` once, then `get_llm()`.
- `config/settings.py` — All config values from `.env.local`.
- `config/ghost_database.yaml` — 27 ghosts. Source of truth for evidence/eliminators.
- `config/evidence_synonyms.yaml` — Maps LLM-generated evidence strings to canonical IDs.

## Key Design Decisions

- **Scaffold code in docs/ is reference only** — not copy-paste-ready. Review critically, especially tool call handling patterns.
- **`bind_state()` / `sync_state_from()`** bridge LangGraph's invocation copy and the caller's live state dict. Always call both.
- **Evidence synonym normalization** happens at the top of `record_evidence()` before validation.
- **Over-proofed detection:** 4+ confirmed evidence triggers a warning. Exception: 3 + orb may indicate The Mimic.
- **Oracle persona:** Dry British wit. Professional with quiet exasperation. Never more than 2 sentences.

## Sprint Build Order

Build and validate in this exact sequence (Sprint 1):
1. `config/settings.py`
2. `graph/state.py`
3. `graph/deduction.py` — test first with `test_deduction.py`
4. `graph/tools.py`
5. `graph/llm.py`
6. `graph/nodes.py`
7. `graph/graph.py`
8. `main.py`

## Documentation Index

| Document | Read when... |
|----------|-------------|
| `AGENTS.md` | Before any code changes — full invariants, state flow, tool reference |
| `docs/Oracle Architecture Design.md` | Before touching `graph/` — rationale for tool-calling design |
| `docs/Roadmap.md` | Planning which sprint to work on |
| `docs/Sprint 1/` | Before implementing Sprint 1 — scaffold code, task board |
| `docs/Insights from Demonic Tutor.md` | Understanding lessons learned from the prototype |
