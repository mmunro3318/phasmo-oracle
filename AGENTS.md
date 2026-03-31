# AGENTS.md — Oracle Project Guide for AI Assistants

This file is addressed to you, the AI. It tells you what Oracle is, what invariants must never be broken, where the sharp edges are, and how to work on the project without undoing careful design decisions.

Read this before touching any code. Read `Oracle Architecture Design.md` next. Then read the relevant sprint plan before making changes.

**Note: I'm developing this project in parallel with other AI coding tools/platforms on separate branches. The best product will be the one that's deployed to the public repo.**

---

## What Oracle Is (and Isn't)

Oracle is a **two-stage LangGraph agent** that identifies Phasmophobia ghosts from spoken evidence. It is **not a chatbot**. The distinction matters for every design decision in the codebase.

The central rule:

> **Ghost deduction is pure Python. The LLM is never asked to reason about ghost identity.**

Oracle uses a **two-stage chain** architecture:

1. **Deterministic intent parser** (`graph/intent_router.py`) — regex/keyword matching handles ~85% of inputs instantly with zero LLM dependency. Falls back to LLM for ambiguous inputs.
2. **LLM narrator** — generates 2-sentence persona responses from tool results. The LLM never calls tools directly.

The LLM's only jobs are:
1. Classify ambiguous inputs that the deterministic parser can't handle (~15% of inputs)
2. Generate natural-language sentences around facts that the deduction engine already computed

If you find yourself adding ghost-identification logic to a prompt, you are doing it wrong. Put it in `graph/deduction.py` instead.

**Model:** `qwen2.5:7b` via Ollama. phi4-mini was tested and failed — it outputs tool-call syntax as plain text instead of structured JSON. See `docs/Insights from Demonic Tutor.md` for model evaluation notes.

---

## Hard Invariants — Never Break These

These are architectural rules. Violating them will produce silent bugs that are difficult to diagnose.

**1. The LLM never writes to `OracleState` directly.**
All state mutations happen inside tool functions (`graph/tools.py`), which write to the shared `_state` dict. The graph then syncs `_state` back to the caller via `sync_state_from()`. If you add a node that lets the LLM write a field directly, the deduction engine and DB layer will see stale data.

**2. `graph/deduction.py` has zero LLM dependencies.**
It imports only `yaml`, `pathlib`, and standard library. It is fully testable with `pytest` and no running services. Never add an `import` from `langchain`, `ollama`, or `graph.llm` here.

**3. `identify_node` is triggered by the graph's conditional edge, not by a tool call.**
The function `route_after_tools` in `graph/nodes.py` decides when identification fires, based on `len(candidates) == 1` and evidence count. The LLM cannot call `identify_ghost` as a tool. This is intentional — it prevents the model from prematurely identifying a ghost before the deduction engine agrees.

**4. `route_after_tools` is a pure function.**
It reads state, returns a string. No side effects, no DB writes, no logging. It is a LangGraph conditional edge function — LangGraph may call it more than once.

**5. Tools write to `_state`, never to a local copy.**
Every tool function uses the module-level `_state` dict that was bound by `bind_state()` before the graph was invoked. Never create a `new_state = {}` inside a tool and return it — changes won't propagate.

**6. `oracle_correct` has three states: `1`, `0`, and `None`.**
`1` = correct identification. `0` = wrong identification. `None` = Oracle never reached a single candidate (inconclusive). Never coerce `None` to `False` or `0`. The stats queries exclude null rows from success rate calculations.

**7. All audio is float32, clipped to `[-1.0, 1.0]` before playback.**
Apply `np.nan_to_num()` then `np.clip()` to any audio array before passing it to `AudioRouter.play()` or `sd.play()`. Skipping this causes `PortAudio` overflow errors.

**8. `sd.play()` must always be called with `blocking=True`.**
Using `blocking=False` alongside an active `sd.InputStream` (the loopback or mic stream) causes a global stream conflict in PortAudio. All playback happens through `AudioRouter._play_device()`, which uses `blocking=True`. Do not add new `sd.play()` calls elsewhere.

---

## Project Structure at a Glance

```
graph/intent_router.py ← deterministic regex intent parser — handles ~85% of inputs, no LLM
graph/deduction.py     ← pure Python rules engine — no LLM, ever
graph/tools.py         ← 5 LangChain tools (Sprint 1); all state mutations happen here
graph/nodes.py         ← graph nodes: parse_intent, llm_classify, execute_tool, narrate
graph/graph.py         ← StateGraph wiring (two-stage chain); don't change topology without updating tests
graph/llm.py           ← LLM factory (Ollama); call init_llm() once
graph/state.py         ← OracleState TypedDict; add fields here when new sprint data needed
graph/session_log.py   ← JSONL event log (Sprint 2+); DB writes go through db/database.py separately
db/database.py         ← SQLite CRUD (Sprint 6); always check session_id before writing
db/queries.py          ← read-only analytics (Sprint 6); never mutates DB
voice/audio_router.py  ← all output device routing (Sprint 3+); do not bypass it
voice/text_to_speech.py← kokoro-onnx synthesis (Sprint 2+); owns is_speaking flag
config/settings.py   ← all config values; never hardcode device names or model strings
```

---

## State Flow

Understanding how state moves through the system prevents most bugs.

```
main.py: make_initial_state()
  → state dict created with all OracleState fields

main.py: run_turn()
  → state["prev_candidate_count"] = len(candidates)  # snapshot before tools run
  → state["messages"] = []                            # fresh thread each turn
  → bind_state(state)                                 # tools now see live state
  → oracle_graph.invoke(state)
      → llm_node: LLM sees state summary + user_text → emits tool_call or text
      → tools node: tool mutates _state dict
      → route_after_tools: reads _state (via OracleState passed by LangGraph)
      → identify_node / commentary_node / respond: produce oracle_response
  → sync_state_from(state)                            # pull _state mutations back
  → result["oracle_response"] → TTS
```

Key point: `bind_state()` and `sync_state_from()` are the bridge between the LangGraph invocation (which gets a copy of state) and the caller's live dict. Always call both. Forgetting `sync_state_from()` means evidence confirmed this turn won't appear in the next turn's state summary.

---

## The Deduction Engine

`graph/deduction.py:narrow_candidates()` is the most important function in the codebase. Understand it before modifying tools or adding new evidence types.

Rules it enforces:

- A ghost is eliminated if it lacks any confirmed evidence, unless difficulty is Nightmare (permissive: a ghost may hide one non-guaranteed evidence)
- A ghost is eliminated if it has any ruled-out evidence, **except** The Mimic, whose `fake_evidence: orb` is not a real evidence type
- A ghost in `eliminated_ghosts` is always removed regardless of evidence

The Mimic exception is tested in `tests/test_deduction.py:test_mimic_survives_orb_ruled_out`. This test must always pass. If you change the deduction logic, run this test first.

---

## Auto-Trigger Logic

`route_after_tools` in `graph/nodes.py` controls when Oracle speaks unprompted. The thresholds:

| Condition                                                   | Route          | Node                     |
| ----------------------------------------------------------- | -------------- | ------------------------ |
| `len(candidates) == 1` AND `len(confirmed) >= threshold`    | `"identify"`   | `identify_node`          |
| candidates changed this turn AND `1 < len(candidates) <= 5` | `"commentary"` | `commentary_node`        |
| anything else                                               | `"llm"`        | loops back to `llm_node` |

Evidence thresholds by difficulty (in `_EVIDENCE_THRESHOLD`):

- Amateur / Intermediate / Professional: **3**
- Nightmare: **2**
- Insanity: **1**

"Candidates changed this turn" is determined by comparing `len(candidates)` to `state["prev_candidate_count"]`, which is snapshotted in `main.py` before each `oracle_graph.invoke()`. If you move the snapshot elsewhere, auto-commentary will fire incorrectly.

---

## Tool Reference

| Tool                      | Writes to DB?                            | Mutates candidates?               | Notes                                            |
| ------------------------- | ---------------------------------------- | --------------------------------- | ------------------------------------------------ |
| `init_investigation`      | Yes — `sessions` row                     | Yes — resets to 27                | Also resets `session_start_time`                 |
| `record_evidence`         | Yes — `evidence_events`                  | Yes — via `narrow_candidates()`   | Handles Mimic exception                          |
| `record_behavioral_event` | No                                       | Yes — if `eliminator_key` matches | Key must match `observation_eliminators` in YAML |
| `get_investigation_state` | No                                       | No                                | Read-only summary                                |
| `query_ghost_database`    | No                                       | No                                | Loads from YAML, case-insensitive name match     |
| `record_ghost_event`      | Yes — `ghost_events`                     | No                                | Normalises event_type to known set               |
| `record_death`            | Yes — `deaths`, increments `death_count` | No                                | Defaults player to `state["speaker"]`            |
| `confirm_true_ghost`      | Yes — closes `sessions` row              | No                                | Computes `oracle_correct`                        |

---

## LLM Configuration

**Model:** `qwen2.5:7b` via Ollama. phi4-mini was tested and **failed** — it outputs tool-call syntax as plain text instead of structured JSON that LangGraph can parse. Do not switch back to phi4-mini.

Never instantiate `ChatOllama` directly in nodes. Always use:

```python
from graph.llm import get_llm

llm = get_llm()               # temperature=0, tools bound
```

`init_llm()` is called once in `main()`. It checks Ollama health, validates tool-call capability, and raises `RuntimeError` if unavailable. The `current_backend()` function returns `"ollama"` or `"unknown"`.

**Note:** In the two-stage chain architecture, the LLM is used for narration and fallback classification only — not for direct tool calling. The deterministic intent router in `graph/intent_router.py` handles evidence parsing.

---

## Database Layer

All writes check `session_id` first:

```python
session_id = _state.get("session_id")
if session_id:
    from db.database import write_evidence_event
    write_evidence_event(...)
```

This guard is important. In text-mode testing, a session may not have been initialised via `init_investigation`. Without the guard, tools will raise a foreign key constraint error trying to write to `evidence_events` with a null `session_id`.

`elapsed_s` is always `time.time() - session_start_time`, computed at write time inside the tool or DB helper. Never compute it in a query — it's denormalised by design for fast analytics without joins.

The DB file lives at `data/oracle_stats.db`. The `data/` directory is gitignored. `init_db()` in `main()` creates it automatically on first run.

---

## Voice Pipeline

The voice pipeline is strictly layered. Data flows one way:

```
WakeWordDetector → VoiceSession._mic_loop / LoopbackCapture._capture_loop
  → SpeechToText.transcribe()
    → main.run_turn()
      → oracle_graph.invoke()
        → TextToSpeech.speak()
          → AudioRouter.play()
            → sd.play() [blocking=True, per device thread]
```

Never shortcut this chain. In particular:

- `TextToSpeech` owns the `is_speaking` flag. Nothing else should set it.
- `AudioRouter` owns all `sd.play()` calls. Don't add playback elsewhere.
- `VoiceSession` owns the turn queue. `main.py` reads from it; voice modules write to it.

The self-feedback guard: both `WakeWordDetector.on_wake()` and `LoopbackCapture._capture_loop()` check `tts.is_speaking` before triggering a recording. If you add a new audio capture path, add the same guard.

---

## Testing

```bash
# Run everything
pytest tests/ -v

# Run without LLM or audio (safe for CI)
pytest tests/test_deduction.py tests/test_triggers.py tests/test_db.py tests/test_ui.py -v

# Tests that require mocking (use as-is, don't change mock targets)
pytest tests/test_llm.py tests/test_audio_router.py tests/test_loopback.py -v
```

Tests that must always pass before any commit:

- `test_deduction.py::test_mimic_survives_orb_ruled_out`
- `test_deduction.py::test_all_ghosts_loaded` (expects exactly 27)
- `test_triggers.py::test_identify_does_not_fire_with_insufficient_evidence`
- `test_triggers.py::test_commentary_does_not_fire_when_count_unchanged`

The fastest development loop is `python main.py --text`. It runs the full graph with typed input and no audio dependencies. All deduction, tools, and auto-triggers work identically to voice mode.

---

## Behavioral Reasoning Layer (Sprint 7)

Sprint 7 adds a `reason_about_observation` tool. It is the **only tool that makes a second LLM call internally.** The following rules apply specifically to this layer:

**The LLM reasons over injected data only.** `graph/behavioral_reasoning.py` retrieves `behavioral_profile` fields for the current candidates and injects them into the reasoning prompt. The reasoning LLM cannot reference behavioral data about a ghost that is not in the prompt. Never loosen this — if profiles are missing, the fallback message should prompt evidence gathering, not allow the LLM to free-recall.

**Behavioral reasoning never eliminates candidates.** The reasoning tool calls `get_commentary_llm()` and returns a commentary string. It does not call `narrow_candidates()` or mutate `_state["candidates"]`. If you find yourself wanting to eliminate a candidate based on a behavioral observation, that observation should instead be classified as a hard eliminator and added to `observation_eliminators` in `ghost_database.yaml` — not handled in the reasoning layer.

**The 10-candidate guard must stay.** `reason_about_observation` returns early if `len(candidates) > 10`. Without this, a player's first behavioral comment injects up to 27 ghost profiles into the LLM context, producing vague or hallucinated responses. The guard is a quality control measure, not a safety issue — don't remove it.

**Classification before retrieval.** `classify_observation()` maps the player's words to behavioral categories (`movement`, `visibility`, `hunting`, etc.). Only matching categories are fetched from each ghost's `behavioral_profile`. This keeps the injected context focused. Don't skip classification and inject entire profiles.

**`behavioral_profile` vs `behavioral_tells`.** The existing `behavioral_tells` list (freeform strings, Sprint 1) is for display in `query_ghost_database`. The new `behavioral_profile` dict (structured, Sprint 7) is for reasoning injection. Both coexist. Don't collapse them.

---

## Adding a New Ghost Event Type

1. Add the string to `_GHOST_EVENT_TYPES` in `graph/tools.py`
2. No other code changes needed — the DB schema uses a free-text `event_type` column
3. Add a test to `tests/test_db.py` if the new type has special handling

## Adding a New Evidence Type

1. Add the string to `EvidenceID` in `graph/state.py`
2. Update `ghost_database.yaml` for all affected ghosts
3. Add the label to `_EVIDENCE_LABELS` in `ui/display.py`
4. Add a test case to `tests/test_deduction.py`

## Adding a New Ghost

Edit `ghost_database.yaml` only. The deduction engine, tools, and stats layer all derive from the YAML at runtime. No code changes required. Run `test_deduction.py::test_all_ghosts_loaded` after — update the expected count if it fails.

---

## Common Mistakes to Avoid

**Don't add blocking calls to nodes.** `llm_node`, `identify_node`, and `commentary_node` are called synchronously by LangGraph inside `oracle_graph.invoke()`. Any `time.sleep()` or synchronous I/O (disk, network) in a node blocks the entire voice loop. DB writes in tools are fine — they're fast. Slow operations belong in background threads.

**Don't change `tools → llm` loop without updating `route_after_tools`.** The tools node loops back to the LLM by default. `route_after_tools` intercepts this for identification and commentary. If you change the topology in `graph/graph.py`, verify the conditional edge still fires correctly with the trigger tests.

**Don't resample audio manually outside `AudioRouter`.** `resample_audio()` in `voice/audio_router.py` uses `scipy.signal.resample_poly` which handles arbitrary rate ratios cleanly. Ad-hoc resampling elsewhere (e.g. with `numpy.interp`) introduces aliasing artifacts audible through TTS.

**Don't hardcode device names.** All device name fragments come from `config/settings.py` which reads `.env.local`. Tests mock `sd.query_devices()` — hardcoded names break the mocks.

**Don't call `sd.play()` with `device=0`.** Device index 0 is not guaranteed to be any particular device. Always pass `device=None` (system default) or a resolved integer ID from `_resolve_output_device()`.

**Don't skip `tts.flush()` before responding.** `main.py` calls `tts.flush()` before `run_turn()` so ambient commentary queued from a previous turn doesn't play after a direct query. If you add a new response path, include the flush.

---

## Sprint Build Order

Build and validate sprints in order. Each sprint's `Definition of Done` is the gate for the next.

| Sprint | First file to build                      | Key test to pass first                                                               |
| ------ | ---------------------------------------- | ------------------------------------------------------------------------------------ |
| 1      | `graph/deduction.py`                     | `test_deduction.py` (no LLM needed)                                                  |
| 2      | `graph/nodes.py` (add trigger functions) | `test_triggers.py`                                                                   |
| 3      | `voice/audio_router.py`                  | `test_audio_router.py`                                                               |
| 4      | `voice/loopback_capture.py`              | `test_loopback.py`                                                                   |
| 5      | `graph/llm.py`                           | `test_llm.py`                                                                        |
| 6      | `db/database.py`                         | `test_db.py` (schema + CRUD before queries)                                          |
| 7      | `ghost_database.yaml` (Tier 1 profiles)  | `test_behavioral_reasoning.py` (classification + profile retrieval before LLM mocks) |

Sprint 1's `python main.py --text` smoke test is the most important regression gate. Run it before and after every change to the graph or tools. If it breaks, fix it before proceeding.

---

## Quick Reference

```bash
# Install dependencies
pip install -e ".[dev]"

# Start Oracle (text mode — Sprint 1)
python main.py

# Diagnostics
python main.py --check

# Tests (no Ollama needed for most)
pytest tests/ -m "not llm" -v

# All tests (requires Ollama with qwen2.5:7b)
pytest tests/ -v

# Pull local model (required for Ollama backend)
ollama pull qwen2.5:7b
```

---

## Document Index

| Document                                            | Read when...                                                                            |
| --------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `README.md`                                         | Starting fresh — overview, install, usage                                               |
| `Oracle Architecture Design.md`                     | Before touching `graph/` — full rationale for tool-calling agent design                 |
| `Roadmap.md`                                        | Planning which sprint to work on                                                        |
| `Sprint N — Detailed Plan.md`                       | Before implementing that sprint — scaffold code, task board, known risks                |
| `ghost_database.yaml` (behavioral_profile sections) | When populating Sprint 7 ghost data — use the speed reference table in the Sprint 7 doc |
| `config/ghost_database.yaml`                        | Adding or correcting ghost data                                                         |
| This file                                           | Before any code changes — rules, invariants, gotchas                                    |
