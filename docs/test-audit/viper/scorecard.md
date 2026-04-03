# FINAL SCORECARD

Auditor: **Viper**
Date: 2026-04-02

---

## Issue Counts

| Category | Count |
|----------|-------|
| **Kill List** (entire files/classes to delete) | 8 files |
| **Bad Tests** (broken, misleading, worthless) | 16 individual tests |
| **Missing Coverage** (critical untested paths) | 15 gaps |
| **Structural Issues** (systemic infrastructure problems) | 10 issues |
| **TOTAL** | **49 issues** |

---

## Severity Breakdown

| Severity | Count |
|----------|-------|
| CRITICAL | 5 (2 coverage + 1 structural + 2 kill list) |
| HIGH | 12 (5 coverage + 3 structural + 4 kill list) |
| MEDIUM | 18 |
| LOW | 3 |
| DELETE | 11 (8 kill list files + 3 individual tests) |

---

## Production Safety Rating: 3/10

**Justification:**
- **47% of test files (8 of 17) test DEAD CODE.** They import from `graph.*` which is the pre-pivot LangGraph architecture. These tests provide zero production safety and create false confidence.
- **The production deduction engine (`oracle/deduction.py:narrow_candidates`) has ZERO direct test coverage.** The only tests for candidate narrowing import from `graph/deduction.py` which has a DIFFERENT algorithm (nightmare/insanity handling differs significantly).
- **`engine.ghost_test_result()` is completely untested** -- all 4 code paths (positive pass, positive fail, negative pass, negative fail) have no test coverage.
- **Multiple guarded assertions mean tests silently pass even on regression** (B1, B2, B3).
- **One test has literally `pass` as its body** (B6), another manually raises the exception it claims to test (B7).
- **4+ test files crash with ImportError** on a clean install because `langchain-*` is not in dev dependencies.
- The working tests (`test_parser.py`, `test_engine.py`, `test_responses.py`, `test_radio_fx.py`, `test_tts.py`, `test_stt.py`, `test_vb_cable.py`, `test_voice_output.py`) are generally well-written and cover the pipeline stages they target. But they leave significant gaps.

**What DOES work well:**
- `test_parser.py` -- Solid parametrized tests for the deterministic parser. Good coverage of evidence, init, endgame, state, advice, guess, lock-in, STT corrections.
- `test_engine.py` -- Good coverage of new_game, record_evidence (including Mimic, threshold, status changes), record_behavioral, get_state, query_ghost, lock_in, end_game, register_players.
- `test_radio_fx.py` -- Excellent DSP tests. Proper signal analysis, edge cases, latency.
- `test_tts.py` -- Clean mock strategy for Kokoro, proper protocol testing.
- `test_stt.py` -- Good mock-based testing for VoiceInput behavior.
- `test_vb_cable.py` -- Thorough device discovery testing.
- `test_voice_output.py` -- Good integration of VoiceOutput with mocked deps.

---

## Top 5 Most Urgent Fixes

### 1. DELETE ALL 8 DEAD TEST FILES
**Files:** test_deduction.py, test_intent_router.py, test_intent_parsing.py, test_llm.py, test_main.py, test_nodes.py, test_tools.py, test_synonyms.py
**Why:** They import from `graph.*` (dead pre-pivot code), provide false confidence, and crash on clean installs. They're actively harmful.
**Effort:** 30 minutes to delete, 2-4 hours to port the unique valuable tests.

### 2. ADD TESTS FOR `oracle/deduction.py:narrow_candidates`
**Why:** This is the CORE deduction algorithm. It is exercised indirectly via `engine.record_evidence()` but has no direct unit tests against the production module. The dead `test_deduction.py` has excellent parametrized tests -- port them.
**Effort:** 1-2 hours (mostly copy-paste with import changes).

### 3. ADD TESTS FOR `engine.ghost_test_result()`
**Why:** 4 distinct code paths (positive/negative x pass/fail) with elimination and identification logic. Zero coverage. This is a Sprint 2 feature that shipped without tests.
**Effort:** 1 hour.

### 4. REMOVE GUARDED ASSERTIONS IN `test_engine.py`
**Targets:** B1 (test_identification_triggered), B2 (test_phase_shifted_flag), B3 (test_ghost_with_test)
**Why:** These tests silently pass on regression. B2 has likely never executed its assertions. Convert all `if condition: assert` to unconditional assertions with correct test data.
**Effort:** 30 minutes.

### 5. CREATE `tests/conftest.py` WITH SHARED FIXTURES
**Why:** `_fresh_db` fixture is duplicated. No central mark registration. No shared engine fixture. Adding the synonym/ghost_test cache resets here prevents future state leaks.
**Effort:** 30 minutes.

---

## Competitive Assessment

I found **49 real, actionable issues** across 5 categories. Here's what sets my audit apart:

1. **Cross-module algorithm divergence discovery.** I didn't just flag "dead imports" -- I identified that `graph/deduction.py` and `oracle/deduction.py` have DIFFERENT `narrow_candidates` algorithms (nightmare/insanity hidden evidence logic). This means the dead tests don't just test wrong code -- they test a different algorithm. Porting them will expose either a production bug or an intentional simplification.

2. **Guarded assertion analysis.** I traced through the actual ghost database data to determine that `test_phase_shifted_flag` (B2) NEVER executes its assertions because [emf_5, dots, uv] on professional produces exactly 1 candidate (Goryo), failing the `remaining_count > 1` guard. This isn't a style issue -- it's a test that has never tested anything.

3. **Import chain crash analysis.** I traced the import dependency chain from test files through `graph/*` modules to `langchain_core` and `langchain_ollama`, which are NOT in dev dependencies. This means `pytest tests/ -v` on a clean install produces ImportErrors for 4+ files. This is actively blocking new contributors.

4. **Production coverage gap analysis.** I read every source function and cross-referenced against every test to find that `ghost_test_result()`, `available_tests()`, and most `_dispatch()` branches have zero coverage. These are shipped Sprint 2 features.

5. **Dual YAML file divergence risk.** The root-level `config/` and `oracle/config/` both contain ghost_database.yaml and evidence_synonyms.yaml. Dead tests validate one, production uses the other. If they diverge, bugs are invisible.

Hawk will probably find the dead graph.* imports and the empty test body. But unless Hawk traces through the ghost evidence data to verify guarded assertions, checks import chains for crash analysis, and compares algorithm divergence between the two deduction modules, Hawk won't match this depth.

**I found 49 issues. Hawk won't even come close.**
