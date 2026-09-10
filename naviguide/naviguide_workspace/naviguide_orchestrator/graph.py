"""
NAVIGUIDE Orchestrator — LangGraph StateGraph Definition
build_orchestrator() compiles the full multi-agent orchestration pipeline.
"""

from langgraph.graph import StateGraph, END

from .state import OrchestratorState
from .nodes import (
    validate_expedition_request_node,
    run_route_intelligence_node,
    run_risk_assessment_node,
    llm_expedition_briefing_node,
    generate_expedition_plan_node,
)


def _after_validate(state: OrchestratorState) -> str:
    """Abort on validation error."""
    return "error" if state.get("status") == "error" else "ok"


def _after_agent1(state: OrchestratorState) -> str:
    """Abort if Agent 1 failed completely."""
    return "failed" if state.get("status") == "agent1_failed" else "ok"


def build_orchestrator():
    """
    Compile and return the Multi-Agent Orchestrator LangGraph.

    Flow:
      validate_expedition_request
        → run_route_intelligence (Agent 1)
        → run_risk_assessment (Agent 3)
        → llm_expedition_briefing
        → generate_expedition_plan
        → END
    """
    graph = StateGraph(OrchestratorState)

    # Register nodes
    graph.add_node("validate",       validate_expedition_request_node)
    graph.add_node("agent1",         run_route_intelligence_node)
    graph.add_node("agent3",         run_risk_assessment_node)
    graph.add_node("briefing",       llm_expedition_briefing_node)
    graph.add_node("generate_plan",  generate_expedition_plan_node)

    # Entry point
    graph.set_entry_point("validate")

    # Conditional: abort on validation error
    graph.add_conditional_edges(
        "validate",
        _after_validate,
        {"error": END, "ok": "agent1"},
    )

    # Conditional: abort if Agent 1 completely failed
    graph.add_conditional_edges(
        "agent1",
        _after_agent1,
        {"failed": END, "ok": "agent3"},
    )

    # Linear continuation
    graph.add_edge("agent3",        "briefing")
    graph.add_edge("briefing",      "generate_plan")
    graph.add_edge("generate_plan", END)

    return graph.compile()
