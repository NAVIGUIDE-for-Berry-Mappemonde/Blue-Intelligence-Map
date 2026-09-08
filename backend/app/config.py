"""
app.config — Chemins, variables d'environnement et réglages par défaut.

Chargé en premier par tous les modules : le .env du backend est lu ici,
avant toute lecture de os.environ (Mongo, clés API…).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

DATA_DIR = BACKEND_DIR / "data"
MODELS_DIR = BACKEND_DIR / "models"
ROUTE_FILE = DATA_DIR / "route.geojson"

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

# Complétions : NVIDIA NIM si NVIDIA_API_KEY (Pro → Muse → gpt-oss / Kimi).
# OpenRouter reste pour la recherche web (:online) et le fallback.
# load_dotenv n'écrase pas un MONGO_URL déjà présent dans le process.
DEFAULT_SETTINGS = {
    "_id": "global",
    "nvidia_api_key": "",
    "llm_provider": "auto",
    "openrouter_api_key": "",
    "tinyfish_api_key": "",
    "serper_api_key": "",
    "tinyfish_agents": 2,
    "extract_concurrency": 6,
    "max_coast_km": 50,
    "max_inland_km": 15.0,
    "min_marine_score": 0.5,
    "gatekeeper_accept": 0.85,
    "gatekeeper_reject": 0.12,
    "allow_tinyfish_agent": True,
    "test_max_urls_per_seed": 6,
    "full_max_urls_per_seed": 20,
    "min_zoom": 2,
    "max_markers": 1000,
    "follow_the_money": True,
    "max_partner_orgs": 5,
    "saturation_limit": 50,
    "rescan_after_days": 7,
    "marina_search_radius_nm": 10.0,
    "marina_batch_concurrency": 2,
    "openrouter_min_credits_usd": 0.5,
    "enrich_stale_days": 365,
    "anthropic_api_key": "",
    "claude_budget_usd": 0.0,
}
