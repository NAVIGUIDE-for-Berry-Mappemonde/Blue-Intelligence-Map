"""
NAVIGUIDE Agent 3 — LangGraph State Definition
"""

from typing import Any, Dict, List, Optional, TypedDict


class RiskState(TypedDict, total=False):
    """State flowing through the Risk Assessment Agent graph."""

    # Input
    waypoints:           List[Dict[str, Any]]   # [{name, lat, lon}]
    route_segments:      List[Dict[str, Any]]   # optional Agent 1 output
    constraints:         Dict[str, Any]          # e.g. departure_month

    # Intermediate — assessment arrays
    weather_assessments: List[Dict[str, Any]]
    piracy_assessments:  List[Dict[str, Any]]
    medical_assessments: List[Dict[str, Any]]
    cyclone_assessments: List[Dict[str, Any]]
    risk_scores:         List[Dict[str, Any]]   # composite per-waypoint scores

    # LLM briefing
    llm_risk_summary:    str

    # Output
    risk_report:         Dict[str, Any]          # final structured report

    # Execution control
    messages:            List[Any]               # LangChain message history
    errors:              List[str]
    status:              str                     # init / processing / analysed / complete / error
    chat_id:             Optional[str]
    access_token:        Optional[str]
