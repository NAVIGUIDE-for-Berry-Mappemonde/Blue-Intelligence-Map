"""app.routers.capitaineries — dump OSM harbour_master + overlay SHOM CATSCF=6,
enrichissement téléphone / VHF."""
import asyncio
import os
import time
import uuid

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.llm import get_llm_key
from app.core.tasks import BuildState, TaskState, new_task, prune_tasks
from app.db import db, get_settings
from app.services.capitainerie_enrich import (
    ENRICH_FIELDS,
    enrich_capitainerie,
    rank_enrich_candidates,
)
from app.services.capitainerie_world import (
    SLIM_PROJECTION,
    build_world_capitaineries as run_build,
    to_slim_geojson,
)
from app.services.marina_world import official_website
from app.services.swarm_pipeline import now_iso

router = APIRouter(prefix="/api")

BUILD_STATE = BuildState()
ENRICH_BATCH_STATE = TaskState(max_logs=400)
ENRICH_LOCKS: set[str] = set()
ENRICH_TASKS: dict[str, dict] = {}


async def _all_docs(q: dict | None = None, projection: dict | None = None) -> list[dict]:
    cur = db.capitaineries.find(q or {}, projection or SLIM_PROJECTION).sort("name", 1)
    return [doc async for doc in cur]


@router.post("/import/capitaineries.geojson")
async def import_capitaineries_geojson(fc: dict = Body(...)):
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
            shom_id = p.get("shom_id")
            if not name and not osm_id and not shom_id:
                invalid += 1
                continue
            mid = str(p.get("id") or osm_id or shom_id or "").strip() or str(uuid.uuid4())
            website = p.get("website") or official_website({"tags": p.get("tags") or {}})
            doc = {
                "_id": mid,
                "name": name,
                "lat": lat,
                "lon": lon,
                "source": p.get("source") or "openstreetmap",
                "sources": p.get("sources") or [p.get("source") or "openstreetmap"],
                "tags": p.get("tags") or {},
                "osm_id": osm_id,
                "shom_id": shom_id,
                "website": website,
                "website_status": p.get("website_status") or ("unchecked" if website else None),
                "website_source": p.get("website_source") or ("osm_tag" if website else None),
                "telephone": p.get("telephone"),
                "canal_vhf": p.get("canal_vhf"),
                "enriched": bool(p.get("enriched")),
                "enrichment_source": p.get("enrichment_source"),
                "enriched_at": p.get("enriched_at"),
                "stale": bool(p.get("stale")),
                "fetched_at": p.get("fetched_at") or now_iso(),
            }
            existing = await db.capitaineries.find_one({"_id": mid})
            if existing:
                await db.capitaineries.update_one({"_id": mid}, {"$set": doc})
                updated += 1
            else:
                await db.capitaineries.insert_one(doc)
                imported += 1
        except Exception:
            invalid += 1
    total = await db.capitaineries.count_documents({})
    return {
        "imported": imported, "merged": updated, "skipped_existing": 0,
        "invalid": invalid, "total_capitaineries": total,
    }


@router.get("/capitaineries")
async def list_capitaineries(source: str | None = None):
    q: dict = {}
    if source:
        q["source"] = source
    docs = await _all_docs(q)
    return to_slim_geojson(docs)


@router.get("/export/capitaineries.geojson")
async def export_capitaineries():
    docs = await _all_docs({})
    fc = to_slim_geojson(docs)
    return JSONResponse(
        fc,
        headers={"Content-Disposition": "attachment; filename=capitaineries.geojson"},
    )


class BuildBody(BaseModel):
    clear_before: bool = False
    resume: bool = True


@router.post("/capitaineries/build")
async def capitaineries_build_start(body: BuildBody | None = None):
    if BUILD_STATE.running:
        raise HTTPException(409, "A capitaineries build is already running")
    body = body or BuildBody()
    if body.clear_before:
        raise HTTPException(400, "clear_before is forbidden (shared.no_purge)")

    async def _runner():
        try:
            await run_build(
                coll=db.capitaineries,
                cursor_coll=db.capitainerie_world_cursor,
                state=BUILD_STATE,
                resume=body.resume,
            )
        except Exception as exc:
            BUILD_STATE.log(f"build crashed: {type(exc).__name__}: {exc}")

    asyncio.create_task(_runner())
    return {"started": True, "kind": "world_harbour_master", "resume": body.resume}


@router.get("/capitaineries/build/status")
async def capitaineries_build_status():
    s = BUILD_STATE
    return {
        "running": s.running,
        "started_at": s.started_at,
        "finished_at": s.finished_at,
        "progress": s.progress,
        "total": s.total,
        "summary": s.summary,
        "error": s.error,
        "logs_tail": s.logs[-40:],
        "cancelling": s.cancel and s.running,
    }


@router.post("/capitaineries/build/cancel")
async def capitaineries_build_cancel():
    if not BUILD_STATE.running:
        raise HTTPException(409, "No capitaineries build is running")
    BUILD_STATE.cancel = True
    BUILD_STATE.log("Stop demandé")
    return {"cancelling": True}


@router.get("/capitaineries/count")
async def capitaineries_count():
    return {
        "total": await db.capitaineries.count_documents({}),
        "named": await db.capitaineries.count_documents({"name": {"$nin": ["", None]}}),
        "with_phone": await db.capitaineries.count_documents({"telephone": {"$nin": ["", None]}}),
        "with_vhf": await db.capitaineries.count_documents({"canal_vhf": {"$nin": ["", None]}}),
        "with_website": await db.capitaineries.count_documents({"website": {"$nin": ["", None]}}),
        "by_source": {
            "openstreetmap": await db.capitaineries.count_documents({"source": "openstreetmap"}),
            "shom": await db.capitaineries.count_documents({"source": "shom"}),
            "osm+shom": await db.capitaineries.count_documents({"source": "osm+shom"}),
        },
        "enriched": await db.capitaineries.count_documents({"enriched": True}),
    }


class EnrichBatchBody(BaseModel):
    limit: int = 10
    include_enriched: bool = False


_ENGINE_LABELS = {
    "tinyfish": "TinyFish",
    "openrouter": "OpenRouter",
    "tags": "OSM/SHOM tags",
}


async def _telemetry(doc: dict, status: str, duration_ms: float, engine: str, results: int, detail: str):
    await db.telemetry.insert_one({
        "_id": str(uuid.uuid4()),
        "url": official_website(doc) or f"capitainerie:{doc.get('name')}",
        "engine": engine, "status": status,
        "duration_ms": int(duration_ms), "results": results,
        "detail": str(detail)[:500], "ts": now_iso(), "dataset": "capitaineries",
    })


async def _run_enrich_one(doc: dict, min_credit_usd: float, log_fn, skip_tinyfish: bool = False) -> dict:
    settings = await get_settings()
    tf_key = (settings.get("tinyfish_api_key") or os.environ.get("TINYFISH_API_KEY") or "").strip() or None
    or_key = get_llm_key(settings) or None
    skip_tf = skip_tinyfish or bool(doc.get("tinyfish_failed"))
    t0 = time.time()
    try:
        result = await enrich_capitainerie(
            doc,
            tinyfish_key=tf_key,
            openrouter_key=or_key,
            min_credit_usd=min_credit_usd,
            logger=log_fn,
            skip_tinyfish=skip_tf,
        )
    except Exception as e:
        await _telemetry(doc, "FAILED", (time.time() - t0) * 1000, "Enrichment", 0,
                         f"{doc.get('name')} — {type(e).__name__}: {e}")
        raise
    tf_attempted = result.pop("_tinyfish_attempted", False)
    update = {**result, "stale": False,
              "enrich_attempts": int(doc.get("enrich_attempts") or 0) + 1}
    if tf_attempted and result.get("enrichment_source") != "tinyfish":
        update["tinyfish_failed"] = True
    await db.capitaineries.update_one({"_id": doc["_id"]}, {"$set": update})
    src = result.get("enrichment_source") or ""
    filled = [k for k in ENRICH_FIELDS if result.get(k) is not None]
    await _telemetry(
        doc,
        "SUCCESS" if result.get("enriched") else "FAILED",
        (time.time() - t0) * 1000,
        _ENGINE_LABELS.get(src, src or "?"),
        len(filled),
        f"{doc.get('name')} — champs: {', '.join(filled) or 'aucun'}",
    )
    return result


@router.post("/capitaineries/{item_id}/enrich", status_code=202)
async def enrich_one(item_id: str):
    if item_id in ENRICH_LOCKS:
        raise HTTPException(409, "Enrichment already in progress")
    doc = await db.capitaineries.find_one({"_id": item_id})
    if not doc:
        raise HTTPException(404, "capitainerie not found")
    settings = await get_settings()
    min_credit = float(settings.get("openrouter_min_credits_usd") or 0.5)
    prune_tasks(ENRICH_TASKS)
    ENRICH_LOCKS.add(item_id)
    ENRICH_TASKS[item_id] = new_task()

    async def _runner():
        task = ENRICH_TASKS[item_id]

        def log_fn(msg: str):
            task["logs"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
            if len(task["logs"]) > 200:
                task["logs"] = task["logs"][-200:]

        try:
            await _run_enrich_one(doc, min_credit, log_fn)
            fresh = await db.capitaineries.find_one({"_id": item_id})
            task["result"] = {
                k: fresh.get(k) for k in (
                    "_id", "name", "lat", "lon", "source", "osm_id", "shom_id",
                    "enriched", "enrichment_source", "enriched_at", *ENRICH_FIELDS,
                )
            }
            task["state"] = "done"
        except Exception as e:
            task["error"] = f"{type(e).__name__}: {e}"
            task["state"] = "error"
        finally:
            task["finished_at"] = time.time()
            ENRICH_LOCKS.discard(item_id)

    asyncio.create_task(_runner())
    return {"status": "started", "id": item_id}


@router.get("/capitaineries/{item_id}/enrich/status")
async def enrich_status(item_id: str):
    task = ENRICH_TASKS.get(item_id)
    if not task:
        return {"state": "idle", "id": item_id}
    return {
        "state": task["state"], "id": item_id,
        "started_at": task["started_at"], "finished_at": task["finished_at"],
        "result": task["result"], "error": task["error"],
        "logs_tail": task["logs"][-30:],
    }


@router.post("/capitaineries/enrich-batch")
async def enrich_batch(body: EnrichBatchBody | None = None):
    if ENRICH_BATCH_STATE.running:
        raise HTTPException(409, "A capitaineries enrichment batch is already running")
    body = body or EnrichBatchBody()
    settings = await get_settings()
    concurrency = int(settings.get("marina_batch_concurrency") or 2)
    min_credit = float(settings.get("openrouter_min_credits_usd") or 0.5)

    q: dict = {}
    if not body.include_enriched:
        q["$or"] = [{"enriched": {"$ne": True}}, {"enriched": False}]
        q["enrich_attempts"] = {"$not": {"$gte": 2}}

    pool = await db.capitaineries.find(q).to_list(None)
    ranked = rank_enrich_candidates(pool)
    limit = int(body.limit or 0)
    candidates = ranked[:limit] if limit > 0 else ranked

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
        try:
            ENRICH_BATCH_STATE.log(
                f"Selected {len(candidates)} capitaineries (concurrency={concurrency})"
            )
            sem = asyncio.Semaphore(max(1, concurrency))
            counter = {"i": 0}

            async def _one(m):
                async with sem:
                    if ENRICH_BATCH_STATE.cancel:
                        ENRICH_BATCH_STATE.log(f"SKIP {m.get('name')}: batch annulé")
                        return
                    if m["_id"] in ENRICH_LOCKS:
                        ENRICH_BATCH_STATE.log(f"SKIP {m.get('name')}: already locked")
                        return
                    ENRICH_LOCKS.add(m["_id"])
                    ENRICH_BATCH_STATE.log(f"→ {m.get('name')}")
                    try:
                        result = await _run_enrich_one(
                            m, min_credit,
                            lambda s: ENRICH_BATCH_STATE.log(f"  {s}"),
                        )
                        ENRICH_BATCH_STATE.results.append({
                            "id": m["_id"], "name": m.get("name"),
                            "source": result.get("enrichment_source"),
                            "enriched": result.get("enriched"),
                            "fields_filled": [k for k in ENRICH_FIELDS if result.get(k) is not None],
                        })
                    except Exception as e:
                        ENRICH_BATCH_STATE.log(f"  FAILED: {type(e).__name__}: {e}")
                        ENRICH_BATCH_STATE.results.append({
                            "id": m["_id"], "name": m.get("name"),
                            "error": f"{type(e).__name__}: {e}",
                        })
                    finally:
                        ENRICH_LOCKS.discard(m["_id"])
                        counter["i"] += 1
                        ENRICH_BATCH_STATE.progress = counter["i"]

            await asyncio.gather(*(_one(m) for m in candidates))
            ENRICH_BATCH_STATE.log("Done.")
        except Exception as e:
            ENRICH_BATCH_STATE.error = f"{type(e).__name__}: {e}"
            ENRICH_BATCH_STATE.log(f"FATAL {ENRICH_BATCH_STATE.error}")
        finally:
            ENRICH_BATCH_STATE.finished_at = time.time()
            ENRICH_BATCH_STATE.running = False

    asyncio.create_task(_runner())
    return {"started": True, "selected": len(candidates), "concurrency": concurrency}


@router.post("/capitaineries/enrich-batch/cancel")
async def enrich_batch_cancel():
    if not ENRICH_BATCH_STATE.running:
        raise HTTPException(409, "No enrichment batch is running")
    ENRICH_BATCH_STATE.cancel = True
    ENRICH_BATCH_STATE.log("Stop demandé")
    return {"cancelling": True}


@router.get("/capitaineries/enrich-batch/status")
async def enrich_batch_status():
    s = ENRICH_BATCH_STATE
    return {
        "running": s.running, "cancelling": s.cancel,
        "started_at": s.started_at, "finished_at": s.finished_at,
        "progress": s.progress, "total": s.total,
        "results": s.results, "logs_tail": s.logs[-60:], "error": s.error,
    }
