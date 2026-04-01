# TODOS

## ~~Ghost identification announcement at 3 evidence~~ DONE (Sprint 2)
Implemented as `identify_node` in Sprint 2 conditional graph. Auto-fires when 1 candidate remains and evidence threshold is met.

---

## ~~"What should we do next?" — suggest untested evidence~~ DONE (Sprint 1)
`suggest_next_evidence` tool already implemented with evidence diffing, discriminator scoring, and threshold messaging. Bug fix in Sprint 2: `query_field="evidence"` bypass removed.

---

## ~~Mimic edge case — Ghost Orbs always present~~ DONE (Sprint 1)
Over-proofed detection in `record_evidence` + fake_evidence handling in `narrow_candidates`. 7 passing Mimic-specific tests.

---

## ~~Narrator creativity — 15% more personality~~ DONE (Sprint 2)
Updated `_NARRATOR_PROMPT` with BBC presenter persona, example responses showing desired dry wit, and tone directives for multi-beat responses.

---

## Ollama timeout handling
**Priority:** P2 | **Effort:** S (CC: ~10 min) | **Sprint:** 3+

When qwen2.5:7b takes >30s on CPU inference, the REPL blocks with no feedback. Add a timeout wrapper with a "Thinking..." indicator and graceful timeout after 60s.

**Why:** CPU inference occasionally takes 30-60s. Sprint 3 voice mode makes this more critical.

**Where to start:** Wrap `llm.invoke()` in `narrate_node()` and `llm_classify_node()` with a threading timeout. Add a Rich spinner.

---

## Adaptive test fixtures (Ollama auto-detect)
**Priority:** P2 | **Effort:** S (CC: ~10 min) | **Sprint:** 3

Create a pytest fixture that detects whether Ollama is running. If reachable, provide the real LLM; if not, provide a mock with canned responses. Eliminates the need for `@pytest.mark.llm` marker as a hard gate.

**Why:** Makes the test suite work for Kayden who may not have Ollama running. Tests still exercise real LLM when available.

**Where to start:** Add a `conftest.py` fixture that tries `httpx.get("http://localhost:11434/api/tags")`. Provide `llm_or_mock` fixture.
