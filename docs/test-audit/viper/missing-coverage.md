# MISSING COVERAGE -- Critical Untested Production Code

Auditor: **Viper**
Date: 2026-04-02

---

## CRITICAL: Functions with ZERO test coverage in production code

### M1. `oracle/deduction.py:narrow_candidates` -- Nightmare/Insanity ruled_out behavior

**Source:** `oracle/deduction.py`, lines 52-109
**What's untested:** The production `narrow_candidates` treats `difficulty in ("nightmare", "insanity")` as `permissive`, which means ruled-out evidence does NOT eliminate ghosts (except for Mimic fake evidence). The only tests for `narrow_candidates` are in `test_deduction.py` which imports from `graph.deduction` (dead module). The graph version has a different algorithm (max_hidden=1 for nightmare, max_hidden=2 for insanity). **There are ZERO tests verifying the production `oracle.deduction.narrow_candidates` on any difficulty.**

**Concrete test needed:**
```python
# In test_engine.py or a new test_oracle_deduction.py
def test_nightmare_ruled_out_does_not_eliminate():
    """On nightmare, ruling out evidence should NOT eliminate ghosts
    (they might be hiding it), except for Mimic fake evidence."""
    from oracle.deduction import narrow_candidates
    # Wraith has [dots, emf_5, spirit_box]. Rule out dots.
    candidates = narrow_candidates([], ["dots"], [], "nightmare")
    assert "Wraith" in candidates  # Can hide dots on nightmare

def test_professional_ruled_out_eliminates():
    from oracle.deduction import narrow_candidates
    candidates = narrow_candidates([], ["dots"], [], "professional")
    assert "Wraith" not in candidates  # Cannot hide on professional
```

---

### M2. `oracle/deduction.py:narrow_candidates` -- Insanity vs Nightmare (no differentiation)

**Source:** `oracle/deduction.py`, lines 55, 83-93
**What's untested:** The production code treats nightmare and insanity identically -- both are `permissive` (line 55). The graph version differentiates them (max_hidden=1 vs max_hidden=2). This means on production insanity, the code is **more permissive than nightmare** by coincidence (because both skip the ruled_out check entirely), but for the confirmed check, both skip it. **There is no test verifying whether this behavior is intentional or a bug.**

**Concrete test needed:**
```python
def test_insanity_confirmed_check_behavior():
    """On insanity, confirming evidence X should keep ghosts that have X
    but also ghosts that don't have X (because insanity can hide 2)."""
    from oracle.deduction import narrow_candidates
    # All 27 should remain on insanity with just 1 confirmed evidence
    # because any ghost could be hiding its evidence
    candidates = narrow_candidates(["emf_5"], [], [], "insanity")
    # This will actually eliminate ghosts that don't have emf_5 because
    # the production code does NOT implement hiding logic for confirmed evidence.
    # oracle/deduction.py only skips ruled_out check for nightmare/insanity,
    # not the confirmed check. The confirmed check is strict on ALL difficulties.
    # This is correct per the code comment on line 96-102.
```

---

### M3. `oracle/engine.py:_save_session` -- Session persistence

**Source:** `oracle/engine.py`, lines 932-959
**What's untested:** `test_engine.py:TestEndGame.test_writes_to_history_json` does test this path, but it doesn't test:
- Appending to an existing history file (only tests creating a new one)
- Handling of corrupt JSON in existing history file (line 945: `except (json.JSONDecodeError, ValueError)`)
- Concurrent write safety

**Concrete tests needed:**
```python
def test_appends_to_existing_history(engine, tmp_path, monkeypatch):
    monkeypatch.setattr("oracle.engine.config.SESSIONS_DIR", str(tmp_path))
    # Pre-populate
    (tmp_path / "history.json").write_text('[{"ghost": "Spirit"}]')
    engine.lock_in("Wraith")
    engine.end_game("Wraith")
    history = json.loads((tmp_path / "history.json").read_text())
    assert len(history) == 2

def test_recovers_from_corrupt_history(engine, tmp_path, monkeypatch):
    monkeypatch.setattr("oracle.engine.config.SESSIONS_DIR", str(tmp_path))
    (tmp_path / "history.json").write_text("not json{{{")
    engine.lock_in("Wraith")
    engine.end_game("Wraith")
    history = json.loads((tmp_path / "history.json").read_text())
    assert len(history) == 1  # Corrupt data discarded, new entry written
```

---

### M4. `oracle/engine.py:ghost_test_result` -- Elimination and identification logic

**Source:** `oracle/engine.py`, lines 745-805
**What's untested:** `test_engine.py` has `TestGhostTestLookup` but NO tests for `ghost_test_result()`. This method:
- Eliminates ghosts when positive tests fail
- Eliminates ghosts when negative tests pass
- Identifies ghosts when positive tests pass
- Identifies ghosts when negative tests fail
- Re-narrows candidates after elimination

None of these paths are tested.

**Concrete tests needed:**
```python
def test_positive_test_failed_eliminates(engine):
    engine.new_game("professional")
    result = engine.ghost_test_result("Goryo", passed=False)
    assert "Goryo" in result.eliminated_ghosts
    assert "Goryo" not in engine.candidates

def test_positive_test_passed_identifies(engine):
    engine.new_game("professional")
    result = engine.ghost_test_result("Goryo", passed=True)
    assert result.identified_ghost == "Goryo"

def test_negative_test_passed_eliminates(engine):
    engine.new_game("professional")
    # Wraith test is negative type
    result = engine.ghost_test_result("Wraith", passed=True)
    assert "Wraith" in result.eliminated_ghosts

def test_unknown_ghost_test_result(engine):
    result = engine.ghost_test_result("Casper", passed=True)
    assert result.eliminated_ghosts == []
```

---

### M5. `oracle/engine.py:available_tests` -- Available test listing

**Source:** `oracle/engine.py`, lines 692-709
**What's untested:** No test calls `engine.available_tests()`. This method iterates candidates, looks up ghost tests, and returns testable/untestable lists.

**Concrete test needed:**
```python
def test_available_tests_after_narrowing(engine):
    engine.record_evidence("dots", "confirmed")
    engine.record_evidence("emf_5", "confirmed")
    engine.record_evidence("uv", "confirmed")
    result = engine.available_tests()
    assert result.total_candidates == len(engine.candidates)
    # Goryo should be in testable (it has a test in ghost_tests.yaml)
    testable_names = [name for name, _ in result.testable]
    if "Goryo" in engine.candidates:
        assert "Goryo" in testable_names
```

---

### M6. `oracle/runner.py:_dispatch` -- Multiple untested dispatch paths

**Source:** `oracle/runner.py`, lines 239-312
**What's untested:** While `test_voice_output.py` tests `run_loop` end-to-end for a single command, the `_dispatch` function has many branches with no direct tests:
- `action == "record_behavioral_event"` (line 253)
- `action == "query_ghost_database"` (line 262)
- `action == "suggest_next_evidence"` (line 265)
- `action == "record_theory"` (line 267)
- `action == "lock_in"` (line 277)
- `action == "confirm_true_ghost"` (line 280)
- `action == "register_players"` (line 283)
- `action == "query_tests"` (line 286) -- both branches (with and without ghost_name)
- `action == "ghost_test_result"` (line 292)
- `action == "query_behavior"` (line 296)
- `action == "change_voice"` (line 302)
- Extra evidence handling (lines 249-250)

The `extra_evidence` loop on line 249 calls `engine.record_evidence` for each additional evidence but **discards the results**. There's no test verifying this behavior or that multiple evidence in one utterance works correctly.

**Concrete test needed:**
```python
def test_dispatch_extra_evidence():
    from oracle.runner import _dispatch
    from oracle.parser import ParsedIntent
    engine = InvestigationEngine()
    engine.new_game("professional")
    intent = ParsedIntent(
        action="record_evidence",
        evidence_id="orb",
        status="confirmed",
        extra_evidence=["freezing"],
        raw_text="we found orbs and freezing"
    )
    result = _dispatch(engine, intent)
    assert "orb" in engine.evidence_confirmed
    assert "freezing" in engine.evidence_confirmed
```

---

### M7. `oracle/parser.py:parse_intent` -- Voice change pattern

**Source:** `oracle/parser.py`, lines 334-345
**What's untested:** The voice change pattern is not tested in `test_parser.py`. Input like "change voice to bm_fable" should return `action="change_voice"` with `voice_name="bm_fable"`.

**Concrete test needed:**
```python
def test_change_voice():
    intent = parse_intent("change voice to bm_george")
    assert intent.action == "change_voice"
    assert intent.voice_name == "bm_george"
```

---

### M8. `oracle/parser.py:parse_intent` -- Behavioral observation patterns (remaining patterns)

**Source:** `oracle/parser.py`, lines 173-208
**What's untested:** While `test_intent_router.py` (dead) tests some behavioral patterns, `test_parser.py` has ZERO tests for behavioral observation patterns. The following are untested against the production parser:
- `ghost_stepped_in_salt`
- `ghost_is_male`
- `ghost_turned_breaker_on`
- `ghost_turned_breaker_off_directly`
- `airball_event_observed`
- `ghost_changed_favorite_room`
- `ghost_turned_on_standard_light_switch`
- `dots_visible_with_naked_eye`
- `ghost_hunted_from_same_room_as_player`

Also untested: soft fact patterns (`banshee_scream`, `fusebox_emf`, `freezing_breath_during_hunt`).

---

### M9. `oracle/parser.py:parse_intent` -- Theory patterns

**Source:** `oracle/parser.py`, lines 249-253, 409-440
**What's untested in test_parser.py:** Only one theory test exists (`test_we_think_its_a_ghost`), which tests the "we think" phrasing. Missing:
- Named player theories: "Kayden thinks it's a Poltergeist"
- Self theories: "I suspect Wraith", "my theory is Banshee"
- First-person pronoun normalization to "me"

---

### M10. `oracle/parser.py:parse_intent` -- Player registration patterns

**Source:** `oracle/parser.py`, lines 257-260, 443-453
**What's untested in test_parser.py:** Zero tests for player registration. "add player Kayden" and "register Mike and Kayden as players" are only tested in `test_intent_router.py` (dead).

---

### M11. `oracle/parser.py:parse_intent` -- Test query patterns

**Source:** `oracle/parser.py`, lines 237-245, 455-472
**What's untested in test_parser.py:** Zero tests for test query patterns. "what tests for Goryo?", "how do we test for Banshee?", "what tests should we try?" only tested in dead file.

---

### M12. `oracle/engine.py:_check_phase_shift` -- Phase rollback path

**Source:** `oracle/engine.py`, lines 859-879
**What's untested:** The phase rollback logic (lines 868-878) occurs when `investigation_phase == "behavioral"` but evidence drops below threshold. While `test_tools.py` (dead) tests this via `graph.tools`, there's no test in `test_engine.py` for:
```python
# Scenario: Reach threshold -> phase shifts to behavioral -> retract evidence -> phase rolls back
engine.new_game("nightmare")
engine.record_evidence("emf_5", "confirmed")
engine.record_evidence("dots", "confirmed")  # threshold reached
assert engine.investigation_phase == "behavioral"  # (if phase_shift was triggered)
# Retract dots by changing to ruled_out
engine.record_evidence("dots", "ruled_out")
assert engine.investigation_phase == "evidence"  # rollback
```

---

### M13. `oracle/responses.py:_build_ghost_query_response` -- Evidence status "CONFIRMED" vs "confirmed" mismatch

**Source:** `oracle/responses.py`, line 196
**What's untested:** The response builder checks `if st == "confirmed"` (lowercase) but per the known bug listed in the audit instructions, the engine uses `"confirmed"` (lowercase) while responses check `"CONFIRMED"` (uppercase). Wait -- I re-read: responses.py line 196 checks `st == "confirmed"` (lowercase), which matches. But the audit instructions say: "responses.py:_build_ghost_query_response checks 'CONFIRMED' (uppercase) but engine uses 'confirmed'". Let me re-read... Line 196: `confirmed = [ev for ev, st in result.evidence_status.items() if st == "confirmed"]`. This IS lowercase. The known bug may have been fixed already, or the bug description refers to a different state. **Either way, there's no test that verifies the evidence_status matching logic works end-to-end.**

---

### M14. `oracle/engine.py:_find_best_discriminator` -- Best evidence suggestion logic

**Source:** `oracle/engine.py`, lines 888-908
**What's untested:** This method finds the evidence type that best splits candidates in half. While `test_engine.py:TestSuggestNext` exists, it never verifies `best_evidence` is actually returned or correct. The test just checks `evidence_remaining` count and that `suggestion_text` is non-empty.

**Concrete test needed:**
```python
def test_best_discriminator_returned(engine):
    # Narrow to a small set where we can predict the best discriminator
    engine.record_evidence("dots", "confirmed")
    engine.record_evidence("emf_5", "confirmed")
    result = engine.suggest_next()
    # With 2 confirmed and several candidates, best_evidence should be set
    if 1 < len(result.candidates) <= 8:
        assert result.best_evidence is not None
        assert result.best_evidence_label is not None
```

---

### M15. `oracle/responses.py:_build_player_registration_response` -- Known bug untested

**Source:** `oracle/responses.py`, line 373
**What's untested:** The known bug says `result.names` is used instead of `result.added`. Looking at the code: line 373 uses `result.added` (correct field name for `PlayerRegistrationResult`). But there's no test in `test_responses.py` that exercises `_build_player_registration_response` to verify the field access is correct. The `PlayerRegistrationResult` type is not even imported in `test_responses.py` imports (it IS imported but never used in a test).

---

## Summary

| ID | Source File | What's Missing | Severity |
|----|------------|----------------|----------|
| M1 | oracle/deduction.py | narrow_candidates on ANY difficulty | CRITICAL |
| M2 | oracle/deduction.py | Insanity vs Nightmare differentiation | HIGH |
| M3 | oracle/engine.py | Session persistence edge cases | MEDIUM |
| M4 | oracle/engine.py | ghost_test_result (all paths) | CRITICAL |
| M5 | oracle/engine.py | available_tests | HIGH |
| M6 | oracle/runner.py | _dispatch branches (most untested) | HIGH |
| M7 | oracle/parser.py | Voice change pattern | MEDIUM |
| M8 | oracle/parser.py | All behavioral observation patterns | HIGH |
| M9 | oracle/parser.py | Theory patterns (most) | MEDIUM |
| M10 | oracle/parser.py | Player registration patterns | MEDIUM |
| M11 | oracle/parser.py | Test query patterns | MEDIUM |
| M12 | oracle/engine.py | Phase rollback | HIGH |
| M13 | oracle/responses.py | Evidence status matching e2e | MEDIUM |
| M14 | oracle/engine.py | Best discriminator logic | MEDIUM |
| M15 | oracle/responses.py | Player registration response | LOW |

**15 coverage gaps identified. 2 CRITICAL, 5 HIGH, 7 MEDIUM, 1 LOW.**
