#!/usr/bin/env python3
"""Applique la revue manuelle des homes B (hors Complet).

Gagne sur les journaux Search. N'écrit pas `projects`.

    python3 scripts/apply_home_reviews.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ["MONGO_URL"] = "mongodb://127.0.0.1:27017"
os.environ.setdefault("DB_NAME", "bi_home_reviews_unused")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.master_seeds import MASTER_SEEDS_PATH, seeds_for_run  # noqa: E402
from app.services.seed_catalog import (  # noqa: E402
    AUDIT_PATH, HOME_REVIEW_PATH, catalog_summary, overlay_home_reviews,
    persist_catalog, refresh_catalog_queues,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Applique la revue manuelle des homes")
    p.add_argument("--seeds", type=Path, default=MASTER_SEEDS_PATH)
    p.add_argument("--reviews", type=Path, default=HOME_REVIEW_PATH)
    p.add_argument("--audit-out", type=Path, default=AUDIT_PATH)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    data = json.loads(args.seeds.read_text(encoding="utf-8"))
    seeds = data.get("seeds") or []
    before = catalog_summary(seeds)
    n = overlay_home_reviews(seeds, args.reviews)
    refresh_catalog_queues(seeds)
    after = catalog_summary(seeds)
    queued = seeds_for_run(seeds)
    print(f"Revue : {n} graines")
    print(
        f"E : crawl {before['n_crawl']} → {after['n_crawl']}  "
        f"official {before['n_official']} → {after['n_official']}  "
        f"unknown {before['n_unknown_home']} → {after['n_unknown_home']}"
    )
    print(f"  file Complet = {len(queued)}")
    if args.dry_run or not args.apply:
        print("Relancer avec --apply pour écrire le catalogue.")
        return 0
    persist_catalog(
        seeds, args.seeds, args.audit_out,
        source=str(args.seeds) + "+home-review",
    )
    print(f"Conservé : {args.seeds}")
    print(f"Conservé : {args.reviews}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
