# Oracle

A voice-driven Phasmophobia ghost-identification assistant. Oracle listens for a wake word, accepts spoken evidence reports and observations, narrows the ghost candidate pool deterministically, and speaks its findings aloud — routing its voice through Steam so all players hear it in-game.

---

## How It Works

Oracle is a **LangGraph tool-calling agent**, not a raw LLM. The architecture separates two concerns that language models are bad at mixing:

- **Intent parsing** — the LLM maps what you said to the right tool call
- **Ghost deduction** — pure Python narrows 27 candidates by evidence type, no model involved

This means Oracle can never hallucinate a ghost type. It can only identify when the deduction engine — a deterministic set-intersection check against `ghost_database.yaml` — confirms exactly one candidate remains with sufficient evidence. The LLM generates natural language around those facts; the facts themselves come from code.

```
You: "ghost orb confirmed"
  → LLM calls record_evidence("orb", "confirmed")
  → deduction engine narrows candidates: 27 → 11
  → [11 > 5, no auto-comment]

You: "rule out spirit box"
  → LLM calls record_evidence("spirit_box", "ruled_out")
  → deduction engine narrows candidates: 11 → 4
  → [4 ≤ 5, candidates changed] → commentary_node fires
  Oracle: "Four candidates remain: Goryo, Hantu, Mimic, and Raiju.
           Freezing temperatures would eliminate Goryo and Raiju."
```

---

## Features

- **Voice-first** — wake word detection (openwakeword), Whisper STT, Kokoro TTS
- **Deterministic deduction** — all candidate narrowing is pure Python; the LLM never names a ghost unilaterally
- **Auto-commentary** — Oracle speaks unprompted when candidates drop to ≤ 5
- **Auto-identification** — Oracle announces the ghost when 1 candidate + sufficient evidence confirmed (difficulty-aware: 3/2/1 evidence for Professional/Nightmare/Insanity)
- **Steam routing** — Oracle's voice reaches all teammates via Voicemeeter + Steam voice chat
- **Bidirectional** — a second player (Kayden) can query Oracle via WASAPI loopback capture
- **API fallback** — if Ollama is offline, falls back to `claude-haiku-4-5-20251001` automatically
- **Session persistence** — every investigation saved to SQLite with evidence timing, ghost events, deaths, and Oracle accuracy
- **Game metrics** — `--stats` flag shows success rate, speed metrics, per-ghost and per-difficulty breakdowns
- **Session replay** — replay any past session; re-run it through the current graph for regression testing
- **Startup diagnostics** — `--check` verifies all components before a session begins

---

## Requirements

### Runtime
- Python 3.11+
- [Ollama](https://ollama.com) with `phi4-mini` pulled (`ollama pull phi4-mini`)
- [Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx) model files: `kokoro-v0_19.onnx` + `voices-v1_0.bin` (place in project root)

### Optional (for Steam routing and bidirectional mode)
- [Voicemeeter Banana](https://vb-audio.com/Voicemeeter/banana.htm) — mixes your real mic + Oracle's voice into one Steam input
- Windows — WASAPI loopback (used for Kayden's bidirectional capture) is Windows-only

### API fallback (optional)
- Anthropic API key — used automatically if Ollama is unreachable

---

## Installation

```bash
# 1. Clone and enter the project
git clone https://github.com/mmunro3318/phasmo-oracle   # main branch
cd phasmo-oracle
# switch to main dev branch
git fetch origin
git checkout claude-code-dev

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install langgraph langchain-ollama langchain-core langchain-anthropic \
            pyyaml pydantic-settings faster-whisper kokoro-onnx \
            sounddevice pyaudio openwakeword scipy rich httpx pytest

# 4. Pull the local model
ollama pull phi4-mini

# 5. Copy and configure environment
cp config/.env.local.example config/.env.local
# Edit config/.env.local — see Configuration below

# 6. Run startup diagnostics
python main.py --check

# 7. Start Oracle
python main.py
```

---

## Configuration

All settings live in `config/.env.local`. The file is gitignored — never commit API keys.

```env
# ── LLM ───────────────────────────────────────────────────────────────────────
OLLAMA_MODEL=phi4-mini
OLLAMA_BASE_URL=http://localhost:11434

# ── API fallback (used automatically if Ollama is offline) ────────────────────
# ANTHROPIC_API_KEY=sk-ant-...
FALLBACK_ENABLED=true
FALLBACK_MODEL=claude-haiku-4-5-20251001

# ── Game ──────────────────────────────────────────────────────────────────────
DIFFICULTY=professional          # amateur | intermediate | professional | nightmare | insanity

# ── Voice — STT ───────────────────────────────────────────────────────────────
STT_MODEL=base.en                # tiny.en (faster) or base.en (more accurate)
WAKE_WORD=oracle
# MIC_DEVICE_NAME=Blue Yeti      # fragment of your mic's device name

# ── Voice — TTS ───────────────────────────────────────────────────────────────
TTS_VOICE=bm_fable
# SPEAKER_DEVICE_NAME=VK81       # fragment of your headphone device name

# ── Steam routing (requires Voicemeeter Banana) ───────────────────────────────
# STEAM_ROUTE_DEVICE_NAME=Voicemeeter Input
# STEAM_ROUTE_GAIN=1.0

# ── Bidirectional (second player via WASAPI loopback, Windows only) ───────────
# LOOPBACK_ENABLED=true
# LOOPBACK_DEVICE_NAME=VK81
# MIKE_SPEAKER_NAME=Mike
# KAYDEN_SPEAKER_NAME=Kayden
```

---

## Usage

```bash
# Voice mode (default) — wake word triggers recording
python main.py

# Text mode — typed input, useful for testing without a microphone
python main.py --text

# Override difficulty for this session
python main.py --difficulty nightmare

# Run startup diagnostics only
python main.py --check

# View cumulative game statistics
python main.py --stats

# Replay a past session (display only)
python main.py --replay sessions/20260330_142000.jsonl

# Replay in real-time speed
python main.py --replay sessions/20260330_142000.jsonl --speed 1.0

# Re-execute a past session through the current graph (regression testing)
python main.py --replay sessions/20260330_142000.jsonl --re-run
```

### Voice commands

Oracle responds to anything phrased naturally after the wake word. Examples:

```
"oracle, new investigation on nightmare"
"oracle, ghost orb confirmed"
"oracle, rule out spirit box"
"oracle, what ghosts are left?"
"oracle, what does the Deogen do?"
"oracle, the ghost stepped in salt"
"oracle, the ghost just hunted"
"oracle, I died"
"oracle, Kayden died"
"oracle, it was a Wraith"          ← post-game confirmation
```

---

## Project Structure

```
oracle/
├── main.py                        # Entry point — all CLI modes
├── config/
│   ├── settings.py                # pydantic-settings config
│   ├── .env.local                 # your local config (gitignored)
│   └── ghost_database.yaml        # all 27 ghosts, evidence, tells, eliminators
├── graph/
│   ├── state.py                   # OracleState TypedDict
│   ├── tools.py                   # 8 LangChain tools
│   ├── deduction.py               # pure Python candidate narrowing
│   ├── nodes.py                   # graph nodes: llm, identify, commentary, respond
│   ├── graph.py                   # StateGraph assembly
│   ├── llm.py                     # LLM factory (Ollama → Anthropic fallback)
│   └── session_log.py             # append-only JSONL session log
├── db/
│   ├── database.py                # SQLite CRUD (sessions, evidence, events, deaths)
│   └── queries.py                 # analytics queries (success rate, speed, etc.)
├── voice/
│   ├── wake_word.py               # openwakeword background listener
│   ├── speech_to_text.py          # faster-whisper wrapper
│   ├── text_to_speech.py          # kokoro-onnx wrapper
│   ├── audio_router.py            # dual-output (headphones + VB-Cable/Voicemeeter)
│   ├── loopback_capture.py        # WASAPI loopback for bidirectional mode
│   └── voice_session.py           # dual capture loop coordinator
├── ui/
│   ├── diagnostics.py             # startup health checks
│   ├── display.py                 # Rich live terminal display
│   ├── stats.py                   # Rich stats renderer
│   └── replay.py                  # session replay logic
├── data/
│   └── oracle_stats.db            # SQLite metrics DB (gitignored)
├── sessions/
│   └── *.jsonl                    # session logs (gitignored)
└── tests/
    ├── test_deduction.py
    ├── test_triggers.py
    ├── test_audio_router.py
    ├── test_loopback.py
    ├── test_llm.py
    ├── test_ui.py
    └── test_db.py
```

---

## Architecture

Oracle is a LangGraph `StateGraph`. All ghost deduction is handled by `graph/deduction.py` — a pure Python function that takes confirmed evidence, ruled-out evidence, and behavioral eliminators and returns the remaining candidate list. The LLM's only jobs are intent parsing (routing utterances to tools) and generating two-sentence natural language responses.

```
llm ──[tool call]──▶ tools ──▶ route_after_tools ──[1 candidate + evidence]──▶ identify ──▶ END
 │                                                 ──[≤5 candidates, changed]──▶ commentary ──▶ END
 │                                                 ──[no trigger]──▶ llm (loop)
 │
 └──[direct answer]──▶ respond ──▶ END
```

See `Oracle Architecture Design.md` for a full explanation of the tool-calling agent rationale, `OracleState` schema, all 8 tool definitions, and the difficulty-aware identification trigger logic.

---

## Steam Routing Setup

Oracle can speak into your Steam voice channel so teammates hear it in-game.

1. Install [Voicemeeter Banana](https://vb-audio.com/Voicemeeter/banana.htm) (free, reboot required)
2. In Voicemeeter: set your real mic as **Hardware Input 1**, enable **B1** on both Hardware Input 1 and VAIO
3. In Steam: Settings → Voice → Microphone → **VB-Audio Voicemeeter Output**
4. In `.env.local`: uncomment `STEAM_ROUTE_DEVICE_NAME=Voicemeeter Input`

Your real voice and Oracle's voice both reach teammates. See `Sprint 3 — Detailed Plan.md` and `Sprint 4 — Detailed Plan.md` for full setup detail.

---

## Development

```bash
# Run all tests
pytest tests/ -v

# Run a specific sprint's tests
pytest tests/test_deduction.py -v

# Check type coverage (optional)
pip install mypy
mypy graph/ db/ voice/ ui/
```

### Running without voice hardware

`python main.py --text` runs the full LangGraph agent with typed input and no audio dependencies. All deduction logic, tools, and auto-triggers work identically. This is the recommended mode for development and graph testing.

### Testing without Ollama

Set `ANTHROPIC_API_KEY` in `.env.local` and kill Ollama. Oracle will log a warning and switch to `claude-haiku-4-5-20251001` automatically. All tests that mock `_ollama_available` work without either service running.

---

## Sprint Status

| Sprint | Focus | Status |
|---|---|---|
| Sprint 1 | Core agent loop — text mode, deduction engine, 5 tools | Planned |
| Sprint 2 | Full conditional graph + voice shell (Whisper / Kokoro) | Planned |
| Sprint 3 | Steam routing via Voicemeeter + dual-output TTS | Planned |
| Sprint 4 | Bidirectional — Kayden queries Oracle via loopback | Planned |
| Sprint 5 | API fallback, terminal UI, session replay, diagnostics | Planned |
| Sprint 6 | Session persistence, game metrics, `--stats` flag | Planned |
| Sprint 7 | Behavioral reasoning — speed, visibility, hunting, interaction profiles | Planned |

Detailed implementation plans, scaffold code, and task boards for all six sprints live in the sprint documents in this folder.

---

## Docs

- [Oracle Architecture Design.md](Oracle%20Architecture%20Design.md) — why tool-calling agent, full graph design, state schema, tool definitions
- [Roadmap.md](Roadmap.md) — six-sprint overview with exit criteria
- [Sprint 1](Sprint%201%20—%20Detailed%20Plan.md) through [Sprint 6](Sprint%206%20—%20Detailed%20Plan.md) — implementation order, scaffold code, task boards
