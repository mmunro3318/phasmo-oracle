"""Session replay logic for the --replay CLI flag."""
from __future__ import annotations

import time

from rich.console import Console

from graph.session_log import load_log
from ui.display import render_state

console = Console()


def replay_session(session_id: str, speed: float | None = None) -> None:
    """Display a past session turn by turn.

    Args:
        session_id: The session identifier (filename without .jsonl).
        speed:      Real-time speed multiplier (1.0 = original pace).
                    If None, replays instantly.
    """
    turns = load_log(session_id)
    if not turns:
        console.print(f"[red]No session found: {session_id}[/red]")
        return

    console.rule(f"Replay: {session_id}")
    prev_ts: float | None = None

    for turn in turns:
        if speed is not None and prev_ts is not None:
            delay = (turn["ts"] - prev_ts) / speed
            time.sleep(max(0.0, delay))

        console.print(f"\n[bold cyan]Player:[/bold cyan] {turn.get('user_text', '')}")
        render_state(turn)
        if turn.get("oracle_response"):
            console.print(f"[magenta]Oracle:[/magenta] {turn['oracle_response']}")

        prev_ts = turn["ts"]

    console.rule("End of session")


def rerun_session(session_id: str) -> None:
    """Re-execute a past session through the current graph for regression testing.

    Each turn's user_text is fed back through the live Oracle graph and the new
    oracle_response is compared to the logged one.
    """
    from graph.graph import oracle_graph
    from graph.state import make_initial_state
    from graph.tools import bind_state, sync_state_from

    turns = load_log(session_id)
    if not turns:
        console.print(f"[red]No session found: {session_id}[/red]")
        return

    console.rule(f"Re-run: {session_id}")
    first = turns[0]
    difficulty = first.get("difficulty", "professional")
    state = make_initial_state(difficulty=difficulty)  # type: ignore[arg-type]

    for i, turn in enumerate(turns):
        user_text = turn.get("user_text", "")
        expected = turn.get("oracle_response", "")

        state["prev_candidate_count"] = len(state.get("candidates", []))  # type: ignore[assignment]
        state["messages"] = []  # type: ignore[assignment]
        state["user_text"] = user_text  # type: ignore[assignment]

        bind_state(state)
        result = oracle_graph.invoke(state)
        sync_state_from(state)

        actual = result.get("oracle_response", "")
        match = "✓" if actual == expected else "~"
        console.print(f"  [{i+1}] {match} {user_text!r}")

    console.rule("Re-run complete")
