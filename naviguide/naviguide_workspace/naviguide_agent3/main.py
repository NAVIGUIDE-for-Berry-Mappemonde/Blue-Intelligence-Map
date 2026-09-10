"""
NAVIGUIDE — Agent 3: Risk Assessment Agent
FastAPI entry point

Endpoints
─────────
GET  /                                  Health check
POST /api/v1/agent/risk                 Custom waypoint risk assessment
POST /api/v1/agent/risk/berry-mappemonde  Pre-configured expedition assessment
GET  /api/v1/agent/risk/graph           LangGraph diagram (ASCII)
GET  /api/v1/agent/risk/zones           All risk zone databases (piracy, cyclone, weather)
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .graph       import build_risk_assessment_agent
from .state       import RiskState
from .geojson_data import BERRY_MAPPEMONDE_WAYPOINTS
from .risk_engine import PIRACY_ZONES, CYCLONE_BASINS, WEATHER_WINDOWS

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_DIR = Path(
    "/mnt/efs/spaces/ef014a98-8a1c-4b16-8e06-5d2c5b364d08"
    "/3838ab1e-0224-400b-b357-cd566e2f7d0b/logs"
)
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_DIR / "agent3.log"),
        logging.StreamHandler(),
    ],
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
)
log = logging.getLogger("agent3")

# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="NAVIGUIDE — Risk Assessment Agent",
    description=(
        "LangGraph-powered maritime risk agent covering weather windows, "
        "piracy zones, medical access, and cyclone exposure."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compile agent graph once at startup
agent_graph = build_risk_assessment_agent()
log.info("Risk Assessment Agent graph compiled successfully.")


# ── Pydantic models ───────────────────────────────────────────────────────────

class WaypointIn(BaseModel):
    name: str
    lat:  float
    lon:  float


class RiskRequestIn(BaseModel):
    waypoints:       List[WaypointIn]
    constraints:     Dict[str, Any] = {}   # e.g. {"departure_month": 11}
    route_segments:  List[Dict[str, Any]] = []  # optional — from Agent 1


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_initial_state(waypoints, constraints, route_segments) -> RiskState:
    return {
        "waypoints":            waypoints,
        "route_segments":       route_segments,
        "weather_assessments":  [],
        "piracy_assessments":   [],
        "medical_assessments":  [],
        "cyclone_assessments":  [],
        "risk_scores":          [],
        "risk_report":          {},
        "messages":             [],
        "errors":               [],
        "status":               "init",
        "chat_id":              None,
        "access_token":         None,
        "llm_risk_summary":     "",
        "constraints":          constraints,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
def health():
    return {
        "agent":        "Risk Assessment Agent",
        "version":      "1.0.0",
        "status":       "operational",
        "framework":    "LangGraph",
        "capabilities": [
            "weather_window_analysis",
            "piracy_zone_detection",
            "medical_evacuation_assessment",
            "cyclone_hurricane_exposure",
            "composite_risk_scoring",
            "llm_executive_briefing",
        ],
    }


@app.post("/api/v1/agent/risk")
async def assess_custom_risk(request: RiskRequestIn):
    """
    Run the Risk Assessment Agent for a custom set of waypoints.
    Optionally accepts route_segments from Agent 1 for enriched context.
    """
    log.info(f"Risk request: {len(request.waypoints)} waypoints")

    initial_state = _build_initial_state(
        waypoints       = [wp.dict() for wp in request.waypoints],
        constraints     = request.constraints,
        route_segments  = request.route_segments,
    )

    try:
        result = agent_graph.invoke(initial_state)
        log.info(f"Risk assessed: status={result['status']}")
        return {
            "status":      result["status"],
            "risk_report": result["risk_report"],
            "errors":      result.get("errors", []),
            "summary": {
                "waypoints_assessed":      len(result.get("risk_scores", [])),
                "expedition_risk_level":   result["risk_report"].get("metadata", {}).get("expedition_risk_level"),
                "overall_score":           result["risk_report"].get("metadata", {}).get("overall_expedition_risk"),
                "critical_alerts":         result["risk_report"].get("critical_alerts", []),
                "executive_briefing":      result.get("llm_risk_summary", ""),
            },
        }
    except Exception as exc:
        log.error(f"Agent execution error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/v1/agent/risk/berry-mappemonde")
async def assess_berry_mappemonde(departure_month: int = None):
    """
    Pre-configured Berry-Mappemonde expedition risk assessment.
    Optionally pass departure_month (1-12) to adjust seasonal risk.
    """
    log.info(f"Berry-Mappemonde risk assessment requested. departure_month={departure_month}")

    constraints = {}
    if departure_month:
        constraints["departure_month"] = departure_month

    initial_state = _build_initial_state(
        waypoints      = BERRY_MAPPEMONDE_WAYPOINTS,
        constraints    = constraints,
        route_segments = [],
    )

    try:
        result = agent_graph.invoke(initial_state)
        log.info(f"Berry-Mappemonde risk assessed: status={result['status']}")
        return {
            "status":      result["status"],
            "risk_report": result["risk_report"],
            "errors":      result.get("errors", []),
        }
    except Exception as exc:
        log.error(f"Berry-Mappemonde risk error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v1/agent/risk/zones")
def get_risk_zones():
    """Return all loaded risk zone databases for front-end map overlay."""
    return {
        "piracy_zones":   PIRACY_ZONES,
        "cyclone_basins": CYCLONE_BASINS,
        "weather_windows": [
            {k: v for k, v in w.items() if k != "score_seasonal"}
            for w in WEATHER_WINDOWS
        ],
    }


@app.get("/api/v1/agent/risk/graph")
def get_graph_diagram():
    """Return an ASCII representation of the LangGraph workflow."""
    diagram = """
    NAVIGUIDE — Risk Assessment Agent (LangGraph)
    ═══════════════════════════════════════════════════

    [START]
       │
       ▼
    ┌─────────────────────────────────┐
    │  parse_risk_request             │  Validate waypoint coordinates
    └──────────────┬──────────────────┘
                   │ error ──────────────────────────► [END]
                   ▼
    ┌─────────────────────────────────┐
    │  assess_weather_risks           │  Seasonal window quality (ECMWF/Copernicus)
    └──────────────┬──────────────────┘
                   ▼
    ┌─────────────────────────────────┐
    │  assess_piracy_zones            │  IMB/MDAT hotspot proximity check
    └──────────────┬──────────────────┘
                   ▼
    ┌─────────────────────────────────┐
    │  assess_medical_safety          │  Hospital access · medevac hours · vaccinations
    └──────────────┬──────────────────┘
                   ▼
    ┌─────────────────────────────────┐
    │  assess_cyclone_risks           │  NHC/RSMC basin + seasonal timing
    └──────────────┬──────────────────┘
                   ▼
    ┌─────────────────────────────────┐
    │  compute_risk_scores            │  Weighted composite (weather 25% | piracy 30%
    │                                 │  | medical 20% | cyclone 25%)
    └──────────────┬──────────────────┘
                   ▼
    ┌─────────────────────────────────┐
    │  llm_risk_analyst               │  Deploy AI (GPT-4o) executive briefing
    └──────────────┬──────────────────┘
                   ▼
    ┌─────────────────────────────────┐
    │  generate_risk_report           │  Final structured report + critical alerts
    └──────────────┬──────────────────┘
                   ▼
                [END]
    """
    return {"diagram": diagram}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8003))
    uvicorn.run("naviguide_agent3.main:app", host="0.0.0.0", port=port, reload=False)
