"""Seeds de découverte Projets.

Les 21 listings curés donnent des URLs de listing fiables. `MASTER_SEEDS`
charge l'union v1 (~861 financeurs) depuis `data/master_seeds.json` (CDC C5).
Sans fichier, repli = les 21 curés. Tous les financeurs avec URL sont à égalité.
"""

CURATED_SEEDS = [
    {"name": "The Ocean Foundation", "url": "https://oceanfdn.org/projects/", "country": "US", "category": "Conservation & Research"},
    {"name": "Oceana", "url": "https://oceana.org/campaigns/", "country": "US", "category": "Advocacy & Campaigns"},
    {"name": "Blue Marine Foundation", "url": "https://www.bluemarinefoundation.com/projects/", "country": "UK", "category": "Conservation & Research"},
    {"name": "Fondation de la Mer", "url": "https://www.fondationdelamer.org/", "country": "FR", "category": "Conservation & Research"},
    {"name": "Pure Ocean Foundation", "url": "https://www.pure-ocean.org/", "country": "FR", "category": "Applied Research"},
    {"name": "Fondation CMA CGM", "url": "https://www.cmacgm-group.com/fr/fondation", "country": "FR", "category": "Shipping & Ocean Protection", "aliases": ["CMA CGM Group"]},
    {"name": "IFREMER", "url": "https://www.ifremer.fr/fr", "country": "FR", "category": "Marine Science"},
    {"name": "Institut Océanographique Paul Ricard", "url": "https://www.institut-paul-ricard.org/", "country": "FR", "category": "Marine Biology"},
    {"name": "SHOM", "url": "https://www.shom.fr/fr", "country": "FR", "category": "Hydrography"},
    {"name": "CORDIS Europe", "url": "https://cordis.europa.eu/projects/en", "country": "EU", "category": "EU Research"},
    {"name": "Prince Albert II Foundation", "url": "https://www.fpa2.org/en/initiatives", "country": "MC", "category": "Mediterranean & MPA"},
    {"name": "Coral Reef Alliance", "url": "https://coral.org/en/where-we-work/", "country": "US", "category": "Coral Reefs"},
    {"name": "Mission Blue", "url": "https://missionblue.org/hope-spots/", "country": "US", "category": "Hope Spots"},
    {"name": "Seacology", "url": "https://www.seacology.org/projects/", "country": "US", "category": "Island Conservation"},
    {"name": "Ocean Conservancy", "url": "https://oceanconservancy.org/programs/", "country": "US", "category": "Conservation & Research"},
    {"name": "Pew Charitable Trusts", "url": "https://www.pewtrusts.org/en/projects", "country": "US", "category": "Policy & Research", "aliases": ["The Pew Charitable Trusts", "The Pew Charitable Trust"]},
    {"name": "WWF Oceans", "url": "https://www.worldwildlife.org/initiatives/oceans", "country": "INT", "category": "Conservation & Research", "aliases": ["WWF"]},
    {"name": "Packard Foundation", "url": "https://www.packard.org/what-we-fund/ocean/", "country": "US", "category": "Philanthropy"},
    {"name": "Rare Fish Forever", "url": "https://rare.org/program/fish-forever/", "country": "US", "category": "Sustainable Fisheries", "aliases": ["Rare"]},
    {"name": "Fauna & Flora Oceans", "url": "https://www.fauna-flora.org/environments/oceans/", "country": "UK", "category": "Conservation & Research", "aliases": ["Fauna & Flora"]},
    {"name": "Wildlife Conservation Society Marine", "url": "https://www.wcs.org/our-work/oceans", "country": "US", "category": "Conservation & Research", "aliases": ["WCS"]},
]

TEST_SEED_COUNT = 3

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

# Import tardif : master_seeds.py importe CURATED_SEEDS depuis ce module.
from app.services.master_seeds import load_master_seeds  # noqa: E402

MASTER_SEEDS = load_master_seeds()
