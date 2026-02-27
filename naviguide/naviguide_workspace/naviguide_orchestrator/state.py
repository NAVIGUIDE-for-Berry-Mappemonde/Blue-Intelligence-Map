"""
NAVIGUIDE Orchestrator — LangGraph State Definition
"""

from typing import Any, Dict, List, Optional, TypedDict


class OrchestratorState(TypedDict, total=False):
    """State flowing through the multi-agent Orchestrator graph."""

    # Input
    waypoints:             List[Dict[str, Any]]
    vessel_specs:          Dict[str, Any]
    constraints:           Dict[str, Any]

    # Agent 1 outputs
    agent1_status:         str
    agent1_errors:         List[str]
    route_plan:            Dict[str, Any]         # GeoJSON FeatureCollection
    anti_shipping_avg:     float

    # Agent 3 outputs
    agent3_status:         str
    agent3_errors:         List[str]
    risk_report:           Dict[str, Any]
    expedition_risk_level: str

    # Final output
    expedition_plan:       Dict[str, Any]         # merged digital twin
    executive_briefing:    str

    # Execution control
    messages:              List[Any]
    errors:                List[str]
    status:                str                    # init / running_a1 / running_a3 / briefing / complete / error
    chat_id:               Optional[str]
    access_token:          Optional[str]
