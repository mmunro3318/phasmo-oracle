# KILL LIST -- Files That Must Die

Auditor: **Viper**
Date: 2026-04-02

---

## 1. `tests/test_deduction.py` -- IMPORTS FROM DEAD MODULE

**Path:** `tests/test_deduction.py`
**Why it must die:** Every single import in this file is from `graph.deduction`, which is the **pre-pivot LangGraph-era module**. The current production code lives in `oracle/deduction.py`. These tests do NOT test production code.

```python
from graph.deduction import (
    all_ghost_names,
    apply_observation_eliminator,
    get_ghost,
    load_db,
    narrow_candidates,
    reset_db,
)
```

The `graph/deduction.py` loads its database from `config/ghost_database.yaml` (root-level config), while the production `oracle/deduction.py` loads from `oracle/config/ghost_database.yaml`. These could drift apart silently. Moreover, `graph/deduction.py` has a **different `narrow_candidates` implementation** -- it uses `max_hidden = 1 for nightmare, 2 for insanity` (lines 96-110), while `oracle/deduction.py` treats both nightmare and insanity identically as `permissive` (doesn't count hidden evidence). **These tests validate the WRONG algorithm.**

The Sprint 2 sections at the bottom import inline from `graph.deduction`:
- `TestEvidenceThresholdReached` -- `from graph.deduction import evidence_threshold_reached`
- `TestEliminateByGuaranteedEvidence` -- `from graph.deduction import eliminate_by_guaranteed_evidence`
- `TestRankDiscriminatingTests` -- `from graph.deduction import rank_discriminating_tests`
- `TestApplySoftFactEliminators` -- `from graph.deduction import apply_soft_fact_eliminators`

All dead module. Class-level import `from graph.deduction import eliminate_by_guaranteed_evidence` on line 455 is doubly problematic -- it runs at import time and pollutes the module scope.

**Replacement:** Port all valuable tests to import from `oracle.deduction`. The parametrized tests (`_ghost_evidence_params`, nightmare/insanity permissiveness, Mimic handling) are excellent and should be preserved -- just redirected to the real module. The `test_insanity_more_permissive` test will FAIL against `oracle/deduction.py` because the production code treats nightmare and insanity identically. This exposes a **production bug or intentional simplification** that needs investigation.

**Verdict: DELETE and rebuild from `oracle.deduction` imports.**

---

## 2. `tests/test_intent_router.py` -- IMPORTS FROM DEAD MODULE

**Path:** `tests/test_intent_router.py`
**Why it must die:** Imports `from graph.intent_router import parse_intent`. The production parser is `oracle/parser.py`. While `graph/intent_router.py` is nearly identical to `oracle/parser.py`, it's the dead pre-pivot version.

Key differences from `oracle/parser.py`:
- `graph/intent_router.py` returns `action="llm_fallback"` for unknown inputs; `oracle/parser.py` returns `action="unknown"`. Tests assert `action == "llm_fallback"` (line 249), which would FAIL against production.
- `graph/intent_router.py` returns `action="null"` for empty inputs; `oracle/parser.py` returns `action="unknown"`. Test at line 258 asserts `action == "null"`, which would FAIL against production.
- The `TestLLMFallback` class (lines 239-249) tests behavior that doesn't exist in the production parser at all.

The `TestGhostEvidenceQueryFix` test (line 361-367) is a valuable regression test but targets the wrong module.

**Replacement:** `tests/test_parser.py` already covers most of the same patterns with correct imports. Port the unique tests from this file (evidence misidentification prevention, soft fact patterns, ghost evidence query fix, theory patterns, player patterns, test query patterns) to `test_parser.py`.

**Verdict: DELETE. Merge unique cases into test_parser.py.**

---

## 3. `tests/test_intent_parsing.py` -- LLM INTEGRATION TESTS FOR DEAD ARCHITECTURE

**Path:** `tests/test_intent_parsing.py`
**Why it must die:** Tests require a running Ollama instance with phi4-mini model. Every test imports from the dead LangGraph architecture:

```python
from config.settings import config  # Dead config (not oracle.config.settings)
from graph.llm import init_llm      # Dead LLM factory
from graph.graph import oracle_graph  # Dead LangGraph graph
from graph.deduction import all_ghost_names  # Dead deduction module
from graph.tools import bind_state, sync_state_from  # Dead tools
```

The entire LLM pipeline has been replaced by `oracle/parser.py` (deterministic). These tests validate the old two-stage chain (regex -> LLM fallback) which no longer exists. They are permanently skipped in CI via `_ollama_available()` check.

The CLAUDE.md explicitly says: "Legacy code: main.py and graph/ at project root are from the pre-pivot LangGraph architecture. Not used."

**Replacement:** None needed -- the deterministic parser tests in `test_parser.py` and `test_engine.py` cover the same input patterns without LLM.

**Verdict: DELETE. No replacement needed.**

---

## 4. `tests/test_llm.py` -- TESTS FOR DEAD LLM FACTORY

**Path:** `tests/test_llm.py`
**Why it must die:** Tests `graph/llm.py` which is the Ollama/ChatOllama LLM factory from the pre-pivot architecture. Every test imports from `graph.llm`:

```python
import graph.llm as llm_mod
```

Tests mock `ChatOllama`, `httpx.get` for Ollama health checks, and `_validate_tool_calling`. None of this code is used in production. The project has zero LLM dependencies in the core pipeline.

**Replacement:** None. LLM is dead.

**Verdict: DELETE.**

---

## 5. `tests/test_main.py` -- TESTS FOR DEAD ENTRY POINT

**Path:** `tests/test_main.py`
**Why it must die:** Tests `main.py` at the project root, which is the pre-pivot LangGraph entry point. Imports:

```python
from main import make_initial_state, run_diagnostics, SessionLogger
```

The production entry point is `oracle/runner.py`. The `SessionLogger` class, `make_initial_state()`, and `run_diagnostics()` are all dead code.

The `TestRunDiagnostics.test_ollama_check_fails_gracefully` test patches `httpx.get` for Ollama connectivity -- Ollama is not used in production.

**Replacement:** None needed. `test_engine.py` already tests the current `InvestigationEngine`. Runner tests are in `test_voice_output.py`.

**Verdict: DELETE.**

---

## 6. `tests/test_nodes.py` -- TESTS FOR DEAD LANGGRAPH NODES

**Path:** `tests/test_nodes.py`
**Why it must die:** Tests `graph/nodes.py` which contains the LangGraph node functions (`build_state_summary`, `parse_intent_node`, `execute_tool_node`, `route_after_parse`, `route_after_tools`, `identify_node`, `phase_shift_node`). All dead.

The test at line 107 asserts `intent["action"] == "llm_fallback"` -- a concept that doesn't exist in the production system.

The `TestRouteAfterTools` class tests routing logic (`"identify"`, `"phase_shift"`, `"comment"`, `"normal"`) that was part of the LangGraph state machine. In the new architecture, this routing happens inside `engine.py` methods directly.

**Replacement:** The routing/identification logic is now tested implicitly via `test_engine.py` (phase shift, identification trigger, etc.). No new tests needed.

**Verdict: DELETE.**

---

## 7. `tests/test_tools.py` -- TESTS FOR DEAD TOOL IMPLEMENTATIONS

**Path:** `tests/test_tools.py`
**Why it must die:** Tests `graph/tools.py` which contains the LangChain `@tool`-decorated functions that mutate a shared `_state` dict. Every import is from the dead module:

```python
from graph.tools import (
    bind_state, sync_state_from, init_investigation,
    record_evidence, record_behavioral_event,
    get_investigation_state, query_ghost_database,
    register_players, record_theory, suggest_next_evidence,
    VALID_EVIDENCE, normalize_evidence_id, _state,
)
from graph.deduction import all_ghost_names
from graph.state import DEFAULT_SOFT_FACTS
```

The production equivalent is `oracle/engine.py::InvestigationEngine` which owns state as instance attributes instead of a shared mutable dict. The `bind_state`/`sync_state_from` pattern is explicitly called out as replaced in CLAUDE.md.

Tests directly access `_state` (the module-level mutable dict), which leaks state between tests. The `autouse` fixture does `bind_state()` then `sync_state_from()` but this is testing the old state management pattern.

**Replacement:** `test_engine.py` already covers all the same operations with the new `InvestigationEngine` API. Many tests are near-duplicates.

**Verdict: DELETE.**

---

## 8. `tests/test_synonyms.py` -- IMPORTS FROM DEAD MODULE

**Path:** `tests/test_synonyms.py`
**Why it must die:** Imports from `graph.tools`:

```python
from graph.tools import normalize_evidence_id, VALID_EVIDENCE, _load_synonyms
```

While the synonym logic is identical in `oracle/engine.py`, these tests target the dead module. Also, line 21 hardcodes the synonym YAML path:

```python
path = Path(__file__).parent.parent / "config" / "evidence_synonyms.yaml"
```

This points to the root-level `config/evidence_synonyms.yaml`, NOT `oracle/config/evidence_synonyms.yaml` which is where production reads from. If these files diverge, tests pass but production breaks.

**Replacement:** Rewrite imports to use `oracle.engine.normalize_evidence_id` and point at `oracle/config/evidence_synonyms.yaml`. The test logic itself is solid -- just wrong module.

**Verdict: DELETE and rebuild from `oracle.engine` imports.**

---

## Summary

| # | File | Why | Risk if kept |
|---|------|-----|--------------|
| 1 | test_deduction.py | Imports `graph.deduction` (dead) | Tests wrong algorithm, false confidence |
| 2 | test_intent_router.py | Imports `graph.intent_router` (dead) | Tests wrong action names |
| 3 | test_intent_parsing.py | Requires Ollama, LangGraph (dead) | Always skipped, dead code |
| 4 | test_llm.py | Tests `graph.llm` (dead) | Tests dead LLM factory |
| 5 | test_main.py | Tests `main.py` (dead) | Tests dead entry point |
| 6 | test_nodes.py | Tests `graph.nodes` (dead) | Tests dead routing logic |
| 7 | test_tools.py | Tests `graph.tools` (dead) | Tests old state pattern |
| 8 | test_synonyms.py | Imports `graph.tools` (dead) | Tests wrong module + wrong YAML path |

**8 of 17 test files (47%) test DEAD CODE.** That means nearly half the test suite provides zero production safety.
