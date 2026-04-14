# Oracle

A voice-driven Phasmophobia ghost-identification assistant. Oracle narrows 27 ghost candidates using evidence you report, then responds through a CB radio voice effect.

---

## Quick Start

```bash
git clone https://github.com/mmunro3318/phasmo-oracle.git
cd phasmo-oracle
python -m venv .venv
.venv/Scripts/activate
pip install -e ".[dev,voice]"     # voice output with radio FX
python -m oracle --text --speak --difficulty professional

# OR: hands-free mode (wake word + STT + TTS)
pip install -e ".[dev,voice-full]"
python -m oracle --voice --difficulty professional
```

Model files (~90MB) download automatically on first run.

**Text only (no voice):**

```bash
pip install -e ".[dev]"
python -m oracle --text --difficulty professional
```

---

## Command Reference

Oracle uses pattern matching — phrase commands naturally. Here's what works:

### Evidence

| What you say          | What happens                    |
| --------------------- | ------------------------------- |
| `confirm EMF 5`       | Records EMF 5 as confirmed      |
| `we found ghost orbs` | Records Ghost Orb as confirmed  |
| `rule out spirit box` | Rules out Spirit Box            |
| `no freezing temps`   | Rules out Freezing Temperatures |
| `deny ghost writing`  | Rules out Ghost Writing         |

**Tip:** You can say evidence names casually — "orbs", "freezing", "UV", "dots", "writing", "spirit box", "EMF" all work.

### Investigation

| What you say                | What happens                               |
| --------------------------- | ------------------------------------------ |
| `what's left` / `status`    | Shows remaining candidates                 |
| `what should we check next` | Suggests the most useful evidence to test  |
| `what tests can we try`     | Lists available tests for remaining ghosts |

### Ghost Info

| What you say                   | What happens                             |
| ------------------------------ | ---------------------------------------- |
| `tell me about the Banshee`    | Ghost card — evidence, behaviors, tests  |
| `what's the Goryo test`        | Specific ghost test lookup               |
| `Goryo test passed` / `failed` | Records test result, may eliminate ghost |

### Guessing & Endgame

| What you say                | What happens                  |
| --------------------------- | ----------------------------- |
| `I think it's a Deogen`     | Records your theory           |
| `lock in Deogen`            | Locks in your final answer    |
| `game over it was a Wraith` | Ends the game, records result |
| `new game nightmare`        | Starts a fresh investigation  |

### Voice

| What you say               | What happens            |
| -------------------------- | ----------------------- |
| `change voice to af_bella` | Switches Oracle's voice |

Voice names are shown in "The Team" table at startup. Set a default in `.env.local` with `KOKORO_VOICE=bm_fable`.

---

## How It Works

Oracle uses a fully deterministic pipeline — no LLM, no cloud APIs, everything runs locally:

```
Your voice / keyboard → Regex Parser (instant) → Deduction Engine → Scripted Response → TTS + Radio FX → Speaker / VB-Cable
```

1. **Parser** (`oracle/parser.py`) — regex pattern matching classifies your input into actions (confirm evidence, query ghost, start game, etc.)
2. **Engine** (`oracle/engine.py`) — pure Python deduction narrows 27 ghost candidates by evidence rules, handles Mimic edge cases, Nightmare/Insanity difficulty thresholds
3. **Responses** (`oracle/responses.py`) — scripted templates produce natural responses from typed results
4. **Voice** (`oracle/voice/`) — Kokoro TTS synthesizes speech, CB radio FX chain applies band-pass filter + saturation + confidence-coded static, then plays through speakers

---

## Prerequisites (First-Time Setup)

### 1. Install Python

1. Download [Python 3.11+](https://www.python.org/downloads/)
2. **IMPORTANT:** Check **"Add python.exe to PATH"** during installation
3. Verify: `python --version`

### 2. Install Git

1. Download [Git for Windows](https://git-scm.com/download/win) and install with defaults
2. Verify: `git --version`

### 3. (Optional) Install VS Code

1. Download [Visual Studio Code](https://code.visualstudio.com/)
2. Install the **Python** extension (Ctrl+Shift+X → search "Python")

---

## Installation (Step-by-Step)

### Option A — conda (recommended if you already use Anaconda or Miniconda)

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd oracle

# 2. Create and activate the conda environment from the provided file
conda env create -f environment.yml
conda activate oracle

# 3. Pull the local model
ollama pull phi4-mini

# 4. Copy and configure environment
cp config/.env.local.example config/.env.local
# Edit config/.env.local — see Configuration below

# 5. Run startup diagnostics
python main.py --check

# 6. Start Oracle
python main.py
```

> **Tip — reactivating later:** every time you open a new terminal, run `conda activate oracle` before `python main.py`. To deactivate the environment, run `conda deactivate`.

> **Updating packages:** if dependencies change, run `conda env update -f environment.yml --prune` inside the activated environment.

---

### Option B — standard venv

```bash
# Clone and enter the project
git clone https://github.com/mmunro3318/phasmo-oracle.git
cd phasmo-oracle

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate        # You need to do this every new terminal session

# Install with voice support
pip install -e ".[dev,voice]"

# Run Oracle
python -m oracle --text --speak --difficulty professional
```

If you get "execution of scripts is disabled":

```
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Troubleshooting

| Problem                            | Fix                                           |
| ---------------------------------- | --------------------------------------------- |
| `python: command not found`        | Reinstall Python with "Add to PATH" checked   |
| `ModuleNotFoundError`              | Activate the venv: `.venv\Scripts\activate`   |
| `execution of scripts is disabled` | Run the `Set-ExecutionPolicy` command above   |
| No audio output                    | Check `.env.local` for `AUDIO_DEVICE` setting |

---

## Configuration

Settings live in `.env.local` at the project root (gitignored).

```env
# Voice name (see "The Team" table at startup for options)
KOKORO_VOICE=bm_fable

# Audio output device (leave empty for system default)
# AUDIO_DEVICE=

# Voice input: physical mic index for STT (run pyaudio device list to find)
# STT_INPUT_DEVICE=

# VB-Cable device name for routing TTS to Steam Voice Chat
# VB_CABLE_DEVICE=
```

---

## Development

```bash
# Run all tests
pytest tests/ -v

# Run with Kokoro integration tests (requires model files)
pytest tests/ -v --run-integration

# Preview radio FX tuning
python tools/radio_preview.py
```

---

## Project Structure

```
phasmo-oracle/
├── oracle/
│   ├── parser.py              # Deterministic regex command parser
│   ├── engine.py              # Investigation engine — all game state + deduction
│   ├── deduction.py           # Pure Python candidate narrowing (no LLM)
│   ├── responses.py           # Scripted response templates
│   ├── runner.py              # Main loop, I/O protocols, CLI entry point
│   ├── state.py               # Type definitions (EvidenceID, Difficulty)
│   ├── voice/
│   │   ├── tts.py             # Kokoro TTS wrapper (swappable via TTSProvider)
│   │   ├── stt.py             # RealtimeSTT wrapper — wake word + STT input
│   │   ├── radio_fx.py        # CB radio FX chain (band-pass, saturation, noise)
│   │   └── audio_config.py    # Audio + STT config, VB-Cable device discovery
│   └── config/
│       ├── ghost_database.yaml    # 27 ghosts — evidence, tells, eliminators
│       ├── ghost_tests.yaml       # 26 deterministic ghost tests
│       └── evidence_synonyms.yaml # Maps spoken evidence to canonical IDs
├── tests/                     # ~320 tests (no audio deps needed)
├── tools/
│   └── radio_preview.py       # Standalone radio FX tuning tool
├── docs/                      # Sprint specs, ghost guides
├── CLAUDE.md                  # Project guide for AI assistants
├── BENCHMARK_GUIDE.md         # Kokoro TTS latency benchmarking
└── TODOS.md                   # Deferred work items
```

---

## Docs

| Document                                                             | Purpose                                                       |
| -------------------------------------------------------------------- | ------------------------------------------------------------- |
| [CLAUDE.md](CLAUDE.md)                                               | Project guide — architecture, invariants, build/test commands |
| [INSIGHTS.md](INSIGHTS.md)                                           | Lessons from the LangGraph→deterministic pivot                |
| [BENCHMARK_GUIDE.md](BENCHMARK_GUIDE.md)                             | How to measure TTS latency on your hardware                   |
| [Ghost Identification Guide](docs/Ghost%20Identification%20Guide.md) | Phasmophobia game mechanics reference                         |
| [Sprint 3b](docs/Sprint%203b%20-%20Voice%20Pipeline.md)              | Voice output sprint spec (complete)                           |
