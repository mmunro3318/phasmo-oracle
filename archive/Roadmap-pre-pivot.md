# Oracle — Development Roadmap

*Last updated after Architecture Design session. Reflects tool-calling agent pivot.*

---

## Overview

Oracle is a voice-driven Phasmophobia ghost-identification assistant built as a LangGraph tool-calling agent. The LLM handles intent parsing and natural language; a Python deduction engine handles all candidate narrowing. They never swap roles.

The roadmap is structured in 5 sprints. Each sprint ends with a self-contained, runnable milestone. Detailed implementation plans and task boards live in the per-sprint documents linked below.

---

## Sprint 1 — Core Agent Loop (Text-First)
**Goal:** Evidence recording and ghost deduction works correctly. Oracle responds to typed input.
**Voice:** None — Sprint 1 runs in a terminal text loop.
**Detail doc:** [[Sprint 1 — Detailed Plan]]

Key deliverables:
- `ghost_database.yaml` loaded and queryable
- `deduction.py` narrows 27 ghosts by evidence + eliminators
- All 5 tools wired and functional
- LangGraph graph compiles and routes (linear path only — no auto-commentary)
- `main.py` text loop: type evidence → Oracle responds

Exit criteria: "ghost orb confirmed", "rule out spirit box", "what ghosts are left?" all produce correct, deterministic responses.

---

## Sprint 2 — Full Conditional Graph + Auto-Commentary
**Goal:** Oracle proactively comments when candidates narrow. Announces identification automatically.

Key deliverables:
- `post_tool_check` node and conditional edges
- Auto-comment fires when candidates drop to ≤ 5
- Identification announcement fires at exactly 1 candidate + 3 confirmed evidence
- `identify_ghost` node (graph-triggered, not LLM tool call)
- Session log: append-only `session.jsonl` with timestamps and state snapshots
- Voice shell: Whisper STT + Kokoro TTS wrapped around the graph (wake word optional)

Exit criteria: Full match simulation via voice. Oracle identifies ghost without being asked. Session log replays correctly.

---

## Sprint 3 — Steam Chat Routing via VB-Cable
**Goal:** Oracle's voice is routed into Steam voice chat so teammates hear it in-game.

Key deliverables:
- VB-Cable virtual audio device integration
- Oracle output routed to VB-Cable Input (appears as microphone to Steam)
- Real mic captured on separate physical device
- `SPEAKER_DEVICE_NAME` config selects real headphones for Oracle's monitoring output
- `STEAM_ROUTE_DEVICE_NAME` config selects VB-Cable Input for team broadcast
- Dual-output TTS: speak to headphones AND write to VB-Cable simultaneously

Exit criteria: Oracle audible to both player and Steam teammates without echo.

---

## Sprint 4 — Bidirectional: Kayden Queries Oracle
**Goal:** A second player (Kayden) can also speak to Oracle and receive responses through Steam chat.

Key deliverables:
- Loopback capture: record Steam voice channel output (what Kayden says)
- Speaker diarization or name-prefix heuristic to distinguish Mike vs. Kayden utterances
- `speaker` field in `OracleState` correctly set per turn
- Oracle acknowledges speaker in response where helpful ("Mike already confirmed Ghost Orb")
- Wake word per speaker optional (Sprint 4b)

Exit criteria: Two-player session. Both players can query Oracle and receive correct responses.

---

## Sprint 5 — Polish, API Fallback, Terminal UI
**Goal:** Production-ready session tool with fallback for when Ollama is unavailable.

Key deliverables:
- API fallback: `claude-haiku-4-5-20251001` via `langchain-anthropic` if Ollama unreachable
- Rich terminal UI: live candidate list, evidence state, session log viewer (using `rich` or `textual`)
- Session replay: load `session.jsonl` and step through a previous match
- Startup diagnostics: check Ollama running, model pulled, audio devices present
- `--difficulty` CLI flag, `--replay` flag

Exit criteria: Oracle starts cleanly with helpful errors on misconfiguration. A previous session can be reviewed turn-by-turn.

---

## Sprint 6 — Session Persistence & Game Metrics
**Goal:** Every investigation is persisted to a local SQLite database. Voice commands record ghost events and deaths. Post-game confirmation tracks Oracle's accuracy over time.

Key deliverables:
- SQLite database (`data/oracle_stats.db`) with 5 tables: sessions, evidence_events, ghost_events, deaths, candidate_snapshots
- Three new tools: `record_ghost_event`, `record_death`, `confirm_true_ghost`
- `evidence_events` and `candidate_snapshots` written automatically (no extra voice commands)
- `--stats` flag: Rich terminal table showing success rate, speed metrics, per-ghost and per-difficulty breakdowns
- `elapsed_s` on every event row — no joins needed for time analytics
- End-of-session prompt and/or voice command to confirm true ghost type

Exit criteria: Full match logged to DB. `--stats` shows accurate success rate and timing data.

---

## Sprint 7 — Behavioral Reasoning Layer
**Goal:** Oracle can reason about nuanced observational evidence — ghost movement speed, hunting behavior, visual appearance, interaction patterns — using structured behavioral profiles injected from `ghost_database.yaml`. The LLM reasons over data we hand it, not training memory.

Key deliverables:
- `behavioral_profile` block per ghost in `ghost_database.yaml` (speed values, visual quirks, hunt mechanics, interaction patterns)
- `graph/behavioral_reasoning.py` — observation classifier, profile retriever, reasoning prompt builder
- `reason_about_observation` tool (9th tool) — triggers a focused LLM sub-call with candidate-only profiles
- 10-candidate guard: reasoning only fires when field is partially narrowed
- Updated `llm_node` system prompt with explicit routing rules distinguishing evidence vs observation
- Hard invariant preserved: behavioral reasoning never eliminates candidates

Exit criteria: "it moved incredibly fast then slowed when it reached me" correctly invokes `reason_about_observation`, not `record_evidence`. Oracle names Revenant specifically and explains why. Discrete evidence inputs still route to `record_evidence`.

---

## Technology Stack

| Layer | Library | Notes |
|---|---|---|
| Graph orchestration | `langgraph` | `StateGraph`, conditional edges, `ToolNode` |
| LLM binding | `langchain-ollama` | `ChatOllama`, `bind_tools()` |
| Local model | `phi4-mini` via Ollama | Temperature 0, structured output |
| API fallback | `langchain-anthropic` | Sprint 5 |
| Game database | `PyYAML` | `ghost_database.yaml`, loaded once at startup |
| Config | `pydantic-settings` | `.env.local` pattern |
| STT | `faster-whisper` | Sprint 2 voice shell |
| TTS | `kokoro-onnx` | Sprint 2 voice shell, `bm_fable` voice |
| Wake word | `openwakeword` | Sprint 2 voice shell |
| Terminal UI | `rich` / `textual` | Sprint 5 |
| Game metrics DB | `sqlite3` (stdlib) | Sprint 6 |
| Behavioral reasoning | `ghost_database.yaml` profiles + `get_commentary_llm()` | Sprint 7 |

---

## File Layout (target at Sprint 2)

```
oracle/
├── main.py
├── config/
│   ├── settings.py
│   ├── .env.local
│   └── ghost_database.yaml
├── graph/
│   ├── state.py
│   ├── tools.py
│   ├── deduction.py
│   ├── nodes.py
│   └── graph.py
└── voice/
    ├── wake_word.py
    ├── speech_to_text.py
    └── text_to_speech.py
```
