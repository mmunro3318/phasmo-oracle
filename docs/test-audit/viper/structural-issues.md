# STRUCTURAL ISSUES -- Systemic Problems in the Test Infrastructure

Auditor: **Viper**
Date: 2026-04-02

---

## S1. DUAL DATABASE PROBLEM -- graph/ and oracle/ load different YAML files

**Severity: CRITICAL**

The project has two copies of the ghost database:
- `config/ghost_database.yaml` (loaded by `graph/deduction.py` via `Path(__file__).parent.parent / "config"`)
- `oracle/config/ghost_database.yaml` (loaded by `oracle/deduction.py` via `Path(__file__).parent / "config"`)

Both `deduction.py` files have a global `_DB` cache. The dead test files (`test_deduction.py`, `test_tools.py`, `test_synonyms.py`) import from `graph/deduction.py` and test against the root `config/ghost_database.yaml`. The live test files (`test_engine.py`, `test_parser.py`) import from `oracle/` and test against `oracle/config/ghost_database.yaml`.

If these YAML files ever diverge (someone edits one but not the other), **half the tests pass with wrong data**. There's no CI check ensuring they stay synchronized.

**Fix:** Delete root-level `config/` directory (it's dead code data). Or add a test that asserts the two YAML files are identical.

---

## S2. DUAL SYNONYM FILES

**Severity: HIGH**

Same problem as S1 but for evidence synonyms:
- `config/evidence_synonyms.yaml` (root level, used by `graph/tools.py`)
- `oracle/config/evidence_synonyms.yaml` (used by `oracle/engine.py`)

`test_synonyms.py` hardcodes the path to the root-level file (line 21):
```python
path = Path(__file__).parent.parent / "config" / "evidence_synonyms.yaml"
```

This tests the dead copy, not the production copy.

**Fix:** Delete root-level `config/evidence_synonyms.yaml`. Redirect `test_synonyms.py` to `oracle/config/evidence_synonyms.yaml`.

---

## S3. MODULE-LEVEL GLOBAL STATE IN `deduction.py` (both copies)

**Severity: MEDIUM**

Both `graph/deduction.py` and `oracle/deduction.py` use a module-level `_DB: dict | None = None` cache. The `test_engine.py` `_fresh_db` autouse fixture correctly resets `oracle.deduction._DB` via `reset_db()`. But:

1. `test_deduction.py` resets `graph.deduction._DB` -- different module, different global
2. If both test files run in the same pytest session (they do, since `testpaths = ["tests"]`), the `graph.deduction._DB` and `oracle.deduction._DB` are separate globals. No cross-contamination here. BUT:
3. `oracle/engine.py` calls `from oracle.deduction import load_db` which uses `oracle.deduction._DB`. If any test modifies the DB dict in-place (not just reassigns _DB), mutations leak to subsequent tests.

The real risk: `load_db()` returns the same dict object every time after first load. If a test mutates `db["ghosts"]` (e.g., appending or modifying a ghost entry), that mutation persists for all subsequent tests. The `reset_db()` call creates a fresh load, but only if `_DB` is set to None first.

The `_fresh_db` fixture in `test_engine.py` does:
```python
reset_db()  # Sets _DB = None
yield
reset_db()  # Sets _DB = None again
```

This is correct but fragile -- it depends on no test holding a reference to the old DB dict across the yield. The `InvestigationEngine.__init__` stores `self._db = load_db()` which is a reference to the cached dict. If the fixture resets _DB during teardown, the engine's `self._db` still points to the old dict. This is fine for test isolation (each test gets a fresh engine), but could cause subtle issues if a test modifies the dict.

**Fix:** Consider making `load_db()` return a deep copy, or document the constraint.

---

## S4. MODULE-LEVEL GLOBAL STATE IN `engine.py` -- Synonym and Ghost Test caches

**Severity: MEDIUM**

`oracle/engine.py` has two module-level caches:
- `_SYNONYMS: dict[str, str] | None = None` (line 48)
- `_GHOST_TESTS: dict[str, dict] | None = None` (line 79)

Neither is reset by any test fixture. Once loaded in the first test, they persist for the entire session. If a test needed to verify behavior with modified synonyms or tests, it couldn't -- the cache would serve stale data.

The `_fresh_db` fixture in `test_engine.py` only resets `oracle.deduction._DB`, not `oracle.engine._SYNONYMS` or `oracle.engine._GHOST_TESTS`.

**Current risk:** Low, because no test currently modifies these. But it's a ticking bomb for future tests.

**Fix:** Add `_SYNONYMS = None` and `_GHOST_TESTS = None` reset to the autouse fixture, or provide reset functions.

---

## S5. NO `conftest.py` -- No shared fixtures, no marks configuration

**Severity: MEDIUM**

There is no `conftest.py` in the `tests/` directory or project root. This means:
- The `_fresh_db` fixture is duplicated across test files (once in `test_engine.py`, once in `test_deduction.py`)
- There's no central place to register custom marks (`llm`, `integration`)
- No session-scoped fixtures for expensive setup (like loading the ghost database once)
- No `filterwarnings` configuration for known deprecation warnings
- No `pytest_collection_modifyitems` hook to auto-skip dead tests

**Fix:** Create `tests/conftest.py` with shared fixtures (fresh_db, engine, etc.) and mark registration.

---

## S6. `pyproject.toml` testpaths includes dead tests

**Severity: HIGH**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```

This runs ALL tests in `tests/`, including the 8 dead files that import from `graph.*`. If `graph/` modules have import errors (e.g., `langchain_core` not installed in dev environment), these tests will fail with ImportError, not with meaningful test failures. This creates noise in CI output.

The `[project.optional-dependencies]` section shows that `langchain_ollama` and `langchain_core` are NOT in any dependency group. This means `test_tools.py`, `test_nodes.py`, `test_llm.py`, and `test_main.py` will **crash with ImportError** in a clean install. The dead tests break the test suite for new contributors.

**Fix:** Either add `langchain-*` to dev dependencies, move dead tests to a separate directory, or delete them (preferred).

---

## S7. `graph/tools.py` requires `langchain_core` at import time

**Severity: HIGH (for test suite health)**

`graph/tools.py` line 11: `from langchain_core.tools import tool`
`graph/nodes.py` line 14: `from langchain_core.messages import SystemMessage, HumanMessage`
`graph/llm.py` line 12: `from langchain_ollama import ChatOllama`

These are not in `pyproject.toml` dependencies. Any test that imports from `graph.*` will fail with `ModuleNotFoundError` in a fresh dev environment without these packages. This means:
- `test_deduction.py` -- crashes at import (imports `graph.deduction` which is OK -- no langchain)
- `test_tools.py` -- crashes at import (`graph.tools` imports `langchain_core`)
- `test_nodes.py` -- crashes at import (`graph.nodes` imports `langchain_core`)
- `test_llm.py` -- crashes at import (`graph.llm` imports `langchain_ollama`)
- `test_intent_router.py` -- probably OK (graph.intent_router has no langchain imports)
- `test_synonyms.py` -- crashes at import (`graph.tools` imports `langchain_core`)
- `test_main.py` -- probably OK (main.py doesn't directly import langchain, but imports graph.tools transitively)

Wait: `test_deduction.py` imports from `graph.deduction` which does NOT import langchain. So it would work. But `test_synonyms.py` imports `from graph.tools import normalize_evidence_id, VALID_EVIDENCE, _load_synonyms` which DOES import langchain at the top of `graph/tools.py`. So `test_synonyms.py` crashes.

**Result:** In a clean `pip install -e ".[dev]"` environment, at least 4 of 17 test files crash at import time. pytest collects them as errors, not skips. This is actively harmful to developer experience.

---

## S8. Test data validation: `test_deduction.py` soft fact eliminators depend on YAML data

**Severity: MEDIUM**

`TestApplySoftFactEliminators` (in dead `test_deduction.py`) asserts that `model_gender: "male"` eliminates Banshee and Dayan. This requires `ghost_database.yaml` to have `soft_fact_eliminators` entries for those ghosts. The first 100 lines of the YAML don't show these entries. They must be deeper in the file. If the YAML is restructured and these entries are removed, the test silently starts passing vacuously (empty eliminated list would not contain Banshee, and the test asserts `"Banshee" in eliminated` which would fail). So actually the test would catch the removal -- but only if it's not masked by the import crash (S7).

**Fix:** This is handled by kill-list. When porting to oracle.deduction, verify the YAML entries exist.

---

## S9. `oracle/engine.py:_load_synonyms` -- Global module state loaded from filesystem

**Severity: LOW**

`_load_synonyms()` reads from `config.SYNONYMS_PATH` which is a filesystem path. Tests that call `record_evidence()` indirectly trigger synonym loading. If the YAML file is missing or corrupt, tests fail with an unhelpful I/O error rather than a clear test setup failure. No fixture ensures the synonym file exists before tests run.

Similarly, `_load_ghost_tests()` reads from `config.GHOST_TESTS_PATH`.

**Fix:** Low priority. The YAML files are in the repo and always present. But consider adding a session-scoped fixture that validates all config files exist before any tests run.

---

## S10. Non-deterministic noise in radio FX tests

**Severity: LOW**

`test_radio_fx.py:TestConfidenceCodedNoise.test_more_candidates_means_more_noise` (line 153) creates silence, applies noise, then compares RMS values. The noise is generated with `np.random.default_rng()` (no seed) on line 179 of `radio_fx.py`. This means each test run gets different noise. The test asserts `rms_27 > rms_1 * 2` which should be statistically robust due to the 6.67x sigma ratio (0.020 vs 0.003), but could theoretically flake on an extremely unlucky seed.

**Fix:** Low priority. The statistical margin is large enough. But for absolute determinism, seed the RNG in the fixture.

---

## Summary

| ID | Issue | Severity | Impact |
|----|-------|----------|--------|
| S1 | Dual ghost database YAML | CRITICAL | Tests validate wrong data |
| S2 | Dual synonym YAML | HIGH | Synonym tests on wrong file |
| S3 | Module-level _DB cache | MEDIUM | Potential mutation leaks |
| S4 | Synonym/ghost test caches | MEDIUM | No reset in fixtures |
| S5 | No conftest.py | MEDIUM | Duplicated fixtures, no marks |
| S6 | testpaths includes dead tests | HIGH | CI runs dead tests |
| S7 | langchain not in dev deps | HIGH | 4+ tests crash on clean install |
| S8 | Soft fact test data coupling | MEDIUM | YAML-dependent assertions |
| S9 | Filesystem-dependent loading | LOW | Unhelpful errors if files missing |
| S10 | Non-deterministic noise | LOW | Theoretical flakiness |

**10 structural issues identified. 1 CRITICAL, 3 HIGH, 4 MEDIUM, 2 LOW.**
