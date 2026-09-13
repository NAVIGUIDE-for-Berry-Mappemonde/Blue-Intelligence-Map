#!/usr/bin/env python3
"""Étape C (hors Complet) : Search page-liste sur la home officielle.

Règle : même domaine que la home, chemin catalogue (`/projects/`, `/nos-projets/`…).
Pas d'Agent TinyFish, pas de juge LLM. Miss → on garde la homepage (toujours crawlable).

Chaque résultat est append dans `official_listings_search.jsonl` (fsync),
puis le catalogue est réécrit atomiquement tous les N organismes.

    python3 scripts/resolve_project_listings.py --dry-run
    python3 scripts/resolve_project_listings.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from pathlib import Path

os.environ["MONGO_URL"] = "mongodb://127.0.0.1:27017"
os.environ.setdefault("DB_NAME", "bi_official_listings_unused")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND / ".env")

from app.core.serper import serper_api_key, serper_search  # noqa: E402
from app.core.tinyfish import tf_api_key, tf_search  # noqa: E402
from app.services.master_seeds import (  # noqa: E402
    MASTER_SEEDS_PATH, now_iso, projects_from_geojson,
)
from app.services.project_listing import (  # noqa: E402
    listing_from_hits, listing_search_query, listing_search_retry_query,
)
from app.services.seed_catalog import (  # noqa: E402
    AUDIT_PATH, LISTING_JOURNAL_PATH, LISTING_PROGRESS_PATH, LISTING_SOURCE_SEARCH,
    LISTING_SOURCE_V1, append_search_journal, apply_listing_result, catalog_summary,
    infer_listings_onto_official_homes, journal_done_names, listing_candidates,
    load_search_journal, overlay_listing_results, persist_catalog,
    write_search_progress,
)

LISTING_PURPOSE = (
    "Index page that lists multiple marine, ocean or coastal projects, "
    "programmes, campaigns or grants of this organization. "
    "Prefer /projects /projets /programmes /campaigns. Not news, donate or about."
)
EMPTY_HITS_ABORT = 5
DEFAULT_GEOJSON = BACKEND.parent / "seed" / "projects.geojson"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_search_settings() -> dict:
    return {
        "tinyfish_api_key": tf_api_key(),
        "serper_api_key": serper_api_key(),
    }


async def _search(query: str, settings: dict) -> tuple[list, list[str], str | None]:
    hits: list = []
    engines: list[str] = []
    errors: list[str] = []
    tf_key = tf_api_key(settings)
    if tf_key:
        try:
            got = await tf_search(
                query, tf_key, purpose=LISTING_PURPOSE, log=lambda m: None,
            ) or []
            if got:
                hits.extend(got)
                engines.append("tinyfish")
            else:
                errors.append("tinyfish_empty")
        except Exception as exc:
            errors.append(f"tinyfish:{type(exc).__name__}")
    sp_key = serper_api_key(settings)
    if sp_key:
        try:
            got = await serper_search(query, sp_key) or []
            if got:
                hits.extend(got)
                engines.append("serper")
            else:
                errors.append("serper_empty")
        except Exception as exc:
            errors.append(f"serper:{type(exc).__name__}")
    return hits, engines, (",".join(errors) if errors and not hits else None)


async def resolve_one(seed: dict, settings: dict) -> tuple[str, dict]:
    query_seed = {
        "name": seed.get("name"),
        "url": seed.get("home_url") or seed.get("url"),
        "home_url": seed.get("home_url"),
    }
    meta = {
        "query": listing_search_query(query_seed),
        "retry_query": listing_search_retry_query(query_seed),
        "n_hits": 0,
        "engines": [],
        "error": None,
    }
    hits, engines, err = await _search(meta["query"], settings)
    meta["engines"] = list(engines)
    meta["n_hits"] = len(hits)
    found = listing_from_hits(hits, query_seed) if hits else ""
    if found:
        return found, meta
    retry = meta["retry_query"]
    if retry and retry != meta["query"]:
        hits2, engines2, err2 = await _search(retry, settings)
        meta["n_hits"] += len(hits2)
        for eng in engines2:
            if eng not in meta["engines"]:
                meta["engines"].append(eng)
        found = listing_from_hits(hits2, query_seed) if hits2 else ""
        if found:
            return found, meta
        if err2 and not hits2:
            err = err2 if not hits else err
    if not found and err and not hits:
        meta["error"] = err
    return found or "", meta


def _print_keys(settings: dict) -> None:
    tf = "oui" if settings.get("tinyfish_api_key") else "non"
    sp = "oui" if settings.get("serper_api_key") else "non"
    print(f"Clés Search : TinyFish={tf}  Serper={sp}")


def _copy_artifacts(dest: Path, *paths: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for src in paths:
        if src.is_file():
            (dest / src.name).write_bytes(src.read_bytes())


async def apply(
    seeds: list[dict],
    settings: dict,
    *,
    limit: int,
    catalog_path: Path,
    journal_path: Path,
    audit_path: Path,
    progress_path: Path,
    checkpoint_every: int,
    retry_unknown: bool,
    stop: dict,
    artifact_dir: Path | None,
) -> int:
    source = str(catalog_path) + "+listing-search"
    journal = load_search_journal(journal_path)
    n_overlay = overlay_listing_results(seeds, journal=journal)
    done = journal_done_names(journal, retry_unknown=retry_unknown, result_key="listing")
    todo = listing_candidates(
        seeds, done_names=done, retry_unknown=retry_unknown,
    )[:limit]
    print(
        f"Reprise : {len(journal)} consignés, {n_overlay} réappliqués, "
        f"{len(todo)} à Search (limite {limit})"
    )
    write_search_progress(progress_path, {
        "phase": "c_project_listings",
        "catalog": str(catalog_path),
        "journal": str(journal_path),
        "done": len(journal),
        "todo": len(todo),
        "ok": 0,
        "miss": 0,
        "errors": 0,
        "status": "running",
    })

    ok = miss = errors = 0
    empty_streak = 0
    treated = 0
    for seed in todo:
        if stop.get("flag"):
            print("Arrêt demandé — checkpoint final.", flush=True)
            break
        name = (seed.get("name") or "").strip()
        listing, meta = await resolve_one(seed, settings)
        record = {
            "ts": now_iso(),
            "name": name,
            "listing": listing or None,
            "home_url": seed.get("home_url") or seed.get("url"),
            "ok": bool(listing),
            "query": meta.get("query"),
            "retry_query": meta.get("retry_query"),
            "n_hits": meta.get("n_hits") or 0,
            "engines": meta.get("engines") or [],
            "error": meta.get("error"),
            "source": LISTING_SOURCE_SEARCH,
        }
        if meta.get("error") and not listing:
            errors += 1
            empty_streak += 1
            append_search_journal(journal_path, record)
            print(f"  ERR {name[:60]}  ({meta.get('error')})", flush=True)
            if empty_streak >= EMPTY_HITS_ABORT and ok == 0 and miss == 0:
                print(
                    f"Search : {EMPTY_HITS_ABORT} appels sans hit. "
                    "Arrêt sans marquer les misses (catalogue conservé).",
                    flush=True,
                )
                write_search_progress(progress_path, {
                    "phase": "c_project_listings",
                    "status": "aborted_empty_search",
                    "ok": ok, "miss": miss, "errors": errors,
                })
                return treated
        else:
            apply_listing_result(seed, listing, source=LISTING_SOURCE_SEARCH)
            append_search_journal(journal_path, record)
            if listing or (meta.get("n_hits") or 0) > 0:
                empty_streak = 0
            else:
                empty_streak += 1
            if listing:
                ok += 1
                print(f"  OK  {name[:60]} → {listing}", flush=True)
            else:
                miss += 1
                print(f"  ..  {name[:60]}  (hits={meta.get('n_hits') or 0})", flush=True)
        treated += 1
        if treated % max(1, checkpoint_every) == 0:
            persist_catalog(seeds, catalog_path, audit_path, source=source)
            write_search_progress(progress_path, {
                "phase": "c_project_listings",
                "status": "running",
                "done": len(journal) + treated,
                "todo": max(0, len(todo) - treated),
                "ok": ok, "miss": miss, "errors": errors,
                "summary": catalog_summary(seeds),
            })
            print(f"  · checkpoint {treated}/{len(todo)}  ok={ok} miss={miss}", flush=True)
            if artifact_dir:
                _copy_artifacts(
                    artifact_dir, catalog_path, journal_path, audit_path,
                    audit_path.with_suffix(".csv"), progress_path,
                )

    persist_catalog(seeds, catalog_path, audit_path, source=source)
    write_search_progress(progress_path, {
        "phase": "c_project_listings",
        "status": "stopped" if stop.get("flag") else "done",
        "done": len(journal) + treated,
        "todo": max(0, len(todo) - treated),
        "ok": ok, "miss": miss, "errors": errors,
        "summary": catalog_summary(seeds),
    })
    if artifact_dir:
        _copy_artifacts(
            artifact_dir, catalog_path, journal_path, audit_path,
            audit_path.with_suffix(".csv"), progress_path,
        )
    print(f"Traité {treated} / {len(todo)}  ok={ok} miss={miss} errors={errors}", flush=True)
    print(f"Conservé : journal {journal_path}", flush=True)
    print(f"Conservé : catalogue {catalog_path}", flush=True)
    return treated


def main() -> int:
    p = argparse.ArgumentParser(description="Search page-liste hors Complet")
    p.add_argument("--seeds", type=Path, default=MASTER_SEEDS_PATH)
    p.add_argument("--journal", type=Path, default=LISTING_JOURNAL_PATH)
    p.add_argument("--audit-out", type=Path, default=AUDIT_PATH)
    p.add_argument("--progress", type=Path, default=LISTING_PROGRESS_PATH)
    p.add_argument("--geojson", type=Path, default=DEFAULT_GEOJSON)
    p.add_argument("--artifact-dir", type=Path, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--skip-infer", action="store_true")
    p.add_argument("--limit", type=int, default=800)
    p.add_argument("--checkpoint-every", type=int, default=10)
    p.add_argument("--retry-unknown", action="store_true")
    args = p.parse_args()
    data = _load(args.seeds)
    seeds = data.get("seeds") or []

    inferred = 0
    if not args.skip_infer and args.geojson.is_file():
        projects = projects_from_geojson(json.loads(args.geojson.read_text(encoding="utf-8")))
        inferred = infer_listings_onto_official_homes(seeds, projects)
        print(f"Indice v1 : {inferred} pages-listes déduites sans Search")

    journal = load_search_journal(args.journal)
    done = journal_done_names(journal, retry_unknown=args.retry_unknown, result_key="listing")
    todo = listing_candidates(seeds, done_names=done, retry_unknown=args.retry_unknown)
    print(f"{len(todo)} graines à résoudre (home officielle, pas encore de catalogue)")
    print(f"Journal : {args.journal}  ({len(journal)} noms consignés)")
    if args.dry_run or not args.apply:
        for s in todo[:20]:
            home = (s.get("home_url") or s.get("url") or "")[:50]
            print(f"  {(s.get('listing_kind') or '?'):13}  {s['name'][:48]:48}  {home}")
        if len(todo) > 20:
            print(f"  … +{len(todo) - 20}")
        print("Relancer avec --apply pour Search (TinyFish / Serper).")
        return 0

    settings = load_search_settings()
    _print_keys(settings)
    if not settings.get("tinyfish_api_key") and not settings.get("serper_api_key"):
        print("Aucune clé Search. Abandon — catalogue et journal intacts.")
        return 2
    if inferred:
        for seed in seeds:
            if (seed.get("listing_source") or "") != LISTING_SOURCE_V1:
                continue
            listing = seed.get("listing_url") or ""
            if not listing:
                continue
            key = (seed.get("name") or "").strip()
            if key in journal:
                continue
            append_search_journal(args.journal, {
                "ts": now_iso(),
                "name": key,
                "listing": listing,
                "home_url": seed.get("home_url"),
                "ok": True,
                "n_hits": 0,
                "engines": [],
                "error": None,
                "source": LISTING_SOURCE_V1,
            })
        persist_catalog(
            seeds, args.seeds, args.audit_out,
            source=str(args.seeds) + "+listing-infer",
        )

    stop = {"flag": False}

    def _handle(signum, _frame):
        stop["flag"] = True
        print(f"Signal {signum} — fin de l'organisme en cours puis checkpoint.", flush=True)

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)
    asyncio.run(apply(
        seeds,
        settings,
        limit=args.limit,
        catalog_path=args.seeds,
        journal_path=args.journal,
        audit_path=args.audit_out,
        progress_path=args.progress,
        checkpoint_every=args.checkpoint_every,
        retry_unknown=args.retry_unknown,
        stop=stop,
        artifact_dir=args.artifact_dir,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
