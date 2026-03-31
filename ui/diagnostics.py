"""Startup diagnostics — checks all components before a session begins."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)
console = Console()


@dataclass
class DiagnosticResult:
    name: str
    ok: bool
    message: str = ""


def _check_ollama() -> DiagnosticResult:
    from config.settings import config
    from graph.llm import _ollama_available

    ok = _ollama_available(config.OLLAMA_BASE_URL)
    return DiagnosticResult(
        "Ollama",
        ok,
        f"Reachable at {config.OLLAMA_BASE_URL}" if ok else "Not reachable — will try Anthropic fallback",
    )


def _check_db_path() -> DiagnosticResult:
    import pathlib

    from config.settings import config

    p = pathlib.Path(config.DB_PATH)
    ok = p.exists()
    return DiagnosticResult("Ghost DB", ok, str(p) if ok else f"Missing: {p}")


def _check_audio_devices() -> DiagnosticResult:
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        return DiagnosticResult("Audio devices", True, f"{len(devices)} devices found")
    except Exception as exc:
        return DiagnosticResult("Audio devices", False, str(exc))


def run_diagnostics() -> list[DiagnosticResult]:
    """Run all startup checks and return results."""
    checks = [
        _check_ollama,
        _check_db_path,
        _check_audio_devices,
    ]
    results = []
    for check in checks:
        try:
            results.append(check())
        except Exception as exc:
            results.append(DiagnosticResult(check.__name__, False, str(exc)))
    return results


def print_diagnostics() -> bool:
    """Run and pretty-print all diagnostics.

    Returns:
        True if all critical checks passed, False otherwise.
    """
    results = run_diagnostics()
    table = Table(title="Oracle Diagnostics", show_header=True)
    table.add_column("Component")
    table.add_column("Status")
    table.add_column("Detail")

    all_ok = True
    for r in results:
        status = "[green]✓ OK[/green]" if r.ok else "[red]✗ FAIL[/red]"
        table.add_row(r.name, status, r.message)
        if not r.ok:
            all_ok = False

    console.print(table)
    return all_ok
