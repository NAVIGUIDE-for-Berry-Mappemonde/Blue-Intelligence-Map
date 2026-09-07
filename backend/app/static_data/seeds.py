"""MasterSeeds Projets : 21 listings curés (priority 1) + fichier élargi (~861)."""
from __future__ import annotations

import json

from app.config import DATA_DIR

CURATED_SEEDS = [
    {"name": "The Ocean Foundation", "url": "https://oceanfdn.org/projects/", "country": "US", "priority": 1, "category": "Conservation & Research"},
    {"name": "Oceana", "url": "https://oceana.org/campaigns/", "country": "US", "priority": 1, "category": "Advocacy & Campaigns"},
    {"name": "Blue Marine Foundation", "url": "https://www.bluemarinefoundation.com/projects/", "country": "UK", "priority": 1, "category": "Conservation & Research"},
    {"name": "Fondation de la Mer", "url": "https://www.fondationdelamer.org/", "country": "FR", "priority": 1, "category": "Conservation & Research"},
    {"name": "Pure Ocean Foundation", "url": "https://www.pure-ocean.org/", "country": "FR", "priority": 1, "category": "Applied Research"},
    {"name": "Fondation CMA CGM", "url": "https://www.cmacgm-group.com/fr/fondation", "country": "FR", "priority": 1, "category": "Shipping & Ocean Protection"},
    {"name": "IFREMER", "url": "https://www.ifremer.fr/fr", "country": "FR", "priority": 1, "category": "Marine Science"},
    {"name": "Institut Océanographique Paul Ricard", "url": "https://www.institut-paul-ricard.org/", "country": "FR", "priority": 2, "category": "Marine Biology"},
    {"name": "SHOM", "url": "https://www.shom.fr/fr", "country": "FR", "priority": 2, "category": "Hydrography"},
    {"name": "CORDIS Europe", "url": "https://cordis.europa.eu/projects/en", "country": "EU", "priority": 2, "category": "EU Research"},
    {"name": "Prince Albert II Foundation", "url": "https://www.fpa2.org/en/initiatives", "country": "MC", "priority": 1, "category": "Mediterranean & MPA"},
    {"name": "Coral Reef Alliance", "url": "https://coral.org/en/where-we-work/", "country": "US", "priority": 2, "category": "Coral Reefs"},
    {"name": "Mission Blue", "url": "https://missionblue.org/hope-spots/", "country": "US", "priority": 2, "category": "Hope Spots"},
    {"name": "Seacology", "url": "https://www.seacology.org/projects/", "country": "US", "priority": 2, "category": "Island Conservation"},
    {"name": "Ocean Conservancy", "url": "https://oceanconservancy.org/programs/", "country": "US", "priority": 2, "category": "Conservation & Research"},
    {"name": "Pew Charitable Trusts", "url": "https://www.pewtrusts.org/en/projects", "country": "US", "priority": 2, "category": "Policy & Research"},
    {"name": "WWF Oceans", "url": "https://www.worldwildlife.org/initiatives/oceans", "country": "INT", "priority": 2, "category": "Conservation & Research"},
    {"name": "Packard Foundation", "url": "https://www.packard.org/what-we-fund/ocean/", "country": "US", "priority": 2, "category": "Philanthropy"},
    {"name": "Rare Fish Forever", "url": "https://rare.org/program/fish-forever/", "country": "US", "priority": 2, "category": "Sustainable Fisheries"},
    {"name": "Fauna & Flora Oceans", "url": "https://www.fauna-flora.org/environments/oceans/", "country": "UK", "priority": 2, "category": "Conservation & Research"},
    {"name": "Wildlife Conservation Society Marine", "url": "https://www.wcs.org/our-work/oceans", "country": "US", "priority": 2, "category": "Conservation & Research"},
]

TEST_SEED_COUNT = 3
MASTER_SEEDS_PATH = DATA_DIR / "master_seeds.json"


def load_master_seeds() -> list[dict]:
    """21 curés en tête si le fichier manque ; sinon le dump ~861."""
    if MASTER_SEEDS_PATH.exists():
        try:
            data = json.loads(MASTER_SEEDS_PATH.read_text(encoding="utf-8"))
            seeds = data.get("seeds") if isinstance(data, dict) else data
            if isinstance(seeds, list) and seeds:
                return seeds
        except Exception:
            pass
    return list(CURATED_SEEDS)


# Compat : les imports existants lisent MASTER_SEEDS (fichier s'il est là).
MASTER_SEEDS = load_master_seeds()

URL_PATTERNS = [
    "/project", "/campaign", "/initiative", "/hope-spot", "/where-we-work/",
    "/programs/", "/grants/", "/our-work/", "/program/", "/projets",
    "/projet", "/nos-actions", "/actions", "/missions", "/expeditions",
]

CRAWL_BLACKLIST = (
    "contact", "about", "a-propos", "privacy", "terms", "donate", "don", "blog",
    "news", "actualites", "team", "equipe", "login", "cart", "shop", "boutique",
    "event", "job", "recrutement", "press", "presse", "media", "faq",
    "mentions-legales", "cookies", "newsletter", "sitemap", "search", "tag",
)
