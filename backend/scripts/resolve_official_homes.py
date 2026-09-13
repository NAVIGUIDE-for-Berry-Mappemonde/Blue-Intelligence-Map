#!/usr/bin/env python3
"""Étape B (hors Complet) : Search « official site » pour les homes inconnues.

Règle stricte : le domaine doit coller au nom (`domain_matches_org`).
Sinon `home_status=unknown`, pas de crawl. Pas d'Agent TinyFish.

    python3 scripts/resolve_official_homes.py --dry-run
    python3 scripts/resolve_official_homes.py --apply   # TinyFish / Serper
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.master_seeds import (  # noqa: E402
    MASTER_SEEDS_PATH, official_site_query, official_site_retry_query,
)
from app.services.seed_catalog import dump_catalog  # noqa: E402


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


async def _search(query: str, settings: dict) -> list:
    hits = []
    from app.core.tinyfish import tf_search
    from app.core.serper import serper_search
    key = settings.get("tinyfish_api_key") or ""
    if key:
        try:
            hits.extend(await tf_search(query, key, max_results=8) or [])
        except Exception:
            pass
    try:
        hits.extend(await serper_search(query, settings=settings) or [])
    except Exception:
        pass
    return hits


async def resolve_one(seed: dict, settings: dict) -> str:
    from app.services.swarm_pipeline import official_site_from_hits
    name = (seed.get("name") or "").strip()
    if not name:
        return ""
    hits = await _search(official_site_query(name), settings)
    site = official_site_from_hits(hits, funder_name=name)
    if site:
        return site
    retry = official_site_retry_query(name)
    if not retry:
        return ""
    hits2 = await _search(retry, settings)
    return official_site_from_hits(hits2, funder_name=name)


def candidates(seeds: list[dict]) -> list[dict]:
    out = []
    for s in seeds:
        if (s.get("name_status") or "ok") != "ok":
            continue
        if (s.get("home_status") or "") not in {
            "borrowed_hub", "unknown", "empty", "publisher",
        }:
            continue
        if (s.get("queue") or "") == "skip":
            continue
        out.append(s)
    return out


async def apply(seeds: list[dict], settings: dict, limit: int) -> int:
    n = 0
    for seed in candidates(seeds)[:limit]:
        site = await resolve_one(seed, settings)
        n += 1
        if site:
            seed["home_url"] = site
            seed["url"] = seed.get("listing_url") or site
            seed["home_status"] = "official"
            seed["home_source"] = "search"
            seed["queue"] = "crawl"
            if not seed.get("listing_kind") or seed["listing_kind"] == "unknown":
                seed["listing_kind"] = "homepage"
            print(f"  OK  {seed['name'][:60]} → {site}")
        else:
            seed["home_status"] = "unknown"
            seed["queue"] = "resolve"
            print(f"  ??  {seed['name'][:60]}")
    return n


def main() -> int:
    p = argparse.ArgumentParser(description="Search official site hors Complet")
    p.add_argument("--seeds", type=Path, default=MASTER_SEEDS_PATH)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--limit", type=int, default=800)
    args = p.parse_args()
    data = _load(args.seeds)
    seeds = data.get("seeds") or []
    todo = candidates(seeds)
    print(f"{len(todo)} graines à résoudre (borrowed/unknown/empty, nom ok)")
    if args.dry_run or not args.apply:
        for s in todo[:20]:
            print(f"  {s.get('home_status'):13}  {s['name'][:70]}")
        if len(todo) > 20:
            print(f"  … +{len(todo) - 20}")
        print("Relancer avec --apply pour Search (TinyFish / Serper).")
        return 0
    from app.config import settings as app_settings
    settings = dict(app_settings or {})
    n = asyncio.run(apply(seeds, settings, args.limit))
    dump_catalog(seeds, args.seeds, source=str(args.seeds) + "+official-search")
    print(f"Traité {n} / {len(todo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
