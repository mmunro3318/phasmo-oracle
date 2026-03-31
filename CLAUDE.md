# CLAUDE.md — Oracle Project Guide

## Project Overview

Oracle is a Phasmophobia ghost-identification assistant built as a LangGraph two-stage chain. A deterministic regex router handles ~85% of inputs instantly; the LLM only does intent classification for ambiguous inputs and generates 2-sentence narrative responses. A pure Python deduction engine handles all candidate narrowing. The LLM never reasons about ghost identity.

**Current sprint:** Sprint 1 — Core Agent Loop (Text-First)
**Model:** qwen2.5:7b via Ollama (phi4-mini was tried and failed at tool calling)

## Hard Invariants — Never Break These

1. **The LLM never writes to `OracleState` directly.** All state mutations happen inside tool functions in `graph/tools.py` via the shared `_state` dict.
2. **`graph/deduction.py` has zero LLM dependencies.** It imports only `yaml`, `pathlib`, and stdlib. Never add imports from `langchain`, `ollama`, or `graph.llm`.
3. **Tools write to `_state`, never to a local copy.** Every tool function uses the module-level `_state` dict bound by `bind_state()`. Never create a `new_state = {}` inside a tool.
4. **`oracle_correct` has three states: `1`, `0`, and `None`.** Never coerce `None` to `False` or `0`.
5. **The deterministic intent router handles evidence parsing, not the LLM.** The LLM is only used for narration and ambiguous input classification. Never route evidence confirm/rule_out through the LLM classifier.

## Build / Test / Run

```bash
# Install dependencies (includes pytest)
pip install -e ".[dev]"

# Pull the LLM model (requires Ollama running)
ollama pull qwen2.5:7b

# Run all non-LLM tests (fast, no Ollama needed)
pytest tests/ -m "not llm" -v

# Run LLM-dependent tests (requires Ollama with qwen2.5:7b)
pytest tests/ -m llm -v

# Run all tests
pytest tests/ -v

# Start Oracle (text mode, requires Ollama)
python main.py

# Startup diagnostics
python main.py --check
```

## Architecture — Two-Stage Chain

```
user_text → intent_router.py (deterministic, instant)
                ├── [match ~85%] → tools.py (execute) → LLM narrator → response
                └── [no match]   → LLM classifier → tools.py (execute) → LLM narrator → response
```

### Graph topology (graph/graph.py)

```
parse_intent ──[deterministic match]──▶ execute_tool ──▶ narrate ──▶ END
     │
     └──[llm_fallback]──▶ llm_classify ──▶ execute_tool ──▶ narrate ──▶ END
```

### File responsibilities

- `graph/intent_router.py` — Deterministic regex router. Classifies evidence, init, state queries, ghost lookups, behavioral events. Falls back to LLM for ambiguous inputs.
- `graph/deduction.py` — Pure Python rules engine. No LLM, ever.
- `graph/tools.py` — 5 LangChain `@tool` functions + `bind_state`/`sync_state_from` + synonym normalization + over-proofed detection.
- `graph/nodes.py` — Graph nodes: `parse_intent_node`, `llm_classify_node`, `execute_tool_node`, `narrate_node`.
- `graph/graph.py` — `StateGraph` assembly with conditional routing.
- `graph/llm.py` — LLM factory. Call `init_llm()` once, then `get_llm()`.
- `config/settings.py` — All config values from `.env.local`.
- `config/ghost_database.yaml` — 27 ghosts. Source of truth for evidence/eliminators.
- `config/evidence_synonyms.yaml` — Maps LLM-generated evidence strings to canonical IDs.

## Key Design Decisions

- **Scaffold code in docs/ is reference only** — not copy-paste-ready. Review critically, especially tool call handling patterns.
- **phi4-mini failed at tool calling** — outputs tool-call syntax as plain text instead of structured JSON. Replaced with qwen2.5:7b. See `docs/Insights from Demonic Tutor.md` for prior model evaluation.
- **Deterministic router over LLM routing** — evidence vocabulary is closed (7 types + synonyms), confirm/rule_out maps to clear lexical patterns. LLM routing was unreliable for this.
- **Rule-out signals take precedence** over confirm signals when both match (e.g., "don't have" contains "have" but is a negation).
- **`bind_state()` / `sync_state_from()`** bridge LangGraph's invocation copy and the caller's live state dict. Always call both.
- **Evidence synonym normalization** happens at the top of `record_evidence()` before validation.
- **Over-proofed detection:** 4+ confirmed evidence triggers a warning. Exception: 3 + orb may indicate The Mimic.
- **Oracle persona:** Dry British wit. Professional with quiet exasperation. Never more than 2 sentences.

## Documentation Index

| Document | Read when... |
|----------|-------------|
| `AGENTS.md` | Before any code changes — full invariants, state flow, tool reference |
| `docs/Oracle Architecture Design.md` | Before touching `graph/` — rationale for tool-calling design |
| `docs/Roadmap.md` | Planning which sprint to work on |
| `docs/Sprint 1/` | Sprint 1 scaffold code and task board (reference only, not literal) |
| `docs/Insights from Demonic Tutor.md` | Lessons from the prototype — voice pipeline, model failures |
