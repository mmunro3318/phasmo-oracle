# REFACTOR.md — Structural Observations

*Documented during Sprint 2 engineering review. These are observations about code structure that could be streamlined for easier debugging and iteration.*

---

## Bugs Fixed (Sprint 2 Phase 0)

### 1. Ghost evidence query returned raw dump
`intent_router.py` set `query_field="evidence"` for ghost evidence queries, bypassing the rich contextualized response in `query_ghost_database` (lines 286-322). Removed `query_field` so the full summary runs with CONFIRMED/untested markers and "Still need to test" breakdown.

### 2. Duplicate behavioral pattern key
`ghost_stepped_in_salt` appeared twice in `BEHAVIORAL_PATTERNS`. The second (overly broad: just `salt`) overwrote the first (specific: `stepped in salt`, `salt footprints`). Deleted the duplicate.

---

## Structural Changes Made

### Evidence thresholds moved to deduction.py
`_EVIDENCE_THRESHOLDS` was in `tools.py` but needed by `deduction.py` and `nodes.py`. Moved to `deduction.py` as `EVIDENCE_THRESHOLDS` (public) alongside a new `evidence_threshold_reached()` helper. This prevents the threshold check from being reimplemented in 4 places.

### Hard Invariant #1 expanded
Updated CLAUDE.md to allow pure Python graph nodes to mutate state. The invariant's purpose is preventing LLM state corruption — pure Python nodes are safe.

---

## Observations for Future Refactoring

### `record_evidence` is 110 lines and does 6 things
`tools.py:record_evidence` handles: synonym normalization, validation, state update, deduction re-run, over-proofed/threshold detection, identification announcement, and Mimic awareness. Consider extracting the over-proofed detection and identification logic into separate helpers. Not blocking — the function is well-organized with clear sections.

### `execute_tool_node` is a growing dispatch table
`nodes.py:execute_tool_node` is an if/elif chain that maps action strings to tool invocations. Sprint 2 adds 4+ new cases. Consider a registry pattern: `TOOL_DISPATCH = {"record_evidence": lambda intent: record_evidence.invoke({...})}`. Not blocking — the current approach is explicit and easy to debug.

### Intent router pattern ordering matters
The router checks patterns in a specific order (init → endgame → evidence → advice → ghost query → state → behavioral → generic ghost → fallback). Adding new pattern groups requires careful insertion to avoid shadowing. Consider adding a comment block documenting the priority order and why. Partially addressed in Sprint 2 with new pattern groups.

### `_state` dict is untyped
The shared mutable state dict has no schema enforcement. New fields added to `OracleState` TypedDict don't automatically validate at runtime. Consider a `validate_state()` helper that checks required keys exist — useful for debugging when a new field is missing.

### Ghost database YAML has no schema validation
`ghost_database.yaml` is loaded and cached but never validated against an expected schema. Missing fields (e.g., a ghost without `community_tests`) cause runtime errors in tools that assume the field exists. Consider a startup validation step that checks all ghosts have required fields.
