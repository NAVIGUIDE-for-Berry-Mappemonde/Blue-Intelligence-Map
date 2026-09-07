"""
app.routers.runs — Runs versionnés du pipeline PoE (plusieurs en parallèle).

POST /api/poe/runs                     démarre (ou reprend) un run
POST /api/poe/runs/multi               lance v1 + v2 + tinyfish en parallèle
GET  /api/poe/runs                     liste des runs
GET  /api/poe/runs/searxng             santé du moteur de recherche
GET  /api/poe/runs/compare             comparaison à N runs (+ v1)
POST /api/poe/runs/best-of             synthèse dans un nouveau run (jamais v1)
GET  /api/poe/runs/{id}/status
POST /api/poe/runs/{id}/cancel
GET  /api/poe/runs/{id}/ports
GET  /api/poe/runs/{id}/events
GET  /api/poe/runs/{id}/diff
GET  /api/poe/runs/{id}/report
GET  /api/poe/runs/{id}/listing-control   rapport de contrôle vs listing_ref
POST /api/poe/runs/{id}/listing-control   calcule + persist la file de revue
GET  /api/poe/listing-control/v1
POST /api/poe/listing-control/v1
GET  /api/poe/listing-control/compare
GET  /api/poe/listing-control/review
GET  /api/poe/listing-control/ref
GET  /api/poe/listing-control/canary
GET  /api/poe/seeds/union              union bottom-up v1+runs+OSM+listing (aucun crawl)
POST /api/poe/seeds/build              reconstruit poe_seed_ports (pas poe_ports)
GET  /api/poe/seeds                    lecture poe_seed_ports
GET  /api/poe/seeds/gps-audit          audit GPS confirmed (dry-run, pas persist)
GET  /api/poe/seeds/line               requête TinyFish + résumé inventaire
POST /api/poe/seeds/verify             classe les graines + run versionné (pas poe_ports)
POST /api/poe/seeds/enrich             géocode + juge (lots, pas poe_ports)
GET  /api/poe/seeds/enrich/status
POST /api/poe/seeds/enrich/cancel
GET  /api/poe/seeds/osm                Taginfo + cache OSM (pas d'Overpass)
POST /api/poe/seeds/osm/refresh        recharge Overpass → osm_port_seeds
GET  /api/poe/runs/code-fingerprint
"""
import asyncio
import os
import time

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.core.tasks import TaskState
from app.db import db as _db
from app.services import poe_pipeline as poe
from app.services import poe_runs
from app.services.listing_control import (
    build_listing_control_report, compare_runs_to_listing, persist_review,
    suggest_canary_zones,
)
from app.services.run_fingerprint import build_code_fingerprint
from app.services.listing_ref import project_listing
from app.services.poe_bestof import compare_runs, synthesize_best_of
from app.services.poe_diff import diff_run_vs_baseline
from app.services.poe_pipeline import normalize_variant
from app.services.poe_report import build_run_report, report_to_markdown
from app.services.poe_seeds import (
    SEARCH_EXCLUDE_DOMAINS, SEED_LEGEND, build_seed_union, collect_seed_report,
    format_seed_line, match_named_seed, persist_seed_database,
    persist_verify_run, public_seed_view, seed_from_files, seed_search_query,
)
from app.services.poe_confirmed_gps_audit import audit_from_db

router = APIRouter(prefix="/api")

MAX_PARALLEL_RUNS = 4
RUN_STATES: dict[str, TaskState] = {}


def _active_ids() -> list[str]:
    return [rid for rid, st in RUN_STATES.items() if st.running]


class RunBody(BaseModel):
    label: str = ""
    limit: int = 0
    concurrency: int = 2
    zones: list[int] | None = None
    resume_run_id: str | None = None
    variant: str = "tinyfish"           # v1 | v2 | tinyfish


class MultiRunBody(BaseModel):
    variants: list[str] = Field(default_factory=lambda: ["v1", "v2", "tinyfish"])
    limit: int = 0
    concurrency: int = 2
    zones: list[int] | None = None
    label_prefix: str = "bestof"


class BestOfBody(BaseModel):
    run_ids: list[str]
    include_v1: bool = True
    label: str = ""


class SeedBuildBody(BaseModel):
    run_ids: list[str] = Field(default_factory=list)
    include_v1: bool = True
    include_listing: bool = True
    include_osm: bool = True
    use_default_mondials: bool = True


class SeedVerifyBody(BaseModel):
    run_ids: list[str] = Field(default_factory=list)
    include_v1: bool = True
    include_listing: bool = True
    include_osm: bool = True
    use_default_mondials: bool = True
    persist: bool = True
    label: str = "seed-verify"


class SeedEnrichBody(BaseModel):
    source: str = "seeds"          # seeds = poe_seed_ports ; run = poe_run_ports
    run_id: str = ""
    do_geocode: bool = True
    do_verify: bool = True
    verdicts: list[str] = Field(default_factory=lambda: ["name_only"])
    limit: int = 200
    concurrency: int = 2
    use_agent: bool = True


async def _launch_run(*, resume: bool, run_id: str, label: str, limit: int,
                      zones, concurrency: int, variant: str) -> str:
    if len(_active_ids()) >= MAX_PARALLEL_RUNS:
        raise HTTPException(409, f"déjà {MAX_PARALLEL_RUNS} runs actifs")
    if run_id in RUN_STATES and RUN_STATES[run_id].running:
        raise HTTPException(409, f"Run {run_id} already running")
    state = TaskState(max_logs=2000)
    state.start()
    RUN_STATES[run_id] = state

    async def _runner():
        try:
            state.summary = await poe_runs.execute_run(
                _db, state, run_id, label=label, limit=limit,
                only_zones=zones, concurrency=concurrency, resume=resume,
                variant=variant)
        except Exception as e:
            state.error = f"{type(e).__name__}: {e}"
            state.log(f"FATAL: {state.error}")
            await _db.poe_runs.update_one({"_id": run_id}, {"$set": {
                "state": "failed", "error": state.error,
                "finished_at": poe.now_iso()}})
        finally:
            state.finish()

    asyncio.create_task(_runner())
    return run_id


@router.post("/poe/runs", status_code=202)
async def poe_run_start(body: RunBody | None = None):
    body = body or RunBody()
    resume = bool(body.resume_run_id)
    if resume:
        existing = await _db.poe_runs.find_one({"_id": body.resume_run_id})
        if not existing:
            raise HTTPException(404, f"Run {body.resume_run_id} unknown — cannot resume")
        run_id = body.resume_run_id
        params = existing.get("params") or {}
        label = body.label or existing.get("label") or ""
        limit = int(params.get("limit") or 0)
        zones = params.get("only_zones")
        concurrency = int(params.get("concurrency") or body.concurrency)
        variant = params.get("variant") or body.variant
    else:
        run_id = poe_runs.new_run_id()
        label, limit, zones, concurrency = body.label, body.limit, body.zones, body.concurrency
        variant = body.variant
    try:
        variant = normalize_variant(variant)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not label:
        label = f"{variant}-full"
    await _launch_run(resume=resume, run_id=run_id, label=label, limit=limit,
                      zones=zones, concurrency=concurrency, variant=variant)
    return {"status": "started", "run_id": run_id, "resume": resume, "variant": variant}


@router.post("/poe/runs/multi", status_code=202)
async def poe_run_multi(body: MultiRunBody | None = None):
    """Lance les variants demandés en parallèle. Chaque run a son run_id."""
    body = body or MultiRunBody()
    started = []
    errors = []
    for raw in body.variants:
        try:
            variant = normalize_variant(raw)
        except ValueError as e:
            errors.append({"variant": raw, "error": str(e)})
            continue
        try:
            run_id = poe_runs.new_run_id()
            label = f"{body.label_prefix}-{variant}"
            await _launch_run(
                resume=False, run_id=run_id, label=label,
                limit=body.limit, zones=body.zones,
                concurrency=body.concurrency, variant=variant)
            started.append({"run_id": run_id, "variant": variant, "label": label})
            await asyncio.sleep(0.05)
        except HTTPException as e:
            errors.append({"variant": variant, "error": e.detail})
    if not started:
        raise HTTPException(409, {"detail": "aucun run démarré", "errors": errors})
    return {"status": "started", "runs": started, "errors": errors,
            "active_run_ids": _active_ids()}


@router.get("/poe/runs/code-fingerprint")
async def poe_runs_code_fingerprint():
    """Empreinte qui serait écrite dans params.code au prochain POST /runs."""
    from app.db import get_settings
    settings = await get_settings()
    return build_code_fingerprint(settings, zone_timeout_s=poe_runs.ZONE_TIMEOUT_S)


@router.get("/poe/runs/searxng")
async def poe_searxng_health():
    instances = poe.searx_instances()
    own = (os.environ.get("SEARXNG_URL") or "").strip().rstrip("/")
    results = []
    for inst in instances[:6]:
        t0 = time.time()
        ok = False
        n = 0
        err = None
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(f"{inst}/search",
                                     params={"q": "ports of entry france customs",
                                             "format": "json"})
                if r.status_code == 200:
                    n = len((r.json().get("results") or []))
                    ok = n > 0
                else:
                    err = f"HTTP {r.status_code}"
        except Exception as e:
            err = f"{type(e).__name__}"
        results.append({"instance": inst, "ok": ok, "n": n, "error": err,
                        "ms": int((time.time() - t0) * 1000),
                        "local": inst == own})
    return {"searxng_url": own or None, "instances": results,
            "ok": any(x["ok"] for x in results)}


@router.get("/poe/runs")
async def poe_runs_list():
    docs = await _db.poe_runs.find({}).sort("created_at", -1).to_list(100)
    return {"count": len(docs), "active_run_ids": _active_ids(),
            "active_run_id": (_active_ids() or [None])[0], "items": docs}


@router.get("/poe/listing-control/ref")
async def listing_control_ref():
    """Projection slug → mrgid (pas les ports détaillés)."""
    proj = project_listing()
    return {
        "listing_ref_id": proj["listing_ref_id"],
        "generated_at": proj.get("generated_at"),
        "disclaimer": proj.get("disclaimer"),
        "stats": proj["stats"],
        "unresolved": proj.get("unresolved") or [],
        "resolutions": [
            {k: r[k] for k in ("slug", "name", "mrgids", "iso2", "method")}
            for r in proj.get("resolutions") or []
        ],
    }


@router.get("/poe/listing-control/v1")
async def listing_control_v1(restrict_to_run_zones: bool = False):
    return await build_listing_control_report(
        _db, "v1", restrict_to_run_zones=restrict_to_run_zones)


@router.post("/poe/listing-control/v1")
async def listing_control_v1_persist(restrict_to_run_zones: bool = False):
    report = await build_listing_control_report(
        _db, "v1", restrict_to_run_zones=restrict_to_run_zones)
    persisted = await persist_review(_db, report)
    return {"report": report, "persisted": persisted}


@router.get("/poe/listing-control/compare")
async def listing_control_compare(run_ids: str = "", include_v1: bool = True,
                                  persist: bool = False):
    ids = [x.strip() for x in run_ids.split(",") if x.strip()]
    if not include_v1 and not ids:
        raise HTTPException(400, "run_ids requis si include_v1=false")
    for rid in ids:
        if not await _db.poe_runs.find_one({"_id": rid}):
            raise HTTPException(404, f"Run {rid} unknown")
    return await compare_runs_to_listing(
        _db, ids, include_v1=include_v1, persist=persist)


@router.get("/poe/listing-control/canary")
async def listing_control_canary(run_ids: str = "", include_v1: bool = True,
                                 limit: int = 25):
    """ZEE à passer en canari (listing_only ∪ erreur) — aucun crawl."""
    ids = [x.strip() for x in run_ids.split(",") if x.strip()]
    return await suggest_canary_zones(
        _db, ids, include_v1=include_v1, limit=limit)


@router.get("/poe/seeds/osm")
async def poe_seeds_osm():
    """Comptages Taginfo mondiaux + état du cache osm_port_seeds. Pas d'Overpass."""
    from app.services.osm_seeds import osm_inventory
    return await osm_inventory(_db)


@router.post("/poe/seeds/osm/refresh")
async def poe_seeds_osm_refresh():
    """Recharge Overpass (lent, 2–10 min). N'écrit pas dans poe_ports."""
    from app.services.osm_seeds import refresh_osm_cache
    return await refresh_osm_cache(_db)


@router.post("/poe/seeds/build")
async def poe_seeds_build(body: SeedBuildBody | None = None):
    """Reconstruit poe_seed_ports (runs ∪ listing ∪ OSM). Aucun crawl, pas poe_ports."""
    body = body or SeedBuildBody()
    ids = [x.strip() for x in body.run_ids if str(x).strip()]
    report = await collect_seed_report(
        _db, ids, include_v1=body.include_v1,
        include_listing=body.include_listing,
        include_osm=body.include_osm,
        use_default_mondials=body.use_default_mondials)
    persisted = await persist_seed_database(_db, report)
    out = public_seed_view(report, mode="seed-db")
    out["persisted"] = persisted
    return out


@router.get("/poe/seeds")
async def poe_seeds_list(mrgid: int | None = None, verdict: str | None = None,
                         limit: int = 50):
    """Lecture de poe_seed_ports. Pas d'écriture poe_ports."""
    q: dict = {}
    if mrgid is not None:
        q["mrgid"] = int(mrgid)
    if verdict:
        q["verify_verdict"] = verdict
    total = await _db.poe_seed_ports.count_documents(q)
    cap = max(0, min(int(limit or 50), 200))
    docs = await _db.poe_seed_ports.find(q).to_list(cap)
    return {
        "total": total,
        "limit": cap,
        "seeds": docs,
        "wrote_poe_ports": False,
    }


@router.get("/poe/seeds/gps-audit")
async def poe_seeds_gps_audit():
    """Audit GPS des `confirmed` (dry-run). Pas de persist, pas poe_ports, pas build."""
    return await audit_from_db(_db)


@router.get("/poe/seeds/line")
async def poe_seeds_line(mrgid: int, name: str):
    """Une ligne juge pour un candidat (collection, sinon listing + priors)."""
    docs = await _db.poe_seed_ports.find({"mrgid": int(mrgid)}).to_list(8000)
    hit = match_named_seed(docs, mrgid, name)
    source = "poe_seed_ports"
    if hit is None:
        hit = seed_from_files(int(mrgid), name)
        source = "files"
    if hit is None:
        raise HTTPException(404, "seed unknown")
    return {
        "name": hit.get("name"),
        "search_query": hit.get("search_query") or seed_search_query(hit),
        "search_exclude_domains": list(
            hit.get("search_exclude_domains") or SEARCH_EXCLUDE_DOMAINS),
        "line": hit.get("seed_line") or format_seed_line(hit),
        "legend": SEED_LEGEND,
        "source": source,
        "seed": hit,
        "wrote_poe_ports": False,
    }


@router.get("/poe/seeds/union")
async def poe_seeds_union(run_ids: str = "", include_v1: bool = True,
                          include_listing: bool = True,
                          include_osm: bool = True,
                          use_default_mondials: bool = False):
    """Union bottom-up des graines (v1, runs, OSM, listing). Aucun crawl, pas d'écriture poe_ports.

    `use_default_mondials=true` ajoute les 5 runs 285 ZEE déjà en base si
    `run_ids` est vide. OSM vient du cache `osm_port_seeds` (pas d'Overpass ici).
    Le résidu = noms listing à géocoder, pas à re-scraper.
    """
    ids = [x.strip() for x in run_ids.split(",") if x.strip()]
    return await build_seed_union(
        _db, ids, include_v1=include_v1, include_listing=include_listing,
        include_osm=include_osm, use_default_mondials=use_default_mondials)


@router.post("/poe/seeds/verify")
async def poe_seeds_verify(body: SeedVerifyBody | None = None):
    """Inventaire + verdict PoE. Optionnellement persisté en run `verify`.

    Aucun crawl SERP. Aucune écriture dans poe_ports. Le crawl (géocode /
    OSM / Claude juge) ne vise que `name_only` et `unverified`, plus tard.
    """
    body = body or SeedVerifyBody()
    ids = [x.strip() for x in body.run_ids if str(x).strip()]
    report = await collect_seed_report(
        _db, ids, include_v1=body.include_v1,
        include_listing=body.include_listing,
        include_osm=body.include_osm,
        use_default_mondials=body.use_default_mondials)
    out = public_seed_view(report, mode="seed-verify")
    if body.persist:
        persisted = await persist_verify_run(_db, report, label=body.label)
        out["persisted"] = persisted
        out["run_id"] = persisted["run_id"]
    return out


@router.post("/poe/seeds/enrich", status_code=202)
async def poe_seeds_enrich(body: SeedEnrichBody | None = None):
    """Géocode / juge un lot. N'écrit pas dans poe_ports.

    Défaut : collection `poe_seed_ports` (source=seeds). TinyFish cherche
    le nom de la graine ; noonsite.com est exclu. Claude juge les extraits.
    `source=run` + `run_id` relit un run verify versionné.
    """
    from app.services.poe_seed_enrich import execute_enrich

    body = body or SeedEnrichBody()
    source = (body.source or "seeds").strip()
    if source not in ("seeds", "run"):
        raise HTTPException(400, "source doit être seeds ou run")
    run_id = (body.run_id or "").strip()
    task_id = "seed-enrich" if source == "seeds" else run_id
    if source == "run":
        if not run_id:
            raise HTTPException(400, "run_id requis si source=run")
        existing = await _db.poe_runs.find_one({"_id": run_id})
        if not existing:
            raise HTTPException(404, f"Run {run_id} unknown — lancer POST /api/poe/seeds/verify")
    else:
        n = await _db.poe_seed_ports.count_documents({})
        if not n:
            raise HTTPException(404, "poe_seed_ports vide — lancer POST /api/poe/seeds/build")
    if len(_active_ids()) >= MAX_PARALLEL_RUNS:
        raise HTTPException(409, f"déjà {MAX_PARALLEL_RUNS} runs actifs")
    if task_id in RUN_STATES and RUN_STATES[task_id].running:
        raise HTTPException(409, f"Enrich {task_id} already running")
    verdicts = [v for v in (body.verdicts or ["name_only"]) if v]
    state = TaskState(max_logs=2000)
    state.start()
    RUN_STATES[task_id] = state

    async def _runner():
        try:
            state.summary = await execute_enrich(
                _db, state, run_id=run_id, source=source,
                do_geocode=body.do_geocode, do_verify=body.do_verify,
                verdicts=verdicts, limit=int(body.limit or 0),
                concurrency=max(1, min(2, int(body.concurrency or 2))),
                use_agent=bool(body.use_agent))
        except Exception as e:
            state.error = f"{type(e).__name__}: {e}"
            state.log(f"FATAL: {state.error}")
            await _db.poe_runs.update_one({"_id": task_id}, {"$set": {
                "enrich_error": state.error,
                "enrich_finished_at": poe.now_iso()}}, upsert=True)
        finally:
            state.finish()

    asyncio.create_task(_runner())
    return {
        "status": "started",
        "source": source,
        "run_id": task_id,
        "limit": body.limit,
        "verdicts": verdicts,
        "do_geocode": body.do_geocode,
        "do_verify": body.do_verify,
        "use_agent": body.use_agent,
        "wrote_poe_ports": False,
    }


@router.get("/poe/seeds/enrich/status")
async def poe_seeds_enrich_status(run_id: str = "seed-enrich"):
    doc = await _db.poe_runs.find_one({"_id": run_id})
    if not doc:
        raise HTTPException(404, f"Run {run_id} unknown")
    out = {"run_id": run_id, "enrich": doc.get("enrich"),
           "enriched_at": doc.get("enriched_at"),
           "wrote_poe_ports": False}
    st = RUN_STATES.get(run_id)
    if st is not None:
        out["live"] = st.status()
    return out


@router.post("/poe/seeds/enrich/cancel")
async def poe_seeds_enrich_cancel(run_id: str = "seed-enrich"):
    st = RUN_STATES.get(run_id)
    if st is None or not st.running:
        raise HTTPException(409, f"Enrich {run_id} is not running")
    st.cancel = True
    st.log("Annulation enrich demandée — les graines restantes ne démarreront pas")
    return {"cancelling": True, "run_id": run_id}


@router.get("/poe/listing-control/review")
async def listing_control_review(run_id: str | None = None, reason: str | None = None,
                                 skip: int = 0, limit: int = 500):
    q: dict = {}
    if run_id:
        q["run_id"] = run_id
    if reason:
        q["reason"] = reason
    total = await _db.poe_listing_review.count_documents(q)
    docs = await _db.poe_listing_review.find(q).skip(skip).to_list(min(limit, 2000))
    return {"total": total, "skip": skip, "count": len(docs), "items": docs}


@router.get("/poe/runs/compare")
async def poe_runs_compare(run_ids: str, include_v1: bool = True):
    ids = [x.strip() for x in run_ids.split(",") if x.strip()]
    if not ids:
        raise HTTPException(400, "run_ids requis (csv)")
    for rid in ids:
        if not await _db.poe_runs.find_one({"_id": rid}):
            raise HTTPException(404, f"Run {rid} unknown")
    return await compare_runs(_db, ids, include_v1=include_v1)


@router.post("/poe/runs/best-of")
async def poe_runs_best_of(body: BestOfBody):
    if not body.run_ids:
        raise HTTPException(400, "run_ids requis")
    for rid in body.run_ids:
        if not await _db.poe_runs.find_one({"_id": rid}):
            raise HTTPException(404, f"Run {rid} unknown")
    summary = await synthesize_best_of(
        _db, body.run_ids, include_v1=body.include_v1, label=body.label)
    return {"status": "done", **summary}


@router.get("/poe/runs/{run_id}/status")
async def poe_run_status(run_id: str):
    doc = await _db.poe_runs.find_one({"_id": run_id})
    if not doc:
        raise HTTPException(404, f"Run {run_id} unknown")
    out = {"run": doc}
    st = RUN_STATES.get(run_id)
    if st is not None and st.running:
        out["live"] = st.status()
    return out


@router.post("/poe/runs/{run_id}/cancel")
async def poe_run_cancel(run_id: str):
    st = RUN_STATES.get(run_id)
    if st is None or not st.running:
        raise HTTPException(409, f"Run {run_id} is not running")
    st.cancel = True
    st.log("Annulation demandée — les zones restantes ne démarreront pas")
    return {"cancelling": True, "run_id": run_id}


@router.get("/poe/runs/{run_id}/ports")
async def poe_run_ports(run_id: str, mrgid: int | None = None):
    q: dict = {"run_id": run_id}
    if mrgid is not None:
        q["mrgid"] = mrgid
    docs = await _db.poe_run_ports.find(q).to_list(20000)
    return poe.ports_to_geojson(docs)


@router.get("/poe/runs/{run_id}/events")
async def poe_run_events(run_id: str, step: str | None = None, mrgid: int | None = None,
                         skip: int = 0, limit: int = 500):
    q: dict = {"run_id": run_id}
    if step:
        q["step"] = step
    if mrgid is not None:
        q["mrgid"] = mrgid
    total = await _db.poe_run_events.count_documents(q)
    docs = await _db.poe_run_events.find(q).sort("seq", 1).skip(skip).to_list(min(limit, 2000))
    return {"total": total, "skip": skip, "count": len(docs), "items": docs}


@router.get("/poe/runs/{run_id}/diff")
async def poe_run_diff(run_id: str, moved_km: float = 2.0, full: bool = False):
    if not await _db.poe_runs.find_one({"_id": run_id}):
        raise HTTPException(404, f"Run {run_id} unknown")
    diff = await diff_run_vs_baseline(_db, run_id, moved_km=moved_km)
    if not full:
        diff["matched"] = [m for m in diff["matched"] if m["flags"]][:200]
        diff["added"] = diff["added"][:200]
        diff["removed"] = diff["removed"][:200]
    return diff


@router.get("/poe/runs/{run_id}/report")
async def poe_run_report(run_id: str, format: str = "json"):
    if not await _db.poe_runs.find_one({"_id": run_id}):
        raise HTTPException(404, f"Run {run_id} unknown")
    t0 = time.time()
    rep = await build_run_report(_db, run_id)
    rep["built_in_s"] = round(time.time() - t0, 2)
    if format == "markdown":
        return PlainTextResponse(report_to_markdown(rep), media_type="text/markdown; charset=utf-8")
    return rep


@router.get("/poe/runs/{run_id}/listing-control")
async def poe_run_listing_control(run_id: str, restrict_to_run_zones: bool = True):
    if not await _db.poe_runs.find_one({"_id": run_id}):
        raise HTTPException(404, f"Run {run_id} unknown")
    return await build_listing_control_report(
        _db, run_id, restrict_to_run_zones=restrict_to_run_zones)


@router.post("/poe/runs/{run_id}/listing-control")
async def poe_run_listing_control_persist(run_id: str, restrict_to_run_zones: bool = True):
    if not await _db.poe_runs.find_one({"_id": run_id}):
        raise HTTPException(404, f"Run {run_id} unknown")
    report = await build_listing_control_report(
        _db, run_id, restrict_to_run_zones=restrict_to_run_zones)
    persisted = await persist_review(_db, report)
    return {"report": report, "persisted": persisted}
