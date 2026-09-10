"""app.routers.marinas — Marinas & mouillages : build (OSM/SHOM), imports/exports,
enrichissement IA à l'unité et par lot."""
import asyncio
import os
import time
import uuid

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import ROUTE_FILE
from app.core.llm import get_llm_key
from app.core.tasks import BuildState, TaskState, new_task, prune_tasks
from app.db import db, get_settings
from app.services.anchorage_build import build_anchorages as run_build_anchorages, anchorages_to_geojson
from app.services.marina_enrich import ENRICH_FIELDS, enrich_marina
from app.services.marina_maps_place import is_google_place_url, resolve_maps_places
from app.services.marina_world import (
    SLIM_PROJECTION,
    marinas_to_slim_geojson,
    official_website,
    build_world_marinas as run_build_world_marinas,
)
from app.services.swarm_pipeline import now_iso
from app.state import swarm

router = APIRouter(prefix="/api")

# ---------------------------------------------------------------------------
# Import — Marinas GeoJSON (2026-08-24 bug-fix: previously only projects had
# an import endpoint; the sidebar "Import GeoJSON" button silently sent
# marinas/formalities exports to the projects endpoint, discarding them).
# Accepts the `FeatureCollection` produced by `/api/export/marinas.geojson`.
# Each feature.properties.id is used as the Mongo `_id` for idempotent
# upserts, so re-importing the same file is a no-op (updated count grows,
# imported stays at 0).
# ---------------------------------------------------------------------------
@router.post("/import/marinas.geojson")
async def import_marinas_geojson(fc: dict = Body(...)):
    feats = fc.get("features") or []
    if fc.get("type") != "FeatureCollection" or not isinstance(feats, list) or not feats:
        raise HTTPException(400, "invalid GeoJSON FeatureCollection")
    imported = updated = invalid = 0
    for f in feats:
        try:
            geom = f.get("geometry") or {}
            if geom.get("type") != "Point":
                invalid += 1
                continue
            coords = geom.get("coordinates") or []
            if len(coords) < 2:
                invalid += 1
                continue
            lon, lat = float(coords[0]), float(coords[1])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                invalid += 1
                continue
            p = f.get("properties") or {}
            name = str(p.get("name") or "").strip()
            osm_id = p.get("osm_id")
            if not name and not osm_id:
                invalid += 1
                continue
            mid = str(p.get("id") or osm_id or "").strip() or str(uuid.uuid4())
            website = p.get("website") or official_website({"tags": p.get("tags") or {}})
            doc = {
                "_id": mid,
                "name": name,
                "lat": lat,
                "lon": lon,
                "source": p.get("source") or "openstreetmap",
                "tags": p.get("tags") or {},
                "osm_id": osm_id,
                "website": website,
                "website_status": p.get("website_status") or ("unchecked" if website else None),
                "website_source": p.get("website_source") or ("osm_tag" if website else None),
                "image": p.get("image"),
                "enriched": bool(p.get("enriched")),
                "enrichment_source": p.get("enrichment_source"),
                "enriched_at": p.get("enriched_at"),
                "stale": bool(p.get("stale")),
                "canal_vhf": p.get("canal_vhf"),
                "places_visiteurs": p.get("places_visiteurs"),
                "tirant_eau_max_metres": p.get("tirant_eau_max_metres"),
                "score_protection_meteo": p.get("score_protection_meteo"),
                "services_disponibles": p.get("services_disponibles"),
                "telephone_capitainerie": p.get("telephone_capitainerie"),
                "resume_avis": p.get("resume_avis"),
                "fetched_at": p.get("fetched_at") or now_iso(),
            }
            if p.get("priority") is not None:
                doc["priority"] = int(p["priority"])
            if p.get("nearest_waypoint"):
                doc["nearest_waypoint"] = p["nearest_waypoint"]
            place = p.get("maps_place_url")
            if is_google_place_url(place):
                doc["maps_place_url"] = place
                doc["maps_place_status"] = "found"
                doc["maps_place_source"] = p.get("maps_place_source") or "import"
            existing = await db.marinas.find_one({"_id": mid})
            if existing:
                await db.marinas.update_one({"_id": mid}, {"$set": doc})
                updated += 1
            else:
                await db.marinas.insert_one(doc)
                imported += 1
        except Exception:
            invalid += 1
    total = await db.marinas.count_documents({})
    swarm.log(f"Marinas GeoJSON import: {imported} imported, {updated} updated, {invalid} invalid", "success")
    return {"imported": imported, "merged": updated, "skipped_existing": 0, "invalid": invalid, "total_marinas": total}

# ---------- Marinas (Phase 2) ----------
MARINA_BUILD_STATE = BuildState()
# Phase 8 — Anchorages (Mouillages)
ANCHORAGE_BUILD_STATE = BuildState()


async def _all_marinas(q: dict | None = None, projection: dict | None = None) -> list[dict]:
    # Tri en Python (0.01 s) plutôt que Mongo : sur Atlas M0 le débit est le
    # facteur limitant, et batch_size réduit borne la durée de chaque lecture
    # socket (un batch 16 Mo par défaut peut dépasser le socketTimeoutMS).
    cur = db.marinas.find(q or {}, projection or SLIM_PROJECTION).batch_size(4000)
    docs = [doc async for doc in cur]
    docs.sort(key=lambda d: (d.get("name") or ""))
    return docs


@router.get("/marinas")
async def list_marinas(
    priority: int | None = None,
    source: str | None = None,
    visible: bool = False,
):
    q: dict = {}
    if priority is not None:
        q["priority"] = int(priority)
    if source:
        q["source"] = source
    if MARINA_BUILD_STATE.running:
        raise HTTPException(
            503,
            "marina dump running — skip full GeoJSON until the tile job finishes",
        )
    docs = await _all_marinas(q)
    if visible:
        from app.services.review_gold import filter_visible
        docs = await filter_visible(db, "marina", docs, lambda m: m.get("_id"))
    return marinas_to_slim_geojson(docs)


@router.get("/export/marinas.geojson")
async def export_marinas():
    from app.core.export_meta import export_response
    docs = await _all_marinas({})
    fc = marinas_to_slim_geojson(docs)
    return export_response(fc, "marinas", "marinas.geojson",
                           license_note="© OpenStreetMap contributors (ODbL)")

class MarinasBuildBody(BaseModel):
    clear_before: bool = False
    resume: bool = True
    profile: str | None = None
    rules: dict | None = None
    # Conservés pour ne pas casser les anciens clients / la carte Audit mouillages.
    radius_nm: float | None = None
    include_corridor: bool | None = None
    corridor_step_nm: float | None = None
    corridor_radius_nm: float | None = None
    maps_place_after: bool = False


async def _marina_rules_and_radii(body, settings: dict, extra_overrides: dict | None = None):
    from app.core.run_rules import RuleError, bind_rules, snapshot_for_run
    overrides = dict(body.rules or {})
    if extra_overrides:
        overrides.update({k: v for k, v in extra_overrides.items() if v is not None})
    try:
        rules = snapshot_for_run(mode="marinas", settings=settings,
                                 overrides=overrides or None, profile=body.profile)
    except RuleError as e:
        raise HTTPException(400, str(e)) from e
    bind_rules(rules)
    chosen = rules.get("chosen") or {}
    radius_nm = float(
        body.radius_nm
        if body.radius_nm is not None
        else chosen.get("marinas.waypoint_radius_nm", {}).get("value")
        or settings.get("marina_search_radius_nm")
        or 10.0
    )
    step = float(
        body.corridor_step_nm
        if body.corridor_step_nm is not None
        else chosen.get("marinas.corridor_step_nm", {}).get("value")
        or 25.0
    )
    rad = float(
        body.corridor_radius_nm
        if body.corridor_radius_nm is not None
        else chosen.get("marinas.corridor_radius_nm", {}).get("value")
        or 25.0
    )
    return rules, radius_nm, step, rad


async def _persist_marina_run(kind: str, rules: dict, extra: dict, *,
                              resume: bool = False, settings: dict | None = None,
                              rules_overrides: dict | None = None) -> dict:
    from app.services import isolated_runs
    opened = await isolated_runs.open_run(
        db, "marinas", kind=kind, label=f"marinas-{kind}",
        settings=settings or {}, extra_params=extra,
        profile=rules.get("profile"),
        rules_overrides=rules_overrides,
        resume=resume,
    )
    return opened


@router.post("/marinas/build")
async def marinas_build_start(body: MarinasBuildBody | None = None):
    if MARINA_BUILD_STATE.running:
        raise HTTPException(409, "A marinas build is already running")
    body = body or MarinasBuildBody()
    settings = await get_settings()
    rules, _radius_nm, _step, _rad = await _marina_rules_and_radii(body, settings)

    if body.clear_before:
        raise HTTPException(400, "clear_before is forbidden (shared.no_purge)")

    opened = await _persist_marina_run("marinas_world", rules, {
        "resume": body.resume,
        "profile": rules.get("profile"),
        "kind": "world_leisure_marina",
    }, resume=body.resume, settings=settings, rules_overrides=body.rules)
    run_id = opened["run_id"]
    MARINA_BUILD_STATE.run_id = run_id
    from app.services.isolated_runs import reset_run as _reset_iso
    from app.core.run_rules import bind_rules, reset_rules
    _reset_iso(opened["token"])

    async def _runner():
        from app.services import isolated_runs
        rules_token = bind_rules(rules)
        try:
            await run_build_world_marinas(
                marinas_coll=db.marina_run_marinas,
                cursor_coll=db.marina_run_cursors,
                state=MARINA_BUILD_STATE,
                resume=body.resume,
                run_id=run_id,
            )
            await isolated_runs.finalize_run(
                db, "marinas", run_id, extra=MARINA_BUILD_STATE.summary)
            if body.maps_place_after and not MAPS_PLACE_STATE.running:
                MARINA_BUILD_STATE.log("Dump terminé — résolution des fiches Google /place/")
                await resolve_maps_places(
                    marinas_coll=db.marina_run_marinas,
                    state=MAPS_PLACE_STATE,
                    skip_search=True,
                    extra_filter={"run_id": run_id},
                    run_id=run_id,
                    dest_db=db,
                )
        except Exception as e:
            await isolated_runs.finalize_run(
                db, "marinas", run_id, error=str(e)[:200])
        finally:
            reset_rules(rules_token)

    asyncio.create_task(_runner())
    return {
        "started": True,
        "run_id": run_id,
        "kind": "world_leisure_marina",
        "resume": body.resume,
        "maps_place_after": body.maps_place_after,
        "profile": rules.get("profile"),
        "rules_hash": rules.get("hash"),
        "wrote_marinas": False,
    }


@router.get("/marinas/build/status")
async def marinas_build_status():
    s = MARINA_BUILD_STATE
    return {
        "running": s.running,
        "started_at": s.started_at,
        "finished_at": s.finished_at,
        "progress": s.progress,
        "total": s.total,
        "summary": s.summary,
        "error": s.error,
        "logs_tail": s.logs[-40:],
        "run_id": s.run_id,
        "wrote_marinas": False,
    }


@router.get("/marinas/count")
async def marinas_count():
    async def _count(q: dict):
        try:
            return await db.marinas.count_documents(q, maxTimeMS=4000)
        except Exception:
            return None

    async def _est():
        try:
            return await db.marinas.estimated_document_count()
        except Exception:
            return None

    total, named, with_website, osm, shom, curated, enriched, place = await asyncio.gather(
        _est(),
        _count({"name": {"$nin": ["", None]}}),
        _count({"website": {"$nin": ["", None]}}),
        _count({"source": "openstreetmap"}),
        _count({"source": "shom"}),
        _count({"source": "curated"}),
        _count({"enriched": True}),
        _count({"maps_place_status": "found"}),
    )
    return {
        "total": total,
        "named": named,
        "with_website": with_website,
        "by_source": {
            "openstreetmap": osm,
            "shom": shom,
            "curated": curated,
        },
        "enriched": enriched,
        "with_google_place": place,
    }


# ---------- Anchorages (Phase 8 — Mouillages) ----------

class AnchoragesBuildBody(BaseModel):
    radius_nm: float | None = None
    clear_before: bool = False
    include_corridor: bool = True
    corridor_step_nm: float | None = None
    corridor_radius_nm: float | None = None
    profile: str | None = None
    rules: dict | None = None


@router.get("/anchorages")
async def list_anchorages(
    priority: int | None = None,
    anchorage_type: str | None = None,
):
    q: dict = {}
    if priority is not None:
        q["priority"] = int(priority)
    if anchorage_type:
        q["anchorage_type"] = anchorage_type
    docs = await db.anchorages.find(q).sort([("priority", 1), ("name", 1)]).to_list(20000)
    return anchorages_to_geojson(docs)


@router.get("/export/anchorages.geojson")
async def export_anchorages():
    from app.core.export_meta import export_response
    docs = await db.anchorages.find({}).sort([("priority", 1), ("name", 1)]).to_list(20000)
    fc = anchorages_to_geojson(docs)
    return export_response(fc, "anchorages", "anchorages.geojson",
                           license_note="© OpenStreetMap contributors (ODbL)")


@router.post("/anchorages/build")
async def anchorages_build_start(body: AnchoragesBuildBody | None = None):
    if ANCHORAGE_BUILD_STATE.running:
        raise HTTPException(409, "An anchorages build is already running")
    body = body or AnchoragesBuildBody()
    settings = await get_settings()
    extra = {}
    if body.corridor_step_nm is not None:
        extra["marinas.corridor_step_nm"] = body.corridor_step_nm
    if body.corridor_radius_nm is not None:
        extra["marinas.corridor_radius_nm"] = body.corridor_radius_nm
    if body.radius_nm is not None:
        extra["marinas.waypoint_radius_nm"] = body.radius_nm
    rules, radius_nm, step, rad = await _marina_rules_and_radii(body, settings, extra)

    if body.clear_before:
        raise HTTPException(400, "clear_before is forbidden (shared.no_purge)")

    opened = await _persist_marina_run("anchorages", rules, {
        "radius_nm": radius_nm,
        "include_corridor": body.include_corridor,
        "corridor_step_nm": step,
        "corridor_radius_nm": rad,
        "profile": rules.get("profile"),
    }, settings=settings, rules_overrides=body.rules)
    run_id = opened["run_id"]
    ANCHORAGE_BUILD_STATE.run_id = run_id
    from app.services.isolated_runs import reset_run as _reset_iso
    from app.core.run_rules import bind_rules, reset_rules
    _reset_iso(opened["token"])

    async def _runner():
        from app.services import isolated_runs
        rules_token = bind_rules(rules)
        try:
            await run_build_anchorages(
                anchorages_coll=db.marina_run_anchorages,
                route_path=ROUTE_FILE,
                radius_nm=radius_nm,
                state=ANCHORAGE_BUILD_STATE,
                include_corridor=body.include_corridor,
                corridor_step_nm=step,
                corridor_radius_nm=rad,
                run_id=run_id,
            )
            await isolated_runs.finalize_run(
                db, "marinas", run_id, extra=ANCHORAGE_BUILD_STATE.summary)
        except Exception as e:
            await isolated_runs.finalize_run(
                db, "marinas", run_id, error=str(e)[:200])
        finally:
            reset_rules(rules_token)

    asyncio.create_task(_runner())
    return {
        "started": True,
        "run_id": run_id,
        "radius_nm": radius_nm,
        "include_corridor": body.include_corridor,
        "corridor_step_nm": step,
        "corridor_radius_nm": rad,
        "corridor_band_nm": rad * 2,
        "profile": rules.get("profile"),
        "rules_hash": rules.get("hash"),
        "wrote_marinas": False,
        "wrote_anchorages": False,
    }


@router.get("/anchorages/build/status")
async def anchorages_build_status():
    s = ANCHORAGE_BUILD_STATE
    return {
        "running": s.running,
        "started_at": s.started_at,
        "finished_at": s.finished_at,
        "progress": s.progress,
        "total": s.total,
        "summary": s.summary,
        "error": s.error,
        "logs_tail": s.logs[-40:],
        "run_id": s.run_id,
        "wrote_marinas": False,
    }


@router.get("/anchorages/count")
async def anchorages_count():
    return {
        "total": await db.anchorages.count_documents({}),
        "by_priority": {
            "1": await db.anchorages.count_documents({"priority": 1}),
            "2": await db.anchorages.count_documents({"priority": 2}),
            "3": await db.anchorages.count_documents({"priority": 3}),
        },
        "by_type": {
            "anchorage": await db.anchorages.count_documents({"anchorage_type": "anchorage"}),
            "anchor_berth": await db.anchorages.count_documents({"anchorage_type": "anchor_berth"}),
            "bay": await db.anchorages.count_documents({"anchorage_type": "bay"}),
        },
    }


# ---------- Marina enrichment (Phase 3) ----------
# Per-id lock so the SAME marina can't be enriched concurrently.
ENRICH_LOCKS: set[str] = set()
# Per-id state registry for on-demand tasks (marinas + projects). Kept in-memory,
# TTL-cleaned when a new task starts.
MARINA_ENRICH_TASKS: dict[str, dict] = {}




class MarinaEnrichBatchBody(BaseModel):
    limit: int = 10   # 0 = toutes les marinas restantes (mode "Tout enchaîner")
    priority: int | None = None
    include_enriched: bool = False   # if True, re-enrich already-enriched ones
    stale_only: bool = False   # if True, filter to stale-only (needs enriched_at)
    profile: str | None = None
    rules: dict | None = None


ENRICH_BATCH_STATE = TaskState(max_logs=400)
MAPS_PLACE_STATE = TaskState(max_logs=400)


class MapsPlaceBody(BaseModel):
    limit: int = 0
    force: bool = False
    skip_search: bool = True
    profile: str | None = None
    rules: dict | None = None


_MARINA_ENGINE_LABELS = {
    "tinyfish": "TinyFish Agent",
    "fetch": "Fetch / regex",
    "nvidia": "NVIDIA NIM",
    "nvidia-deepseek": "NVIDIA DeepSeek",
    "nvidia-muse": "NVIDIA Muse",
    "nvidia-gpt-oss": "NVIDIA gpt-oss",
    "openrouter": "OpenRouter",
    "tags": "OSM tags",
    "fallback": "OSM Fallback",
}


async def _marina_telemetry(marina: dict, status: str, duration_ms: float, engine: str, results: int, detail: str):
    """Telemetry row tagged dataset=marinas so the Audit table tracks each enrichment."""
    tags = marina.get("tags") or {}
    target = tags.get("website") or tags.get("contact:website") or tags.get("url") or f"marina:{marina.get('name')}"
    await db.telemetry.insert_one({
        "_id": str(uuid.uuid4()), "url": target, "engine": engine, "status": status,
        "duration_ms": int(duration_ms), "results": results, "detail": str(detail)[:500],
        "ts": now_iso(), "dataset": "marinas",
    })


async def _run_marina_enrich_one(marina: dict, min_credit_usd: float, log_fn,
                                skip_tinyfish: bool = False, run_id: str | None = None) -> dict:
    """Run the enrichment chain. `run_id` → marina_run_marinas ; sinon carte live (fiche unitaire)."""
    settings = await get_settings()
    tf_key = (settings.get("tinyfish_api_key") or os.environ.get("TINYFISH_API_KEY") or "").strip() or None
    or_key = get_llm_key(settings) or None
    # Économie de crédits : après un échec TinyFish, on ne re-paye plus pour cette marina.
    skip_tf = skip_tinyfish or bool(marina.get("tinyfish_failed"))
    t0 = time.time()
    try:
        result = await enrich_marina(
            marina,
            tinyfish_key=tf_key,
            openrouter_key=or_key,
            min_credit_usd=min_credit_usd,
            logger=log_fn,
            skip_tinyfish=skip_tf,
            settings=settings,
        )
    except Exception as e:
        await _marina_telemetry(marina, "FAILED", (time.time() - t0) * 1000, "Enrichment", 0,
                                f"{marina.get('name')} — {type(e).__name__}: {e}")
        raise
    tf_attempted = result.pop("_tinyfish_attempted", False)
    update = {**result, "stale": False,
              "enrich_attempts": int(marina.get("enrich_attempts") or 0) + 1}
    if tf_attempted and result.get("enrichment_source") != "tinyfish":
        update["tinyfish_failed"] = True
    if run_id:
        from app.services.isolated_runs import write_item
        await write_item(
            db, "marinas", run_id, {**marina, **update},
            source_id=marina.get("source_id") or marina.get("osm_id") or marina.get("_id"),
        )
    else:
        await db.marinas.update_one({"_id": marina["_id"]}, {"$set": update})
    src = result.get("enrichment_source") or ""
    filled = [k for k in ENRICH_FIELDS if result.get(k) is not None]
    await _marina_telemetry(
        marina,
        "SUCCESS" if result.get("enriched") else "FAILED",
        (time.time() - t0) * 1000,
        _MARINA_ENGINE_LABELS.get(src, src or "?"),
        len(filled),
        f"{marina.get('name')} — champs: {', '.join(filled) or 'aucun'}",
    )
    return result


@router.post("/marinas/{marina_id}/enrich", status_code=202)
async def marina_enrich_one(marina_id: str):
    """
    Start marina enrichment as a background task and return 202 immediately.
    Poll GET /api/marinas/{marina_id}/enrich/status for progress/result.
    """
    if marina_id in ENRICH_LOCKS:
        raise HTTPException(409, "Enrichment already in progress for this marina")
    marina = await db.marinas.find_one({"_id": marina_id})
    if not marina:
        raise HTTPException(404, "marina not found")
    settings = await get_settings()
    min_credit = float(settings.get("openrouter_min_credits_usd") or 0.5)

    prune_tasks(MARINA_ENRICH_TASKS)
    ENRICH_LOCKS.add(marina_id)
    MARINA_ENRICH_TASKS[marina_id] = new_task()

    async def _runner():
        task = MARINA_ENRICH_TASKS[marina_id]

        def log_fn(msg: str):
            task["logs"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
            if len(task["logs"]) > 200:
                task["logs"] = task["logs"][-200:]

        try:
            await _run_marina_enrich_one(marina, min_credit, log_fn)
            fresh = await db.marinas.find_one({"_id": marina_id})
            task["result"] = {
                k: fresh.get(k) for k in (
                    "_id", "name", "lat", "lon", "source", "priority",
                    "nearest_waypoint", "tags", "osm_id", "enriched",
                    "enrichment_source", "enriched_at", "stale",
                    *ENRICH_FIELDS,
                )
            }
            task["state"] = "done"
        except Exception as e:
            task["error"] = f"{type(e).__name__}: {e}"
            task["state"] = "error"
        finally:
            task["finished_at"] = time.time()
            ENRICH_LOCKS.discard(marina_id)

    asyncio.create_task(_runner())
    return {"status": "started", "marina_id": marina_id}


@router.get("/marinas/{marina_id}/enrich/status")
async def marina_enrich_status(marina_id: str):
    """Poll the state of an on-demand marina enrichment. Returns 'idle' if no task."""
    task = MARINA_ENRICH_TASKS.get(marina_id)
    if not task:
        return {"state": "idle", "marina_id": marina_id}
    return {
        "state": task["state"],
        "marina_id": marina_id,
        "started_at": task["started_at"],
        "finished_at": task["finished_at"],
        "result": task["result"],
        "error": task["error"],
        "logs_tail": task["logs"][-30:],
    }


@router.post("/marinas/enrich-batch")
async def marina_enrich_batch(body: MarinaEnrichBatchBody | None = None):
    if ENRICH_BATCH_STATE.running:
        raise HTTPException(409, "A marinas enrichment batch is already running")
    body = body or MarinaEnrichBatchBody()
    settings = await get_settings()
    concurrency = int(settings.get("marina_batch_concurrency") or 2)
    min_credit = float(settings.get("openrouter_min_credits_usd") or 0.5)
    stale_days = int(settings.get("enrich_stale_days") or 365)

    # Selection query
    q: dict = {}
    if body.priority is not None:
        q["priority"] = int(body.priority)
    if body.stale_only:
        # cutoff timestamp
        cutoff = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() - stale_days * 86400),
        )
        q["$or"] = [{"enriched_at": {"$lt": cutoff}}, {"enriched": {"$ne": True}}]
    elif not body.include_enriched:
        q["$or"] = [{"enriched": {"$ne": True}}, {"enriched": False}]
        # Économie de crédits : après 2 tentatives échouées, la marina sort des lots
        # automatiques (toujours relançable à l'unité via son bouton Enrich).
        q["enrich_attempts"] = {"$not": {"$gte": 2}}

    limit = int(body.limit or 0)
    candidates = await db.marinas.find(q).sort([("priority", 1), ("name", 1)]).to_list(limit if limit > 0 else None)

    from app.core.run_rules import RuleError, snapshot_for_run
    try:
        rules = snapshot_for_run(
            mode="marinas", settings=settings,
            overrides=body.rules, profile=body.profile)
    except RuleError as e:
        raise HTTPException(400, str(e)) from e
    opened = await _persist_marina_run(
        "enrich", rules, {"limit": body.limit, "priority": body.priority},
        settings=settings, rules_overrides=body.rules)
    run_id = opened["run_id"]
    ENRICH_BATCH_STATE.run_id = run_id
    from app.services.isolated_runs import reset_run as _reset_iso
    _reset_iso(opened["token"])

    ENRICH_BATCH_STATE.running = True
    ENRICH_BATCH_STATE.started_at = time.time()
    ENRICH_BATCH_STATE.finished_at = None
    ENRICH_BATCH_STATE.progress = 0
    ENRICH_BATCH_STATE.total = len(candidates)
    ENRICH_BATCH_STATE.results = []
    ENRICH_BATCH_STATE.logs = []
    ENRICH_BATCH_STATE.error = None
    ENRICH_BATCH_STATE.cancel = False

    async def _runner():
        from app.core.run_rules import bind_rules, reset_rules
        rules_token = bind_rules(rules)
        try:
            ENRICH_BATCH_STATE.log(
                f"Selected {len(candidates)} marinas (concurrency={concurrency}, "
                f"limit={body.limit}, priority={body.priority}, min_credit=${min_credit})"
            )
            sem = asyncio.Semaphore(max(1, concurrency))
            counter = {"i": 0}

            async def _one(m):
                async with sem:
                    if ENRICH_BATCH_STATE.cancel:
                        ENRICH_BATCH_STATE.log(f"SKIP {m['name']}: batch annulé")
                        return
                    if m["_id"] in ENRICH_LOCKS:
                        ENRICH_BATCH_STATE.log(f"SKIP {m['name']}: already locked")
                        return
                    ENRICH_LOCKS.add(m["_id"])
                    ENRICH_BATCH_STATE.log(f"→ {m['name']} (P{m.get('priority')})")
                    per_logs: list[str] = []
                    try:
                        result = await _run_marina_enrich_one(
                            m, min_credit,
                            lambda s: (per_logs.append(s), ENRICH_BATCH_STATE.log(f"  {s}")),
                            run_id=run_id,
                        )
                        ENRICH_BATCH_STATE.results.append({
                            "id": m["_id"], "name": m["name"],
                            "source": result.get("enrichment_source"),
                            "enriched": result.get("enriched"),
                            "fields_filled": [k for k in ENRICH_FIELDS if result.get(k) is not None],
                        })
                    except Exception as e:
                        ENRICH_BATCH_STATE.log(f"  FAILED: {type(e).__name__}: {e}")
                        ENRICH_BATCH_STATE.results.append({
                            "id": m["_id"], "name": m["name"], "error": f"{type(e).__name__}: {e}",
                        })
                    finally:
                        ENRICH_LOCKS.discard(m["_id"])
                        counter["i"] += 1
                        ENRICH_BATCH_STATE.progress = counter["i"]

            await asyncio.gather(*(_one(m) for m in candidates))
            by_src = {"tinyfish": 0, "openrouter": 0, "fallback": 0}
            for r in ENRICH_BATCH_STATE.results:
                s = r.get("source")
                if s in by_src:
                    by_src[s] += 1
            ENRICH_BATCH_STATE.log(f"Done. Sources: {by_src}")
        except Exception as e:
            ENRICH_BATCH_STATE.error = f"{type(e).__name__}: {e}"
            ENRICH_BATCH_STATE.log(f"FATAL {ENRICH_BATCH_STATE.error}")
        finally:
            from app.services import isolated_runs
            from app.core.run_rules import reset_rules as _reset_rules
            await isolated_runs.finalize_run(
                db, "marinas", run_id,
                cancelled=ENRICH_BATCH_STATE.cancel,
                error=ENRICH_BATCH_STATE.error,
                extra={"results": len(ENRICH_BATCH_STATE.results)},
            )
            ENRICH_BATCH_STATE.finished_at = time.time()
            ENRICH_BATCH_STATE.running = False
            _reset_rules(rules_token)

    asyncio.create_task(_runner())
    return {
        "started": True, "selected": len(candidates), "concurrency": concurrency,
        "run_id": run_id, "wrote_marinas": False,
        "profile": rules.get("profile"), "rules_hash": rules.get("hash"),
    }


@router.post("/marinas/enrich-batch/cancel")
async def marina_enrich_batch_cancel():
    """Stop the running enrichment batch — remaining marinas are not launched."""
    if not ENRICH_BATCH_STATE.running:
        raise HTTPException(409, "No enrichment batch is running")
    ENRICH_BATCH_STATE.cancel = True
    ENRICH_BATCH_STATE.log("⛔ Stop demandé — les marinas restantes ne seront pas lancées")
    return {"cancelling": True}


@router.get("/marinas/enrich-batch/status")
async def marina_enrich_batch_status():
    s = ENRICH_BATCH_STATE
    return {
        "running": s.running,
        "cancelling": s.cancel,
        "started_at": s.started_at,
        "finished_at": s.finished_at,
        "progress": s.progress,
        "total": s.total,
        "results": s.results,
        "logs_tail": s.logs[-60:],
        "error": s.error,
        "run_id": s.run_id,
        "wrote_marinas": False,
    }


@router.post("/marinas/maps-place")
async def marinas_maps_place_start(body: MapsPlaceBody | None = None):
    if MAPS_PLACE_STATE.running:
        raise HTTPException(409, "A Google-place resolve is already running")
    body = body or MapsPlaceBody()
    settings = await get_settings()
    from app.core.run_rules import RuleError, snapshot_for_run
    try:
        rules = snapshot_for_run(
            mode="marinas", settings=settings,
            overrides=body.rules, profile=body.profile)
    except RuleError as e:
        raise HTTPException(400, str(e)) from e
    opened = await _persist_marina_run(
        "maps_place", rules,
        {"limit": body.limit, "force": body.force, "skip_search": body.skip_search},
        settings=settings, rules_overrides=body.rules)
    run_id = opened["run_id"]
    MAPS_PLACE_STATE.run_id = run_id
    from app.services.isolated_runs import reset_run as _reset_iso
    _reset_iso(opened["token"])

    async def _runner():
        from app.services import isolated_runs
        from app.core.run_rules import bind_rules, reset_rules
        rules_token = bind_rules(rules)
        try:
            await resolve_maps_places(
                marinas_coll=db.marinas,
                state=MAPS_PLACE_STATE,
                limit=int(body.limit or 0),
                force=bool(body.force),
                skip_search=bool(body.skip_search),
                run_id=run_id,
                dest_db=db,
            )
            await isolated_runs.finalize_run(
                db, "marinas", run_id, extra=MAPS_PLACE_STATE.summary)
        except Exception as exc:
            MAPS_PLACE_STATE.error = f"{type(exc).__name__}: {exc}"
            await isolated_runs.finalize_run(
                db, "marinas", run_id, error=MAPS_PLACE_STATE.error)
        finally:
            reset_rules(rules_token)

    asyncio.create_task(_runner())
    return {
        "started": True,
        "limit": body.limit,
        "force": body.force,
        "skip_search": body.skip_search,
        "run_id": run_id,
        "wrote_marinas": False,
        "profile": rules.get("profile"),
        "rules_hash": rules.get("hash"),
    }


@router.post("/marinas/maps-place/cancel")
async def marinas_maps_place_cancel():
    if not MAPS_PLACE_STATE.running:
        raise HTTPException(409, "No Google-place resolve is running")
    MAPS_PLACE_STATE.cancel = True
    MAPS_PLACE_STATE.log("Stop demandé")
    return {"cancelling": True}


@router.get("/marinas/maps-place/status")
async def marinas_maps_place_status():
    s = MAPS_PLACE_STATE
    return {
        "running": s.running,
        "cancelling": s.cancel,
        "started_at": s.started_at,
        "finished_at": s.finished_at,
        "progress": s.progress,
        "total": s.total,
        "summary": s.summary,
        "error": s.error,
        "logs_tail": s.logs[-40:],
        "run_id": s.run_id,
        "wrote_marinas": False,
    }


@router.get("/marinas/runs")
async def marinas_runs_list():
    from app.services import isolated_runs
    items = await isolated_runs.list_meta_runs(db, "marinas")
    return {
        "count": len(items),
        "wrote_marinas": False,
        "items": items,
    }


@router.get("/marinas/runs/{run_id}")
async def marinas_run_detail(run_id: str):
    from app.services import isolated_runs
    doc = await isolated_runs.get_meta_run(db, "marinas", run_id)
    if not doc:
        raise HTTPException(404, f"Run {run_id} unknown")
    return {**doc, "wrote_marinas": False}


@router.get("/marinas/runs/{run_id}/geojson")
async def marinas_run_geojson(run_id: str):
    """FeatureCollection du run — sélecteur de run de la carte.

    Les dumps live historiques (`wrote_marinas=true`) n'ont pas d'items
    isolés : on sert alors la collection live, qu'ils ont écrite.
    """
    meta = await db.marina_runs.find_one({"_id": run_id})
    if not meta:
        raise HTTPException(404, f"Run {run_id} unknown")
    docs = await db.marina_run_marinas.find(
        {"run_id": run_id}, SLIM_PROJECTION).to_list(50000)
    live_fallback = False
    if not docs and meta.get("wrote_marinas"):
        docs = await _all_marinas()
        live_fallback = True
    fc = marinas_to_slim_geojson(docs)
    fc["run_id"] = run_id
    fc["live_fallback"] = live_fallback
    return fc
