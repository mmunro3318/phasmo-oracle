"""Rich terminal display — live candidate list, evidence panel, session log."""
from __future__ import annotations

from typing import Any

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

_EVIDENCE_LABELS: dict[str, str] = {
    "emf_5": "EMF Level 5",
    "dots": "D.O.T.S.",
    "uv": "Ultraviolet",
    "freezing": "Freezing Temps",
    "orb": "Ghost Orb",
    "writing": "Ghost Writing",
    "spirit_box": "Spirit Box",
}

console = Console()


def render_state(state: dict[str, Any]) -> None:
    """Print a Rich-formatted snapshot of the current Oracle state."""
    confirmed = state.get("evidence_confirmed", [])
    ruled_out = state.get("evidence_ruled_out", [])
    candidates = state.get("candidates", [])
    difficulty = state.get("difficulty", "?")
    response = state.get("oracle_response") or ""

    # Evidence panel
    evidence_table = Table(show_header=True, header_style="bold cyan", expand=True)
    evidence_table.add_column("Evidence")
    evidence_table.add_column("Status")
    for eid, label in _EVIDENCE_LABELS.items():
        if eid in confirmed:
            evidence_table.add_row(label, Text("✓ Confirmed", style="green"))
        elif eid in ruled_out:
            evidence_table.add_row(label, Text("✗ Ruled out", style="red"))
        else:
            evidence_table.add_row(label, Text("—", style="dim"))

    # Candidates panel
    cand_text = Text()
    for name in candidates:
        cand_text.append(f"  • {name}\n", style="yellow")
    if not candidates:
        cand_text.append("  (none)", style="dim red")

    panels = Columns(
        [
            Panel(evidence_table, title="Evidence", border_style="cyan"),
            Panel(cand_text, title=f"Candidates ({len(candidates)})", border_style="yellow"),
        ]
    )
    console.print(panels)
    if response:
        console.print(Panel(response, title=f"Oracle [{difficulty}]", border_style="magenta"))
