"""StateGraph assembly — two-stage Oracle agent graph.

Topology:
    parse_intent ──[deterministic match]──▶ execute_tool ──▶ narrate ──▶ END
         │
         └──[llm_fallback]──▶ llm_classify ──▶ execute_tool ──▶ narrate ──▶ END

~85% of inputs are handled by the deterministic parser (instant, no LLM).
The LLM is only called for the narrator (persona response) and ambiguous
inputs that the parser can't classify.
"""
from __future__ import annotations

from langgraph.graph import StateGraph, START, END
from .state import OracleState
from .nodes import (
    parse_intent_node,
    llm_classify_node,
    execute_tool_node,
    narrate_node,
    route_after_parse,
)


def build_graph():
    builder = StateGraph(OracleState)

    # Nodes
    builder.add_node("parse_intent", parse_intent_node)
    builder.add_node("llm_classify", llm_classify_node)
    builder.add_node("execute_tool", execute_tool_node)
    builder.add_node("narrate", narrate_node)

    # Entry: always start with deterministic parsing
    builder.add_edge(START, "parse_intent")

    # Route: deterministic match → execute, fallback → LLM classify
    builder.add_conditional_edges(
        "parse_intent",
        route_after_parse,
        {"execute_tool": "execute_tool", "llm_classify": "llm_classify"},
    )

    # LLM classifier feeds into tool execution
    builder.add_edge("llm_classify", "execute_tool")

    # Tool execution feeds into narrator
    builder.add_edge("execute_tool", "narrate")

    # Narrator is terminal
    builder.add_edge("narrate", END)

    return builder.compile()


# Module-level singleton
oracle_graph = build_graph()
