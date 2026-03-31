# Contributing to Oracle

Thank you for considering a contribution!  Oracle is an AI-native voice assistant
built with LangGraph.  Before you start, read the [AGENTS.md](AGENTS.md) file —
it contains hard invariants that must never be broken.

---

## Development Setup

```bash
# 1. Clone and create a virtual environment
git clone <repo-url>
cd phasmo-oracle
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 2. Install development dependencies
pip install -e ".[dev]"

# 3. Install pre-commit hooks
pre-commit install

# 4. Copy the env template
cp config/.env.local.example config/.env.local
# Edit config/.env.local as needed
```

---

## Branches

| Branch | Owner | Purpose |
|---|---|---|
| `main` | upstream | Stable releases |
| `copilot/github-copilot-dev` | GitHub Copilot | AI-assisted development |

Each AI framework works on its own isolated branch.  **Never push to another
framework's branch.**

---

## Code Style

- **Python 3.11+**
- Formatted with **ruff** (`ruff format .`)
- Linted with **ruff** (`ruff check .`)
- Type-checked with **mypy** for core modules
- Line length: 100 characters

Run all checks before committing:

```bash
ruff format .
ruff check --fix .
mypy graph/deduction.py graph/state.py db/database.py --ignore-missing-imports
pytest tests/test_deduction.py tests/test_triggers.py tests/test_db.py -v
```

Pre-commit hooks run automatically on `git commit` if you ran `pre-commit install`.

---

## Architecture Rules (non-negotiable)

1. **Ghost deduction is pure Python** — never ask the LLM to reason about ghost identity.
2. **The LLM never writes to `OracleState` directly** — all state mutations go through tools.
3. **`identify_node` is triggered by the graph, not by the LLM** — the LLM cannot call
   `identify_ghost` as a tool.
4. **`route_after_tools` is a pure function** — no side effects, no DB writes, no logging.
5. **All audio is float32, clipped to [-1, 1]** — use `AudioRouter.play()` for all playback.
6. **`sd.play()` must always be called with `blocking=True`** — do not add new `sd.play()` calls.

See [AGENTS.md](AGENTS.md) for the full list of invariants.

---

## Adding a New Ghost

Edit `config/ghost_database.yaml` only.  No code changes required.  Run
`pytest tests/test_deduction.py::test_all_ghosts_loaded` and update the expected
count if it fails.

## Adding a New Evidence Type

1. Add to `EvidenceID` in `graph/state.py`
2. Update `config/ghost_database.yaml` for affected ghosts
3. Add the label to `_EVIDENCE_LABELS` in `ui/display.py`
4. Add a test to `tests/test_deduction.py`

## Adding a New Ghost Event Type

1. Add the string to `_GHOST_EVENT_TYPES` in `graph/tools.py`
2. Add a test to `tests/test_db.py` if it has special handling

---

## Tests

```bash
# Fast — no LLM, no audio
pytest tests/test_deduction.py tests/test_triggers.py tests/test_db.py tests/test_ui.py -v

# All tests (requires mocked audio fixtures)
pytest tests/ -v
```

Critical tests that must always pass:
- `test_deduction.py::test_mimic_survives_orb_ruled_out`
- `test_deduction.py::test_all_ghosts_loaded`
- `test_triggers.py::test_identify_does_not_fire_with_insufficient_evidence`
- `test_triggers.py::test_commentary_does_not_fire_when_count_unchanged`

---

## Memory Docs

Capture key insights and solutions in `docs/memory/`.  Use the
[template](docs/memory/template.md) to record discoveries during development.
This helps future contributors (human or AI) understand decisions made along the way.

---

## Pull Request Checklist

- [ ] All critical tests pass (`pytest tests/test_deduction.py tests/test_triggers.py -v`)
- [ ] Ruff checks pass (`ruff check . && ruff format --check .`)
- [ ] No new `sd.play()` calls outside `AudioRouter`
- [ ] No LLM imports in `graph/deduction.py`
- [ ] DB writes are guarded by `if session_id`
- [ ] Memory doc added if a significant design decision was made
