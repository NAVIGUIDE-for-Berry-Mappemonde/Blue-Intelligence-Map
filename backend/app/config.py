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

# Tous les appels IA passent par OpenRouter (clé UI prioritaire, sinon
# OPENROUTER_API_KEY ; modèle via OPENROUTER_MODEL, défaut openai/gpt-4o-mini).
DEFAULT_SETTINGS = {
    "_id": "global",
    "openrouter_api_key": "",
    "tinyfish_api_key": "",
    "tinyfish_agents": 2,
    "extract_concurrency": 6,
    "max_coast_km": 50,
    "min_marine_score": 0.5,
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
    # Corroboration Noonsite (compte gratuit 3 pays/mois — pas un Gold Dataset)
    "noonsite_enabled": False,
    "noonsite_watchlist": [],
    "noonsite_profile_id": "",
    "noonsite_credential_item_ids": [],
    "noonsite_use_vault": True,
    "noonsite_use_profile": True,
    "noonsite_browser_profile": "stealth",
    "noonsite_use_proxy": False,
}
