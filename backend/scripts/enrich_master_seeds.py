#!/usr/bin/env python3
"""Audit + enrichissement hors Complet de backend/data/master_seeds.json.

Ne touche pas `projects`. Classe homes / listes / noms, puis n'envoie en
file Complet que les graines crawlables.

    python3 scripts/enrich_master_seeds.py --from-geojson ../seed/projects.geojson
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.master_seeds import (  # noqa: E402
    MASTER_SEEDS_PATH, fetch_production_projects, projects_from_geojson,
    seeds_for_run,
)
from app.services.seed_catalog import (  # noqa: E402
    HOME_REVIEW_PATH, LISTING_JOURNAL_PATH, SEARCH_JOURNAL_PATH,
    build_enriched_master_seeds, catalog_summary, dump_catalog,
    overlay_home_reviews, overlay_listing_results, overlay_search_results,
    write_audit,
)

AUDIT_PATH = BACKEND / "data" / "master_seeds_audit.json"


def projects_from_mongo() -> list[dict]:
    from app.config import DB_NAME, MONGO_URL
    from pymongo import MongoClient

    db = MongoClient(MONGO_URL)[DB_NAME]
    return list(db.projects.find({}, {"url": 1, "funders": 1, "funder": 1, "title": 1}))


def main() -> int:
    p = argparse.ArgumentParser(description="Enrichit MasterSeeds sans crawler Complet")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-geojson", type=Path, help="GeoJSON v1 (seed/projects.geojson)")
    src.add_argument("--from-api", action="store_true")
    src.add_argument("--from-mongo", action="store_true")
    p.add_argument("--out", type=Path, default=MASTER_SEEDS_PATH)
    p.add_argument("--audit-out", type=Path, default=AUDIT_PATH)
    p.add_argument(
        "--reset-search",
        action="store_true",
        help="Ne pas réappliquer les homes Search B (journal + catalogue actuel)",
    )
    args = p.parse_args()

    if args.from_geojson:
        fc = json.loads(args.from_geojson.read_text(encoding="utf-8"))
        projects = projects_from_geojson(fc)
        source = str(args.from_geojson)
    elif args.from_api:
        projects = fetch_production_projects()
        source = "https://blueintelligence.online/api/projects"
    else:
        projects = projects_from_mongo()
        source = "mongo:projects"

    seeds = build_enriched_master_seeds(projects)
    if not args.reset_search:
        previous = []
        if args.out.is_file():
            previous = json.loads(args.out.read_text(encoding="utf-8")).get("seeds") or []
        journal = SEARCH_JOURNAL_PATH if SEARCH_JOURNAL_PATH.is_file() else None
        kept = overlay_search_results(seeds, previous=previous, journal=journal)
        print(f"  overlay Search B : {kept} graines préservées (journal + catalogue)")
        listing_journal = LISTING_JOURNAL_PATH if LISTING_JOURNAL_PATH.is_file() else None
        listed = overlay_listing_results(
            seeds, previous=previous, journal=listing_journal,
        )
        print(f"  overlay Search C : {listed} pages-listes préservées")
        reviewed = overlay_home_reviews(seeds, HOME_REVIEW_PATH)
        print(f"  overlay revue homes : {reviewed} graines")
    path = dump_catalog(seeds, args.out, source=source)
    audit = write_audit(seeds, args.audit_out, source=source)
    summary = catalog_summary(seeds)
    queued = seeds_for_run(seeds)
    print(f"Wrote {path} — {summary['n']} financeurs")
    print(
        f"  crawl={summary['n_crawl']} resolve={summary['n_resolve']} "
        f"skip={summary['n_skip']} official={summary['n_official']} "
        f"borrowed={summary['n_borrowed']} compound={summary['n_compound']}"
    )
    print(f"  file Complet = {len(queued)} (queue=crawl)")
    print(f"  audit {audit} + {audit.with_suffix('.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
