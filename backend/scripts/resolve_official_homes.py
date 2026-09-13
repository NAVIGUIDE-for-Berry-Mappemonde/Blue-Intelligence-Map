#!/usr/bin/env python3
"""Étape B (hors Complet) : Search « official site » pour les homes inconnues.

Règle stricte : le domaine doit coller au nom (`domain_matches_org`).
Sinon `home_status=unknown`, pas de crawl. Pas d'Agent TinyFish.

Chaque résultat est d'abord append dans `official_homes_search.jsonl`
(fsync), puis le catalogue est réécrit atomiquement tous les N organismes.
Une interruption reprend sans rejouer les noms déjà consignés.

    python3 scripts/resolve_official_homes.py --dry-run
    python3 scripts/resolve_official_homes.py --apply   # TinyFish / Serper
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from pathlib import Path

# Ce script ne parle pas à Mongo (ni Atlas figé, ni VPS). Forcer localhost
# avant tout import éventuel de app.config.
os.environ["MONGO_URL"] = "mongodb://127.0.0.1:27017"
os.environ.setdefault("DB_NAME", "bi_official_homes_unused")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND / ".env")

from app.core.serper import serper_api_key, serper_search  # noqa: E402
from app.core.tinyfish import tf_api_key, tf_search  # noqa: E402
from app.services.master_seeds import (  # noqa: E402
    MASTER_SEEDS_PATH, now_iso, official_site_query, official_site_retry_query,
)
from app.services.seed_catalog import (  # noqa: E402
    AUDIT_PATH, SEARCH_JOURNAL_PATH, SEARCH_PROGRESS_PATH,
    append_search_journal, apply_official_site_result, catalog_summary,
    journal_done_names, load_search_journal, overlay_search_results,
    persist_catalog, search_candidates, write_search_progress,
)

OFFICIAL_SITE_PURPOSE = (
    "Official homepage of the named marine, ocean or coastal organization "
    "(foundation, agency, institute, NGO). Prefer the organization's own domain. "
    "Ignore news articles, journals, Wikipedia and shared project hubs."
)

# Si les N premiers appels renvoient 0 hit, l'API est probablement hors service :
# on s'arrête sans marquer les graines « unknown » (reprise possible).
EMPTY_HITS_ABORT = 5


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_search_settings() -> dict:
    """Clés env / .env uniquement — pas de get_settings() Mongo."""
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
                query, tf_key, purpose=OFFICIAL_SITE_PURPOSE, log=lambda m: None,
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
    from app.services.swarm_pipeline import official_site_from_hits

    name = (seed.get("name") or "").strip()
    meta = {
        "query": official_site_query(name),
        "retry_query": official_site_retry_query(name),
        "n_hits": 0,
        "engines": [],
        "error": None,
    }
    if not name:
        meta["error"] = "empty_name"
        return "", meta
    hits, engines, err = await _search(meta["query"], settings)
    meta["engines"] = list(engines)
    meta["n_hits"] = len(hits)
    site = official_site_from_hits(hits, funder_name=name) if hits else ""
    if site:
        return site, meta
    retry = meta["retry_query"]
    if retry:
        hits2, engines2, err2 = await _search(retry, settings)
        meta["n_hits"] += len(hits2)
        for eng in engines2:
            if eng not in meta["engines"]:
                meta["engines"].append(eng)
        site = official_site_from_hits(hits2, funder_name=name) if hits2 else ""
        if site:
            return site, meta
        if err2 and not hits2:
            err = err2 if not hits else err
    if not site and err and not hits:
        meta["error"] = err
    return site or "", meta


def _print_keys(settings: dict) -> None:
    tf = "oui" if settings.get("tinyfish_api_key") else "non"
    sp = "oui" if settings.get("serper_api_key") else "non"
    print(f"Clés Search : TinyFish={tf}  Serper={sp}")


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
    source = str(catalog_path) + "+official-search"
    journal = load_search_journal(journal_path)
    n_overlay = overlay_search_results(seeds, journal=journal)
    done = journal_done_names(journal, retry_unknown=retry_unknown)
    todo = search_candidates(seeds, done_names=done, retry_unknown=retry_unknown)[:limit]
    print(
        f"Reprise : {len(done)} déjà consignés, {n_overlay} réappliqués, "
        f"{len(todo)} à Search (limite {limit})"
    )
    write_search_progress(progress_path, {
        "phase": "b_official_homes",
        "catalog": str(catalog_path),
        "journal": str(journal_path),
        "audit": str(audit_path),
        "done": len(done),
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
        site, meta = await resolve_one(seed, settings)
        record = {
            "ts": now_iso(),
            "name": name,
            "site": site or None,
            "home_status": "official" if site else "unknown",
            "ok": bool(site),
            "query": meta.get("query"),
            "retry_query": meta.get("retry_query"),
            "n_hits": meta.get("n_hits") or 0,
            "engines": meta.get("engines") or [],
            "error": meta.get("error"),
        }
        if meta.get("error") and not site:
            errors += 1
            empty_streak += 1
            append_search_journal(journal_path, record)
            print(f"  ERR {name[:60]}  ({meta.get('error')})", flush=True)
            if empty_streak >= EMPTY_HITS_ABORT and ok == 0 and miss == 0:
                print(
                    f"Search : {EMPTY_HITS_ABORT} appels sans hit. "
                    "Arrêt sans marquer unknown (catalogue conservé).",
                    flush=True,
                )
                write_search_progress(progress_path, {
                    "phase": "b_official_homes",
                    "status": "aborted_empty_search",
                    "done": len(done),
                    "ok": ok,
                    "miss": miss,
                    "errors": errors,
                    "catalog": str(catalog_path),
                    "journal": str(journal_path),
                })
                return treated
        else:
            apply_official_site_result(seed, site)
            record["home_status"] = seed.get("home_status")
            append_search_journal(journal_path, record)
            empty_streak = 0 if (site or (meta.get("n_hits") or 0) > 0) else empty_streak + 1
            if site:
                ok += 1
                print(f"  OK  {name[:60]} → {site}", flush=True)
            else:
                miss += 1
                print(f"  ??  {name[:60]}  (hits={meta.get('n_hits') or 0})", flush=True)
        treated += 1
        if treated % max(1, checkpoint_every) == 0:
            persist_catalog(seeds, catalog_path, audit_path, source=source)
            write_search_progress(progress_path, {
                "phase": "b_official_homes",
                "status": "running",
                "done": len(done) + treated,
                "todo": max(0, len(todo) - treated),
                "ok": ok,
                "miss": miss,
                "errors": errors,
                "catalog": str(catalog_path),
                "journal": str(journal_path),
                "summary": catalog_summary(seeds),
            })
            print(f"  · checkpoint {treated}/{len(todo)}  ok={ok} miss={miss}", flush=True)
            if artifact_dir:
                _copy_artifacts(artifact_dir, catalog_path, journal_path, audit_path, progress_path)

    persist_catalog(seeds, catalog_path, audit_path, source=source)
    write_search_progress(progress_path, {
        "phase": "b_official_homes",
        "status": "stopped" if stop.get("flag") else "done",
        "done": len(done) + treated,
        "todo": max(0, len(todo) - treated),
        "ok": ok,
        "miss": miss,
        "errors": errors,
        "catalog": str(catalog_path),
        "journal": str(journal_path),
        "summary": catalog_summary(seeds),
    })
    if artifact_dir:
        _copy_artifacts(artifact_dir, catalog_path, journal_path, audit_path, progress_path)
    print(
        f"Traité {treated} / {len(todo)}  ok={ok} miss={miss} errors={errors}",
        flush=True,
    )
    print(f"Conservé : journal {journal_path}", flush=True)
    print(f"Conservé : catalogue {catalog_path}", flush=True)
    print(f"Conservé : audit {audit_path} + {audit_path.with_suffix('.csv')}", flush=True)
    return treated


def _copy_artifacts(
    dest: Path,
    catalog: Path,
    journal: Path,
    audit: Path,
    progress: Path,
) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for src in (catalog, journal, audit, audit.with_suffix(".csv"), progress):
        if not src.is_file():
            continue
        target = dest / src.name
        target.write_bytes(src.read_bytes())


def main() -> int:
    p = argparse.ArgumentParser(description="Search official site hors Complet")
    p.add_argument("--seeds", type=Path, default=MASTER_SEEDS_PATH)
    p.add_argument("--journal", type=Path, default=SEARCH_JOURNAL_PATH)
    p.add_argument("--audit-out", type=Path, default=AUDIT_PATH)
    p.add_argument("--progress", type=Path, default=SEARCH_PROGRESS_PATH)
    p.add_argument("--artifact-dir", type=Path, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--limit", type=int, default=800)
    p.add_argument("--checkpoint-every", type=int, default=10)
    p.add_argument("--retry-unknown", action="store_true")
    args = p.parse_args()
    data = _load(args.seeds)
    seeds = data.get("seeds") or []
    journal = load_search_journal(args.journal)
    done = journal_done_names(journal, retry_unknown=args.retry_unknown)
    todo = search_candidates(seeds, done_names=done, retry_unknown=args.retry_unknown)
    print(f"{len(todo)} graines à résoudre (borrowed/unknown/empty, nom ok)")
    print(f"Journal : {args.journal}  ({len(journal)} noms consignés)")
    print(f"Catalogue : {args.seeds}  (checkpoint tous les {args.checkpoint_every})")
    if args.dry_run or not args.apply:
        for s in todo[:20]:
            print(f"  {s.get('home_status'):13}  {s['name'][:70]}")
        if len(todo) > 20:
            print(f"  … +{len(todo) - 20}")
        print("Relancer avec --apply pour Search (TinyFish / Serper).")
        return 0

    settings = load_search_settings()
    _print_keys(settings)
    if not settings.get("tinyfish_api_key") and not settings.get("serper_api_key"):
        print("Aucune clé Search. Abandon — catalogue et journal intacts.")
        return 2

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
