# STRUCTURAL ISSUES -- Hawk Audit

Test infrastructure problems, global state pollution, non-determinism, and import masking.

---

## 1. HALF THE TEST SUITE TESTS DEAD CODE

**Severity: CRITICAL**

8 of 16 test files import from `graph.*` or `main` -- modules from the pre-pivot LangGraph architecture that is no longer the production code path. These tests all pass, but they validate dead code, not the running system.

Files affected: `test_deduction.py`, `test_intent_parsing.py`, `test_intent_router.py`, `test_llm.py`, `test_main.py`, `test_nodes.py`, `test_tools.py`, `test_synonyms.py`.

**Impact:** A developer running `pytest tests/ -v` sees green across the board and believes the system is well-tested. In reality, the production `oracle/deduction.py` module (the core algorithm) has ZERO test coverage. A bug in `oracle/deduction.py:narrow_candidates()` would not be caught by any test.

---

## 2. MODULE-LEVEL GLOBAL STATE IN `oracle/deduction.py`

**Severity: HIGH**

`oracle/deduction.py` caches the ghost database in a module-level global `_DB` (line 12). `oracle/engine.py` caches synonyms in `_SYNONYMS` (line 48) and ghost tests in `_GHOST_TESTS` (line 78).

The `test_engine.py` fixture calls `reset_db()` from `oracle.deduction` before each test:
```python
@pytest.fixture(autouse=True)
def _fresh_db():
    reset_db()
    yield
    reset_db()
```

But there is NO equivalent reset for `_SYNONYMS` or `_GHOST_TESTS`. If a test modifies or corrupts these caches, the corruption persists across all subsequent tests in the session.

**Currently not exploited** because no test modifies these, but the lack of reset means:
- A test that monkeypatches `config.SYNONYMS_PATH` to a different file will leave the old synonym cache in place for subsequent tests.
- A test that monkeypatches `config.GHOST_TESTS_PATH` similarly leaks.

**Fix:** Add reset functions for `_SYNONYMS` and `_GHOST_TESTS` and call them in the autouse fixture.

---

## 3. `test_deduction.py` AND `test_engine.py` USE DIFFERENT DATABASES

**Severity: HIGH**

`test_deduction.py` imports from `graph.deduction` which loads from `config/ghost_database.yaml` (the old config directory, via `graph/deduction.py`'s `_DB_PATH`).

`test_engine.py` imports from `oracle.deduction` which loads from `oracle/config/ghost_database.yaml` (via `oracle/deduction.py`'s `_DB_PATH`).

If these two YAML files ever diverge (which they will over time since only `oracle/config/` is actively maintained), the two test files will silently test against different ghost data. This makes test results meaningless for comparison.

---

## 4. `test_radio_fx.py` -- NON-DETERMINISTIC NOISE

**Severity: MEDIUM**

`RadioFX.apply()` (production code, `oracle/voice/radio_fx.py` line 178) uses an unseeded RNG:
```python
noise = np.random.default_rng().normal(0, sigma, len(processed))
```

Tests that verify noise properties (`test_more_candidates_means_more_noise`) rely on statistical expectations rather than deterministic outputs. While unlikely to flake, this is a structural weakness. The production code should accept an optional seed, or tests should mock the RNG.

---

## 5. `test_voice_output.py:TestCLIFlags.test_text_only_no_speak` -- IMPORT SIDE EFFECTS

**Severity: MEDIUM**

```python
def test_text_only_no_speak(self):
    from oracle.runner import main, RichOutput
    with patch("sys.argv", ["oracle", "--text"]):
        with patch("oracle.runner.run_loop") as mock_loop:
            with patch("oracle.runner.RichOutput") as mock_rich:
                main()
```

This test calls `main()` which triggers argparse, engine creation, and potentially Rich console initialization. If `main()` has any side effects before `run_loop` is patched (like creating an `InvestigationEngine`), those leak. The test also patches `sys.argv` globally, which could affect parallel test execution.

---

## 6. `test_stt.py` -- FRAGILE TEST CONSTRUCTION

**Severity: MEDIUM**

`_make_voice_input()` bypasses `VoiceInput.__init__` using `__new__` and manually sets internal attributes:
```python
vi = VoiceInput.__new__(VoiceInput)
vi._is_speaking = False
vi._barged_in = False
vi._consecutive_failures = 0
vi._max_failures = 3
vi._recorder = mock_recorder
vi._sd = mock_sd
```

If `VoiceInput.__init__` adds a new attribute (e.g., `self._model_size = whisper_model`), the test factory silently produces objects missing that attribute. Tests will fail with confusing `AttributeError` messages instead of clearly indicating the factory is stale.

**Same pattern in `test_tts.py:_make_mock_tts()`** (line 33-48) and `test_voice_output.py:_make_voice_output()` (line 29-63).

---

## 7. `test_engine.py:TestEndGame.test_writes_to_history_json` -- FILESYSTEM DEPENDENCY

**Severity: LOW**

Uses `tmp_path` fixture and writes to filesystem. This is the correct pytest pattern, but note:
- The `monkeypatch.setattr("oracle.engine.config.SESSIONS_DIR", str(tmp_path))` patches a Pydantic settings object's attribute at runtime. If `config` is frozen or immutable in a future Pydantic version, this breaks.

---

## 8. MISSING `conftest.py`

**Severity: MEDIUM**

The `tests/` directory has no `conftest.py`. Common fixtures (like `_fresh_db`, `engine`) are duplicated across files. `test_deduction.py` and `test_engine.py` both define their own `_fresh_db` fixture with the same pattern but importing from different modules. A shared `conftest.py` would:
- Centralize the DB reset
- Prevent import divergence
- Provide a shared `engine` fixture

---

## 9. NO TEST MARKERS OR CATEGORIZATION

**Severity: MEDIUM**

Tests are not marked by category. There is no way to run only:
- Core logic tests (parser, engine, deduction, responses)
- Voice tests (TTS, radio FX, STT, VB-Cable)
- Legacy tests (graph/* tests that should be killed)
- Integration tests

The only marker used is `@pytest.mark.llm` in the dead `test_intent_parsing.py` and `@pytest.mark.integration` mentioned in CLAUDE.md but never appears in any test file.

**Impact:** Cannot selectively run fast unit tests vs slow voice tests in CI.

---

## 10. `test_responses.py` -- RANDOMNESS IN PRODUCTION CODE MAKES TESTS FRAGILE

**Severity: LOW**

`oracle/responses.py:_build_evidence_response()` uses `random.choice(templates)` (line 137) to select response templates. Tests check for keywords like "confirmed" or "ruled out" which appear in all templates, so this currently works. But if a new template variant is added that uses different wording, tests could intermittently fail depending on which template `random.choice` picks.

**Fix:** Either seed the random module in tests, or use `random.seed()` in test fixtures, or make the response builder accept an optional template index for testing.

---

## Summary

| # | Issue | Severity | Impact |
|---|-------|----------|--------|
| 1 | Half the test suite tests dead code | CRITICAL | False confidence in test coverage |
| 2 | No reset for `_SYNONYMS`/`_GHOST_TESTS` caches | HIGH | Potential cross-test contamination |
| 3 | Two test files use different database files | HIGH | Silent divergence risk |
| 4 | Unseeded RNG in noise tests | MEDIUM | Potential flakiness |
| 5 | CLI test calls `main()` with side effects | MEDIUM | State leakage |
| 6 | `__new__` bypass in test factories | MEDIUM | Stale mocks on attr changes |
| 7 | Filesystem dependency in end_game test | LOW | Pydantic version sensitivity |
| 8 | No conftest.py for shared fixtures | MEDIUM | Duplicated fixtures, import divergence |
| 9 | No test markers | MEDIUM | Cannot run selective test suites |
| 10 | Random template selection in responses | LOW | Potential intermittent failures |

**10 structural issues found.**
