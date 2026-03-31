"""LangGraph StateGraph assembly.

The graph topology (do not change without updating test_triggers.py):

    llm ──[tool call]──▶ tools ──▶ route_after_tools
                                        ├── "identify"   ──▶ identify ──▶ END
                                        ├── "commentary" ──▶ commentary ──▶ END
                                        └── "llm"        ──▶ llm (loop)
     │
     └──[direct answer]──▶ respond ──▶ END
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from graph.nodes import (
    commentary_node,
    identify_node,
    llm_node,
    respond_node,
    route_after_llm,
    route_after_tools,
)
from graph.state import OracleState
from graph.tools import ALL_TOOLS


def build_graph():
    """Assemble and compile the Oracle StateGraph.

    Returns:
        A compiled LangGraph runnable.
    """
    builder = StateGraph(OracleState)

    # Nodes
    builder.add_node("llm", llm_node)
    builder.add_node("tools", ToolNode(ALL_TOOLS))
    builder.add_node("identify", identify_node)
    builder.add_node("commentary", commentary_node)
    builder.add_node("respond", respond_node)

    # Entry
    builder.set_entry_point("llm")

    # Conditional edge: after LLM — either call tools or produce a direct response
    builder.add_conditional_edges(
        "llm",
        route_after_llm,
        {"tools": "tools", "respond": "respond"},
    )

    # Conditional edge: after tools — identify / commentary / loop
    builder.add_conditional_edges(
        "tools",
        route_after_tools,
        {"identify": "identify", "commentary": "commentary", "llm": "llm"},
    )

    # Terminal nodes
    builder.add_edge("identify", END)
    builder.add_edge("commentary", END)
    builder.add_edge("respond", END)

    return builder.compile()


# Module-level compiled graph (imported by main.py)
oracle_graph = build_graph()
