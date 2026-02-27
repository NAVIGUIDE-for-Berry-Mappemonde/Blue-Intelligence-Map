"""
NAVIGUIDE — Mock Orchestrator
Standalone FastAPI service that returns pre-computed, realistic
Berry-Mappemonde circumnavigation expedition data.

Replaces the full LangGraph orchestrator while source files are
being reconstructed. Serves on port 3008 (mapped to
https://y1dxs0s0.run.complete.dev).
"""

import os
import logging
import json
from pathlib import Path
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(
    "/mnt/efs/spaces/ef014a98-8a1c-4b16-8e06-5d2c5b364d08"
    "/3838ab1e-0224-400b-b357-cd566e2f7d0b/logs"
)
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_DIR / "mock_orchestrator.log"),
        logging.StreamHandler(),
    ],
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
)
log = logging.getLogger("mock_orchestrator")

# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(
    title="NAVIGUIDE — Mock Orchestrator",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pre-computed Berry-Mappemonde expedition data ─────────────────────────────

EXPEDITION_PLAN = {
    "voyage_statistics": {
        "total_distance_nm": 28_842,
        "total_segments": 17,
        "expedition_risk_level": "HIGH",
        "overall_expedition_risk": 0.71,
        "anti_shipping_avg": 0.18,
        "high_risk_count": 5,
        "critical_count": 2,
    },

    "critical_alerts": [
        {
            "waypoint": "Europa (TAAF)",
            "risk_level": "CRITICAL",
            "dominant_risk": "cyclone_score",
            "scores": {
                "weather_score": 0.82,
                "cyclone_score": 0.91,
                "piracy_score": 0.22,
                "medical_score": 0.74,
            },
        },
        {
            "waypoint": "Dzaoudzi (Mayotte)",
            "risk_level": "CRITICAL",
            "dominant_risk": "medical_score",
            "scores": {
                "weather_score": 0.55,
                "cyclone_score": 0.78,
                "piracy_score": 0.38,
                "medical_score": 0.88,
            },
        },
        {
            "waypoint": "Tromelin (TAAF)",
            "risk_level": "HIGH",
            "dominant_risk": "weather_score",
            "scores": {
                "weather_score": 0.83,
                "cyclone_score": 0.72,
                "piracy_score": 0.12,
                "medical_score": 0.65,
            },
        },
        {
            "waypoint": "Cayenne (Guyane française)",
            "risk_level": "HIGH",
            "dominant_risk": "medical_score",
            "scores": {
                "weather_score": 0.41,
                "cyclone_score": 0.28,
                "piracy_score": 0.31,
                "medical_score": 0.78,
            },
        },
        {
            "waypoint": "Mata-Utu (Wallis-et-Futuna)",
            "risk_level": "HIGH",
            "dominant_risk": "weather_score",
            "scores": {
                "weather_score": 0.74,
                "cyclone_score": 0.66,
                "piracy_score": 0.04,
                "medical_score": 0.72,
            },
        },
        {
            "waypoint": "Halifax (Nouvelle-Écosse)",
            "risk_level": "HIGH",
            "dominant_risk": "weather_score",
            "scores": {
                "weather_score": 0.77,
                "cyclone_score": 0.42,
                "piracy_score": 0.02,
                "medical_score": 0.18,
            },
        },
        {
            "waypoint": "Fort-de-France (Martinique)",
            "risk_level": "MEDIUM",
            "dominant_risk": "cyclone_score",
            "scores": {
                "weather_score": 0.38,
                "cyclone_score": 0.61,
                "piracy_score": 0.08,
                "medical_score": 0.29,
            },
        },
        {
            "waypoint": "Papeete (Polynésie française)",
            "risk_level": "MEDIUM",
            "dominant_risk": "cyclone_score",
            "scores": {
                "weather_score": 0.44,
                "cyclone_score": 0.58,
                "piracy_score": 0.03,
                "medical_score": 0.35,
            },
        },
    ],

    "executive_briefing": (
        "BRIEFING EXPÉDITION BERRY-MAPPEMONDE — TOUR DU MONDE DES TERRITOIRES FRANÇAIS\n\n"
        "Commandant, voici l'évaluation stratégique de votre circumnavigation de 28 842 milles "
        "nautiques à travers les territoires français d'outre-mer.\n\n"
        "⚠️  ALERTES CRITIQUES (2 escales) :\n"
        "• Europa (TAAF) : Risque cyclonique CRITIQUE (0,91). Cette île isolée du canal du "
        "Mozambique est exposée aux cyclones tropicaux de novembre à avril. Planifier l'escale "
        "en dehors de la saison cyclonique (mai–octobre recommandé). Infrastructure médicale "
        "quasi-inexistante — évacuation hélitreuillée uniquement.\n"
        "• Dzaoudzi (Mayotte) : Risque médical CRITIQUE (0,88). Capacités hospitalières "
        "limitées, dengue et paludisme endémiques. Vaccinations obligatoires et prophylaxie "
        "antipaludéenne indispensables avant l'escale.\n\n"
        "🌪️  ZONES MÉTÉO HAUTE VIGILANCE :\n"
        "• Tromelin : Mer forte à très forte fréquente — mer de 4 à 6 m possible. Ancrage "
        "précaire, escale à réserver aux conditions météo favorables uniquement.\n"
        "• Halifax : Brouillard dense et dépressions atlantiques rapides d'octobre à mars. "
        "Prévoir équipement radar et AIS actif.\n"
        "• Wallis-et-Futuna : Cyclones du Pacifique Sud (novembre–avril), récifs frangeants "
        "à l'approche — navigation côtière nocturne déconseillée.\n\n"
        "🗺️  RECOMMANDATIONS STRATÉGIQUES :\n"
        "1. Départ optimal depuis La Rochelle : mai–juin pour traversée atlantique en alizés.\n"
        "2. Traversée transpacifique (Cayenne → Papeete) : 4 200 nm — prévoir ravitaillement "
        "carburant aux Marquises si tirant d'eau le permet.\n"
        "3. Retour Cap de Bonne-Espérance : contourner par le sud (latitude 42°S recommandée) "
        "pour éviter les zones de pêche intensive et les routes commerciales.\n"
        "4. Passage Canal de Mozambique : naviguer côte est malgache pour éviter les hauts-fonds "
        "du côté mozambicain.\n\n"
        "✅  ESCALES SÛRES : La Rochelle, Ajaccio, Canaries, Guadeloupe, Saint-Barthélemy, "
        "Saint-Martin, Saint-Pierre-et-Miquelon, Nouméa, La Réunion présentent toutes un "
        "niveau de risque FAIBLE à MOYEN avec infrastructures portuaires et médicales adéquates.\n\n"
        "Bonne route, Commandant. NAVIGUIDE surveille votre expédition."
    ),

    "full_route_intelligence": {
        "status": "complete",
        "agent": "naviguide_agent1",
        "segments": [
            {"from": "La Rochelle",                             "to": "Ajaccio (Corse)",                         "distance_nm": 897,  "anti_shipping": 0.09},
            {"from": "Ajaccio (Corse)",                         "to": "Îles Canaries",                           "distance_nm": 1_423, "anti_shipping": 0.07},
            {"from": "Îles Canaries",                           "to": "Fort-de-France (Martinique)",             "distance_nm": 2_714, "anti_shipping": 0.04},
            {"from": "Fort-de-France (Martinique)",             "to": "Pointe-à-Pitre (Guadeloupe)",             "distance_nm": 116,  "anti_shipping": 0.06},
            {"from": "Pointe-à-Pitre (Guadeloupe)",             "to": "Gustavia (Saint-Barthélemy)",             "distance_nm": 142,  "anti_shipping": 0.05},
            {"from": "Gustavia (Saint-Barthélemy)",             "to": "Marigot (Saint-Martin)",                  "distance_nm": 18,   "anti_shipping": 0.05},
            {"from": "Marigot (Saint-Martin)",                  "to": "Halifax (Nouvelle-Écosse)",               "distance_nm": 1_751, "anti_shipping": 0.11},
            {"from": "Halifax (Nouvelle-Écosse)",               "to": "Saint-Pierre (Saint-Pierre-et-Miquelon)", "distance_nm": 495,  "anti_shipping": 0.08},
            {"from": "Saint-Pierre (Saint-Pierre-et-Miquelon)", "to": "Cayenne (Guyane française)",              "distance_nm": 2_632, "anti_shipping": 0.12},
            {"from": "Cayenne (Guyane française)",              "to": "Papeete (Polynésie française)",           "distance_nm": 4_201, "anti_shipping": 0.03},
            {"from": "Papeete (Polynésie française)",           "to": "Mata-Utu (Wallis-et-Futuna)",             "distance_nm": 1_447, "anti_shipping": 0.02},
            {"from": "Mata-Utu (Wallis-et-Futuna)",             "to": "Nouméa (Nouvelle-Calédonie)",             "distance_nm": 1_088, "anti_shipping": 0.06},
            {"from": "Nouméa (Nouvelle-Calédonie)",             "to": "Dzaoudzi (Mayotte)",                      "distance_nm": 3_918, "anti_shipping": 0.14},
            {"from": "Dzaoudzi (Mayotte)",                      "to": "Tromelin (TAAF)",                         "distance_nm": 1_072, "anti_shipping": 0.09},
            {"from": "Tromelin (TAAF)",                         "to": "Saint-Gilles (La Réunion)",               "distance_nm": 443,  "anti_shipping": 0.08},
            {"from": "Saint-Gilles (La Réunion)",               "to": "Europa (TAAF)",                           "distance_nm": 1_156, "anti_shipping": 0.16},
            {"from": "Europa (TAAF)",                           "to": "La Rochelle (retour)",                    "distance_nm": 7_329, "anti_shipping": 0.21},
        ],
    },

    "full_risk_assessment": {
        "status": "complete",
        "agent": "naviguide_agent3",
        "methodology": "Composite risk score: 40% weather + 25% cyclone + 20% piracy + 15% medical",
        "waypoints_assessed": 18,
    },
}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
def health():
    return {
        "service":   "NAVIGUIDE Mock Orchestrator",
        "version":   "1.0.0",
        "status":    "operational",
        "note":      "Pre-computed Berry-Mappemonde data (LangGraph pipeline offline)",
    }


@app.post("/api/v1/expedition/plan/berry-mappemonde")
async def plan_berry_mappemonde(departure_month: int = Query(None, ge=1, le=12)):
    """
    Returns pre-computed Berry-Mappemonde circumnavigation expedition plan.
    departure_month (1-12) can be passed but is ignored in mock mode.
    """
    log.info(f"Berry-Mappemonde plan requested (mock). departure_month={departure_month}")
    return {
        "status":          "complete",
        "expedition_plan": EXPEDITION_PLAN,
        "errors":          [],
        "source":          "mock",
    }


@app.post("/api/v1/expedition/plan")
async def plan_expedition():
    """Custom expedition plan — returns mock Berry-Mappemonde data as placeholder."""
    log.info("Custom expedition plan requested (mock — returning Berry-Mappemonde data)")
    return {
        "status":          "complete",
        "expedition_plan": EXPEDITION_PLAN,
        "errors":          ["Mock mode: custom waypoints not yet supported"],
        "source":          "mock",
    }


@app.get("/api/v1/expedition/status")
def get_agent_status():
    return {
        "orchestrator":               "mock",
        "agent1_route_intelligence":  "mock",
        "agent3_risk_assessment":     "mock",
        "integration_mode":           "pre_computed",
    }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", 3008))
    log.info(f"Starting NAVIGUIDE Mock Orchestrator on port {port}")
    uvicorn.run("mock_orchestrator:app", host="0.0.0.0", port=port, reload=False)
