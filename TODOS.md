# TODOS

## Ollama timeout handling
**Priority:** P2 | **Effort:** S (CC: ~10 min)

When phi4-mini hangs >30s on CPU inference, the REPL blocks with no feedback. Add a timeout wrapper around the LLM call with a "Thinking..." indicator and graceful timeout after 60s.

**Why:** CPU inference on complex prompts occasionally takes 30-60s. Sprint 2 voice mode makes this more critical since the user is waiting silently with no visual feedback.

**Depends on:** Sprint 1 core complete.

**Where to start:** Wrap `llm.invoke()` in `llm_node()` with a threading timeout or async pattern. Add a Rich spinner that shows "Thinking..." while waiting.
