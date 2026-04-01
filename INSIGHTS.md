# Insights from the LangGraph/LLM Phase

Documented during the voice-first pivot (2026-04-01). These lessons informed the decision to strip the LLM layer and go deterministic.

## What Worked

1. **Deterministic intent router** — Regex-based parsing handled ~85% of inputs instantly with zero latency. The pattern vocabulary for evidence confirmation/denial is closed and well-defined. This survives the pivot unchanged.

2. **Pure Python deduction engine** — `deduction.py` with zero LLM dependencies was the right call from day one. All 27 ghosts, Mimic handling, observation eliminators, difficulty thresholds — flawless. 200+ tests pass without any external services.

3. **Ghost database YAML** — Structured data (evidence, eliminators, community tests, behavioral tells) proved far more useful than free-form text. The schema grew organically across sprints and remained clean.

4. **Evidence synonym normalization** — Mapping LLM-generated strings to canonical IDs (`"fingerprints" -> "uv"`, `"emf" -> "emf_5"`) was essential. This pattern carries forward for STT mishearings.

5. **Test-first approach** — Parametrized tests across all 27 ghosts caught edge cases immediately. The Mimic fake_evidence bug was caught by tests before it ever reached a user.

## What Didn't Work

1. **LLM narration was unreliable** — qwen2.5:7b (7B parameter model) frequently said wrong things in narrator mode. It would hallucinate ghost identifications, misstate evidence, or generate responses that contradicted the tool results it was given. The narrator prompt engineering never fully solved this.

2. **Tool-calling overhead** — The LangChain `@tool` decorator + `bind_state()`/`sync_state_from()` pattern was necessary for LangGraph but added ceremony. Every tool call required binding state before and syncing after. This was a footgun that caused multiple bugs.

3. **LLM latency killed the experience** — 2-5 seconds per response on CPU inference. For a game where hunts can start any second, this made Oracle unusable as a real-time assistant. The deterministic path (regex + deduction) runs in <10ms.

4. **phi4-mini was a dead end** — Outputs tool-call syntax as plain text instead of structured JSON. Burned a full sprint evaluating it before switching to qwen2.5:7b.

5. **LangGraph conditional routing was over-engineered** — The `route_after_tools` function with 4 conditional paths (identify, phase_shift, comment, normal) was elegant but hard to debug. Simple if/elif in a main loop would have been clearer.

## Key Decision: Why We Pivoted

The deduction engine is the product. The LLM was a learning exercise that taught us about tool-calling architectures, but it was blocking the feature that actually makes Oracle exciting: **voice**. A deterministic pipeline (STT -> regex -> deduction -> scripted strings -> TTS) can respond in <500ms. The LLM added 2-5 seconds and got the answer wrong.

The LLM may return later as a "juice" layer — taking scripted responses and adding personality variation. But the core loop must be deterministic and fast.

## Archived Code

The LangGraph implementation is preserved in `archive/langgraph-v1/` for reference:
- `graph/llm.py` — Ollama LLM factory
- `graph/nodes.py` — Graph nodes (parse, classify, execute, narrate, identify, phase_shift, commentary)
- `graph/graph.py` — StateGraph assembly
- `main.py` — LangGraph-based REPL
- `tests/test_llm.py`, `tests/test_intent_parsing.py`, `tests/test_nodes.py`, `tests/test_main.py`
