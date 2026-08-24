import asyncio
import difflib
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")
ROUTE_FILE = ROOT_DIR / "data" / "route.geojson"

from fastapi import APIRouter, Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel

from ai import extract_project, gatekeeper_check
from categories import CATEGORY_GROUPS, normalize_category
from enrichment import ENRICH_FIELDS, enrich_marina, is_stale
from geo import haversine_km, is_ocean, ocean_fallback_coords, snap_to_ocean, geocode
from marinas import BuildState, build_marinas as run_build_marinas, marinas_to_geojson
from pipeline import Swarm, now_iso
from tinyfish_client import EXTRACT_SCHEMA, extract_goal, tf_run_sync

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]

app = FastAPI(title="Blue Intelligence API")
router = APIRouter(prefix="/api")
swarm = Swarm(db)

DEFAULT_SETTINGS = {
    "_id": "global",
    "gemini_api_key": "",
    "tinyfish_api_key": "",
    "tinyfish_agents": 2,
    "extract_concurrency": 6,
    "gatekeeper_model": "gemini-3-flash-preview",
    "extract_model": "gemini-3.1-pro-preview",
    "max_coast_km": 50,
    "min_marine_score": 0.5,
    "test_max_urls_per_seed": 6,
    "full_max_urls_per_seed": 20,
    "min_zoom": 2,
    "max_markers": 1000,
    "follow_the_money": True,
    "max_partner_orgs": 5,
    "saturation_limit": 50,
    "rescan_after_days": 7,
    "marina_search_radius_nm": 10.0,
    "marina_batch_concurrency": 2,
    "openrouter_min_credits_usd": 0.5,
    "enrich_stale_days": 365,
}


async def get_settings() -> dict:
    doc = await db.settings.find_one({"_id": "global"})
    merged = {**DEFAULT_SETTINGS, **(doc or {})}
    for k in ("gatekeeper_model", "extract_model"):
        if not str(merged.get(k, "")).startswith("gemini"):
            merged[k] = DEFAULT_SETTINGS[k]
    return merged


class DeployBody(BaseModel):
    mode: str = "test"
    clear_db: bool = False
    force_rescan: bool = False


class SettingsBody(BaseModel):
    gemini_api_key: str | None = None
    tinyfish_api_key: str | None = None
    tinyfish_agents: int | None = None
    extract_concurrency: int | None = None
    gatekeeper_model: str | None = None
    extract_model: str | None = None
    max_coast_km: float | None = None
    min_marine_score: float | None = None
    test_max_urls_per_seed: int | None = None
    full_max_urls_per_seed: int | None = None
    min_zoom: int | None = None
    max_markers: int | None = None
    follow_the_money: bool | None = None
    max_partner_orgs: int | None = None
    saturation_limit: int | None = None
    rescan_after_days: float | None = None
    marina_search_radius_nm: float | None = None
    marina_batch_concurrency: int | None = None
    openrouter_min_credits_usd: float | None = None
    enrich_stale_days: int | None = None


def project_to_feature(p: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
        "properties": {
            "id": p["_id"],
            "title": p["title"],
            "url": p["url"],
            "description": p.get("description", ""),
            "funder": ", ".join(p.get("funders") or [p.get("funder", "")]),
            "location": p.get("location"),
            "s_ocean": p.get("s_ocean"),
            "snapped": p.get("snapped", False),
            "image": p.get("image"),
            "category": p.get("category"),
            "category_group": p.get("category_group") or normalize_category(p.get("category")),
        },
    }


@router.get("/")
async def health():
    return {"service": "Blue Intelligence", "status": "operational", "ts": now_iso()}


@router.get("/projects")
async def get_projects(funder: str | None = None):
    q = {}
    if funder and funder != "All":
        q = {"funders": funder}
    docs = await db.projects.find(q).to_list(20000)
    return {"type": "FeatureCollection", "features": [project_to_feature(p) for p in docs]}


@router.get("/funders")
async def get_funders():
    docs = await db.projects.find({}, {"funders": 1}).to_list(20000)
    counts = {}
    for d in docs:
        for f in d.get("funders") or []:
            counts[f] = counts.get(f, 0) + 1
    return {"total": len(docs), "funders": [{"name": k, "count": v} for k, v in sorted(counts.items())]}


@router.delete("/projects")
async def clear_projects():
    res = await db.projects.delete_many({})
    swarm.log(f"All projects cleared ({res.deleted_count})", "warn")
    return {"deleted": res.deleted_count}


@router.get("/export/geojson")
async def export_geojson():
    docs = await db.projects.find({}).to_list(20000)
    fc = {"type": "FeatureCollection", "features": [project_to_feature(p) for p in docs]}
    return JSONResponse(fc, headers={"Content-Disposition": "attachment; filename=blue_intelligence_projects.geojson"})


@router.post("/swarm/deploy")
async def deploy(body: DeployBody):
    if body.mode not in ("test", "full"):
        raise HTTPException(400, "mode must be test|full")
    settings = await get_settings()
    try:
        await swarm.deploy(body.mode, body.clear_db, settings, body.force_rescan)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"status": "deployed", "mode": body.mode}


@router.post("/swarm/stop")
async def stop():
    await swarm.stop()
    return {"status": "stopped"}


@router.get("/swarm/status")
async def status():
    return swarm.status()


@router.get("/stats")
async def stats():
    total = await db.telemetry.count_documents({})
    success = await db.telemetry.count_documents({"status": {"$in": ["SUCCESS", "MERGED"]}})
    projects = await db.projects.count_documents({})
    return {"total_extractions": total, "success_rate": round(success / total * 100, 1) if total else 0.0,
            "projects_mapped": projects}


@router.get("/telemetry")
async def telemetry():
    docs = await db.telemetry.find({}).sort("ts", -1).to_list(200)
    for d in docs:
        d["id"] = d.pop("_id")
    return docs


@router.get("/failed")
async def failed():
    docs = await db.failed.find({}).sort("ts", -1).to_list(200)
    for d in docs:
        d["id"] = d.pop("_id")
    return docs


@router.delete("/audit")
async def clear_audit():
    t = await db.telemetry.delete_many({})
    f = await db.failed.delete_many({})
    return {"telemetry_deleted": t.deleted_count, "failed_deleted": f.deleted_count}


async def _force_extract_one(row: dict, settings: dict):
    key = (settings.get("tinyfish_api_key") or os.environ.get("TINYFISH_API_KEY") or "").strip()
    url = row["url"]
    aid = swarm.new_agent("TinyFish", "extract", url, row.get("source", ""))
    swarm.set_agent(aid, status="RUNNING")
    swarm.agent_log(aid, "Force extraction with TinyFish agent")
    t0 = time.time()
    try:
        body = await tf_run_sync(url, extract_goal(url), EXTRACT_SCHEMA, key)
        if body.get("status") != "COMPLETED" or not body.get("result"):
            raise ValueError(body.get("error") or f"run {body.get('status')}")
        res = body["result"]
        title = (res.get("title") or url)[:200]
        lat, lon = res.get("latitude"), res.get("longitude")
        if not Swarm._valid_coords(lat, lon):
            lat = lon = None
            if res.get("location"):
                g = await geocode(res["location"])
                if g:
                    lat, lon = g
            if lat is None:
                g = await geocode(title)
                if g:
                    lat, lon = g
            if lat is None:
                lat, lon = ocean_fallback_coords(title)
        snapped = False
        if not is_ocean(lat, lon):
            lat, lon, snapped = snap_to_ocean(lat, lon)
        existing = await db.projects.find_one({"url": url})
        if not existing:
            await db.projects.insert_one({
                "_id": str(uuid.uuid4()), "title": title, "url": url,
                "description": (res.get("description") or "")[:250],
                "funder": row.get("funder", ""), "funders": [row.get("funder", "")],
                "location": res.get("location"), "lat": float(lat), "lon": float(lon),
                "s_ocean": 0.7, "snapped": snapped, "geo_source": "tinyfish-force",
                "image": None, "engine": "TinyFish Force Extract", "created_at": now_iso(),
            })
        await db.failed.delete_one({"_id": row["_id"]})
        swarm.set_agent(aid, status="SUCCESS")
        swarm.log(f"Force extract OK: {title[:60]}", "success")
        await swarm.telemetry(url, "TinyFish", "SUCCESS", (time.time() - t0) * 1000, 1, "force extract")
    except Exception as e:
        swarm.set_agent(aid, status="FAILED")
        swarm.log(f"Force extract failed for {url[:60]}: {str(e)[:100]}", "error")
        await swarm.telemetry(url, "TinyFish", "FAILED", (time.time() - t0) * 1000, 0, str(e))


@router.post("/failed/{fid}/force")
async def force_one(fid: str):
    settings = await get_settings()
    key = (settings.get("tinyfish_api_key") or os.environ.get("TINYFISH_API_KEY") or "").strip()
    if not key:
        raise HTTPException(400, "TinyFish API key not configured")
    row = await db.failed.find_one({"_id": fid})
    if not row:
        raise HTTPException(404, "failed entry not found")
    asyncio.create_task(_force_extract_one(row, settings))
    return {"status": "started", "url": row["url"]}


@router.post("/failed/force-all")
async def force_all():
    settings = await get_settings()
    key = (settings.get("tinyfish_api_key") or os.environ.get("TINYFISH_API_KEY") or "").strip()
    if not key:
        raise HTTPException(400, "TinyFish API key not configured")
    rows = await db.failed.find({}).to_list(100)

    async def run_all():
        sem = asyncio.Semaphore(3)

        async def one(r):
            async with sem:
                await _force_extract_one(r, settings)
        await asyncio.gather(*[one(r) for r in rows])

    asyncio.create_task(run_all())
    return {"status": "started", "count": len(rows)}


@router.post("/import/geojson")
async def import_geojson(fc: dict = Body(...)):
    feats = fc.get("features") or []
    if fc.get("type") != "FeatureCollection" or not isinstance(feats, list) or not feats:
        raise HTTPException(400, "invalid GeoJSON FeatureCollection")
    existing = await db.projects.find({}, {"url": 1, "title": 1, "lat": 1, "lon": 1, "funders": 1}).to_list(50000)
    seen_urls = {e.get("url") for e in existing}
    grid = {}
    for e in existing:
        grid.setdefault((round(e["lat"], 1), round(e["lon"], 1)), []).append(e)
    imported = merged = invalid = skipped = 0
    docs = []
    for f in feats:
        try:
            geom = f.get("geometry") or {}
            if geom.get("type") != "Point":
                invalid += 1
                continue
            lon, lat = float(geom["coordinates"][0]), float(geom["coordinates"][1])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                invalid += 1
                continue
            p = f.get("properties") or {}
            title = str(p.get("title") or "").strip()
            url = str(p.get("url") or "").strip()
            if not title or not url:
                invalid += 1
                continue
            if url in seen_urls:
                # URL already imported — silent backfill of category/category_group if missing.
                incoming_cat = p.get("category")
                incoming_grp = p.get("category_group") or normalize_category(incoming_cat)
                if incoming_cat or incoming_grp:
                    update_set = {}
                    if incoming_cat:
                        update_set["category"] = incoming_cat
                    if incoming_grp:
                        update_set["category_group"] = incoming_grp
                    if update_set:
                        await db.projects.update_one(
                            {"url": url, "$or": [
                                {"category_group": {"$exists": False}},
                                {"category_group": None},
                                {"category_group": ""},
                                {"category_group": "Other"},
                            ]},
                            {"$set": update_set},
                        )
                skipped += 1
                continue
            s = p.get("s_ocean", p.get("s_ocean_score", p.get("relevance_score", 0.5)))
            try:
                s = float(s)
                s = round(s / 100, 3) if s > 1 else round(s, 3)
            except (TypeError, ValueError):
                s = 0.5
            funder = str(p.get("funder") or "Imported").strip() or "Imported"
            cell = (round(lat, 1), round(lon, 1))
            dup = None
            for e in grid.get(cell, []):
                if difflib.SequenceMatcher(None, title.lower(), e["title"].lower()).ratio() > 0.9:
                    dup = e
                    break
            if dup:
                funders = list(set((dup.get("funders") or []) + [funder]))
                update_set = {"funders": funders}
                # Backfill category & category_group on already-imported docs (fixes historical import loss)
                incoming_cat = p.get("category")
                incoming_grp = p.get("category_group") or normalize_category(incoming_cat)
                if incoming_cat and not dup.get("category"):
                    update_set["category"] = incoming_cat
                if incoming_grp and not dup.get("category_group"):
                    update_set["category_group"] = incoming_grp
                await db.projects.update_one({"_id": dup["_id"]}, {"$set": update_set})
                merged += 1
                seen_urls.add(url)
                continue
            doc = {
                "_id": str(uuid.uuid4()), "title": title[:200], "url": url,
                "description": str(p.get("description") or "")[:250],
                "funder": funder, "funders": [funder],
                "location": p.get("location"), "lat": lat, "lon": lon,
                "s_ocean": s, "snapped": bool(p.get("snapped") or p.get("snapped_coastal") or False),
                "geo_source": "import", "image": p.get("image") or p.get("image_url"),
                "category": p.get("category"),
                "category_group": p.get("category_group") or normalize_category(p.get("category")),
                "engine": "GeoJSON Import", "created_at": now_iso(),
            }
            docs.append(doc)
            seen_urls.add(url)
            grid.setdefault(cell, []).append({"_id": doc["_id"], "title": title, "lat": lat, "lon": lon, "funders": [funder]})
            imported += 1
        except Exception:
            invalid += 1
    if docs:
        await db.projects.insert_many(docs)
    total = await db.projects.count_documents({})
    swarm.log(f"GeoJSON import: {imported} imported, {merged} merged, {skipped} already known, {invalid} invalid", "success")
    return {"imported": imported, "merged": merged, "skipped_existing": skipped, "invalid": invalid, "total_projects": total}


@router.get("/categories")
async def get_categories():
    rows = await db.projects.aggregate([
        {"$group": {"_id": "$category_group", "n": {"$sum": 1}}},
    ]).to_list(50)
    counts = {r["_id"] or "Other": r["n"] for r in rows}
    return {"groups": [{"name": g, "color": c, "count": counts.get(g, 0)} for g, c in CATEGORY_GROUPS.items()]}


# ---------- Marinas (Phase 2) ----------
MARINA_BUILD_STATE = BuildState()


@router.get("/marinas")
async def list_marinas(
    priority: int | None = None,
    source: str | None = None,
):
    q: dict = {}
    if priority is not None:
        q["priority"] = int(priority)
    if source:
        q["source"] = source
    docs = await db.marinas.find(q).sort([("priority", 1), ("name", 1)]).to_list(20000)
    return marinas_to_geojson(docs)


@router.get("/export/marinas.geojson")
async def export_marinas():
    docs = await db.marinas.find({}).sort([("priority", 1), ("name", 1)]).to_list(20000)
    fc = marinas_to_geojson(docs)
    return JSONResponse(
        fc,
        headers={"Content-Disposition": "attachment; filename=marinas.geojson"},
    )


@router.get("/export/route.geojson")
async def export_route():
    if not ROUTE_FILE.exists():
        raise HTTPException(404, "route.geojson not found")
    import json as _json
    data = _json.loads(ROUTE_FILE.read_text(encoding="utf-8"))
    return JSONResponse(
        data,
        headers={"Content-Disposition": "attachment; filename=route.geojson"},
    )


class MarinasBuildBody(BaseModel):
    radius_nm: float | None = None
    clear_before: bool = False
    include_corridor: bool = True
    corridor_step_nm: float = 100.0


@router.post("/marinas/build")
async def marinas_build_start(body: MarinasBuildBody | None = None):
    if MARINA_BUILD_STATE.running:
        raise HTTPException(409, "A marinas build is already running")
    body = body or MarinasBuildBody()
    settings = await get_settings()
    radius_nm = float(body.radius_nm or settings.get("marina_search_radius_nm") or 10.0)

    if body.clear_before:
        await db.marinas.delete_many({})

    async def _runner():
        try:
            await run_build_marinas(
                marinas_coll=db.marinas,
                route_path=ROUTE_FILE,
                radius_nm=radius_nm,
                state=MARINA_BUILD_STATE,
                include_corridor=body.include_corridor,
                corridor_step_nm=body.corridor_step_nm,
            )
        except Exception:
            pass

    asyncio.create_task(_runner())
    return {"started": True, "radius_nm": radius_nm, "include_corridor": body.include_corridor}


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
    }


@router.get("/marinas/count")
async def marinas_count():
    return {
        "total": await db.marinas.count_documents({}),
        "by_priority": {
            "1": await db.marinas.count_documents({"priority": 1}),
            "2": await db.marinas.count_documents({"priority": 2}),
            "3": await db.marinas.count_documents({"priority": 3}),
        },
        "by_source": {
            "openstreetmap": await db.marinas.count_documents({"source": "openstreetmap"}),
            "shom": await db.marinas.count_documents({"source": "shom"}),
            "curated": await db.marinas.count_documents({"source": "curated"}),
        },
        "enriched": await db.marinas.count_documents({"enriched": True}),
    }


# ---------- Marina enrichment (Phase 3) ----------
# Per-id lock so the SAME marina can't be enriched concurrently.
ENRICH_LOCKS: set[str] = set()


class MarinaEnrichBatchBody(BaseModel):
    limit: int = 10
    priority: int | None = None
    include_enriched: bool = False   # if True, re-enrich already-enriched ones
    stale_only: bool = False   # if True, filter to stale-only (needs enriched_at)


class EnrichBatchState:
    """Progress state for the running batch."""
    def __init__(self):
        self.running: bool = False
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.progress: int = 0
        self.total: int = 0
        self.results: list[dict] = []
        self.logs: list[str] = []
        self.error: str | None = None

    def log(self, msg: str):
        self.logs.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        if len(self.logs) > 400:
            self.logs = self.logs[-400:]


ENRICH_BATCH_STATE = EnrichBatchState()


def _keys() -> tuple[str | None, str | None]:
    return (
        (os.environ.get("TINYFISH_API_KEY") or "").strip() or None,
        (os.environ.get("OPENROUTER_API_KEY") or "").strip() or None,
    )


async def _run_marina_enrich_one(marina: dict, min_credit_usd: float, log_fn) -> dict:
    """Run the enrichment chain and upsert the enriched fields on the marina doc."""
    tf_key, or_key = _keys()
    result = await enrich_marina(
        marina,
        tinyfish_key=tf_key,
        openrouter_key=or_key,
        min_credit_usd=min_credit_usd,
        logger=log_fn,
    )
    update = {**result, "stale": False}
    await db.marinas.update_one({"_id": marina["_id"]}, {"$set": update})
    return result


@router.post("/marinas/{marina_id}/enrich")
async def marina_enrich_one(marina_id: str):
    if marina_id in ENRICH_LOCKS:
        raise HTTPException(409, "Enrichment already in progress for this marina")
    marina = await db.marinas.find_one({"_id": marina_id})
    if not marina:
        raise HTTPException(404, "marina not found")
    settings = await get_settings()
    min_credit = float(settings.get("openrouter_min_credits_usd") or 0.5)
    ENRICH_LOCKS.add(marina_id)
    logs: list[str] = []

    def log_fn(msg: str):
        logs.append(f"[{time.strftime('%H:%M:%S')}] {msg}")

    try:
        result = await _run_marina_enrich_one(marina, min_credit, log_fn)
        # Return the updated document merged with the enrichment result
        fresh = await db.marinas.find_one({"_id": marina_id})
        return {
            "ok": True,
            "marina": {
                **{k: fresh.get(k) for k in (
                    "_id", "name", "lat", "lon", "source", "priority",
                    "nearest_waypoint", "tags", "osm_id", "enriched",
                    "enrichment_source", "enriched_at", "stale",
                    *ENRICH_FIELDS,
                )},
            },
            "logs": logs,
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "logs": logs}
    finally:
        ENRICH_LOCKS.discard(marina_id)


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

    candidates = await db.marinas.find(q).sort([("priority", 1), ("name", 1)]).to_list(int(body.limit) or 10)

    ENRICH_BATCH_STATE.running = True
    ENRICH_BATCH_STATE.started_at = time.time()
    ENRICH_BATCH_STATE.finished_at = None
    ENRICH_BATCH_STATE.progress = 0
    ENRICH_BATCH_STATE.total = len(candidates)
    ENRICH_BATCH_STATE.results = []
    ENRICH_BATCH_STATE.logs = []
    ENRICH_BATCH_STATE.error = None

    async def _runner():
        try:
            ENRICH_BATCH_STATE.log(
                f"Selected {len(candidates)} marinas (concurrency={concurrency}, "
                f"limit={body.limit}, priority={body.priority}, min_credit=${min_credit})"
            )
            sem = asyncio.Semaphore(max(1, concurrency))
            counter = {"i": 0}

            async def _one(m):
                async with sem:
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
            ENRICH_BATCH_STATE.finished_at = time.time()
            ENRICH_BATCH_STATE.running = False

    asyncio.create_task(_runner())
    return {"started": True, "selected": len(candidates), "concurrency": concurrency}


@router.get("/marinas/enrich-batch/status")
async def marina_enrich_batch_status():
    s = ENRICH_BATCH_STATE
    return {
        "running": s.running,
        "started_at": s.started_at,
        "finished_at": s.finished_at,
        "progress": s.progress,
        "total": s.total,
        "results": s.results,
        "logs_tail": s.logs[-60:],
        "error": s.error,
    }


# ---------- On-demand project enrich (Phase 3) ----------
@router.post("/projects/{project_id}/enrich")
async def project_enrich_one(project_id: str):
    """
    Re-run the extraction chain on a single project's URL and update the doc in place.
    Uses the same TinyFish → OpenRouter fallback that pipeline._process_url uses,
    but scoped to this project only. Returns the updated project + logs.
    """
    proj = await db.projects.find_one({"_id": project_id})
    if not proj:
        raise HTTPException(404, "project not found")
    url = proj.get("url")
    if not url:
        raise HTTPException(400, "project has no URL")
    settings = await get_settings()
    logs: list[str] = []

    def log_fn(msg: str):
        logs.append(f"[{time.strftime('%H:%M:%S')}] {msg}")

    log_fn(f"Refreshing {url}")

    # Import inside — pipeline dependencies are heavy
    import httpx as _httpx
    from bs4 import BeautifulSoup as _BS
    from readability import Document as _Doc
    from ai import extract_project as _extract, gatekeeper_check as _gk
    from pipeline import UA as _UA, pick_image as _pick_image

    try:
        async with _httpx.AsyncClient(timeout=25, follow_redirects=True, headers=_UA) as c:
            r = await c.get(url)
            html = r.text
        doc = _Doc(html)
        page_title = (doc.short_title() or "").strip() or proj.get("title") or url
        summary_html = doc.summary()
        soup = _BS(summary_html, "html.parser")
        import re as _re
        text = _re.sub(r"\s+", " ", soup.get_text(" ")).strip()
        full = _BS(html, "html.parser")
        if len(text) < 200:
            text = _re.sub(r"\s+", " ", full.get_text(" ")).strip()[:8000]
        meta = full.find("meta", attrs={"name": "description"}) or full.find("meta", attrs={"property": "og:description"})
        meta_desc = meta.get("content", "").strip() if meta else ""
        image = _pick_image(full, soup, url)
        log_fn(f"Fetched + Readability: {len(text)} chars")
        gk = await _gk(page_title, text, settings)
        if not gk["accepted"]:
            log_fn(f"Gatekeeper REJECTED: {gk['reason'][:80]}")
            return {"ok": False, "error": f"gatekeeper: {gk['reason']}", "logs": logs}
        funder = proj.get("funder") or (proj.get("funders") or ["Unknown"])[0]
        extracted = await _extract(page_title, text, meta_desc, url, funder, settings)
        log_fn(f"Extraction engine={extracted.get('engine')}, title='{(extracted.get('title') or '')[:60]}'")

        update: dict = {}
        # Only overwrite when the new value looks meaningful and different
        for field, key in [
            ("title", "title"),
            ("description", "description"),
            ("location", "location"),
            ("category", "category"),
        ]:
            new_v = extracted.get(key)
            if new_v and str(new_v).strip() and str(new_v) != str(proj.get(field) or ""):
                update[field] = str(new_v).strip()[:250 if field == "description" else 200]
        if extracted.get("category"):
            update["category_group"] = normalize_category(extracted["category"])
        # New image only if we didn't have one OR the extracted one is different + valid
        if image and (not proj.get("image") or image != proj.get("image")):
            update["image"] = image
        # S_ocean: overwrite if the new one is a valid float
        try:
            new_s = extracted.get("s_ocean")
            if new_s is not None:
                update["s_ocean"] = round(float(new_s), 3)
        except (TypeError, ValueError):
            pass
        update["enriched"] = True
        update["enriched_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        update["enrichment_source"] = extracted.get("engine", "unknown")
        await db.projects.update_one({"_id": project_id}, {"$set": update})
        log_fn(f"Updated fields: {list(update.keys())}")
        fresh = await db.projects.find_one({"_id": project_id})
        return {"ok": True, "project": project_to_feature(fresh), "updates": list(update.keys()), "logs": logs}
    except Exception as e:
        log_fn(f"FAILED: {type(e).__name__}: {str(e)[:200]}")
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "logs": logs}


class ReportBody(BaseModel):
    name: str
    url: str
    description: str = ""


@router.post("/report-project")
async def report_project(body: ReportBody):
    name, url = body.name.strip(), body.url.strip()
    if not name or not url.startswith("http"):
        raise HTTPException(400, "name required and url must start with http(s)")
    rid = str(uuid.uuid4())
    email_status = "skipped"
    resend_key = (os.environ.get("RESEND_API_KEY") or "").strip()
    if resend_key:
        try:
            import resend
            resend.api_key = resend_key
            params = {
                "from": os.environ.get("SENDER_EMAIL", "onboarding@resend.dev"),
                "to": [os.environ.get("REPORT_RECIPIENT", "clementfilisetti@berrymappemonde.org")],
                "subject": f"[Blue Intelligence] Projet signalé : {name[:80]}",
                "html": f"""<table style="font-family:Arial,sans-serif;max-width:560px;"><tr><td>
<h2 style="color:#0284c7;">🌊 Nouveau projet signalé sur Blue Intelligence</h2>
<p><b>Nom du projet :</b> {name}</p>
<p><b>URL :</b> <a href="{url}">{url}</a></p>
<p><b>Description :</b><br/>{(body.description or '—')[:1000]}</p>
<p style="color:#64748b;font-size:12px;">Ce projet a été ajouté automatiquement à la file d'attente du Swarm et sera analysé lors du prochain run.</p>
</td></tr></table>""",
            }
            result = await asyncio.to_thread(resend.Emails.send, params)
            email_status = "sent" if result.get("id") else "failed"
        except Exception as e:
            email_status = f"failed: {str(e)[:120]}"
    await db.reported_projects.insert_one({
        "_id": rid, "name": name, "url": url, "description": body.description[:1000],
        "status": "queued", "email_status": email_status, "ts": now_iso(),
    })
    await db.deeplink_pages.update_one(
        {"url": url},
        {"$set": {"url": url, "funder": "Community Report", "source": "user-report", "ts": now_iso()},
         "$setOnInsert": {"_id": str(uuid.uuid4())}},
        upsert=True,
    )
    queued_now = False
    if swarm.running and swarm.queue is not None:
        swarm.queued_count += 1
        await swarm.queue.put({"url": url, "funder": "Community Report", "source": "user-report", "depth": 1})
        queued_now = True
    swarm.log(f"Community report: '{name[:50]}' → {'queue (live)' if queued_now else 'DeepLinkCache (next run)'}", "success")
    return {"id": rid, "status": "queued_now" if queued_now else "queued_next_run", "email_status": email_status}


@router.get("/reports")
async def get_reports():
    docs = await db.reported_projects.find({}).sort("ts", -1).to_list(100)
    for d in docs:
        d["id"] = d.pop("_id")
    return docs


ARCGIS_MPA_URL = "https://services9.arcgis.com/lm7wE8a9YA9rKfzy/arcgis/rest/services/Navigator_AllSites_010925_attributes/FeatureServer/0/query"
MPA_FIELDS = ["SITE_ID", "site_name", "url", "country", "designation", "category_name", "managing_authority", "lfp", "protection_focus"]


@router.get("/mpa")
async def get_mpa(bbox: str):
    try:
        min_lon, min_lat, max_lon, max_lat = [float(x) for x in bbox.split(",")]
    except ValueError:
        raise HTTPException(400, "bbox must be minLon,minLat,maxLon,maxLat")
    key = f"{round(min_lon, 1)},{round(min_lat, 1)},{round(max_lon, 1)},{round(max_lat, 1)}"
    offset = max(0.005, round((max_lon - min_lon) / 500, 4))
    key = f"{key}|{offset}"
    cached = await db.mpa_cache.find_one({"_id": key})
    if cached:
        age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(cached["ts"])).total_seconds() / 86400
        if age_days < 3:
            return JSONResponse(cached["geojson"])
    params = {
        "where": "1=1",
        "geometry": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326", "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*", "f": "geojson",
        "resultRecordCount": "250",
        "maxAllowableOffset": str(offset),
        "geometryPrecision": "4",
    }
    import httpx as _httpx
    try:
        async with _httpx.AsyncClient(timeout=90) as c:
            r = await c.get(ARCGIS_MPA_URL, params=params, headers={"Accept-Encoding": "gzip"})
            data = r.json()
    except Exception as e:
        raise HTTPException(502, f"ProtectedSeas upstream error: {str(e)[:100]}")
    if "features" not in data:
        raise HTTPException(502, f"ProtectedSeas query error: {str(data.get('error'))[:150]}")
    feats = []
    for f in data["features"]:
        p = f.get("properties") or {}
        try:
            lfp = int(float(p.get("lfp") or 0))
        except (TypeError, ValueError):
            lfp = 0
        feats.append({
            "type": "Feature",
            "geometry": f["geometry"],
            "properties": {
                "ps_id": p.get("SITE_ID"),
                "site_name": p.get("site_name"),
                "url": p.get("url"),
                "country": p.get("country"),
                "designation": p.get("designation"),
                "category_name": p.get("category_name"),
                "managing_authority": p.get("managing_authority"),
                "protection_focus": p.get("protection_focus"),
                "lfp": lfp,
            },
        })
    fc = {"type": "FeatureCollection", "features": feats,
          "attribution": "The ProtectedSeas Navigator Map of Conservation Regulations, ProtectedSeas®, https://map.navigatormap.org — CC BY 4.0"}
    await db.mpa_cache.update_one({"_id": key}, {"$set": {"geojson": fc, "ts": now_iso()}}, upsert=True)
    return JSONResponse(fc)


@router.get("/settings")
async def read_settings():
    s = await get_settings()
    s.pop("_id", None)
    if s.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY") or os.environ.get("EMERGENT_LLM_KEY"):
        s["gemini_api_key_set"] = True
        s["gemini_api_key"] = ""
    else:
        s["gemini_api_key_set"] = False
    s.pop("anthropic_api_key", None)
    if s.get("tinyfish_api_key") or os.environ.get("TINYFISH_API_KEY"):
        s["tinyfish_api_key_set"] = True
        s["tinyfish_api_key"] = ""
    else:
        s["tinyfish_api_key_set"] = False
    return s


@router.put("/settings")
async def write_settings(body: SettingsBody):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    for k in ("gemini_api_key", "tinyfish_api_key"):
        if k in updates and updates[k] == "":
            del updates[k]
    if updates:
        await db.settings.update_one({"_id": "global"}, {"$set": updates}, upsert=True)
    return await read_settings()


MANUALS = {
    "en": """# Blue Intelligence — User Manual

## Overview
Blue Intelligence transforms the living web of maritime data into an executable geospatial database.
TinyFish agents discover project pages on foundation portals; Readability + Gemini extract, filter (Gatekeeper Protocol) and score each project (S_ocean); results are mapped live and exportable as GeoJSON.

## Map View (default)
- **World map**: single-world Leaflet dark map (light/dark toggle in the header ☀/🌙). Markers are colored by category and clustered.
- **Popup**: click a marker → photo, title, funder, category, description, S_ocean score, "View project" link and a **Donate** button. The popup always stays fully on screen without moving the map.
- **Left sidebar**:
  - *Legend*: 9 color-coded categories (MPA, Conservation, Research, Fisheries, Policy & Advocacy, Pollution, Coastal & Habitat, Education, Other). Click a category to filter the map.
  - *Organization filter* and *Category filter* dropdowns.
  - *Instant search* across titles, descriptions, funders and locations.
  - *Project list* with Donate buttons and source links.
  - *"Missing project?"*: report a project we missed (name, URL, description). It is emailed to the Blue Intelligence team and queued for the next Swarm run.

## Donations (Global Pot)
The header shows the global donation counter in euros. Click **Donate** on any project, pick an amount (5–100 €) and pay through Stripe. Sandbox mode: test card 4242 4242 4242 4242.

## Swarm Intelligence Audit (header toggle)
Operator console:
- **Swarm Controls**: Test mode (3 foundations) or Full mode (all MasterSeeds + DeepLinkCache), "clear DB before start", Deploy / Stop buttons, live log stream.
- **Live Swarm Console**: one card per agent (TinyFish discover / Readability extract) with status, live-view link and stream logs.
- **Auto-Stop**: the swarm shuts down gracefully after N consecutive extractions without a new unique project (default 50) to save credits.
- **Follow the Money**: agents detect partner/grantee NGOs on project pages and recursively queue their sites.
- **KPIs**: total extractions, success rate, projects mapped.
- **Telemetry table** and **Failed extractions** with per-URL Force Extract (TinyFish) or Force Extract All.

## Settings (right panel, gear icon)
- **Documentation**: download this manual (EN/FR).
- **Data**: Import GeoJSON (validates coordinates, counts and merges duplicates), Export GeoJSON, Clear all projects.
- **Marine filtering**: max coast distance (km), minimum marine score.
- **Extraction**: parallel TinyFish agents (1-2), extraction concurrency (1-20), Gemini model per stage (Gatekeeper / Extraction+Scoring), Follow the Money toggle, Auto-Stop limit.
- **Map**: minimum zoom, max markers.
- **API keys**: TinyFish and Gemini (stored server-side, never exposed).

## Pipeline (how it works)
1. **Discovery**: TinyFish web agents navigate foundation portals (SSE live streaming, polling fallback, crawler fallback).
2. **Extraction**: Readability cleans the page → Gemini Gatekeeper rejects terrestrial/freshwater projects → Gemini extracts title, description (<250 chars), location, category, partners and S_ocean score.
3. **Geocoding**: extracted GPS → Nominatim → Gemini smart geocoding → Point-in-Ocean test → coastal snapping when inland.
4. **Deduplication**: URL match, spatial proximity (<500 m) + title similarity (>90%) → funders merged.
""",
    "fr": """# Blue Intelligence — Manuel utilisateur

## Vue d'ensemble
Blue Intelligence transforme le web vivant des données maritimes en base géospatiale exploitable.
Les agents TinyFish découvrent les fiches projets sur les portails des fondations ; Readability + Gemini extraient, filtrent (Protocole Gatekeeper) et notent chaque projet (S_ocean) ; les résultats sont cartographiés en direct et exportables en GeoJSON.

## Vue Carte (par défaut)
- **Carte mondiale** : carte Leaflet sombre à monde unique (bascule clair/sombre dans l'en-tête ☀/🌙). Marqueurs colorés par catégorie et regroupés en clusters.
- **Popup** : cliquer un marqueur → photo, titre, financeur, catégorie, description, score S_ocean, lien « Voir le projet » et bouton **Donner**. L'encadré reste toujours entièrement visible sans déplacer la carte.
- **Bandeau gauche** :
  - *Légende* : 9 catégories colorées (AMP, Conservation, Recherche, Pêcheries, Politique & Plaidoyer, Pollution, Côtes & Habitats, Éducation, Autre). Cliquer une catégorie filtre la carte.
  - Menus *Filtre par organisation* et *Filtre par catégorie*.
  - *Recherche instantanée* sur titres, descriptions, financeurs et lieux.
  - *Liste des projets* avec boutons Donner et liens sources.
  - *« Projet manquant ? »* : signaler un projet oublié (nom, URL, description). Un email est envoyé à l'équipe Blue Intelligence et le projet est mis en file pour le prochain run du Swarm.

## Dons (Cagnotte globale)
L'en-tête affiche le compteur global de dons en euros. Cliquez **Donner** sur un projet, choisissez un montant (5–100 €) et payez via Stripe. Mode sandbox : carte de test 4242 4242 4242 4242.

## Audit Swarm Intelligence (bascule dans l'en-tête)
Console opérateur :
- **Contrôles du Swarm** : mode Test (3 fondations) ou Complet (tous les MasterSeeds + DeepLinkCache), « vider la base avant de démarrer », boutons Déployer / Arrêter, flux de logs en direct.
- **Console Swarm en direct** : une carte par agent (découverte TinyFish / extraction Readability) avec statut, lien « Voir l'agent » et logs.
- **Auto-Stop** : le swarm s'arrête proprement après N extractions consécutives sans nouveau projet unique (50 par défaut) pour économiser les crédits.
- **Follow the Money** : les agents détectent les ONG partenaires/bénéficiaires sur les pages et explorent récursivement leurs sites.
- **KPIs** : extractions totales, taux de succès, projets cartographiés.
- **Table de télémétrie** et **Extractions échouées** avec Force Extract (TinyFish) par URL ou global.

## Paramètres (bandeau droit, icône engrenage)
- **Documentation** : télécharger ce manuel (EN/FR).
- **Données** : Importer GeoJSON (validation des coordonnées, comptage et fusion des doublons), Exporter GeoJSON, Effacer tous les projets.
- **Filtrage marin** : distance max à la côte (km), score marin minimum.
- **Extraction** : agents TinyFish en parallèle (1-2), concurrence des extractions (1-20), modèle Gemini par étape (Gatekeeper / Extraction+Scoring), interrupteur Follow the Money, limite Auto-Stop.
- **Carte** : zoom minimum, marqueurs max.
- **Clés API** : TinyFish et Gemini (stockées côté serveur, jamais exposées).

## Pipeline (fonctionnement)
1. **Découverte** : les agents web TinyFish naviguent sur les portails des fondations (flux SSE en direct, repli polling, repli crawler).
2. **Extraction** : Readability nettoie la page → le Gatekeeper Gemini rejette les projets terrestres/eau douce → Gemini extrait titre, description (<250 caractères), lieu, catégorie, partenaires et score S_ocean.
3. **Géocodage** : GPS extrait → Nominatim → géocodage intelligent Gemini → test Point-in-Ocean → recalage côtier si à l'intérieur des terres.
4. **Déduplication** : URL identique, proximité spatiale (<500 m) + similarité de titre (>90 %) → financeurs fusionnés.
""",
}


@router.get("/manual")
async def manual(lang: str = "en"):
    text = MANUALS.get(lang, MANUALS["en"])
    return PlainTextResponse(text, headers={"Content-Disposition": f"attachment; filename=blue_intelligence_manual_{lang}.md"})


# ---------- Donations (Stripe sandbox) ----------
DONATION_PACKAGES = {"don_5": 5.0, "don_10": 10.0, "don_25": 25.0, "don_50": 50.0, "don_100": 100.0}


def _stripe_checkout(request: Request):
    from emergentintegrations.payments.stripe.checkout import StripeCheckout
    host_url = str(request.base_url)
    return StripeCheckout(api_key=os.environ["STRIPE_API_KEY"], webhook_url=f"{host_url}api/webhook/stripe")


class DonationCheckoutBody(BaseModel):
    package_id: str
    origin_url: str
    project_id: str | None = None
    project_title: str | None = None


@router.post("/donations/checkout")
async def donation_checkout(body: DonationCheckoutBody, request: Request):
    amount = DONATION_PACKAGES.get(body.package_id)
    if amount is None:
        raise HTTPException(400, "invalid package_id")
    from emergentintegrations.payments.stripe.checkout import CheckoutSessionRequest
    sc = _stripe_checkout(request)
    req = CheckoutSessionRequest(
        amount=amount,
        currency="eur",
        success_url=f"{body.origin_url}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{body.origin_url}/payment/cancel",
        metadata={"project_id": body.project_id or "", "project_title": (body.project_title or "")[:100], "package_id": body.package_id},
    )
    session = await sc.create_checkout_session(req)
    await db.payment_transactions.insert_one({
        "_id": str(uuid.uuid4()), "session_id": session.session_id,
        "package_id": body.package_id, "amount": amount, "currency": "eur",
        "project_id": body.project_id, "project_title": body.project_title,
        "status": "initiated", "payment_status": "pending",
        "created_at": now_iso(), "updated_at": now_iso(),
    })
    return {"checkout_url": session.url, "session_id": session.session_id}


@router.get("/payments/status/{session_id}")
async def payment_status(session_id: str, request: Request):
    record = await db.payment_transactions.find_one({"session_id": session_id})
    if not record:
        raise HTTPException(404, "Transaction not found")
    if record.get("payment_status") != "paid":
        try:
            sc = _stripe_checkout(request)
            st = await sc.get_checkout_status(session_id)
            if st.payment_status == "paid" or st.status == "complete":
                await db.payment_transactions.update_one(
                    {"session_id": session_id, "payment_status": {"$ne": "paid"}},
                    {"$set": {"status": "completed", "payment_status": "paid", "updated_at": now_iso()}},
                )
                record = await db.payment_transactions.find_one({"session_id": session_id})
        except Exception:
            pass
    return {"session_id": record["session_id"], "status": record["status"], "payment_status": record["payment_status"]}


@router.get("/donations/total")
async def donations_total():
    pipeline_agg = [
        {"$match": {"payment_status": "paid"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}, "count": {"$sum": 1}}},
    ]
    rows = await db.payment_transactions.aggregate(pipeline_agg).to_list(1)
    total = rows[0]["total"] if rows else 0.0
    count = rows[0]["count"] if rows else 0
    return {"total_eur": round(total, 2), "count": count}


app.include_router(router)

# --- OpenAPI + static assets exposed under /api (Kubernetes ingress only forwards /api/*) ---
@app.get("/api/openapi.json")
async def openapi_under_api():
    return JSONResponse(app.openapi())


ROUTE_FILE_ENDPOINT_TARGET = ROUTE_FILE  # kept for clarity; original variable is defined at top


@app.get("/api/route")
async def get_route():
    """Serve the official Berry-Mappemonde expedition route (static, read-only)."""
    if not ROUTE_FILE.exists():
        raise HTTPException(404, "route.geojson not found")
    import json as _json
    try:
        data = _json.loads(ROUTE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(500, f"invalid route geojson: {e}")
    return JSONResponse(
        data,
        headers={
            # Static official route: safe to cache 1h publicly + revalidate on redeploy
            "Cache-Control": "public, max-age=3600, must-revalidate",
            "X-Route-Source": "Naviguide Berry-Mappemonde (official)",
        },
    )


from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1500)


@app.post("/api/webhook/stripe")
async def stripe_webhook(request: Request):
    from emergentintegrations.payments.stripe.checkout import StripeCheckout
    host_url = str(request.base_url)
    sc = StripeCheckout(api_key=os.environ["STRIPE_API_KEY"], webhook_url=f"{host_url}api/webhook/stripe")
    body = await request.body()
    try:
        wh = await sc.handle_webhook(body, request.headers.get("Stripe-Signature"))
    except Exception as e:
        raise HTTPException(400, f"webhook error: {e}")
    if wh.payment_status == "paid":
        await db.payment_transactions.update_one(
            {"session_id": wh.session_id, "payment_status": {"$ne": "paid"}},
            {"$set": {"status": "completed", "payment_status": "paid", "updated_at": now_iso()}},
        )
    return {"status": "ok"}


app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown():
    client.close()
