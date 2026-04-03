# KILL LIST -- Hawk Audit

Files or entire test classes that should be **deleted** because they test dead code, import from non-existent (legacy) modules, or are fully superseded.

---

## 1. `tests/test_deduction.py` -- ENTIRE FILE

**Why it should die:** Every import is from `graph.deduction`, which is the **pre-pivot LangGraph-era** module. The current production code lives in `oracle/deduction.py`. These tests exercise the legacy `graph/deduction.py` (still present on disk but not used by the application). Running them gives false confidence because they pass against code that is never called in production.

**Imports:**
```python
from graph.deduction import (
    all_ghost_names, apply_observation_eliminator, get_ghost,
    load_db, narrow_candidates, reset_db,
)
```

The Sprint 2 classes inside (`TestEvidenceThresholdReached`, `TestEliminateByGuaranteedEvidence`, `TestRankDiscriminatingTests`, `TestApplySoftFactEliminators`) all import from `graph.deduction` as well.

**What should replace it:** A new `tests/test_deduction.py` importing from `oracle.deduction`. The test logic can be reused nearly verbatim since `oracle/deduction.py` has the same API, but the imports must change. This is not a cosmetic rename -- the `graph/` code and `oracle/` code could diverge silently.

---

## 2. `tests/test_intent_parsing.py` -- ENTIRE FILE

**Why it should die:** This file tests the **old LangGraph + Ollama pipeline**. It imports from `config.settings` (the old pre-pivot config) and `graph.llm`, `graph.graph`, `graph.tools`. It requires a running Ollama instance with a specific model. The project has pivoted to a deterministic parser (`oracle/parser.py`) with zero LLM dependencies.

**Key evidence:**
- Line 16: `from config.settings import config`
- Line 43-46: `from graph.llm import init_llm`, `from graph.graph import oracle_graph`, `from graph.tools import bind_state, sync_state_from`
- All test classes are marked `@skip_no_ollama` and use `pytest.mark.llm`
- The equivalent deterministic tests now live in `tests/test_parser.py` and `tests/test_intent_router.py`

**What should replace it:** Nothing. `tests/test_parser.py` already covers the same intent classification scenarios deterministically.

---

## 3. `tests/test_intent_router.py` -- ENTIRE FILE

**Why it should die:** Imports from `graph.intent_router`, the **old pre-pivot module**. The current production parser is `oracle/parser.py`. The test file duplicates coverage that `tests/test_parser.py` already provides against the correct module.

**Import:** `from graph.intent_router import parse_intent` (line 9)

**Critical behavioral difference:** The old `graph/intent_router.py` returns `action="llm_fallback"` for unknown inputs and `action="null"` for empty input. The new `oracle/parser.py` returns `action="unknown"` for both. Tests in `test_intent_router.py` assert the old behaviors (see `TestLLMFallback` at line 238 and `TestEdgeCases` at line 254). These tests pass against the wrong module and would FAIL against the production code, masking regressions.

**What should replace it:** Nothing. `tests/test_parser.py` covers the same scenarios against the correct module.

---

## 4. `tests/test_llm.py` -- ENTIRE FILE

**Why it should die:** Tests `graph/llm.py` which is the old LangGraph-era LLM factory. Imports `graph.llm`, tests `_check_ollama_health`, `get_llm`, `init_llm`, `ChatOllama` -- all dead code from the pre-pivot architecture. The current production pipeline has zero LLM dependencies.

**What should replace it:** Nothing. There is no LLM in the current architecture.

---

## 5. `tests/test_main.py` -- ENTIRE FILE

**Why it should die:** Tests `main.py` at the project root, which is the **old LangGraph entry point**. Imports `from main import make_initial_state, run_diagnostics, SessionLogger` (line 9). The current entry point is `oracle/runner.py`.

- `TestMakeInitialState` tests the old state factory that creates a dict with `speaker`, `messages`, `oracle_response`, `parsed_intent` fields -- this is the LangGraph state shape, not the `InvestigationEngine` approach.
- `TestRunDiagnostics` tests Ollama connectivity checks that no longer exist in the current architecture.
- `TestSessionLogger` tests the old JSONL session logger from `main.py`, not the JSON history writer in `oracle/engine.py._save_session`.

**What should replace it:** Tests for `oracle/runner.py` dispatch and loop logic. `tests/test_voice_output.py:TestSpeakingFlag` already partially covers `run_loop`.

---

## 6. `tests/test_nodes.py` -- ENTIRE FILE

**Why it should die:** Tests `graph/nodes.py` -- the LangGraph graph node functions (`build_state_summary`, `parse_intent_node`, `execute_tool_node`, `route_after_parse`, `route_after_tools`, `identify_node`, `phase_shift_node`). These are all part of the dead LangGraph architecture. The current architecture uses `oracle/runner.py:_dispatch()` for routing.

Additionally, `TestExecuteToolNode` calls `from graph.tools import bind_state` which mutates the old global `_state` dict -- a pattern replaced by `InvestigationEngine` instance attributes.

**What should replace it:** Tests for `oracle/runner.py:_dispatch()` function. Currently there are zero dedicated tests for `_dispatch`.

---

## 7. `tests/test_tools.py` -- ENTIRE FILE

**Why it should die:** Tests `graph/tools.py` -- the old `@tool`-decorated LangChain tools (`init_investigation`, `record_evidence`, `record_behavioral_event`, `get_investigation_state`, `query_ghost_database`, `register_players`, `record_theory`, `suggest_next_evidence`). These are the pre-pivot tool functions that used global `_state` dict + `bind_state()`/`sync_state_from()`.

The current architecture uses `InvestigationEngine` methods directly. `tests/test_engine.py` already covers the equivalent functionality.

**What should replace it:** Nothing. `tests/test_engine.py` already covers all engine operations.

---

## 8. `tests/test_synonyms.py` -- ENTIRE FILE

**Why it should die:** Imports from `graph.tools` (line 5: `from graph.tools import normalize_evidence_id, VALID_EVIDENCE, _load_synonyms`). Tests the old synonym normalization from the LangGraph-era tools module. The YAML file path in line 20 (`Path(__file__).parent.parent / "config" / "evidence_synonyms.yaml"`) points to `config/evidence_synonyms.yaml` (the old config directory), not `oracle/config/evidence_synonyms.yaml`.

`tests/test_engine.py:TestRecordEvidence` already tests synonym normalization via `oracle/engine.py:normalize_evidence_id()`.

**What should replace it:** A new synonym test file importing from `oracle.engine` and reading from `oracle/config/evidence_synonyms.yaml`.

---

## Summary

| File | Imports From | Should Die Because | Replacement |
|------|-------------|-------------------|-------------|
| `test_deduction.py` | `graph.deduction` | Tests dead module | Rewrite with `oracle.deduction` imports |
| `test_intent_parsing.py` | `config.settings`, `graph.*` | Tests Ollama/LangGraph pipeline | `test_parser.py` exists |
| `test_intent_router.py` | `graph.intent_router` | Tests old parser with wrong behaviors | `test_parser.py` exists |
| `test_llm.py` | `graph.llm` | Tests dead LLM factory | None needed |
| `test_main.py` | `main` (root) | Tests dead entry point | Test `oracle/runner.py` |
| `test_nodes.py` | `graph.nodes`, `graph.tools` | Tests dead graph nodes | Test `_dispatch()` |
| `test_tools.py` | `graph.tools` | Tests dead tool functions | `test_engine.py` exists |
| `test_synonyms.py` | `graph.tools` | Tests old synonym loader + wrong path | Rewrite with `oracle.engine` |

**8 files should be killed.** That is half the entire test suite (8 of 16 non-init test files).
