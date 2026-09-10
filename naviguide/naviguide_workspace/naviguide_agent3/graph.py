"""
NAVIGUIDE Agent 3 — LangGraph StateGraph Definition
build_risk_assessment_agent() compiles the full risk pipeline graph.
"""

from langgraph.graph import StateGraph, END

from .state import RiskState
from .nodes import (
    parse_risk_request_node,
    assess_weather_risks_node,
    assess_piracy_zones_node,
    assess_medical_safety_node,
    assess_cyclone_risks_node,
    compute_risk_scores_node,
    llm_risk_analyst_node,
    generate_risk_report_node,
)


def _risk_after_parse(state: RiskState) -> str:
    """Conditional edge after parse_risk_request: stop on validation error."""
    return "error" if state.get("status") == "error" else "ok"


def build_risk_assessment_agent():
    """
    Compile and return the Risk Assessment LangGraph.

    Flow:
      parse_risk_request
        → assess_weather_risks → assess_piracy_zones
        → assess_medical_safety → assess_cyclone_risks
        → compute_risk_scores → llm_risk_analyst
        → generate_risk_report → END
    """
    graph = StateGraph(RiskState)

    # Register nodes
    graph.add_node("parse_risk_request",    parse_risk_request_node)
    graph.add_node("assess_weather_risks",  assess_weather_risks_node)
    graph.add_node("assess_piracy_zones",   assess_piracy_zones_node)
    graph.add_node("assess_medical_safety", assess_medical_safety_node)
    graph.add_node("assess_cyclone_risks",  assess_cyclone_risks_node)
    graph.add_node("compute_risk_scores",   compute_risk_scores_node)
    graph.add_node("llm_risk_analyst",      llm_risk_analyst_node)
    graph.add_node("generate_risk_report",  generate_risk_report_node)

    # Entry point
    graph.set_entry_point("parse_risk_request")

    # Conditional: abort on parse error
    graph.add_conditional_edges(
        "parse_risk_request",
        _risk_after_parse,
        {"error": END, "ok": "assess_weather_risks"},
    )

    # Linear pipeline
    graph.add_edge("assess_weather_risks",  "assess_piracy_zones")
    graph.add_edge("assess_piracy_zones",   "assess_medical_safety")
    graph.add_edge("assess_medical_safety", "assess_cyclone_risks")
    graph.add_edge("assess_cyclone_risks",  "compute_risk_scores")
    graph.add_edge("compute_risk_scores",   "llm_risk_analyst")
    graph.add_edge("llm_risk_analyst",      "generate_risk_report")
    graph.add_edge("generate_risk_report",  END)

    return graph.compile()
