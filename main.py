#!/usr/bin/env python3
"""Oracle — Voice-driven Phasmophobia ghost identification assistant.
Sprint 1: text input loop with Rich terminal display.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from config.settings import config
from graph.deduction import all_ghost_names, load_db
from graph.tools import bind_state, sync_state_from

logger = logging.getLogger("oracle")

# ── Rich display (auto-detect TTY) ──────────────────────────────────────────

_USE_RICH = sys.stdout.isatty()

if _USE_RICH:
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text

        console = Console()
    except ImportError:
        _USE_RICH = False

if not _USE_RICH:
    console = None  # type: ignore[assignment]


def _display_state(state: dict) -> None:
    """Show the current investigation state."""
    if not _USE_RICH:
        candidates = state.get("candidates", [])
        n = len(candidates)
        print(f"  [{n} candidate(s)]")
        return

    candidates = state.get("candidates", [])
    confirmed = state.get("evidence_confirmed", [])
    ruled_out = state.get("evidence_ruled_out", [])
    difficulty = state.get("difficulty", "unknown")
    n = len(candidates)

    # Evidence table
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Label", style="dim")
    table.add_column("Value")

    table.add_row("Difficulty", f"[bold]{difficulty}[/bold]")
    table.add_row(
        "Confirmed",
        ", ".join(f"[green]{e}[/green]" for e in confirmed) or "[dim]none[/dim]",
    )
    table.add_row(
        "Ruled out",
        ", ".join(f"[red]{e}[/red]" for e in ruled_out) or "[dim]none[/dim]",
    )

    # Candidates display
    if n == 0:
        cand_text = "[bold red]No candidates — conflicting evidence?[/bold red]"
    elif n <= 8:
        cand_text = ", ".join(candidates)
    else:
        cand_text = f"{n} ghosts"

    table.add_row(f"Candidates ({n})", cand_text)

    console.print(Panel(table, title="[bold]Oracle[/bold]", border_style="blue"))


def _display_response(response: str | None) -> None:
    """Show Oracle's response."""
    if not response:
        return
    if _USE_RICH:
        console.print(f"\n[bold cyan]Oracle:[/bold cyan] {response}\n")
    else:
        print(f"\nOracle: {response}\n")


# ── JSONL Session Logger ────────────────────────────────────────────────────

class SessionLogger:
    """Append-only JSONL logger for session turns."""

    def __init__(self) -> None:
        sessions_dir = Path("sessions")
        sessions_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = sessions_dir / f"{timestamp}.jsonl"
        self._file = open(self.path, "a", encoding="utf-8")

    def log_turn(
        self,
        user_text: str,
        candidates_before: list[str],
        candidates_after: list[str],
        oracle_response: str | None,
    ) -> None:
        entry = {
            "ts": datetime.now().isoformat(),
            "user_text": user_text,
            "candidates_before": candidates_before,
            "candidates_after": candidates_after,
            "oracle_response": oracle_response,
        }
        self._file.write(json.dumps(entry) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


# ── Startup Diagnostics ────────────────────────────────────────────────────

def run_diagnostics() -> list[tuple[str, bool, str]]:
    """Run startup health checks. Returns list of (check_name, passed, detail)."""
    import httpx

    checks: list[tuple[str, bool, str]] = []

    # 1. Ghost database
    try:
        db = load_db()
        ghost_count = len(db.get("ghosts", []))
        if ghost_count == 27:
            checks.append(("Ghost database", True, f"{ghost_count} ghosts loaded"))
        else:
            checks.append(("Ghost database", False, f"Expected 27 ghosts, found {ghost_count}"))
    except Exception as exc:
        checks.append(("Ghost database", False, str(exc)))

    # 2. Ollama reachable
    try:
        resp = httpx.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=5.0)
        resp.raise_for_status()
        checks.append(("Ollama connection", True, f"Reachable at {config.OLLAMA_BASE_URL}"))

        # 3. Model pulled
        models = resp.json().get("models", [])
        model_names = [m.get("name", "").split(":")[0] for m in models]
        target = config.OLLAMA_MODEL.split(":")[0]
        if target in model_names:
            checks.append(("Model available", True, f"{config.OLLAMA_MODEL} is pulled"))
        else:
            checks.append((
                "Model available",
                False,
                f"{config.OLLAMA_MODEL} not found. Run: ollama pull {config.OLLAMA_MODEL}",
            ))
    except (httpx.ConnectError, httpx.TimeoutException):
        checks.append(("Ollama connection", False, f"Not reachable at {config.OLLAMA_BASE_URL}"))
        checks.append(("Model available", False, "Ollama not running"))

    # 4. .env.local
    env_path = Path(config.model_config.get("env_file", "config/.env.local"))
    if env_path.exists():
        checks.append((".env.local", True, "Config file found"))
    else:
        checks.append((".env.local", True, "Not found (using defaults)"))

    return checks


def display_diagnostics(checks: list[tuple[str, bool, str]]) -> bool:
    """Display diagnostic results. Returns True if all critical checks pass."""
    all_passed = True

    for name, passed, detail in checks:
        if _USE_RICH:
            icon = "[green]✓[/green]" if passed else "[red]✗[/red]"
            console.print(f"  {icon} {name}: {detail}")
        else:
            icon = "✓" if passed else "✗"
            print(f"  {icon} {name}: {detail}")

        if not passed and name in ("Ollama connection", "Model available", "Ghost database"):
            all_passed = False

    return all_passed


# ── State Factory ───────────────────────────────────────────────────────────

def make_initial_state() -> dict:
    return {
        "user_text": "",
        "speaker": "Mike",
        "difficulty": config.DIFFICULTY,
        "evidence_confirmed": [],
        "evidence_ruled_out": [],
        "behavioral_observations": [],
        "eliminated_ghosts": [],
        "candidates": all_ghost_names(),
        "parsed_intent": {},
        "tool_result": None,
        "oracle_response": None,
        "messages": [],
    }


# ── Text REPL ───────────────────────────────────────────────────────────────

def run_text_loop() -> None:
    """Sprint 1 entry point: typed input, Rich terminal output."""
    from graph.llm import init_llm
    from graph.graph import oracle_graph

    # Startup diagnostics
    if _USE_RICH:
        console.print("\n[bold]Oracle Startup Diagnostics[/bold]")
    else:
        print("\nOracle Startup Diagnostics")

    checks = run_diagnostics()
    if not display_diagnostics(checks):
        print("\nCritical checks failed. Fix the issues above and try again.")
        sys.exit(1)

    # Initialize LLM
    try:
        init_llm()
    except RuntimeError as exc:
        print(f"\nError: {exc}")
        sys.exit(1)

    # Set up session
    state = make_initial_state()
    session_logger = SessionLogger()
    n = len(state["candidates"])

    if _USE_RICH:
        console.print(
            f"\n[bold green]Oracle ready.[/bold green] "
            f"Difficulty: {state['difficulty']}. {n} candidates loaded."
        )
        console.print("[dim]Type evidence, observations, or questions. Type 'quit' to exit.[/dim]\n")
    else:
        print(f"\nOracle ready. Difficulty: {state['difficulty']}. {n} candidates loaded.")
        print("Type evidence, observations, or questions. Type 'quit' to exit.\n")

    _display_state(state)

    while True:
        try:
            raw = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nOracle offline.")
            break

        if not raw or raw.lower() in ("quit", "exit"):
            if _USE_RICH:
                console.print("[dim]Oracle offline.[/dim]")
            else:
                print("Oracle offline.")
            break

        # Snapshot candidates before this turn
        candidates_before = list(state.get("candidates", []))

        # Prepare this turn
        state["user_text"] = raw
        state["messages"] = []  # fresh message thread per turn
        bind_state(state)  # point tools at live state

        # Run the graph
        try:
            result = oracle_graph.invoke(state)
        except Exception as exc:
            logger.error("Graph invocation failed: %s", exc)
            if _USE_RICH:
                console.print(f"[bold red]Error:[/bold red] {exc}")
            else:
                print(f"Error: {exc}")
            continue

        # Sync tool-mutated state fields back into our session dict
        sync_state_from(state)

        response = result.get("oracle_response")

        # Log the turn
        session_logger.log_turn(
            user_text=raw,
            candidates_before=candidates_before,
            candidates_after=list(state.get("candidates", [])),
            oracle_response=response,
        )

        # Display
        _display_response(response)
        _display_state(state)

    session_logger.close()


# ── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Oracle — Phasmophobia ghost identification assistant")
    parser.add_argument("--check", action="store_true", help="Run startup diagnostics and exit")
    parser.add_argument("--difficulty", choices=["amateur", "intermediate", "professional", "nightmare", "insanity"])
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.difficulty:
        config.DIFFICULTY = args.difficulty

    if args.check:
        if _USE_RICH:
            console.print("\n[bold]Oracle Startup Diagnostics[/bold]")
        else:
            print("\nOracle Startup Diagnostics")
        checks = run_diagnostics()
        passed = display_diagnostics(checks)
        sys.exit(0 if passed else 1)

    run_text_loop()


if __name__ == "__main__":
    main()
