# MISSING COVERAGE -- Hawk Audit

Critical source code paths with ZERO test coverage in the production (`oracle/`) modules. Every item below has no corresponding test in the surviving test files (`test_engine.py`, `test_parser.py`, `test_responses.py`, `test_radio_fx.py`, `test_tts.py`, `test_stt.py`, `test_vb_cable.py`, `test_voice_output.py`).

---

## 1. `oracle/runner.py:_dispatch()` -- ZERO tests

**File:** `oracle/runner.py`, lines 239-312
**What's untested:** The entire dispatch function that maps `ParsedIntent.action` to engine method calls. This is the central routing logic of the application.

**Specific untested branches:**
- `action == "record_evidence"` with `extra_evidence` handling (lines 248-250)
- `action == "record_behavioral_event"` (line 253)
- `action == "query_ghost_database"` (line 262)
- `action == "suggest_next_evidence"` (line 265)
- `action == "record_theory"` (line 267) -- dispatches to `record_guess` with player_name
- `action == "record_guess"` (line 274)
- `action == "lock_in"` (line 277)
- `action == "confirm_true_ghost"` (line 280)
- `action == "register_players"` (line 283)
- `action == "query_tests"` with and without ghost_name (lines 286-290)
- `action == "ghost_test_result"` (line 292)
- `action == "query_behavior"` (line 296)
- `action == "change_voice"` (line 302)
- Default unknown action (line 311)

**Concrete test case:**
```python
def test_dispatch_record_evidence():
    engine = InvestigationEngine()
    engine.new_game("professional")
    intent = ParsedIntent(action="record_evidence", evidence_id="emf_5", status="confirmed")
    result = _dispatch(engine, intent)
    assert isinstance(result, EvidenceResult)
    assert result.evidence == "emf_5"
```

---

## 2. `oracle/runner.py:run_loop()` -- voice change handling untested

**File:** `oracle/runner.py`, lines 339-341
**What's untested:** When `_dispatch` returns a `VoiceChangeResult` with `success=True`, `run_loop` calls `output._tts.set_voice(result.voice_name)`. This wiring is never tested.

**Concrete test case:**
```python
def test_run_loop_applies_voice_change():
    # FakeInput that sends "change voice to af_sarah" then None
    # Mock VoiceOutput with a mock _tts
    # Assert _tts.set_voice was called with "af_sarah"
```

---

## 3. `oracle/engine.py:ghost_test_result()` -- ZERO integration tests

**File:** `oracle/engine.py`, lines 745-805
**What's untested:** No test in `test_engine.py` calls `engine.ghost_test_result()`. The `TestGhostTestLookup` class only tests `ghost_test_lookup()` (read-only). The actual test result recording, elimination logic, and identification signal are completely untested.

**Specific untested paths:**
- Positive test passed -> should_identify = True, ghost set as identified (lines 790-795)
- Positive test failed -> should_eliminate = True, ghost eliminated (lines 769-770)
- Negative test passed -> should_eliminate = True (line 772)
- Negative test failed -> should_identify = True (line 793)
- Ghost not found in database (lines 752-757)
- Ghost already eliminated (line 776 check)

**Concrete test case:**
```python
def test_ghost_test_result_positive_failed_eliminates(engine):
    result = engine.ghost_test_result("Goryo", passed=False)
    assert "Goryo" in result.eliminated_ghosts
    assert "Goryo" not in engine.candidates

def test_ghost_test_result_positive_passed_identifies(engine):
    result = engine.ghost_test_result("Goryo", passed=True)
    assert result.identified_ghost == "Goryo"
```

---

## 4. `oracle/engine.py:available_tests()` -- ZERO tests

**File:** `oracle/engine.py`, lines 692-709
**What's untested:** The method that lists which remaining candidates have deterministic tests. Never called by any test.

**Concrete test case:**
```python
def test_available_tests_returns_testable_and_untestable(engine):
    result = engine.available_tests()
    assert isinstance(result, AvailableTestsResult)
    assert result.total_candidates == 27
    # At least some ghosts should have tests
    assert len(result.testable) + len(result.untestable) == 27
```

---

## 5. `oracle/engine.py:_save_session()` -- error handling untested

**File:** `oracle/engine.py`, lines 932-959
**What's untested:** The `test_writes_to_history_json` test covers the happy path, but these paths are untested:
- Corrupt JSON in existing history file (line 945: `except (json.JSONDecodeError, ValueError): history = []`)
- Multiple sessions appended to same file
- Directory creation with `mkdir(parents=True, exist_ok=True)`

**Concrete test case:**
```python
def test_save_session_handles_corrupt_json(engine, tmp_path, monkeypatch):
    monkeypatch.setattr("oracle.engine.config.SESSIONS_DIR", str(tmp_path))
    # Write corrupt JSON
    (tmp_path / "history.json").write_text("{corrupt")
    engine.lock_in("Wraith")
    engine.end_game("Wraith")
    # Should recover and write a fresh history
    with open(tmp_path / "history.json") as f:
        history = json.load(f)
    assert len(history) == 1
```

---

## 6. `oracle/engine.py:_find_best_discriminator()` -- ZERO direct tests

**File:** `oracle/engine.py`, lines 888-908
**What's untested:** The algorithm that picks the most discriminating evidence type. `test_engine.py:TestSuggestNext` only tests `suggest_next()` at a surface level, never verifying that `best_evidence` is the optimal choice.

**Specific untested paths:**
- Empty remaining list (line 890: `return None`)
- Empty candidates list (line 890)
- Tie-breaking between equally discriminating evidence types

**Concrete test case:**
```python
def test_best_discriminator_splits_evenly(engine):
    # Set up candidates where exactly half have emf_5 and half don't
    engine.record_evidence("dots", "confirmed")
    result = engine.suggest_next()
    # best_evidence should be the type closest to 50/50 split
    assert result.best_evidence is not None
```

---

## 7. `oracle/responses.py:_build_available_tests_response()` -- ZERO tests

**File:** `oracle/responses.py`, lines 381-392
**What's untested:** The response builder for `AvailableTestsResult`. No test constructs an `AvailableTestsResult` and passes it through `build_response()`.

**Concrete test case:**
```python
def test_available_tests_response_lists_testable():
    result = AvailableTestsResult(
        testable=[("Goryo", "Check D.O.T.S. on camera")],
        untestable=["Spirit", "Wraith"],
        total_candidates=3,
    )
    response = build_response(result)
    assert "Goryo" in response
    assert "D.O.T.S." in response
```

---

## 8. `oracle/responses.py:_build_voice_change_response()` -- ZERO tests

**File:** `oracle/responses.py`, lines 397-405
**What's untested:** The voice change response builder. Never tested directly.

**Concrete test case:**
```python
def test_voice_change_success_response():
    result = VoiceChangeResult(voice_name="bm_fable", success=True)
    response = build_response(result)
    assert "Fable" in response

def test_voice_change_failure_response():
    result = VoiceChangeResult(voice_name="nonexistent", success=False, available_voices=["bm_fable"])
    response = build_response(result)
    assert "Unknown voice" in response
```

---

## 9. `oracle/responses.py:_build_test_result_response()` -- ZERO tests

**File:** `oracle/responses.py`, lines 334-352
**What's untested:** The response builder for ghost test results. Four branches:
- Test confirmed identification (line 336)
- Passed + eliminated (line 341)
- Failed + eliminated (line 346)
- Passed/failed with no elimination (lines 350, 352)

**Concrete test case:**
```python
def test_test_result_identification_response():
    result = TestResult(ghost_name="Goryo", passed=True, eliminated_ghosts=[], remaining_count=1, identified_ghost="Goryo")
    response = build_response(result)
    assert "Goryo" in response
    assert "confirmed" in response.lower()
```

---

## 10. `oracle/parser.py` -- voice change pattern untested

**File:** `oracle/parser.py`, lines 334-345
**What's untested:** `parse_intent` matching "change voice to X" / "use voice X". Not a single test in `test_parser.py` covers the `change_voice` action.

**Concrete test case:**
```python
def test_change_voice():
    intent = parse_intent("change voice to bm_george")
    assert intent.action == "change_voice"
    assert intent.voice_name == "bm_george"
```

---

## 11. `oracle/parser.py` -- player registration patterns untested in test_parser.py

**File:** `oracle/parser.py`, lines 443-453
**What's untested:** `test_parser.py` has no tests for `register_players` action. Only `test_intent_router.py` (which is in the kill list) covers player patterns.

**Concrete test case:**
```python
def test_register_player():
    intent = parse_intent("add player Kayden")
    assert intent.action == "register_players"
    assert "Kayden" in intent.player_names
```

---

## 12. `oracle/parser.py` -- theory patterns untested in test_parser.py

**File:** `oracle/parser.py`, lines 409-440
**What's untested:** `test_parser.py` tests `record_theory` only for "we think it's a Wraith" (which routes to theory, not guess). Named-player theories like "Kayden thinks it's a Poltergeist" are only tested in `test_intent_router.py` (kill list).

**Concrete test case:**
```python
def test_named_player_theory():
    intent = parse_intent("Kayden thinks it's a Poltergeist")
    assert intent.action == "record_theory"
    assert intent.player_name == "Kayden"
    assert intent.ghost_name == "Poltergeist"
```

---

## 13. `oracle/parser.py` -- test query patterns untested in test_parser.py

**File:** `oracle/parser.py`, lines 455-472
**What's untested:** `test_parser.py` has no tests for `query_tests` action. Only `test_intent_router.py` (kill list) covers these.

---

## 14. `oracle/parser.py` -- behavioral patterns only partially tested

**File:** `oracle/parser.py`, lines 171-208
**What's untested in test_parser.py:** All behavioral patterns are only tested in `test_intent_router.py` (kill list). `test_parser.py` has zero tests for `record_behavioral_event` action. The following eliminator keys are completely untested against the production parser:
- `ghost_stepped_in_salt`
- `ghost_is_male`
- `ghost_turned_breaker_on`
- `ghost_turned_breaker_off_directly`
- `airball_event_observed`
- `ghost_changed_favorite_room`
- `ghost_turned_on_standard_light_switch`
- `dots_visible_with_naked_eye`
- `ghost_hunted_from_same_room_as_player`

---

## 15. `oracle/deduction.py` -- ZERO tests against production module

**File:** `oracle/deduction.py`, entire file
**What's untested:** Every function in `oracle/deduction.py` has zero test coverage from the surviving test suite. `test_deduction.py` tests `graph/deduction.py` (a different module). Functions completely untested:
- `load_db()`, `reset_db()`, `all_ghost_names()`
- `narrow_candidates()` -- the core deduction algorithm
- `apply_observation_eliminator()`
- `evidence_threshold_reached()`
- `eliminate_by_guaranteed_evidence()`
- `rank_discriminating_tests()`
- `apply_soft_fact_eliminators()`
- `get_ghost()`

This is the MOST CRITICAL gap. The core deduction engine has zero test coverage against the production module.

---

## 16. `oracle/engine.py:normalize_evidence_id()` and `_load_synonyms()` -- tested only indirectly

**File:** `oracle/engine.py`, lines 51-73
**What's untested:** Direct tests exist only in `test_synonyms.py` (kill list, imports from `graph.tools`). `test_engine.py:TestRecordEvidence.test_synonym_normalization_emf` tests it indirectly through `record_evidence`, but there are no direct unit tests for edge cases like missing YAML file, empty YAML, whitespace handling.

---

## 17. `oracle/voice/tts.py:download_models()` -- ZERO tests

**File:** `oracle/voice/tts.py`, lines 61-119
**What's untested:** The model download function with Rich progress bars. Untested paths:
- Download succeeds
- Download fails (line 112-117: cleanup + RuntimeError)
- Models already exist (line 83: early return)

---

## 18. `oracle/voice/tts.py:KokoroTTS.set_voice()` -- ZERO tests

**File:** `oracle/voice/tts.py`, lines 172-186
**What's untested:** Voice switching at runtime. Both success (known voice) and failure (unknown voice) paths.

---

## 19. `oracle/voice/radio_fx.py:get_device_sample_rate()` -- ZERO tests

**File:** `oracle/voice/radio_fx.py`, lines 254-271
**What's untested:** Device sample rate query function. Both the success path (sounddevice available) and fallback path (returns 24000 on exception).

---

## Summary

| # | Source Location | Severity | Description |
|---|----------------|----------|-------------|
| 1 | `runner.py:_dispatch()` | CRITICAL | Zero tests for central routing logic |
| 2 | `runner.py:run_loop()` voice change | HIGH | Voice change wiring untested |
| 3 | `engine.py:ghost_test_result()` | CRITICAL | Test result recording untested |
| 4 | `engine.py:available_tests()` | HIGH | Available tests listing untested |
| 5 | `engine.py:_save_session()` errors | MEDIUM | Error recovery untested |
| 6 | `engine.py:_find_best_discriminator()` | MEDIUM | Optimization algorithm untested |
| 7 | `responses.py:_build_available_tests_response()` | HIGH | Response builder untested |
| 8 | `responses.py:_build_voice_change_response()` | HIGH | Response builder untested |
| 9 | `responses.py:_build_test_result_response()` | HIGH | Response builder untested |
| 10 | `parser.py:change_voice` | HIGH | Voice change parsing untested |
| 11 | `parser.py:register_players` | HIGH | Player registration parsing untested |
| 12 | `parser.py:record_theory` (named) | HIGH | Named player theories untested |
| 13 | `parser.py:query_tests` | HIGH | Test query parsing untested |
| 14 | `parser.py:behavioral patterns` | CRITICAL | All 9 behavioral eliminators untested |
| 15 | `deduction.py` (entire) | **CRITICAL** | Zero tests against production module |
| 16 | `engine.py:normalize_evidence_id()` | MEDIUM | Direct unit tests missing |
| 17 | `tts.py:download_models()` | LOW | Download logic untested |
| 18 | `tts.py:set_voice()` | MEDIUM | Runtime voice switch untested |
| 19 | `radio_fx.py:get_device_sample_rate()` | LOW | Device query untested |

**19 missing coverage areas found.**
