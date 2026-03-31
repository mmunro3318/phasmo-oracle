"""Rich stats renderer for the --stats CLI flag."""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def print_stats() -> None:
    """Fetch and display cumulative game statistics."""
    from db.queries import (
        average_time_to_identify,
        recent_sessions,
        sessions_by_difficulty,
        sessions_by_ghost,
        success_rate,
    )

    rate = success_rate()
    avg_time = average_time_to_identify()

    summary_lines = [
        f"Overall success rate: {rate * 100:.1f}%" if rate is not None else "Overall success rate: N/A",
        f"Avg time to identify: {avg_time:.1f}s" if avg_time is not None else "Avg time to identify: N/A",
    ]
    console.print(Panel("\n".join(summary_lines), title="Oracle Statistics", border_style="cyan"))

    # Per-difficulty
    diff_table = Table(title="By Difficulty", show_header=True)
    diff_table.add_column("Difficulty")
    diff_table.add_column("Total", justify="right")
    diff_table.add_column("Correct", justify="right")
    diff_table.add_column("Rate", justify="right")
    for row in sessions_by_difficulty():
        r = row.get("rate")
        diff_table.add_row(
            row["difficulty"],
            str(row["total"]),
            str(row["correct"]),
            f"{r * 100:.1f}%" if r is not None else "N/A",
        )
    console.print(diff_table)

    # Per-ghost
    ghost_table = Table(title="By Ghost", show_header=True)
    ghost_table.add_column("Ghost")
    ghost_table.add_column("Total", justify="right")
    ghost_table.add_column("Rate", justify="right")
    for row in sessions_by_ghost():
        r = row.get("rate")
        ghost_table.add_row(
            row["true_ghost"] or "Unknown",
            str(row["total"]),
            f"{r * 100:.1f}%" if r is not None else "N/A",
        )
    console.print(ghost_table)

    # Recent sessions
    recent_table = Table(title="Recent Sessions", show_header=True)
    recent_table.add_column("Session ID")
    recent_table.add_column("Difficulty")
    recent_table.add_column("True Ghost")
    recent_table.add_column("Result")
    for row in recent_sessions():
        result_map = {1: "[green]Correct[/green]", 0: "[red]Wrong[/red]", None: "—"}
        recent_table.add_row(
            row["session_id"],
            row["difficulty"],
            row["true_ghost"] or "—",
            result_map.get(row["oracle_correct"], "—"),
        )
    console.print(recent_table)
