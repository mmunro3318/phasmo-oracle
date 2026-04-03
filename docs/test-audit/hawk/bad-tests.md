# BAD TESTS -- Hawk Audit

Individual tests that are broken, misleading, or worthless.

---

## GUARDED ASSERTIONS (silently pass on regression)

### 1. `test_engine.py:TestRecordEvidence.test_identification_triggered_on_single_candidate`
**Lines 144-153**

```python
if result.remaining_count == 1:
    assert result.identification_triggered is True
    assert result.identified_ghost is not None
```

**Problem:** Guarded assertion. If the deduction logic changes and more than 1 candidate survives `[dots, emf_5, uv]` on professional, the `if` branch is never entered, the assertions never run, and the test silently passes. This test should either parametrize to guarantee exactly 1 candidate, or unconditionally assert the expected count first.

**Verdict:** REFACTOR. Remove the `if` guard. Assert `result.remaining_count == 1` unconditionally first, then assert the trigger flags.

---

### 2. `test_engine.py:TestRecordEvidence.test_phase_shifted_flag`
**Lines 224-229**

```python
if result.remaining_count > 1 and result.threshold_reached:
    assert result.phase_shifted is True
    assert engine.investigation_phase == "behavioral"
```

**Problem:** Same guarded assertion pattern. If threshold is not reached or only 1 candidate remains, the test passes without asserting anything. The test name promises to test `phase_shifted_flag` but might never actually test it.

**Verdict:** REFACTOR. Choose specific evidence that guarantees >1 candidate at threshold, then assert unconditionally.

---

### 3. `test_engine.py:TestGhostTestLookup.test_ghost_with_test`
**Lines 416-424**

```python
result = engine.ghost_test_lookup("Goryo")
assert isinstance(result, TestLookupResult)
assert result.found is True
# If the YAML has a test for Goryo:
if result.has_test:
    assert result.test_description is not None
```

**Problem:** Guarded assertion. If the YAML does not have a test for Goryo, `has_test` is False, and the test passes without verifying the description. The test name says "ghost_with_test" but doesn't actually guarantee it.

**Verdict:** REFACTOR. Assert `result.has_test is True` unconditionally, or pick a ghost that is guaranteed to have a test.

---

### 4. `test_engine.py:TestGhostTestLookup.test_ghost_without_test`
**Lines 426-431**

```python
result = engine.ghost_test_lookup("Spirit")
assert result.found is True
# Spirit may or may not have a test -- just verify the structure
assert isinstance(result.has_test, bool)
```

**Problem:** The assertion `isinstance(result.has_test, bool)` is trivially true for any dataclass bool field. This test proves nothing about the actual behavior. It should pick a ghost known to NOT have a test and assert `has_test is False`.

**Verdict:** REFACTOR. Assert `result.has_test is False` for a ghost without a test entry.

---

### 5. `test_nodes.py:TestPhaseShiftNode.test_identifies_when_narrowed_to_one`
**Lines 259-268**

```python
result = phase_shift_node(state)
# Hantu eliminated, only Goryo remains
if len(result["candidates"]) == 1:
    assert result.get("identified_ghost") == "Goryo"
```

**Problem:** Guarded assertion on dead code (test_nodes.py is in the kill list, but the pattern is worth noting).

**Verdict:** DELETE (entire file is in kill list).

---

## THEATER TESTS (assert mocks, not behavior)

### 6. `test_voice_output.py:TestVoiceOutputProtocol.test_has_show_response` (and siblings)
**Lines 17-27**

```python
def test_has_show_response(self):
    from oracle.runner import VoiceOutput
    assert hasattr(VoiceOutput, "show_response")
```

**Problem:** Checks that a class has an attribute. This would pass even if `show_response` was a string constant or a property that returns None. It does not verify the method signature, behavior, or Protocol compliance.

**Verdict:** REFACTOR. Use `isinstance` check against `OutputHandler` protocol, or better yet, call the method and verify it works.

---

### 7. `test_tts.py:TestTTSProviderProtocol.test_kokoro_satisfies_protocol`
**Lines 17-21**

```python
def test_kokoro_satisfies_protocol(self):
    assert hasattr(KokoroTTS, "synthesize")
```

**Problem:** Same issue -- `hasattr` check proves nothing about protocol satisfaction. The adjacent test `test_custom_provider_satisfies_protocol` uses `isinstance(DummyTTS(), TTSProvider)` which is the correct approach, but this test doesn't apply the same rigor to the actual implementation.

**Verdict:** REFACTOR. Use `issubclass(KokoroTTS, TTSProvider)` or verify the method signature matches.

---

### 8. `test_stt.py:TestImportError.test_import_error_without_realtimestt`
**Lines 187-198**

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

**Problem:** This test manually raises the exact ImportError it's checking for. It does not test that `VoiceInput.__init__` raises ImportError when RealtimeSTT is missing. The comment even says "Can't easily test this without actually breaking imports / So we test the error message is correct". The test is pure theater -- it tests that `raise ImportError(...)` raises ImportError.

**Verdict:** DELETE. Replace with a real test that instantiates `VoiceInput()` with RealtimeSTT mocked as None and verifies the exception.

---

## FALSE CONFIDENCE (assertions too weak)

### 9. `test_responses.py:TestEvidenceResponse.test_confirmed_includes_confirmed`
**Lines 75-78**

```python
def test_confirmed_includes_confirmed(self):
    result = _evidence_result(status="confirmed")
    response = build_response(result)
    assert "confirmed" in response.lower() or "in" in response.lower()
```

**Problem:** The second alternative `"in" in response.lower()` would match literally any English sentence containing words like "in", "investigation", "remaining", "mining", etc. This assertion is so weak it would pass on random English text.

**Verdict:** REFACTOR. Assert more specifically, e.g., check for the evidence name AND a confirmation word.

---

### 10. `test_responses.py:TestEvidenceResponse.test_ruled_out_includes_ruled_out`
**Lines 80-83**

```python
response = build_response(result)
assert "ruled out" in response.lower() or "crossing off" in response.lower()
```

**Problem:** This is better than #9 but still fragile -- if the template changes to say "eliminated" or "removed", the test fails. More importantly, it doesn't verify the evidence name appears in the response. A response of "ruled out bananas" would pass.

**Verdict:** REFACTOR. Also assert the evidence name/label appears.

---

### 11. `test_responses.py:TestMinimumLength.test_long_response_not_padded`
**Lines 289-299**

```python
def test_long_response_not_padded(self):
    result = NewGameResult(difficulty="professional", candidate_count=27)
    response = build_response(result)
    assert len(response) >= _MIN_LENGTH
    if len(response) > _MIN_LENGTH + 20:
        pass  # We just check it's valid
```

**Problem:** The `if` block with `pass` is a no-op. The test name says "not padded" but doesn't actually check that the filler string is absent. The only real assertion is `len(response) >= _MIN_LENGTH` which is identical to what `test_short_response_gets_padded` checks.

**Verdict:** REFACTOR. Assert `_FILLER not in response` to actually verify no padding was added.

---

### 12. `test_voice_output.py:TestCLIFlags.test_speak_without_text_exits`
**Lines 193-202**

```python
def test_speak_without_text_exits(self):
    # argparse with store_true and default=True means --text is always True
    # unless we directly test the validation logic
    from oracle.runner import main
    with patch("sys.argv", ["oracle", "--speak"]):
        # --text defaults to True, so --speak alone actually works.
        # The validation checks `not args.text` which is False since
        # --text defaults to True. This is correct behavior.
        pass
```

**Problem:** This test has zero assertions. It's literally `pass`. The test name implies it should verify an error exit, but the body explains why it can't, then does nothing.

**Verdict:** DELETE. Either test the actual validation path (by mocking argparse to set text=False) or remove this dead test.

---

## ERRONEOUS TESTS (bugs in the test itself)

### 13. `test_deduction.py:TestEliminateByGuaranteedEvidence` class-level import
**Line 455**

```python
class TestEliminateByGuaranteedEvidence:
    from graph.deduction import eliminate_by_guaranteed_evidence
```

**Problem:** This class-level import (`from graph.deduction import ...`) at line 455 runs at class definition time and imports from the wrong module. Each test method then re-imports at function scope (e.g., line 458: `from graph.deduction import eliminate_by_guaranteed_evidence`). The class-level import is both unnecessary and confusing -- it creates a class attribute that shadows the local import, though in practice the local import wins. This is dead code at class scope.

**Verdict:** REFACTOR. Remove the class-level import line (file is in kill list anyway, but the pattern should not be carried forward).

---

### 14. `test_deduction.py:test_insanity_more_permissive`
**Lines 308-320**

```python
def test_insanity_more_permissive():
    confirmed = ["emf_5", "dots"]
    night = narrow_candidates(confirmed, [], [], "nightmare")
    insanity = narrow_candidates(confirmed, [], [], "insanity")
    assert len(insanity) > len(night)
```

**Problem:** This test assumes Insanity always returns strictly more candidates than Nightmare. But in the current `oracle/deduction.py`, both Nightmare and Insanity are in the same `permissive` branch (line 55: `difficulty in ("nightmare", "insanity")`). They are treated identically -- both allow hiding evidence. So `len(insanity) == len(night)` and this test would FAIL against the production code. The test only passes because it runs against `graph/deduction.py` which may have different logic.

**Verdict:** DELETE (file is in kill list, but this is also an erroneous assertion).

---

## LEAKY TESTS (shared state, execution order)

### 15. `test_tools.py` -- Global state pollution via `_state`
**Lines 20, 42-46**

```python
from graph.tools import ... _state ...

@pytest.fixture(autouse=True)
def reset_state():
    state = _fresh_state()
    bind_state(state)
    yield state
    sync_state_from(state)
```

**Problem:** Tests directly import and mutate the global `_state` dict from `graph.tools`. Multiple test classes (`TestInitInvestigationSprint2`, `TestPhaseRollback`) directly assign to `_state["investigation_phase"]`, `_state["soft_facts"]`, etc. (lines 431, 437, 441, 445, 542, 549). If the fixture teardown fails or tests run in parallel, state leaks between tests.

**Verdict:** DELETE (file is in kill list). The `InvestigationEngine` pattern in `oracle/engine.py` eliminates this entire class of issues.

---

### 16. `test_radio_fx.py:TestConfidenceCodedNoise.test_more_candidates_means_more_noise`
**Lines 153-171**

```python
def test_more_candidates_means_more_noise(self, config):
    noise_config = AudioConfig(...)
    noise_fx = RadioFX(noise_config)
    result_27 = noise_fx.apply(silence.copy(), sr, candidate_count=27)
    result_1 = noise_fx.apply(silence.copy(), sr, candidate_count=1)
    rms_27 = np.sqrt(np.mean(result_27**2))
    rms_1 = np.sqrt(np.mean(result_1**2))
    assert rms_27 > rms_1 * 2
```

**Problem:** Uses `np.random.default_rng()` without a seed (line 178 in radio_fx.py: `noise = np.random.default_rng().normal(...)`). The noise is random each run. While the mean behavior should hold, with bad luck this test could flake. The `* 2` multiplier assumption could fail for edge-case random seeds.

**Verdict:** REFACTOR (minor). The test is fundamentally sound but should use a seeded RNG or increase the audio length to reduce variance. Low priority.

---

## NON-DETERMINISTIC TESTS

### 17. `test_radio_fx.py:TestProcessingLatency.test_fx_processing_under_50ms`
**Lines 227-231**

```python
def test_fx_processing_under_50ms(self, fx, short_audio, config):
    start = time.perf_counter()
    fx.apply(short_audio, config.sample_rate, candidate_count=10)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 50
```

**Problem:** Timing-based assertion. Will fail on slow CI runners, overloaded machines, or during GC pauses. The 50ms threshold is described as "generous" but hardware-dependent tests are inherently non-deterministic.

**Verdict:** REFACTOR. Use a much higher threshold (200ms+) or mark as `@pytest.mark.slow` and skip in CI. Alternatively, verify algorithmic complexity rather than wall-clock time.

---

## Summary

| # | File:Test | Issue Type | Verdict |
|---|-----------|-----------|---------|
| 1 | `test_engine.py:TestRecordEvidence.test_identification_triggered_on_single_candidate` | Guarded assertion | REFACTOR |
| 2 | `test_engine.py:TestRecordEvidence.test_phase_shifted_flag` | Guarded assertion | REFACTOR |
| 3 | `test_engine.py:TestGhostTestLookup.test_ghost_with_test` | Guarded assertion | REFACTOR |
| 4 | `test_engine.py:TestGhostTestLookup.test_ghost_without_test` | Trivially true assertion | REFACTOR |
| 5 | `test_nodes.py:TestPhaseShiftNode.test_identifies_when_narrowed_to_one` | Guarded assertion (dead file) | DELETE |
| 6 | `test_voice_output.py:TestVoiceOutputProtocol.*` | Theater (hasattr) | REFACTOR |
| 7 | `test_tts.py:TestTTSProviderProtocol.test_kokoro_satisfies_protocol` | Theater (hasattr) | REFACTOR |
| 8 | `test_stt.py:TestImportError.test_import_error_without_realtimestt` | Pure theater (raises own error) | DELETE |
| 9 | `test_responses.py:TestEvidenceResponse.test_confirmed_includes_confirmed` | Weak assertion | REFACTOR |
| 10 | `test_responses.py:TestEvidenceResponse.test_ruled_out_includes_ruled_out` | Weak assertion | REFACTOR |
| 11 | `test_responses.py:TestMinimumLength.test_long_response_not_padded` | No-op if branch | REFACTOR |
| 12 | `test_voice_output.py:TestCLIFlags.test_speak_without_text_exits` | Zero assertions | DELETE |
| 13 | `test_deduction.py:TestEliminateByGuaranteedEvidence` | Class-level dead import | REFACTOR |
| 14 | `test_deduction.py:test_insanity_more_permissive` | Wrong assertion for prod code | DELETE |
| 15 | `test_tools.py` (multiple) | Global state mutation | DELETE |
| 16 | `test_radio_fx.py:test_more_candidates_means_more_noise` | Unseeded RNG | REFACTOR |
| 17 | `test_radio_fx.py:test_fx_processing_under_50ms` | Timing-dependent | REFACTOR |

**17 bad tests found.** 4 should be deleted, 13 should be refactored.
