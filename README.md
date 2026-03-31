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

---

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) with `qwen2.5:7b` pulled

---

## Installation

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd phasmo-oracle

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# 3. Install dependencies (includes dev tools like pytest)
pip install -e ".[dev]"

# 4. Pull the local model (requires Ollama running)
ollama pull qwen2.5:7b

# 5. (Optional) Copy and configure environment
cp config/.env.local.example config/.env.local
# Edit config/.env.local if needed — defaults work out of the box

# 6. Run startup diagnostics
python main.py --check

# 7. Start Oracle
python main.py
```

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

| File | Tests | Ollama? |
|------|-------|---------|
| `test_deduction.py` | 27-ghost parametrized deduction, Mimic edge case, Nightmare/Insanity | No |
| `test_intent_router.py` | 74 natural language → intent classification tests | No |
| `test_tools.py` | All 5 tools, synonyms, over-proofed detection | No |
| `test_nodes.py` | Graph node functions, routing logic | No |
| `test_llm.py` | LLM factory with mocked Ollama | No |
| `test_intent_parsing.py` | LLM intent parsing regression tests | Yes |

---

## Sprint Roadmap

| Sprint | Focus | Status |
|--------|-------|--------|
| 1 | Core agent loop — text mode, deduction engine, 5 tools, two-stage chain | **In Progress** |
| 2 | Full conditional graph + voice shell (Whisper / Kokoro) | Planned |
| 3 | Steam routing via Voicemeeter + dual-output TTS | Planned |
| 4 | Bidirectional — second player queries Oracle via loopback | Planned |
| 5 | API fallback, terminal UI polish, session replay, diagnostics | Planned |
| 6 | Session persistence, game metrics, `--stats` flag | Planned |
| 7 | Behavioral reasoning — speed, visibility, hunting profiles | Planned |

---

## Docs

- [AGENTS.md](AGENTS.md) — AI assistant guide: invariants, state flow, tool reference
- [CLAUDE.md](CLAUDE.md) — Claude Code-specific project guidance
- [Oracle Architecture Design](docs/Oracle%20Architecture%20Design.md) — full rationale for tool-calling agent design
- [Roadmap](docs/Roadmap.md) — seven-sprint overview with exit criteria
- Sprint plans: [Sprint 1](docs/Sprint%201/) through [Sprint 6](docs/Sprint%206/)
