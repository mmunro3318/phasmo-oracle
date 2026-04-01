"""StateGraph assembly — Sprint 2 Oracle agent graph.

Topology (Sprint 2):
    parse_intent ──[match]──▶ execute_tool ──▶ route_after_tools
         │                                        ├──[identify]──▶ identify ──▶ narrate ──▶ END
         │                                        ├──[phase_shift]──▶ phase_shift ──▶ narrate ──▶ END
         │                                        ├──[comment]──▶ commentary ──▶ END
         │                                        └──[normal]──▶ narrate ──▶ END
         └──[fallback]──▶ llm_classify ──▶ execute_tool ──▶ route_after_tools ──▶ ...

~85% of inputs are handled by the deterministic parser (instant, no LLM).
The LLM is called for: narrator (persona response), ambiguous input classification,
and commentary when candidates narrow.
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
    route_after_tools,
    identify_node,
    phase_shift_node,
    commentary_node,
)


def build_graph():
    builder = StateGraph(OracleState)

    # Nodes
    builder.add_node("parse_intent", parse_intent_node)
    builder.add_node("llm_classify", llm_classify_node)
    builder.add_node("execute_tool", execute_tool_node)
    builder.add_node("narrate", narrate_node)
    builder.add_node("identify", identify_node)
    builder.add_node("phase_shift", phase_shift_node)
    builder.add_node("commentary", commentary_node)

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

    # After tool execution: conditional routing
    builder.add_conditional_edges(
        "execute_tool",
        route_after_tools,
        {
            "identify": "identify",
            "phase_shift": "phase_shift",
            "comment": "commentary",
            "normal": "narrate",
        },
    )

    # identify and phase_shift feed into narrator for personality
    builder.add_edge("identify", "narrate")
    builder.add_edge("phase_shift", "narrate")

    # commentary generates its own response — goes straight to END
    builder.add_edge("commentary", END)

    # Narrator is terminal
    builder.add_edge("narrate", END)

    return builder.compile()


# Module-level singleton
oracle_graph = build_graph()
