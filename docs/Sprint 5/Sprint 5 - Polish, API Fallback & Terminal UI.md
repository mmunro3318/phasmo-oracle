**Goal:** Oracle is production-ready. It starts cleanly with clear diagnostics, degrades gracefully when Ollama is unavailable, shows a live terminal display during sessions, and can replay any past session for review or regression testing.

**Builds on:** All previous sprints. No graph or voice changes — Sprint 5 is purely infrastructure and UX.

**Exit criteria:**

- `python main.py --check` runs startup diagnostics and exits cleanly
- If Ollama is offline, Oracle falls back to `claude-haiku-4-5-20251001` automatically
- If Ollama is offline AND no API key is set, Oracle exits with a clear error message
- Live terminal display updates after each turn showing candidates, evidence, and recent activity
- `python main.py --replay sessions/foo.jsonl` replays a past session
- `python main.py --replay sessions/foo.jsonl --re-run` re-executes each turn through the current graph
- All Sprint 1–4 tests still pass

---

## New File Layout

```
oracle/
├── main.py                        ← updated: CLI flags, diagnostics, live display
├── config/
│   ├── settings.py                ← add ANTHROPIC_API_KEY, FALLBACK_MODEL, FALLBACK_ENABLED
│   ├── .env.local
│   └── ghost_database.yaml
├── graph/
│   ├── state.py
│   ├── tools.py
│   ├── deduction.py
│   ├── nodes.py                   ← updated: use get_llm() singleton
│   ├── graph.py
│   ├── session_log.py
│   └── llm.py                     ← NEW: LLM factory with Ollama/Anthropic fallback
├── ui/
│   ├── __init__.py
│   ├── diagnostics.py             ← NEW: startup health checks
│   ├── display.py                 ← NEW: Rich live terminal UI
│   └── replay.py                  ← NEW: session replay logic
└── voice/
    ├── ...
```

---

## Implementation Order

```
1. graph/llm.py          ← LLM factory: Ollama health check + Anthropic fallback
2. graph/nodes.py        ← replace inline ChatOllama with get_llm() / get_commentary_llm()
3. config/settings.py    ← add ANTHROPIC_API_KEY, FALLBACK_MODEL, FALLBACK_ENABLED
4. ui/diagnostics.py     ← startup checks for all components
5. ui/display.py         ← Rich live display: candidates, evidence, activity log
6. ui/replay.py          ← session replay: display-only + re-run modes
7. main.py               ← wire diagnostics, display, replay, all CLI flags
8. tests/test_llm.py     ← Ollama health check, fallback trigger, no-key error
9. tests/test_ui.py      ← diagnostics logic, replay parsing
```

---

## Scaffold Code

### `graph/llm.py`

```python
"""
LLM factory with Ollama availability check and Anthropic API fallback.

Call init_llm() once at startup. All nodes then call get_llm() / get_commentary_llm()
instead of constructing their own ChatOllama instances.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

_primary_llm: Any    = None   # temperature=0 — for tool calls and direct responses
_commentary_llm: Any = None   # temperature=0.3 — for auto-commentary prose


def init_llm() -> tuple[Any, Any]:
    """
    Initialise both LLM instances. Tries Ollama first; falls back to Anthropic.
    Returns (primary_llm, commentary_llm).
    Raises RuntimeError if neither is available.
    """
    global _primary_llm, _commentary_llm

    from config.settings import config
    backend = _detect_backend(config)

    if backend == "ollama":
        from langchain_ollama import ChatOllama
        _primary_llm    = ChatOllama(
            model=config.OLLAMA_MODEL,
            temperature=0,
            base_url=config.OLLAMA_BASE_URL,
        )
        _commentary_llm = ChatOllama(
            model=config.OLLAMA_MODEL,
            temperature=0.3,
            base_url=config.OLLAMA_BASE_URL,
        )
        logger.info(f"LLM: Ollama / {config.OLLAMA_MODEL}")

    elif backend == "anthropic":
        from langchain_anthropic import ChatAnthropic
        _primary_llm = ChatAnthropic(
            model=config.FALLBACK_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            temperature=0,
            max_tokens=256,
        )
        _commentary_llm = ChatAnthropic(
            model=config.FALLBACK_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            temperature=0.3,
            max_tokens=256,
        )
        logger.warning(f"LLM: Anthropic API fallback / {config.FALLBACK_MODEL}")

    else:
        raise RuntimeError(
            "No LLM available. Either:\n"
            "  • Start Ollama and run: ollama pull phi4-mini\n"
            "  • Set ANTHROPIC_API_KEY in .env.local"
        )

    return _primary_llm, _commentary_llm


def get_llm() -> Any:
    if _primary_llm is None:
        raise RuntimeError("LLM not initialised — call init_llm() first.")
    return _primary_llm


def get_commentary_llm() -> Any:
    if _commentary_llm is None:
        raise RuntimeError("LLM not initialised — call init_llm() first.")
    return _commentary_llm


def current_backend() -> str:
    """Return 'ollama', 'anthropic', or 'none'."""
    if _primary_llm is None:
        return "none"
    return "ollama" if "ollama" in type(_primary_llm).__module__ else "anthropic"


# ── Backend detection ─────────────────────────────────────────────────────────

def _detect_backend(config) -> str:
    """Return 'ollama', 'anthropic', or 'none'."""
    if _ollama_available(config):
        return "ollama"
    if config.FALLBACK_ENABLED and config.ANTHROPIC_API_KEY:
        return "anthropic"
    return "none"


def _ollama_available(config) -> bool:
    """Return True if Ollama is running and the configured model is pulled."""
    try:
        import httpx
        resp = httpx.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=3.0)
        if resp.status_code != 200:
            return False
        models = [m["name"] for m in resp.json().get("models", [])]
        pulled = any(config.OLLAMA_MODEL in m for m in models)
        if not pulled:
            logger.warning(
                f"Ollama is running but model '{config.OLLAMA_MODEL}' is not pulled. "
                f"Run: ollama pull {config.OLLAMA_MODEL}"
            )
        return pulled
    except Exception:
        return False
```

---

### `graph/nodes.py` (updated — diff only)

Replace inline `ChatOllama` construction in `llm_node` and `commentary_node`:

```python
# Before (Sprint 2/3/4):
def llm_node(state: OracleState) -> dict:
    from langchain_ollama import ChatOllama
    from config.settings import config
    llm = ChatOllama(model=config.OLLAMA_MODEL, temperature=0, ...)
    llm_with_tools = llm.bind_tools(ORACLE_TOOLS)
    ...

def commentary_node(state: OracleState) -> dict:
    from langchain_ollama import ChatOllama
    from config.settings import config
    llm = ChatOllama(model=config.OLLAMA_MODEL, temperature=0.3, ...)
    ...

# After (Sprint 5):
def llm_node(state: OracleState) -> dict:
    from graph.llm import get_llm
    llm = get_llm()
    llm_with_tools = llm.bind_tools(ORACLE_TOOLS)
    ...

def commentary_node(state: OracleState) -> dict:
    from graph.llm import get_commentary_llm
    llm = get_commentary_llm()
    ...
```

Both `ChatOllama` and `ChatAnthropic` implement the same LangChain `BaseChatModel` interface, so `bind_tools()` and `.invoke()` work identically on both. No other node changes needed.

---

### `config/settings.py` (updated)

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env.local", extra="ignore")

    # LLM — local
    OLLAMA_MODEL: str    = "phi4-mini"
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # LLM — API fallback (Sprint 5)
    FALLBACK_ENABLED: bool       = True
    FALLBACK_MODEL: str          = "claude-haiku-4-5-20251001"
    ANTHROPIC_API_KEY: str | None = None

    # Game
    DIFFICULTY: str = "professional"
    DB_PATH: str    = "config/ghost_database.yaml"

    # Voice — STT
    STT_MODEL: str = "base.en"

    # Voice — TTS
    SPEAKER_DEVICE_NAME: str | None = None
    TTS_VOICE: str                  = "bm_fable"

    # Voice — Steam routing
    STEAM_ROUTE_DEVICE_NAME: str | None = None
    STEAM_ROUTE_GAIN: float             = 1.0

    # Voice — wake word
    WAKE_WORD: str = "oracle"

    # Voice — recording
    MIC_DEVICE_NAME: str | None  = None
    SILENCE_THRESHOLD_DB: float  = -40.0
    MAX_RECORDING_SECONDS: float = 8.0

    # Voice — loopback (Kayden)
    LOOPBACK_ENABLED: bool           = False
    LOOPBACK_DEVICE_NAME: str | None = None
    MIKE_SPEAKER_NAME: str           = "Mike"
    KAYDEN_SPEAKER_NAME: str         = "Kayden"

config = Settings()
```

---

### `config/.env.local` (final template)

```env
# ── LLM — local ───────────────────────────────────────────────────────────────
OLLAMA_MODEL=phi4-mini
OLLAMA_BASE_URL=http://localhost:11434

# ── LLM — API fallback ────────────────────────────────────────────────────────
# Used automatically if Ollama is unavailable. Leave blank to disable.
# ANTHROPIC_API_KEY=sk-ant-...
FALLBACK_ENABLED=true
FALLBACK_MODEL=claude-haiku-4-5-20251001

# ── Game ──────────────────────────────────────────────────────────────────────
DIFFICULTY=professional

# ── Voice (STT) ───────────────────────────────────────────────────────────────
STT_MODEL=base.en
WAKE_WORD=oracle
# MIC_DEVICE_NAME=Blue Yeti
SILENCE_THRESHOLD_DB=-40.0
MAX_RECORDING_SECONDS=8.0

# ── Voice (TTS — local) ───────────────────────────────────────────────────────
TTS_VOICE=bm_fable
# SPEAKER_DEVICE_NAME=VK81

# ── Voice (TTS — Steam via Voicemeeter) ──────────────────────────────────────
# STEAM_ROUTE_DEVICE_NAME=Voicemeeter Input
# STEAM_ROUTE_GAIN=1.0

# ── Voice (Kayden loopback) ───────────────────────────────────────────────────
# LOOPBACK_ENABLED=true
# LOOPBACK_DEVICE_NAME=VK81
# MIKE_SPEAKER_NAME=Mike
# KAYDEN_SPEAKER_NAME=Kayden
```

---

### `ui/diagnostics.py`

```python
"""
Startup health checks for all Oracle components.
Returns a structured list of DiagnosticResult items.
Printed via Rich before Oracle starts (or on --check).
"""

import logging
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

Status = Literal["ok", "warn", "fail"]


@dataclass
class DiagnosticResult:
    component: str
    status: Status
    detail: str
    hint: str = ""


def run_diagnostics(config) -> list[DiagnosticResult]:
    results: list[DiagnosticResult] = []
    results += _check_database(config)
    results += _check_llm(config)
    results += _check_tts()
    results += _check_audio_devices(config)
    return results


def all_passed(results: list[DiagnosticResult]) -> bool:
    return all(r.status != "fail" for r in results)


# ── Individual checks ─────────────────────────────────────────────────────────

def _check_database(config) -> list[DiagnosticResult]:
    from pathlib import Path
    import yaml
    path = Path(config.DB_PATH)
    if not path.exists():
        return [DiagnosticResult(
            "Ghost database", "fail",
            f"{config.DB_PATH} not found",
            hint=f"Ensure ghost_database.yaml is at {config.DB_PATH}",
        )]
    try:
        with open(path) as f:
            db = yaml.safe_load(f)
        n = len(db.get("ghosts", []))
        return [DiagnosticResult("Ghost database", "ok", f"{n} ghosts loaded")]
    except Exception as e:
        return [DiagnosticResult("Ghost database", "fail", str(e))]


def _check_llm(config) -> list[DiagnosticResult]:
    results = []
    # Ollama check
    try:
        import httpx
        resp = httpx.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=3.0)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            if any(config.OLLAMA_MODEL in m for m in models):
                results.append(DiagnosticResult(
                    "Ollama", "ok", f"{config.OLLAMA_MODEL} ready"
                ))
            else:
                results.append(DiagnosticResult(
                    "Ollama", "warn",
                    f"{config.OLLAMA_MODEL} not pulled",
                    hint=f"Run: ollama pull {config.OLLAMA_MODEL}",
                ))
        else:
            results.append(DiagnosticResult(
                "Ollama", "warn", f"HTTP {resp.status_code}"
            ))
    except Exception:
        results.append(DiagnosticResult(
            "Ollama", "warn", "Not reachable",
            hint="Start Ollama or set ANTHROPIC_API_KEY for API fallback",
        ))

    # Anthropic fallback check
    if config.FALLBACK_ENABLED:
        if config.ANTHROPIC_API_KEY:
            results.append(DiagnosticResult(
                "API fallback", "ok",
                f"{config.FALLBACK_MODEL} (key present)",
            ))
        else:
            # Only a failure if Ollama is also unavailable
            ollama_ok = any(r.status == "ok" for r in results if r.component == "Ollama")
            status: Status = "warn" if ollama_ok else "fail"
            results.append(DiagnosticResult(
                "API fallback", status,
                "ANTHROPIC_API_KEY not set",
                hint="Set ANTHROPIC_API_KEY in .env.local to enable fallback",
            ))

    return results


def _check_tts() -> list[DiagnosticResult]:
    from pathlib import Path
    missing = []
    for fname in ("kokoro-v0_19.onnx", "voices-v1_0.bin"):
        if not Path(fname).exists():
            missing.append(fname)
    if missing:
        return [DiagnosticResult(
            "Kokoro TTS", "fail",
            f"Missing: {', '.join(missing)}",
            hint="Download from https://github.com/thewh1teagle/kokoro-onnx/releases",
        )]
    return [DiagnosticResult("Kokoro TTS", "ok", "Model files present")]


def _check_audio_devices(config) -> list[DiagnosticResult]:
    results = []
    try:
        import sounddevice as sd
        devices = sd.query_devices()

        def find(hint: str | None, kind: str) -> tuple[Status, str]:
            if not hint:
                return "ok", f"{kind}: system default"
            for d in devices:
                max_ch = d["max_output_channels"] if kind == "output" else d["max_input_channels"]
                if hint.lower() in d["name"].lower() and max_ch > 0:
                    return "ok", f"{kind}: {d['name']}"
            return "warn", f"{kind}: '{hint}' not found — using system default"

        if config.MIC_DEVICE_NAME:
            status, detail = find(config.MIC_DEVICE_NAME, "input")
            results.append(DiagnosticResult("Microphone", status, detail))
        else:
            results.append(DiagnosticResult("Microphone", "ok", "system default"))

        if config.SPEAKER_DEVICE_NAME:
            status, detail = find(config.SPEAKER_DEVICE_NAME, "output")
            results.append(DiagnosticResult("Speaker", status, detail))
        else:
            results.append(DiagnosticResult("Speaker", "ok", "system default"))

        if config.STEAM_ROUTE_DEVICE_NAME:
            status, detail = find(config.STEAM_ROUTE_DEVICE_NAME, "output")
            results.append(DiagnosticResult(
                "Steam route", status,
                detail,
                hint="Ensure Voicemeeter is running" if status == "warn" else "",
            ))

        if config.LOOPBACK_ENABLED and config.LOOPBACK_DEVICE_NAME:
            status, detail = find(config.LOOPBACK_DEVICE_NAME, "output")
            results.append(DiagnosticResult("Loopback (Kayden)", status, detail))

    except Exception as e:
        results.append(DiagnosticResult("Audio devices", "fail", str(e)))

    return results
```

---

### `ui/display.py`

```python
"""
Rich live terminal display for Oracle sessions.

Layout:
┌─ Oracle ─────────────────────────────────────────────────────┐
│  Session: 20260330_142000 | Difficulty: Professional | 🟢 ok │
├──────────────────────────┬───────────────────────────────────┤
│  Candidates              │  Evidence                         │
│  ─────────────────────── │  ──────────────────────────────── │
│  ▸ Banshee               │  ✓ EMF Level 5                   │
│  ▸ Demon                 │  ✓ UV Fingerprints               │
│  ▸ Shade                 │  ✗ Spirit Box (ruled out)        │
├──────────────────────────┴───────────────────────────────────┤
│  Recent activity                                              │
│  Mike  "ghost orb confirmed"                                 │
│  Oracle  "Three candidates remain: Banshee, Demon, Shade."  │
└──────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

if TYPE_CHECKING:
    pass

console = Console()

_EVIDENCE_LABELS = {
    "emf_5":      "EMF Level 5",
    "dots":       "DOTS Projector",
    "uv":         "UV Fingerprints",
    "freezing":   "Freezing Temps",
    "orb":        "Ghost Orb",
    "writing":    "Ghost Writing",
    "spirit_box": "Spirit Box",
}

_MAX_LOG_LINES = 6


def print_diagnostics(results: list) -> None:
    """Print startup diagnostics table and exit hint if any failures."""
    from rich.table import Table
    t = Table(title="Oracle Startup Diagnostics", box=box.ROUNDED, show_header=True)
    t.add_column("Component",  style="bold")
    t.add_column("Status",     justify="center")
    t.add_column("Detail")
    t.add_column("Hint",       style="dim")

    icons = {"ok": "[green]✓[/green]", "warn": "[yellow]⚠[/yellow]", "fail": "[red]✗[/red]"}
    for r in results:
        t.add_row(r.component, icons[r.status], r.detail, r.hint)

    console.print(t)


class OracleDisplay:
    """
    Manages a Rich Live display that updates after each Oracle turn.
    Use as a context manager:

        with OracleDisplay(session_id, difficulty) as display:
            ...
            display.update(state, speaker, transcript, response)
    """

    def __init__(self, session_id: str, difficulty: str, backend: str = "ollama"):
        self._session_id = session_id
        self._difficulty = difficulty
        self._backend    = backend
        self._log: list[tuple[str, str, str | None]] = []  # (speaker, transcript, response)
        self._live: Live | None = None

    def __enter__(self) -> "OracleDisplay":
        self._live = Live(
            self._render(),
            console=console,
            refresh_per_second=4,
            screen=False,
        )
        self._live.__enter__()
        return self

    def __exit__(self, *args) -> None:
        if self._live:
            self._live.__exit__(*args)

    def update(
        self,
        state: dict,
        speaker: str,
        transcript: str,
        response: str | None,
    ) -> None:
        self._log.append((speaker, transcript, response))
        if len(self._log) > _MAX_LOG_LINES:
            self._log.pop(0)
        if self._live:
            self._live.update(self._render(state))

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render(self, state: dict | None = None) -> Panel:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=1),
            Layout(name="body"),
            Layout(name="log", size=_MAX_LOG_LINES + 2),
        )
        layout["body"].split_row(
            Layout(name="candidates"),
            Layout(name="evidence"),
        )

        backend_icon = "[green]◉ local[/green]" if self._backend == "ollama" \
                       else "[yellow]◉ api[/yellow]"
        layout["header"].update(
            Text(
                f"  Session: {self._session_id}  |  "
                f"Difficulty: {self._difficulty.capitalize()}  |  {backend_icon}",
                style="dim",
            )
        )
        layout["candidates"].update(self._candidate_panel(state))
        layout["evidence"].update(self._evidence_panel(state))
        layout["log"].update(self._log_panel())

        return Panel(layout, title="[bold cyan]Oracle[/bold cyan]", box=box.ROUNDED)

    def _candidate_panel(self, state: dict | None) -> Panel:
        t = Table(box=None, show_header=False, padding=(0, 1))
        t.add_column("", style="cyan")
        candidates = (state or {}).get("candidates", [])
        if not candidates:
            t.add_row("[dim]No candidates[/dim]")
        else:
            for name in candidates:
                t.add_row(f"▸ {name}")
        return Panel(t, title=f"Candidates ({len(candidates)})", box=box.SIMPLE)

    def _evidence_panel(self, state: dict | None) -> Panel:
        t = Table(box=None, show_header=False, padding=(0, 1))
        t.add_column("", no_wrap=True)
        confirmed = set((state or {}).get("evidence_confirmed", []))
        ruled_out = set((state or {}).get("evidence_ruled_out", []))
        for eid, label in _EVIDENCE_LABELS.items():
            if eid in confirmed:
                t.add_row(f"[green]✓[/green] {label}")
            elif eid in ruled_out:
                t.add_row(f"[red]✗[/red] [dim]{label}[/dim]")
            else:
                t.add_row(f"[dim]  {label}[/dim]")
        return Panel(t, title="Evidence", box=box.SIMPLE)

    def _log_panel(self) -> Panel:
        t = Table(box=None, show_header=False, padding=(0, 1))
        t.add_column("who",   style="bold", no_wrap=True, width=10)
        t.add_column("text",  no_wrap=False)
        for speaker, transcript, response in self._log:
            t.add_row(f"[cyan]{speaker}[/cyan]", transcript)
            if response:
                t.add_row("[magenta]Oracle[/magenta]", response)
        return Panel(t, title="Activity", box=box.SIMPLE)
```

---

### `ui/replay.py`

```python
"""
Session replay — load a session.jsonl file and display or re-execute it.

Modes:
  display-only  — render each turn in the terminal UI, no LLM calls
  re-run        — re-execute each turn through the current graph and
                  compare responses to the recorded ones
"""

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def load_session(path: str) -> list[dict]:
    """Load all events from a session JSONL file."""
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def replay_display(path: str, speed: float = 1.0) -> None:
    """
    Display-only replay. Renders each turn in the terminal UI.
    speed: playback multiplier (1.0 = real-time, 2.0 = double speed, 0 = instant)
    """
    from graph.deduction import all_ghost_names
    from ui.display import OracleDisplay
    from config.settings import config

    events = load_session(path)
    session_id = Path(path).stem

    # Extract difficulty from session_start event
    difficulty = config.DIFFICULTY
    for e in events:
        if e.get("event") == "init":
            difficulty = e.get("difficulty", difficulty)
            break

    state = {
        "candidates":          all_ghost_names(),
        "evidence_confirmed":  [],
        "evidence_ruled_out":  [],
        "eliminated_ghosts":   [],
        "behavioral_observations": [],
        "difficulty":          difficulty,
    }

    turn_events = [e for e in events if e.get("event") == "turn"]
    prev_ts: float | None = None

    print(f"\nReplaying session: {session_id}  ({len(turn_events)} turns)\n")

    with OracleDisplay(session_id + " [replay]", difficulty) as display:
        for event in turn_events:
            # Honour original timing if speed > 0
            if speed > 0 and prev_ts is not None:
                delay = (event["ts"] - prev_ts) / speed
                time.sleep(min(delay, 5.0))  # cap at 5s regardless of gaps
            prev_ts = event["ts"]

            # Update state from recorded data
            if "candidates" in event:
                state["candidates"] = event["candidates"]

            speaker    = event.get("speaker", "?")
            transcript = event.get("input", "")
            response   = event.get("response")

            display.update(state, speaker, transcript, response)

    print(f"\nReplay complete. {len(turn_events)} turns.\n")


def replay_rerun(path: str) -> None:
    """
    Re-run replay: re-execute each recorded turn through the current graph.
    Prints a diff of recorded vs. new responses.
    Useful for regression testing after graph or prompt changes.
    """
    from graph.graph import oracle_graph
    from graph.deduction import all_ghost_names
    from graph.tools import bind_state, sync_state_from
    from graph.llm import init_llm
    from ui.display import OracleDisplay, console
    from config.settings import config
    from rich.text import Text

    init_llm()
    events     = load_session(path)
    session_id = Path(path).stem
    turn_events = [e for e in events if e.get("event") == "turn"]

    difficulty = config.DIFFICULTY
    for e in events:
        if e.get("event") == "init":
            difficulty = e.get("difficulty", difficulty)
            break

    state = {
        "user_text": "", "speaker": "Mike", "difficulty": difficulty,
        "evidence_confirmed": [], "evidence_ruled_out": [],
        "behavioral_observations": [], "eliminated_ghosts": [],
        "candidates": all_ghost_names(), "oracle_response": None,
        "prev_candidate_count": 27, "turn_id": 0, "messages": [],
    }

    mismatches = 0
    print(f"\nRe-running session: {session_id}  ({len(turn_events)} turns)\n")

    with OracleDisplay(session_id + " [re-run]", difficulty) as display:
        for event in turn_events:
            transcript = event.get("input", "")
            recorded   = event.get("response", "")
            speaker    = event.get("speaker", "Mike")

            state["speaker"]              = speaker
            state["prev_candidate_count"] = len(state.get("candidates", []))
            state["user_text"]            = transcript
            state["messages"]             = []
            state["turn_id"]             += 1

            bind_state(state)
            result = oracle_graph.invoke(state)
            sync_state_from(state)
            new_response = result.get("oracle_response") or ""

            display.update(state, speaker, transcript, new_response)

            if new_response.strip() != (recorded or "").strip():
                mismatches += 1
                console.print(
                    f"[yellow]Turn {state['turn_id']} mismatch:[/yellow]\n"
                    f"  Recorded: {recorded!r}\n"
                    f"  New:      {new_response!r}"
                )

    print(f"\nRe-run complete. {mismatches}/{len(turn_events)} response mismatches.\n")
```

---

### `main.py` (final version)

```python
#!/usr/bin/env python3
"""Oracle — Phasmophobia ghost identification assistant."""

import argparse
import datetime
import logging

from config.settings import config
from graph.deduction import all_ghost_names
from graph.llm import init_llm, current_backend
from graph.session_log import init_log, log_event
from graph.tools import bind_state, sync_state_from

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("oracle")


# ── Session state ─────────────────────────────────────────────────────────────

def make_initial_state() -> dict:
    return {
        "user_text": "", "speaker": config.MIKE_SPEAKER_NAME,
        "difficulty": config.DIFFICULTY,
        "evidence_confirmed": [], "evidence_ruled_out": [],
        "behavioral_observations": [], "eliminated_ghosts": [],
        "candidates": all_ghost_names(),
        "oracle_response": None,
        "prev_candidate_count": 27, "turn_id": 0, "messages": [],
    }


def run_turn(state: dict, user_text: str) -> str | None:
    from graph.graph import oracle_graph
    state["turn_id"] += 1
    state["user_text"] = user_text
    state["messages"] = []
    state["prev_candidate_count"] = len(state.get("candidates", []))
    bind_state(state)
    result = oracle_graph.invoke(state)
    sync_state_from(state)
    log_event(
        "turn",
        {"speaker": state["speaker"], "input": user_text,
         "response": result.get("oracle_response"),
         "candidates": state.get("candidates", [])},
        state["turn_id"],
    )
    return result.get("oracle_response")


# ── Text loop ─────────────────────────────────────────────────────────────────

def run_text_loop(state: dict) -> None:
    from ui.display import OracleDisplay
    session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    n = len(state["candidates"])
    print(f"\nOracle ready [text mode]. {n} candidates. Type 'quit' to exit.\n")

    with OracleDisplay(session_id, state["difficulty"], current_backend()) as display:
        while True:
            try:
                raw = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nOracle offline.")
                break
            if not raw or raw.lower() in ("quit", "exit"):
                break

            response = run_turn(state, raw)
            display.update(state, state["speaker"], raw, response)
            if response:
                print(f"\nOracle: {response}\n")
            else:
                print(f"  [state updated — {len(state.get('candidates',[]))} candidate(s)]\n")


# ── Voice loop ────────────────────────────────────────────────────────────────

def run_voice_loop(state: dict) -> None:
    from voice.voice_session import VoiceSession
    from voice.speech_to_text import SpeechToText
    from voice.text_to_speech import TextToSpeech
    from ui.display import OracleDisplay

    stt = SpeechToText(model_size=config.STT_MODEL)
    tts = TextToSpeech(
        speaker_device_name=config.SPEAKER_DEVICE_NAME,
        steam_device_name=config.STEAM_ROUTE_DEVICE_NAME,
        steam_gain=config.STEAM_ROUTE_GAIN,
    )
    tts.load()

    session = VoiceSession(
        wake_word=config.WAKE_WORD,
        mic_device=config.MIC_DEVICE_NAME,
        loopback_device=config.LOOPBACK_DEVICE_NAME if config.LOOPBACK_ENABLED else None,
        mike_name=config.MIKE_SPEAKER_NAME,
        kayden_name=config.KAYDEN_SPEAKER_NAME,
        silence_threshold_db=config.SILENCE_THRESHOLD_DB,
        max_record_seconds=config.MAX_RECORDING_SECONDS,
    )
    session.set_tts_ref(lambda: tts.is_speaking)
    mic_detector, loopback = session.start()

    session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    tts.speak(
        f"Oracle online. {state['difficulty'].capitalize()} difficulty. "
        f"{'Bidirectional mode.' if loopback else 'Ready.'}"
    )

    try:
        with OracleDisplay(session_id, state["difficulty"], current_backend()) as display:
            while True:
                command = session.get(timeout=1.0)
                if command is None:
                    continue
                speaker, audio, rate = command
                transcript = stt.transcribe(audio, rate)
                if not transcript:
                    continue
                logger.info(f"{speaker}: {transcript!r}")
                state["speaker"] = speaker
                tts.flush()
                response = run_turn(state, transcript)
                display.update(state, speaker, transcript, response)
                if response:
                    tts.speak(response)
    except KeyboardInterrupt:
        logger.info("Oracle offline.")
    finally:
        if mic_detector:
            mic_detector.stop()
        if loopback:
            loopback.stop()
        tts.shutdown()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Oracle — Phasmophobia ghost assistant")
    parser.add_argument("--text",       action="store_true",  help="Text input mode")
    parser.add_argument("--difficulty", default=None,         help="Override difficulty")
    parser.add_argument("--check",      action="store_true",  help="Run diagnostics and exit")
    parser.add_argument("--replay",     default=None,         metavar="FILE",
                        help="Replay a session.jsonl file")
    parser.add_argument("--re-run",     action="store_true",  help="Re-execute replay through graph")
    parser.add_argument("--speed",      type=float, default=1.0,
                        help="Replay speed multiplier (0=instant, 1=real-time)")
    args = parser.parse_args()

    if args.difficulty:
        config.DIFFICULTY = args.difficulty

    # ── Diagnostics ───────────────────────────────────────────────────────────
    from ui.diagnostics import run_diagnostics, all_passed, print_diagnostics
    results = run_diagnostics(config)
    print_diagnostics(results)

    if args.check:
        raise SystemExit(0 if all_passed(results) else 1)

    if not all_passed(results):
        critical = [r for r in results if r.status == "fail"]
        for r in critical:
            logger.error(f"Fatal: {r.component} — {r.detail}. {r.hint}")
        raise SystemExit(1)

    # ── LLM init ──────────────────────────────────────────────────────────────
    try:
        init_llm()
    except RuntimeError as e:
        logger.error(str(e))
        raise SystemExit(1)

    # ── Replay modes ──────────────────────────────────────────────────────────
    if args.replay:
        from ui.replay import replay_display, replay_rerun
        if args.re_run:
            replay_rerun(args.replay)
        else:
            replay_display(args.replay, speed=args.speed)
        return

    # ── Session setup ─────────────────────────────────────────────────────────
    session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    init_log(session_id)
    state = make_initial_state()
    log_event("init", {"difficulty": state["difficulty"],
                        "candidates": len(state["candidates"])})

    if args.text:
        run_text_loop(state)
    else:
        run_voice_loop(state)


if __name__ == "__main__":
    main()
```

---

### `tests/test_llm.py`

```python
"""Test LLM factory: Ollama detection, fallback trigger, no-key error."""

import pytest
from unittest.mock import patch, MagicMock


def _make_config(ollama_model="phi4-mini", api_key=None, fallback_enabled=True):
    cfg = MagicMock()
    cfg.OLLAMA_MODEL     = ollama_model
    cfg.OLLAMA_BASE_URL  = "http://localhost:11434"
    cfg.ANTHROPIC_API_KEY = api_key
    cfg.FALLBACK_ENABLED  = fallback_enabled
    cfg.FALLBACK_MODEL    = "claude-haiku-4-5-20251001"
    return cfg


# ── _ollama_available ─────────────────────────────────────────────────────────

@patch("graph.llm.httpx.get")
def test_ollama_available_when_model_pulled(mock_get):
    from graph.llm import _ollama_available
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"models": [{"name": "phi4-mini:latest"}]},
    )
    assert _ollama_available(_make_config()) is True


@patch("graph.llm.httpx.get")
def test_ollama_unavailable_when_model_missing(mock_get):
    from graph.llm import _ollama_available
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"models": [{"name": "llama3:latest"}]},
    )
    assert _ollama_available(_make_config()) is False


@patch("graph.llm.httpx.get", side_effect=Exception("connection refused"))
def test_ollama_unavailable_on_connection_error(mock_get):
    from graph.llm import _ollama_available
    assert _ollama_available(_make_config()) is False


# ── _detect_backend ───────────────────────────────────────────────────────────

@patch("graph.llm._ollama_available", return_value=True)
def test_detect_backend_prefers_ollama(mock_avail):
    from graph.llm import _detect_backend
    cfg = _make_config(api_key="sk-ant-xxx")
    assert _detect_backend(cfg) == "ollama"


@patch("graph.llm._ollama_available", return_value=False)
def test_detect_backend_falls_back_to_anthropic(mock_avail):
    from graph.llm import _detect_backend
    cfg = _make_config(api_key="sk-ant-xxx")
    assert _detect_backend(cfg) == "anthropic"


@patch("graph.llm._ollama_available", return_value=False)
def test_detect_backend_returns_none_when_no_fallback(mock_avail):
    from graph.llm import _detect_backend
    cfg = _make_config(api_key=None)
    assert _detect_backend(cfg) == "none"


# ── init_llm error path ───────────────────────────────────────────────────────

@patch("graph.llm._detect_backend", return_value="none")
def test_init_llm_raises_when_no_backend(mock_detect):
    import graph.llm as llm_mod
    llm_mod._primary_llm    = None
    llm_mod._commentary_llm = None
    with pytest.raises(RuntimeError, match="No LLM available"):
        llm_mod.init_llm()
```

---

### `tests/test_ui.py`

```python
"""Tests for diagnostics and replay parsing."""

import json
import tempfile
from pathlib import Path
import pytest


# ── Diagnostics ───────────────────────────────────────────────────────────────

def test_all_passed_true_when_no_failures():
    from ui.diagnostics import DiagnosticResult, all_passed
    results = [
        DiagnosticResult("A", "ok",   "fine"),
        DiagnosticResult("B", "warn", "minor"),
    ]
    assert all_passed(results) is True


def test_all_passed_false_when_any_failure():
    from ui.diagnostics import DiagnosticResult, all_passed
    results = [
        DiagnosticResult("A", "ok",   "fine"),
        DiagnosticResult("B", "fail", "broken"),
    ]
    assert all_passed(results) is False


def test_database_check_fails_on_missing_file():
    from ui.diagnostics import _check_database
    from unittest.mock import MagicMock
    cfg = MagicMock()
    cfg.DB_PATH = "/nonexistent/path/ghost_database.yaml"
    results = _check_database(cfg)
    assert results[0].status == "fail"


# ── Replay parsing ────────────────────────────────────────────────────────────

def test_load_session_parses_jsonl():
    from ui.replay import load_session
    events = [
        {"ts": 1.0, "turn": 0, "event": "session_start"},
        {"ts": 2.0, "turn": 1, "event": "turn",
         "speaker": "Mike", "input": "ghost orb confirmed", "response": "...",
         "candidates": ["Banshee"]},
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
        path = f.name

    loaded = load_session(path)
    assert len(loaded) == 2
    assert loaded[1]["speaker"] == "Mike"


def test_load_session_filters_blanks():
    """Empty lines in the JSONL should not cause errors."""
    from ui.replay import load_session
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write('{"event": "session_start"}\n')
        f.write("\n")   # blank line
        f.write('{"event": "turn", "turn": 1, "input": "test"}\n')
        path = f.name

    loaded = load_session(path)
    assert len(loaded) == 2
```

---

## Installation (Sprint 5 additions)

```bash
# New dependencies
pip install rich httpx langchain-anthropic

# Run full test suite
pytest tests/ -v

# Diagnostics only (no session)
python main.py --check

# Standard voice session
python main.py

# Text mode (testing / no mic)
python main.py --text

# Override difficulty
python main.py --difficulty nightmare

# Replay a session (display only)
python main.py --replay sessions/20260330_142000.jsonl

# Replay in real-time speed
python main.py --replay sessions/20260330_142000.jsonl --speed 1.0

# Replay instantly
python main.py --replay sessions/20260330_142000.jsonl --speed 0

# Regression test: re-run session through current graph
python main.py --replay sessions/20260330_142000.jsonl --re-run
```

---

## Task Board

### Backlog

|ID|Task|Notes|
|---|---|---|
|S5-01|Create `graph/llm.py`|`init_llm()`, `get_llm()`, `get_commentary_llm()`, `_ollama_available()`, `_detect_backend()`|
|S5-02|Update `graph/nodes.py`|Replace inline `ChatOllama` with `get_llm()` / `get_commentary_llm()` — 2 line changes|
|S5-03|Update `config/settings.py`|Add `ANTHROPIC_API_KEY`, `FALLBACK_MODEL`, `FALLBACK_ENABLED`|
|S5-04|Update `config/.env.local`|Document API key + fallback fields|
|S5-05|Create `ui/__init__.py`|Empty — makes `ui/` a package|
|S5-06|Create `ui/diagnostics.py`|All component checks, `DiagnosticResult`, `all_passed()`, `print_diagnostics()`|
|S5-07|Create `ui/display.py`|`OracleDisplay` context manager, `print_diagnostics()`, Rich layout|
|S5-08|Create `ui/replay.py`|`load_session()`, `replay_display()`, `replay_rerun()`|
|S5-09|Update `main.py`|Final version: all CLI flags, diagnostics on startup, `OracleDisplay` in both loops|
|S5-10|Write `tests/test_llm.py`|Ollama detection, fallback, no-key error|
|S5-11|Write `tests/test_ui.py`|Diagnostics logic, replay JSONL parsing|
|S5-12|Run full test suite|`pytest tests/ -v` — all Sprint 1–5 tests pass|
|S5-13|Smoke test: `--check` clean|All components OK → exit 0|
|S5-14|Smoke test: `--check` with failure|Kill Ollama → diagnostics shows warn, API fallback shown|
|S5-15|Smoke test: API fallback live|Kill Ollama, set API key, start Oracle → `◉ api` shown in display|
|S5-16|Smoke test: no backend at all|Kill Ollama, clear API key → clear error message, exit 1|
|S5-17|Smoke test: terminal display|Run `--text` session → confirm live display updates correctly per turn|
|S5-18|Smoke test: `--replay` display|Replay a recorded session — display steps through correctly|
|S5-19|Smoke test: `--replay --re-run`|Re-run a session — 0 mismatches on unchanged graph|
|S5-20|Smoke test: `--replay --re-run` after prompt change|Deliberate prompt tweak → mismatches reported correctly|
|S5-21|Full session test|Complete voice match, review terminal display, replay session afterward|

### Definition of Done (Sprint 5)

- [ ] All `test_llm.py` and `test_ui.py` tests pass
- [ ] All Sprint 1–4 tests still pass
- [ ] `--check` exits 0 when all components healthy
- [ ] Oracle starts and uses API fallback automatically when Ollama is offline
- [ ] Oracle exits with clear error when neither Ollama nor API key is available
- [ ] Terminal display updates live during text and voice sessions
- [ ] `--replay` plays back a session correctly
- [ ] `--replay --re-run` reports 0 mismatches on unchanged graph
- [ ] `Ctrl+C` exits cleanly from all modes

---

## Known Risks

**`httpx` is a new dependency.** It's used only for the Ollama health check (`_ollama_available`). If `httpx` is undesirable, the check can be rewritten with `urllib.request` from the standard library — same timeout, no extra package. Note that `langchain-anthropic` already depends on `httpx` internally, so the net dependency cost is zero once the API fallback is enabled.

**`ChatAnthropic` tool-call schema differences.** Anthropic's tool-call API is slightly stricter than Ollama's about parameter types — in particular, it rejects `int | None` in tool schemas where Ollama tolerates them. If tool calls start failing on the API fallback, inspect the tool schema with `ORACLE_TOOLS[i].args_schema.schema()` and ensure all optional fields have explicit `default` values rather than Python `None` typing.

**`--re-run` response mismatches are expected, not errors.** LLM responses are non-deterministic at any temperature > 0 (commentary node uses 0.3). The re-run mode prints mismatches as informational diffs, not test failures. If you want deterministic replay testing, set `OLLAMA_MODEL` temperature to 0 globally and accept stiffer commentary prose.

**Rich display conflicts with logging output.** `rich.live.Live` and standard `logging` both write to stdout. Concurrent writes produce garbled output. The fix is to route all logging through Rich's handler: `from rich.logging import RichHandler; logging.basicConfig(handlers=[RichHandler()])`. This replaces the plain `logging.basicConfig()` call in `main.py` and gives syntax-highlighted, well-formatted log lines that coexist cleanly with the `Live` display.