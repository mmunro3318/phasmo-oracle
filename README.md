# Oracle

A voice-driven Phasmophobia ghost-identification assistant. Oracle listens for evidence reports and observations, narrows the ghost candidate pool deterministically, and responds with dry British wit.

---

## How It Works

Oracle is a **LangGraph agent with a two-stage chain**, not a raw LLM. The architecture separates three concerns:

1. **Intent parsing** — a deterministic regex router classifies ~85% of inputs instantly (no LLM needed). Ambiguous inputs fall back to an LLM classifier.
2. **Ghost deduction** — pure Python narrows 27 candidates by evidence type. No model involved.
3. **Narration** — the LLM generates a 2-sentence response with Oracle's persona (dry British wit).

The LLM never reasons about ghost identity. It can only report what the deduction engine computes.

```
You: "ghost orb confirmed"
  → Deterministic parser: record_evidence("orb", "confirmed")
  → Deduction engine narrows candidates: 27 → 11
  → LLM narrator: "Ghost Orb duly noted. Eleven suspects remain — do carry on."

You: "rule out spirit box"
  → Deterministic parser: record_evidence("spirit_box", "ruled_out")
  → Deduction engine narrows candidates: 11 → 4
  → LLM narrator: "Spirit Box eliminated. Four candidates remain: Goryo, Hantu, Mimic, and Raiju."
```

### Architecture Diagram

```
user_text → Deterministic Parser (regex, instant)
                ├── [match] → Tool Execution → LLM Narrator → response
                └── [no match] → LLM Classifier → Tool Execution → LLM Narrator → response
```

---

## Current Status: Sprint 1 (Text-First)

Oracle currently runs as a text REPL with a Rich terminal display. Voice integration (Whisper STT, Kokoro TTS, wake word detection) is planned for Sprint 2.

Added a quick sub-app/applet `voice-test` that can be set up to run and hear the different voices available through Kokoro before I fully wire it up in Sprint 2. Instructions below.

---

## Prerequisites (First-Time Setup)

If you've never set up a Python project before, follow this section first. If you already have Python and VS Code, skip to [Installation](#installation).

### 1. Install VS Code

1. Download [Visual Studio Code](https://code.visualstudio.com/) and install it.
2. Open VS Code, go to Extensions (Ctrl+Shift+X), search for **Python**, and install the Microsoft Python extension.

### 2. Install Python

1. Download [Python 3.11+](https://www.python.org/downloads/) (click the big yellow "Download Python" button).
2. **IMPORTANT:** During installation, check the box that says **"Add python.exe to PATH"**. This is the most common setup mistake — if you skip this, nothing works.
3. After installation, open a new terminal (Command Prompt or PowerShell) and verify:
   ```
   python --version
   ```
   You should see something like `Python 3.11.9`. If you get "command not found", Python wasn't added to PATH — uninstall and reinstall with the PATH checkbox checked.

### 3. Install Ollama

1. Download [Ollama](https://ollama.com/) and install it.
2. Ollama runs in the background as a service. After installation, open a terminal and verify:
   ```
   ollama --version
   ```
3. Pull the AI model Oracle uses (this downloads ~4 GB):
   ```
   ollama pull qwen2.5:7b
   ```
   This takes a few minutes. Once done, Ollama is ready.

### 4. Install Git (if you don't have it)

1. Download [Git for Windows](https://git-scm.com/download/win) and install with default settings.
2. Verify: `git --version`

---

## Installation

### Quick start (for experienced developers)

```bash
# In Powershell
git clone https://github.com/mmunro3318/phasmo-oracle.git
cd phasmo-oracle

# Dev/experimentation is generally on `claude-code-dev` branch
# Checkout this branch for most current version, `main` is most stable version
git fetch origin
git checkout claude-code-dev

python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
ollama pull qwen2.5:7b          # you may have to run the model in separate terminal: ollama run qwen2.5:7b
python main.py --check
python main.py
```

### Step-by-step (VS Code on Windows)

**1. Clone the project**

Open a terminal (Command Prompt, PowerShell, or **VS Code terminal**) and run:

```
# Navigate to where you want to store the project, for example:
cd C:/Users/[username]/Desktop/Projects

git clone https://github.com/mmunro3318/phasmo-oracle.git
cd phasmo-oracle

# If you want my more recent/experimental build, switch to branch:
git fetch origin
git checkout claude-code-dev
```

**2. Open in VS Code**

```
code .
```

This opens VS Code in the project folder. If `code .` doesn't work, open VS Code manually and use File → Open Folder.

**3. Create a virtual environment**

Open the VS Code terminal (Ctrl+\` or Terminal → New Terminal) and run:

```
python -m venv .venv
```

This creates an isolated Python environment in a `.venv` folder so Oracle's packages don't interfere with anything else on your computer.

**4. Activate the virtual environment**

```
.venv\Scripts\activate
```

You should see `(.venv)` appear at the start of your terminal prompt. This means the virtual environment is active. **You need to do this every time you open a new terminal.**

If you get an error about "execution of scripts is disabled", run this first:

```
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then try activating again.

**5. Tell VS Code to use this environment**

Press Ctrl+Shift+P, type "Python: Select Interpreter", and choose the one that shows `.venv` in the path (e.g., `.\.venv\Scripts\python.exe`).

**6. Install dependencies**

With the virtual environment active (you should see `(.venv)` in the prompt):

```
pip install -e ".[dev]"
```

This installs Oracle and all its dependencies. The `.[dev]` part also installs testing tools. **If you see errors about "setuptools" or "build backend", make sure you're running this from inside the `phasmo-oracle` folder.**

**7. Verify everything works**

```
python main.py --check
```

You should see green checkmarks for Ghost database, Ollama connection, and Model available. If Ollama checks fail, make sure Ollama is running (check the system tray) and you've pulled the model (`ollama pull qwen2.5:7b`).

**8. Run Oracle**

```
python main.py
```

### Voice Tester (Experimental)

Want to hear the Oracle speak? Check out the **`voice_test/`** sub-app on the `feature/voice-test-app` branch.

It's a standalone terminal tool that plays Phasmophobia-themed dispatches through any Kokoro ONNX voice. Model files download automatically on first run.

**Quick start:**
```bash
git checkout feature/voice-test-app
pip install -r voice_test/requirements.txt
python voice_test/app.py
```

See [`voice_test/README.md`](voice_test/README.md) for full setup details (including how to configure your audio output device).

Type evidence like "ghost orb confirmed" or "rule out spirit box" and Oracle will respond.

### Troubleshooting

| Problem                            | Fix                                                                               |
| ---------------------------------- | --------------------------------------------------------------------------------- |
| `python: command not found`        | Python wasn't added to PATH. Reinstall Python and check "Add to PATH".            |
| `pip: command not found`           | Same as above — pip comes with Python.                                            |
| `ModuleNotFoundError`              | Virtual environment isn't active. Run `.venv\Scripts\activate` first.             |
| `Ollama connection: Not reachable` | Ollama isn't running. Start it from the Start menu or system tray.                |
| `Model not pulled`                 | Run `ollama pull qwen2.5:7b` and wait for it to download.                         |
| `execution of scripts is disabled` | Run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`        |
| Conda conflicts                    | Don't use conda. Use `python -m venv .venv` instead. Oracle is designed for venv. |

---

## Configuration

All settings live in `config/.env.local` (gitignored). If the file doesn't exist, defaults are used.

```env
# LLM model (must support Ollama tool calling)
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_BASE_URL=http://localhost:11434

# Game difficulty
DIFFICULTY=professional
# Options: amateur, intermediate, professional, nightmare, insanity
```

---

## Usage

```bash
# Text mode (Sprint 1 — default)
python main.py

# Override difficulty for this session
python main.py --difficulty nightmare

# Run startup diagnostics only
python main.py --check
```

### Text commands (natural language)

```
"new game on professional"           → starts a new investigation
"ghost orb confirmed"                → confirms Ghost Orb evidence
"we found freezing temps"            → confirms Freezing Temperatures
"rule out spirit box"                → rules out Spirit Box
"no EMF 5"                           → rules out EMF Level 5
"what ghosts are left?"              → shows current investigation state
"what does the Banshee do?"          → looks up Banshee in the database
"the ghost stepped in salt"          → logs behavioral observation, eliminates Wraith
```

---

## Project Structure

```
phasmo-oracle/
├── main.py                        # Entry point — text REPL, Rich display, diagnostics
├── config/
│   ├── settings.py                # pydantic-settings config from .env.local
│   ├── .env.local.example         # Configuration template
│   ├── ghost_database.yaml        # 27 ghosts — evidence, tells, eliminators
│   └── evidence_synonyms.yaml     # Maps LLM-generated strings to canonical IDs
├── graph/
│   ├── intent_router.py           # Deterministic regex intent parser
│   ├── state.py                   # OracleState TypedDict
│   ├── deduction.py               # Pure Python candidate narrowing (no LLM)
│   ├── tools.py                   # 5 LangChain tools + state management
│   ├── llm.py                     # LLM factory (init once, use everywhere)
│   ├── nodes.py                   # Graph nodes: parse, classify, execute, narrate
│   └── graph.py                   # StateGraph assembly (two-stage chain)
├── tests/                         # 222 tests (no Ollama needed for most)
├── docs/                          # Architecture docs, sprint plans, roadmap
├── CLAUDE.md                      # Claude Code project guidance
├── AGENTS.md                      # Cross-tool AI assistant guide
└── TODOS.md                       # Deferred work items
```

---

## Development

```bash
# Run all tests (no Ollama needed for most)
pytest tests/ -v

# Run only non-LLM tests (fast, no dependencies)
pytest tests/ -m "not llm" -v

# Run LLM-dependent tests (requires Ollama with qwen2.5:7b)
pytest tests/ -m llm -v
```

### Key test files

| File                     | Tests                                                                | Ollama? |
| ------------------------ | -------------------------------------------------------------------- | ------- |
| `test_deduction.py`      | 27-ghost parametrized deduction, Mimic edge case, Nightmare/Insanity | No      |
| `test_intent_router.py`  | 74 natural language → intent classification tests                    | No      |
| `test_tools.py`          | All 5 tools, synonyms, over-proofed detection                        | No      |
| `test_nodes.py`          | Graph node functions, routing logic                                  | No      |
| `test_llm.py`            | LLM factory with mocked Ollama                                       | No      |
| `test_intent_parsing.py` | LLM intent parsing regression tests                                  | Yes     |

---

## Sprint Roadmap

| Sprint | Focus                                                                   | Status          |
| ------ | ----------------------------------------------------------------------- | --------------- |
| 1      | Core agent loop — text mode, deduction engine, 5 tools, two-stage chain | **In Progress** |
| 2      | Full conditional graph + voice shell (Whisper / Kokoro)                 | Planned         |
| 3      | Steam routing via Voicemeeter + dual-output TTS                         | Planned         |
| 4      | Bidirectional — second player queries Oracle via loopback               | Planned         |
| 5      | API fallback, terminal UI polish, session replay, diagnostics           | Planned         |
| 6      | Session persistence, game metrics, `--stats` flag                       | Planned         |
| 7      | Behavioral reasoning — speed, visibility, hunting profiles              | Planned         |

---

## Docs

- [AGENTS.md](AGENTS.md) — AI assistant guide: invariants, state flow, tool reference
- [CLAUDE.md](CLAUDE.md) — Claude Code-specific project guidance
- [Oracle Architecture Design](docs/Oracle%20Architecture%20Design.md) — full rationale for tool-calling agent design
- [Roadmap](docs/Roadmap.md) — seven-sprint overview with exit criteria
- Sprint plans: [Sprint 1](docs/Sprint%201/) through [Sprint 6](docs/Sprint%206/)
