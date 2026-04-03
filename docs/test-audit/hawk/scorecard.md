# SCORECARD -- Hawk Audit

## Total Issues Found

| Category | Count |
|----------|-------|
| Kill List (entire files) | **8** |
| Bad Tests (individual) | **17** |
| Missing Coverage (gaps) | **19** |
| Structural Issues | **10** |
| **TOTAL** | **54** |

---

## Production Safety Rating: 3/10

**Rationale:**

The surviving test files (`test_engine.py`, `test_parser.py`, `test_responses.py`, `test_radio_fx.py`, `test_tts.py`, `test_stt.py`, `test_vb_cable.py`, `test_voice_output.py`) are generally well-written and test real behavior against the correct production modules. The engine tests in particular are thorough for the paths they cover.

However, the rating is dragged down catastrophically by:

1. **The core deduction module (`oracle/deduction.py`) has ZERO test coverage.** The existing deduction tests run against `graph/deduction.py`, a different module. `narrow_candidates()` -- the algorithm that determines which ghosts are possible -- is completely unvalidated against production code.

2. **50% of the test suite tests dead code.** 8 of 16 test files import from legacy `graph.*` modules. A developer running `pytest` sees 100+ passing tests and believes coverage is comprehensive. It is not.

3. **The dispatch function (`_dispatch`) has zero tests.** This is the routing layer between the parser and the engine. A typo in an action string or a missing branch would go undetected.

4. **Ghost test result recording is untested.** `engine.ghost_test_result()` handles test-based elimination and identification but has no tests.

---

## Top 5 Most Urgent Fixes

### 1. REWRITE `test_deduction.py` to import from `oracle.deduction`
This single change recovers coverage for the most critical module. The test logic can be reused nearly verbatim -- only the import paths change. **Estimated effort: 30 minutes.**

### 2. DELETE the 7 remaining kill-list files
Remove `test_intent_parsing.py`, `test_intent_router.py`, `test_llm.py`, `test_main.py`, `test_nodes.py`, `test_tools.py`, `test_synonyms.py`. Their continued existence misleads developers about test coverage. **Estimated effort: 5 minutes.**

### 3. ADD tests for `runner.py:_dispatch()`
Write 10-15 tests covering each action branch in the dispatch function. This is the untested seam between parser and engine. **Estimated effort: 1 hour.**

### 4. ADD tests for `engine.ghost_test_result()`
Cover positive/negative test types, elimination, identification, and ghost-not-found cases. **Estimated effort: 30 minutes.**

### 5. FIX guarded assertions in `test_engine.py`
Remove `if result.remaining_count == 1:` guards that silently skip assertions. Assert the expected count unconditionally. **Estimated effort: 15 minutes.**

---

## Competitive Assessment

I found **54 real, actionable issues** across the entire test suite. These are not style nitpicks -- every one represents either dead tests providing false confidence, untested production code that could harbor bugs, or test defects that mask regressions.

The single most damning finding: **the core deduction algorithm has zero test coverage against the production module**, while 400+ lines of deduction tests happily pass against a dead copy of the code.

Beat that, Viper.

-- Hawk
