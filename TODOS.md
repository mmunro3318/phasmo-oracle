# TODOS

## Ghost identification announcement at 3 evidence
**Priority:** P1 | **Effort:** S (CC: ~15 min) | **Sprint:** 2

When 3 evidence types are confirmed and only 1 candidate remains, Oracle should definitively announce the ghost type. Currently Oracle only reports candidate counts — it never says "It's a Banshee."

**Why:** This is the payoff moment of the whole tool. The player confirms 3 evidence, Oracle narrows to 1 ghost, and should announce it with confidence and personality.

**Where to start:** This is the `identify_node` from Sprint 2's plan. The deduction engine already returns 1 candidate when evidence is sufficient — the graph just needs a conditional edge that triggers an identification announcement when `len(candidates) == 1` and `len(evidence_confirmed) >= threshold`.

---

## "What should we do next?" — suggest untested evidence
**Priority:** P1 | **Effort:** S (CC: ~15 min) | **Sprint:** 2

When the player asks "what should we do next?" or "what evidence should we test?", Oracle should suggest which evidence types haven't been confirmed or ruled out yet. Example: "You haven't tested Spirit Box or D.O.T.S. yet. I'd start with Spirit Box — it's quick to check."

**Why:** This is a natural part of the investigation flow. Players often forget which evidence they haven't checked yet, especially mid-game.

**Where to start:** Add a new intent in `intent_router.py` for "advice" queries. The tool result could compute `all_evidence - confirmed - ruled_out` and suggest the remaining types. The narrator adds personality.

---

## Mimic edge case — Ghost Orbs always present
**Priority:** P1 | **Effort:** M (CC: ~20 min) | **Sprint:** 2

The Mimic always generates Ghost Orbs as a fake 4th evidence, on all difficulties. Special handling needed:
- Whenever Ghost Orbs are present, The Mimic should always be mentioned as a possibility (unless other evidence explicitly rules it out).
- If 4 evidence types are confirmed (including orbs), it's always The Mimic.
- On Nightmare/Insanity: Mimic still generates the extra orb evidence. This means a Mimic on Nightmare shows 2 real + 1 orb = 3 observable evidence (not 2 like other ghosts).

**Why:** This is a game-critical edge case. Experienced Phasmo players know to watch for Mimic, and Oracle should flag it proactively.

**Where to start:** The over-proofed detection in `record_evidence` already handles 4+ evidence. Add a Mimic-awareness note to the narrator context when orbs are confirmed and multiple candidates remain. The deduction engine already handles the `fake_evidence` field correctly — this is about proactive commentary, not deduction logic.

---

## Narrator creativity — 15% more personality
**Priority:** P2 | **Effort:** S (CC: ~10 min) | **Sprint:** 2+

The narrator responses are functional but "a tad bland." User wants ~15% more creativity in Oracle's delivery — more dry wit, more character. Not over-the-top, just more personality in the 2-sentence responses.

**Why:** The persona is what makes Oracle delightful vs. just functional. The current narrator prompt is conservative.

**Where to start:** Adjust the `_NARRATOR_PROMPT` in `graph/nodes.py`. Add a few example responses showing the desired tone. Consider bumping narrator temperature from 0 to 0.2-0.3 for more variety.

---

## Ollama timeout handling
**Priority:** P2 | **Effort:** S (CC: ~10 min) | **Sprint:** 2+

When qwen2.5:7b takes >30s on CPU inference, the REPL blocks with no feedback. Add a timeout wrapper with a "Thinking..." indicator and graceful timeout after 60s.

**Why:** CPU inference occasionally takes 30-60s. Sprint 2 voice mode makes this more critical.

**Depends on:** Sprint 1 core complete.

**Where to start:** Wrap `llm.invoke()` in `narrate_node()` and `llm_classify_node()` with a threading timeout. Add a Rich spinner.
