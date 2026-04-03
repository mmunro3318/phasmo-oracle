# BAD TESTS -- Individual Tests That Are Broken, Misleading, or Worthless

Auditor: **Viper**
Date: 2026-04-02

---

## GUARDED ASSERTIONS (silently pass on regression)

### B1. `test_engine.py:TestRecordEvidence.test_identification_triggered_on_single_candidate` (line 144)

```python
if result.remaining_count == 1:
    assert result.identification_triggered is True
    assert result.identified_ghost is not None
```

**Problem:** The assertion is wrapped in `if result.remaining_count == 1`. If the ghost database changes and [dots, emf_5, uv] no longer narrows to exactly 1 candidate, the test **silently passes with zero assertions**. The comment says "Goryo has [dots, emf_5, uv]" but Goryo's actual evidence IS [dots, emf_5, uv], so it should work -- but other ghosts also match (Obake has [emf_5, orb, uv], Banshee has [dots, orb, uv] -- neither has all three). Wait -- confirming all three means the ghost must have ALL of them: dots AND emf_5 AND uv. Only Goryo has exactly that triple. So the guard is unnecessary, and if it ever triggers (doesn't enter the if-block), a regression is hidden.

**Verdict: REFACTOR** -- Remove the `if` guard. Assert unconditionally: `assert result.remaining_count == 1` first, then the rest. If the database changes, the test should FAIL, not silently pass.

---

### B2. `test_engine.py:TestRecordEvidence.test_phase_shifted_flag` (line 222)

```python
if result.remaining_count > 1 and result.threshold_reached:
    assert result.phase_shifted is True
    assert engine.investigation_phase == "behavioral"
```

**Problem:** Same pattern -- guarded assertion. If evidence [emf_5, dots, uv] on professional leaves exactly 1 candidate (which it does -- Goryo), then `remaining_count == 1`, the guard fails, and no assertions execute. This test has likely **never passed its assertions** because confirming all 3 Goryo evidence on professional narrows to exactly 1 candidate. The test description says "Threshold reached + multiple candidates triggers phase_shifted" but the evidence combo chosen produces a single candidate. This test is **completely dead**.

**Verdict: REFACTOR** -- Choose evidence that produces multiple candidates at threshold. For example, confirm [emf_5, freezing, uv] which matches both Jinn and Hantu (2 candidates). Then assert unconditionally.

---

### B3. `test_engine.py:TestGhostTestLookup.test_ghost_with_test` (line 416)

```python
result = engine.ghost_test_lookup("Goryo")
assert isinstance(result, TestLookupResult)
assert result.found is True
# If the YAML has a test for Goryo:
if result.has_test:
    assert result.test_description is not None
```

**Problem:** The YAML DOES have a test for Goryo (ghost_tests.yaml line 18-19). The `if result.has_test` guard is unnecessary and would silently pass if the YAML lost the Goryo entry. Since we know Goryo has a test, assert it directly.

**Verdict: REFACTOR** -- `assert result.has_test is True` then `assert result.test_description is not None`.

---

### B4. `test_engine.py:TestGhostTestLookup.test_ghost_without_test` (line 428)

```python
result = engine.ghost_test_lookup("Spirit")
assert result.found is True
# Spirit may or may not have a test -- just verify the structure
assert isinstance(result.has_test, bool)
```

**Problem:** `assert isinstance(result.has_test, bool)` is a tautological assertion -- `has_test` is defined as `bool` in the dataclass. It tests Python's type system, not production behavior. The ghost_tests.yaml HAS a "spirit" entry (line 101), so `has_test` would actually be True. The comment "Spirit may or may not have a test" is factually wrong -- Spirit DOES have a test. The assertion proves nothing about production logic.

**Verdict: REFACTOR** -- Either assert Spirit has a test (it does in ghost_tests.yaml) or pick a ghost that genuinely lacks one ("The Mimic" per the YAML comment on line 6).

---

## THEATER TESTS (assert mocks, not behavior)

### B5. `test_voice_output.py:TestCLIFlags.test_text_only_no_speak` (line 182)

```python
def test_text_only_no_speak(self):
    from oracle.runner import main, RichOutput
    with patch("sys.argv", ["oracle", "--text"]):
        with patch("oracle.runner.run_loop") as mock_loop:
            with patch("oracle.runner.RichOutput") as mock_rich:
                main()
                call_args = mock_loop.call_args
                assert mock_rich.called
```

**Problem:** This patches `run_loop` to do nothing, then asserts `RichOutput` was instantiated. But the assertion `mock_rich.called` only checks that the mock was called as a constructor -- it doesn't verify that the returned object was actually passed to `run_loop`. The test passes even if `main()` creates a `RichOutput` and then throws it away. Furthermore, patching `RichOutput` means the real initialization code never runs.

**Verdict: REFACTOR** -- Assert that `mock_loop` was called with the RichOutput instance: `assert mock_loop.call_args[0][2] == mock_rich.return_value` or similar.

---

### B6. `test_voice_output.py:TestCLIFlags.test_speak_without_text_exits` (line 193)

```python
def test_speak_without_text_exits(self):
    from oracle.runner import main
    with patch("sys.argv", ["oracle", "--speak"]):
        # --text defaults to True, so --speak alone actually works.
        # The validation checks `not args.text` which is False since
        # --text defaults to True. This is correct behavior.
        pass
```

**Problem:** This test has NO assertions. The entire body is `pass`. It's a commented-out intent that was never implemented. It appears in the test suite and gets counted as "passing" but tests absolutely nothing.

**Verdict: DELETE** -- Either write the actual test or remove it. Currently it inflates the pass count.

---

### B7. `test_stt.py:TestImportError.test_import_error_without_realtimestt` (line 187)

```python
def test_import_error_without_realtimestt(self):
    with patch.dict("sys.modules", {"RealtimeSTT": None}):
        import importlib
        import oracle.voice.stt as stt_module
        with pytest.raises(ImportError, match="RealtimeSTT"):
            raise ImportError(
                "RealtimeSTT is required for voice input. "
                "Install with: pip install -e '.[voice-full]'"
            )
```

**Problem:** This test **manually raises the ImportError it's checking for**. It doesn't test that `VoiceInput.__init__` raises ImportError when RealtimeSTT is missing -- it literally says `raise ImportError(...)` in the test body. The comment even acknowledges: "Can't easily test this without actually breaking imports / So we test the error message is correct". The test proves that `pytest.raises` catches manually raised exceptions. That's stdlib behavior, not production logic.

**Verdict: DELETE** -- This is pure theater. Replace with an actual test that verifies `VoiceInput()` raises ImportError when RealtimeSTT is unavailable (e.g., by patching the import inside `__init__`).

---

## WEAK / FALSE CONFIDENCE ASSERTIONS

### B8. `test_responses.py:TestEvidenceResponse.test_confirmed_includes_confirmed` (line 76)

```python
def test_confirmed_includes_confirmed(self):
    result = _evidence_result(status="confirmed")
    response = build_response(result)
    assert "confirmed" in response.lower() or "in" in response.lower()
```

**Problem:** The assertion `"in" in response.lower()` matches the substring "in" which appears in virtually any English sentence ("investigation", "remaining", "down", etc.). This assertion would pass on literally any response string that contains the two-letter sequence "in". It provides zero confidence that the response actually mentions confirmation.

**Verdict: REFACTOR** -- Use a more specific assertion. The templates use "confirmed" and "is in" -- check for one of those.

---

### B9. `test_responses.py:TestMinimumLength.test_long_response_not_padded` (line 289)

```python
def test_long_response_not_padded(self):
    result = NewGameResult(difficulty="professional", candidate_count=27)
    response = build_response(result)
    assert len(response) >= _MIN_LENGTH
    if len(response) > _MIN_LENGTH + 20:
        pass  # We just check it's valid
```

**Problem:** The second half of the test body is `if condition: pass`. The test name says "not padded" but never asserts the filler text is absent. The `_FILLER` string is `" Say a command when you're ready."` -- the test should assert this is NOT in the response. Currently, even if filler IS wrongly appended, the test passes.

**Verdict: REFACTOR** -- Add `assert _FILLER not in response` or `assert "Say a command" not in response`.

---

### B10. `test_responses.py:TestEvidenceResponse.test_over_proofed_includes_warning` (line 113)

```python
def test_over_proofed_includes_warning(self):
    result = _evidence_result(over_proofed=True)
    response = build_response(result)
    assert "evidence" in response.lower()
    assert "incorrectly" in response.lower()
```

**Problem:** The `_evidence_result` helper doesn't set `zero_candidates=False` and `mimic_detected=False` (they default to False), but it also doesn't set `remaining_count` to match `over_proofed=True` semantics. The `_build_evidence_response` function checks conditions in priority order: `zero_candidates` first, then `mimic_detected`, then `over_proofed`. If someone refactors the priority order, this test could break or pass for wrong reasons. More critically, the response builder returns EARLY for zero_candidates and mimic_detected but NOT for over_proofed -- after the over_proofed block, execution falls through to the normal confirm/rule-out templates. The test only checks the over_proofed message appears, not that it's the ONLY message.

**Verdict: REFACTOR** -- Verify the full response content, not just substring presence. Document why over_proofed doesn't cause an early return.

---

## ERRONEOUS / MISLEADING TESTS

### B11. `test_deduction.py:TestApplySoftFactEliminators.test_male_ghost_eliminates_female_only` (line 551)

```python
def test_male_ghost_eliminates_female_only(self):
    from graph.deduction import apply_soft_fact_eliminators, all_ghost_names
    candidates = all_ghost_names()
    eliminated = apply_soft_fact_eliminators(
        {"model_gender": "male"}, candidates
    )
    assert "Banshee" in eliminated
    assert "Dayan" in eliminated
```

**Problem (beyond dead import):** This test asserts Banshee and Dayan are eliminated when `model_gender=male`. But `apply_soft_fact_eliminators` reads `soft_fact_eliminators` from each ghost's YAML entry. Whether this works depends entirely on whether Banshee and Dayan have `soft_fact_eliminators.model_gender.eliminates_if: "male"` in the YAML. If the YAML data doesn't have these entries, the test fails. If it does, the test is tightly coupled to YAML content without documenting the dependency. **I checked the ghost_database.yaml (first 100 lines) and there are NO `soft_fact_eliminators` fields visible.** This test may already be broken or depends on data deeper in the YAML.

**Verdict: INVESTIGATE** -- If ghost_database.yaml lacks `soft_fact_eliminators` for Banshee/Dayan, this test is always failing (but since it imports from `graph.deduction` which is dead, nobody notices). When ported to `oracle.deduction`, verify the YAML has the necessary data.

---

### B12. `test_engine.py:TestRecordEvidence.test_mimic_detection_above_threshold` (line 171)

```python
def test_mimic_detection_above_threshold(self, engine):
    engine.record_evidence("uv", "confirmed")
    engine.record_evidence("freezing", "confirmed")
    engine.record_evidence("spirit_box", "confirmed")
    result = engine.record_evidence("orb", "confirmed")
    assert result.remaining_count == 1
    assert result.candidates == ["The Mimic"]
    assert result.identification_triggered is True
```

**Problem:** This test asserts `mimic_detected` should be True (based on the class description), but it actually doesn't assert `result.mimic_detected is True`! The test name says "mimic detection above threshold" but only checks remaining_count and candidates. The `_check_mimic` method in engine.py returns True when `len(evidence_confirmed) > threshold` AND orb is confirmed AND Mimic is a candidate. With 4 confirmed evidence (uv, freezing, spirit_box, orb) and threshold=3, `len > threshold` is True (4 > 3). So mimic_detected should be True, but it's never asserted.

**Verdict: REFACTOR** -- Add `assert result.mimic_detected is True` to actually test what the test name claims.

---

### B13. `test_nodes.py:TestIdentifyNode.test_noop_when_already_identified` (line 224)

```python
def test_noop_when_already_identified(self):
    state = _make_state(candidates=["Wraith"], identified_ghost="Wraith")
    result = identify_node(state)
    assert "identified_ghost" not in result or result.get("tool_result") == state.get("tool_result", "")
```

**Problem:** The assertion `"identified_ghost" not in result OR ...` means if `identify_node` incorrectly re-sets `identified_ghost`, the second branch (`tool_result` comparison) can still pass because tool_result might match by coincidence. The `or` makes this a weak assertion that can pass for wrong reasons. (Also, this is dead code from `graph.nodes`, so doubly irrelevant.)

**Verdict: DELETE (part of kill-list item #6).**

---

## STATE LEAKS / NON-DETERMINISTIC

### B14. `test_responses.py:TestEvidenceResponse` -- ALL TESTS (randomness dependency)

The `_build_evidence_response` function uses `random.choice(templates)` (responses.py line 137) to pick between two templates for normal confirm/rule-out responses. Tests like `test_confirmed_includes_confirmed` check for `"confirmed" in response.lower() or "in" in response.lower()` which accommodates both templates. But this means:

1. Tests are non-deterministic -- different runs may exercise different template paths
2. A bug in one template but not the other has a 50% chance of being caught per run
3. The weak `or` assertions (B8) are a workaround for this randomness

**Verdict: REFACTOR** -- Either seed `random` in tests via `monkeypatch` / fixture, or test each template explicitly by mocking `random.choice`.

---

### B15. `test_deduction.py` -- Global `_DB` cache leaks between `graph.deduction` and `oracle.deduction`

Both `graph/deduction.py` and `oracle/deduction.py` have a module-level `_DB` cache. If tests from different files run in the same process, `graph.deduction.load_db()` caches from `config/ghost_database.yaml` while `oracle.deduction.load_db()` caches from `oracle/config/ghost_database.yaml`. The `reset_db()` fixture in `test_deduction.py` only resets `graph.deduction._DB`, not `oracle.deduction._DB`. Cross-contamination between the two caches is possible if test ordering puts them together.

**Verdict: STRUCTURAL ISSUE** (covered in structural-issues.md).

---

## TAUTOLOGICAL

### B16. `test_tts.py:TestTTSProviderProtocol.test_kokoro_satisfies_protocol` (line 17)

```python
def test_kokoro_satisfies_protocol(self):
    assert hasattr(KokoroTTS, "synthesize")
```

**Problem:** This only checks that the class has a `synthesize` attribute. It doesn't verify the method signature matches `TTSProvider`. It would pass even if `synthesize` were a string attribute. Since `TTSProvider` is a `@runtime_checkable` Protocol, the proper test is `assert issubclass(KokoroTTS, TTSProvider)` -- but that requires the class to be importable without kokoro-onnx.

**Verdict: REFACTOR** -- Use `isinstance(KokoroTTS.__new__(KokoroTTS), TTSProvider)` pattern or check method signature explicitly.

---

## Summary Table

| ID | File:Test | Issue | Verdict |
|----|-----------|-------|---------|
| B1 | test_engine.py:TestRecordEvidence.test_identification_triggered | Guarded assertion | REFACTOR |
| B2 | test_engine.py:TestRecordEvidence.test_phase_shifted_flag | Dead guarded assertion (never asserts) | REFACTOR |
| B3 | test_engine.py:TestGhostTestLookup.test_ghost_with_test | Guarded assertion | REFACTOR |
| B4 | test_engine.py:TestGhostTestLookup.test_ghost_without_test | Tautological type assertion | REFACTOR |
| B5 | test_voice_output.py:TestCLIFlags.test_text_only_no_speak | Theater (mocks everything) | REFACTOR |
| B6 | test_voice_output.py:TestCLIFlags.test_speak_without_text_exits | Empty test body (pass) | DELETE |
| B7 | test_stt.py:TestImportError.test_import_error_without_realtimestt | Manually raises the error it tests | DELETE |
| B8 | test_responses.py:TestEvidenceResponse.test_confirmed_includes | "in" matches anything | REFACTOR |
| B9 | test_responses.py:TestMinimumLength.test_long_response_not_padded | Dead branch, no real assertion | REFACTOR |
| B10 | test_responses.py:TestEvidenceResponse.test_over_proofed | Weak substring check | REFACTOR |
| B11 | test_deduction.py:TestApplySoftFactEliminators.test_male_ghost | Depends on missing YAML data | INVESTIGATE |
| B12 | test_engine.py:TestRecordEvidence.test_mimic_detection_above | Doesn't assert mimic_detected | REFACTOR |
| B13 | test_nodes.py:TestIdentifyNode.test_noop_when_already_identified | Weak OR assertion | DELETE (kill list) |
| B14 | test_responses.py:TestEvidenceResponse (all) | Non-deterministic (random.choice) | REFACTOR |
| B15 | test_deduction.py autouse fixture | Only resets graph._DB, not oracle._DB | STRUCTURAL |
| B16 | test_tts.py:TestTTSProviderProtocol.test_kokoro_satisfies | Only checks hasattr, not signature | REFACTOR |

**Total: 16 bad tests identified (3 DELETE, 12 REFACTOR, 1 INVESTIGATE)**
