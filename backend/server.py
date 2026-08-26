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

from ai import extract_project, gatekeeper_check, get_llm_key
from categories import CATEGORY_GROUPS, normalize_category
from enrichment import ENRICH_FIELDS, enrich_marina, is_stale
import poe_routes
from geo import haversine_km, is_ocean, ocean_fallback_coords, snap_to_ocean, geocode
from marinas import BuildState, build_marinas as run_build_marinas, marinas_to_geojson
from anchorages import build_anchorages as run_build_anchorages, anchorages_to_geojson
from zee import (
    EEZ_FILE,
    build_zee_crossings as run_build_zee_crossings,
    crossings_to_summary as zee_crossings_summary,
    filter_french_territories,
)
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
    # Cloudflare Workers AI: dormant while the provided token is rejected + Kimi is paywalled
    # on Free tier. Default model is the free-plan-eligible gpt-oss-120b. Switching to
    # `@cf/moonshotai/kimi-k2.6` after upgrading to Workers Paid activates Kimi with zero
    # code change.
    "cloudflare_model": "@cf/openai/gpt-oss-120b",
    # Phase 5 — swarm extraction engine (used by ai.py). Defaults to gemini
    # (unchanged historical behaviour). Alternates: "gpt" and "claude" (both via
    # EMERGENT_LLM_KEY through emergentintegrations, zero config) and
    # "openrouter" (uses OPENROUTER_API_KEY + openai/gpt-4o-mini).
    "extraction_engine": "gemini",
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
    cloudflare_model: str | None = None


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
    st = swarm.status()
    # Phase 5 — expose the active LLM engine so the UI can render it dynamically
    # instead of a hard-coded "GEMINI" badge.
    try:
        sdoc = await db.settings.find_one({"_id": "global"}) or {}
        engine = sdoc.get("extraction_engine") or "gemini"
    except Exception:
        engine = "gemini"
    st["engine"] = engine
    return st


@router.get("/stats")
async def stats(mode: str = "projects"):
    """KPI counters shown in the Swarm Intelligence Audit view.

    Bug-fix 2026-08-24 — `projects_mapped` used to always return
    `db.projects.count_documents({})` (4463), regardless of the active mode.
    The Audit view now passes `?mode=marinas|formalities|projects` so the
    counter reflects the actual dataset the user is looking at. Extractions
    and success_rate are read from a mode-scoped `dataset` field in the
    telemetry collection when present; legacy rows without that field are
    counted for projects only (backwards-compat).
    """
    m = (mode or "projects").lower()
    if m == "marinas":
        items = await db.marinas.count_documents({})
        tele_filter = {"dataset": "marinas"}
    elif m == "formalities":
        # Refactor 2026-06 — mode Formalités = carte mondiale [ZEE -> PoE].
        # ITEMS MAPPED = nombre de ports d'entrée extraits.
        items = await db.poe_ports.count_documents({})
        tele_filter = {"dataset": "formalities"}
    else:  # projects (default)
        items = await db.projects.count_documents({})
        # Legacy rows have no `dataset` field — count them as projects.
        tele_filter = {"$or": [{"dataset": "projects"}, {"dataset": {"$exists": False}}]}

    total = await db.telemetry.count_documents(tele_filter)
    success = await db.telemetry.count_documents({**tele_filter, "status": {"$in": ["SUCCESS", "MERGED"]}})
    return {
        "mode": m,
        "total_extractions": total,
        "success_rate": round(success / total * 100, 1) if total else 0.0,
        "projects_mapped": items,  # legacy key kept for backwards-compat
        "items_mapped": items,
    }


def _dataset_filter(mode: str) -> dict:
    """Mode-scoped telemetry filter — mirrors /api/stats (legacy rows = projects)."""
    m = (mode or "projects").lower()
    if m == "marinas":
        return {"dataset": "marinas"}
    if m == "formalities":
        return {"dataset": "formalities"}
    return {"$or": [{"dataset": "projects"}, {"dataset": {"$exists": False}}]}


@router.get("/telemetry")
async def telemetry(mode: str = "projects"):
    docs = await db.telemetry.find(_dataset_filter(mode)).sort("ts", -1).to_list(200)
    for d in docs:
        d["id"] = d.pop("_id")
    return docs


@router.get("/failed")
async def failed(mode: str = "projects"):
    docs = await db.failed.find(_dataset_filter(mode)).sort("ts", -1).to_list(200)
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
            if not name:
                invalid += 1
                continue
            mid = str(p.get("id") or "").strip() or str(uuid.uuid4())
            doc = {
                "_id": mid,
                "name": name,
                "lat": lat,
                "lon": lon,
                "source": p.get("source") or "curated",
                "priority": int(p.get("priority") or 3),
                "nearest_waypoint": p.get("nearest_waypoint") or {},
                "tags": p.get("tags") or {},
                "osm_id": p.get("osm_id"),
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


@router.get("/categories")
async def get_categories():
    rows = await db.projects.aggregate([
        {"$group": {"_id": "$category_group", "n": {"$sum": 1}}},
    ]).to_list(50)
    counts = {r["_id"] or "Other": r["n"] for r in rows}
    return {"groups": [{"name": g, "color": c, "count": counts.get(g, 0)} for g, c in CATEGORY_GROUPS.items()]}


# ---------- Marinas (Phase 2) ----------
MARINA_BUILD_STATE = BuildState()
# Phase 8 — Anchorages (Mouillages)
ANCHORAGE_BUILD_STATE = BuildState()


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
    # Phase 8 — continuous 50 NM band: 25 NM sampling step × ±25 NM buffer
    corridor_step_nm: float = 25.0
    corridor_radius_nm: float = 25.0


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
                corridor_radius_nm=body.corridor_radius_nm,
            )
        except Exception:
            pass

    asyncio.create_task(_runner())
    return {
        "started": True,
        "radius_nm": radius_nm,
        "include_corridor": body.include_corridor,
        "corridor_step_nm": body.corridor_step_nm,
        "corridor_radius_nm": body.corridor_radius_nm,
        "corridor_band_nm": body.corridor_radius_nm * 2,
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


# ---------- Anchorages (Phase 8 — Mouillages) ----------

class AnchoragesBuildBody(BaseModel):
    radius_nm: float | None = None
    clear_before: bool = False
    include_corridor: bool = True
    # Same corridor defaults as marinas: ±25 NM band (25 NM step × ±25 NM buffer)
    corridor_step_nm: float = 25.0
    corridor_radius_nm: float = 25.0


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
    docs = await db.anchorages.find({}).sort([("priority", 1), ("name", 1)]).to_list(20000)
    fc = anchorages_to_geojson(docs)
    return JSONResponse(
        fc,
        headers={"Content-Disposition": "attachment; filename=anchorages.geojson"},
    )


@router.post("/anchorages/build")
async def anchorages_build_start(body: AnchoragesBuildBody | None = None):
    if ANCHORAGE_BUILD_STATE.running:
        raise HTTPException(409, "An anchorages build is already running")
    body = body or AnchoragesBuildBody()
    settings = await get_settings()
    # Reuse marina_search_radius_nm as default waypoint radius for anchorages too
    radius_nm = float(body.radius_nm or settings.get("marina_search_radius_nm") or 10.0)

    if body.clear_before:
        await db.anchorages.delete_many({})

    async def _runner():
        try:
            await run_build_anchorages(
                anchorages_coll=db.anchorages,
                route_path=ROUTE_FILE,
                radius_nm=radius_nm,
                state=ANCHORAGE_BUILD_STATE,
                include_corridor=body.include_corridor,
                corridor_step_nm=body.corridor_step_nm,
                corridor_radius_nm=body.corridor_radius_nm,
            )
        except Exception:
            pass

    asyncio.create_task(_runner())
    return {
        "started": True,
        "radius_nm": radius_nm,
        "include_corridor": body.include_corridor,
        "corridor_step_nm": body.corridor_step_nm,
        "corridor_radius_nm": body.corridor_radius_nm,
        "corridor_band_nm": body.corridor_radius_nm * 2,
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
PROJECT_ENRICH_TASKS: dict[str, dict] = {}


def _prune_tasks(registry: dict, max_age_s: int = 3600):
    """Drop tasks that finished more than max_age_s ago to bound memory."""
    now = time.time()
    for k in list(registry.keys()):
        t = registry.get(k) or {}
        finished = t.get("finished_at") or 0
        if finished and (now - finished) > max_age_s:
            registry.pop(k, None)


class MarinaEnrichBatchBody(BaseModel):
    limit: int = 10   # 0 = toutes les marinas restantes (mode "Tout enchaîner")
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
        self.cancel: bool = False

    def log(self, msg: str):
        self.logs.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        if len(self.logs) > 400:
            self.logs = self.logs[-400:]


ENRICH_BATCH_STATE = EnrichBatchState()


def _keys() -> tuple[str | None, str | None, str | None, str | None]:
    return (
        (os.environ.get("TINYFISH_API_KEY") or "").strip() or None,
        (os.environ.get("OPENROUTER_API_KEY") or "").strip() or None,
        (os.environ.get("CLOUDFLARE_ACCOUNT_ID") or "").strip() or None,
        (os.environ.get("CLOUDFLARE_API_TOKEN") or "").strip() or None,
    )


_MARINA_ENGINE_LABELS = {
    "gemini": "Gemini",
    "tinyfish": "TinyFish",
    "cloudflare": "Cloudflare AI",
    "openrouter": "OpenRouter",
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


async def _run_marina_enrich_one(marina: dict, min_credit_usd: float, log_fn, skip_tinyfish: bool = False) -> dict:
    """Run the enrichment chain and upsert the enriched fields on the marina doc."""
    tf_key, or_key, cf_account, cf_token = _keys()
    settings = await get_settings()
    gemini_key = get_llm_key(settings)
    # Économie de crédits : après un échec TinyFish, on ne re-paye plus pour cette marina.
    skip_tf = skip_tinyfish or bool(marina.get("tinyfish_failed"))
    t0 = time.time()
    try:
        result = await enrich_marina(
            marina,
            tinyfish_key=tf_key,
            openrouter_key=or_key,
            cf_account=cf_account,
            cf_token=cf_token,
            gemini_key=gemini_key,
            min_credit_usd=min_credit_usd,
            logger=log_fn,
            skip_tinyfish=skip_tf,
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

    _prune_tasks(MARINA_ENRICH_TASKS)
    ENRICH_LOCKS.add(marina_id)
    MARINA_ENRICH_TASKS[marina_id] = {
        "state": "running",
        "started_at": time.time(),
        "finished_at": None,
        "result": None,
        "error": None,
        "logs": [],
    }

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
    }


# ---------- On-demand project enrich (Phase 3, async as of Phase 3.1) ----------
async def _run_project_enrich(project_id: str, task: dict):
    """Actual enrichment work — runs in background."""

    def log_fn(msg: str):
        task["logs"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        if len(task["logs"]) > 200:
            task["logs"] = task["logs"][-200:]

    proj = await db.projects.find_one({"_id": project_id})
    if not proj:
        task["state"] = "error"
        task["error"] = "project not found"
        task["finished_at"] = time.time()
        return
    url = proj.get("url")
    if not url:
        task["state"] = "error"
        task["error"] = "project has no URL"
        task["finished_at"] = time.time()
        return
    log_fn(f"Refreshing {url}")

    import httpx as _httpx
    from bs4 import BeautifulSoup as _BS
    from readability import Document as _Doc
    from ai import extract_project as _extract, gatekeeper_check as _gk
    from pipeline import UA as _UA, pick_image as _pick_image

    try:
        settings = await get_settings()
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
            task["state"] = "error"
            task["error"] = f"gatekeeper: {gk['reason']}"
            task["finished_at"] = time.time()
            return
        funder = proj.get("funder") or (proj.get("funders") or ["Unknown"])[0]
        extracted = await _extract(page_title, text, meta_desc, url, funder, settings)
        log_fn(f"Extraction engine={extracted.get('engine')}, title='{(extracted.get('title') or '')[:60]}'")

        update: dict = {}
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
        if image and (not proj.get("image") or image != proj.get("image")):
            update["image"] = image
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
        task["result"] = {
            "project": project_to_feature(fresh),
            "updates": list(update.keys()),
        }
        task["state"] = "done"
    except Exception as e:
        log_fn(f"FAILED: {type(e).__name__}: {str(e)[:200]}")
        task["state"] = "error"
        task["error"] = f"{type(e).__name__}: {e}"
    finally:
        task["finished_at"] = time.time()


@router.post("/projects/{project_id}/enrich", status_code=202)
async def project_enrich_one(project_id: str):
    """
    Kick off project re-extraction as a background task.
    Returns 202 immediately; poll GET /api/projects/{project_id}/enrich/status.
    """
    proj = await db.projects.find_one({"_id": project_id})
    if not proj:
        raise HTTPException(404, "project not found")
    if not proj.get("url"):
        raise HTTPException(400, "project has no URL")

    existing = PROJECT_ENRICH_TASKS.get(project_id)
    if existing and existing.get("state") == "running":
        raise HTTPException(409, "Enrichment already in progress for this project")

    _prune_tasks(PROJECT_ENRICH_TASKS)
    PROJECT_ENRICH_TASKS[project_id] = {
        "state": "running",
        "started_at": time.time(),
        "finished_at": None,
        "result": None,
        "error": None,
        "logs": [],
    }
    asyncio.create_task(_run_project_enrich(project_id, PROJECT_ENRICH_TASKS[project_id]))
    return {"status": "started", "project_id": project_id}


@router.get("/projects/{project_id}/enrich/status")
async def project_enrich_status(project_id: str):
    task = PROJECT_ENRICH_TASKS.get(project_id)
    if not task:
        return {"state": "idle", "project_id": project_id}
    return {
        "state": task["state"],
        "project_id": project_id,
        "started_at": task["started_at"],
        "finished_at": task["finished_at"],
        "result": task["result"],
        "error": task["error"],
        "logs_tail": task["logs"][-30:],
    }


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


ARCGIS_MPA_URL = ""  # Removed in Phase 5 — MPA layer decommissioned.
MPA_FIELDS: list[str] = []  # Deprecated in Phase 5: MPA layer removed entirely.


# ---------- MPA endpoint removed in Phase 5 (Protected Areas layer decommissioned). ----------
# The /api/mpa endpoint returned MPA polygons from ArcGIS ProtectedSeas Navigator.
# Kept as HTTP 410 for backward compatibility with older frontends that may still ping it.
@router.get("/mpa", status_code=410, include_in_schema=False)
async def mpa_deprecated(bbox: str = ""):
    raise HTTPException(410, "MPA layer removed in Phase 5.")


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
Blue Intelligence turns the living web of maritime data into an executable geospatial database. The app offers three complementary modes, an operator Audit console, contextual GeoJSON exports and a single global donation pot. AI-generated content is produced by an OpenRouter + Gemini (fallback) synthesis pipeline; the swarm extraction engine is configurable in Settings (Gemini default · Claude · OpenRouter).

## Three modes (header switch)
The header pill lets you switch between three modes. Each mode paints the app with its own accent theme (cyan · red · amber) and shows its dedicated sidebar and map layer.

### 1) Projects (cyan)
- **World map**: single-world Leaflet map with light/dark basemap toggle in the header. Project markers are colored by category and grouped into clusters. The Berry-Mappemonde route is drawn under the clusters as a neutral polyline.
- **Popup**: click a marker → photo, title, funder, category, description, S_ocean score and a "View project" link. No per-project donate button — donations are global (see below). The popup always stays fully on screen without moving the map.
- **Left sidebar**:
  - *Legend*: 9 color-coded categories (Conservation, Research, Fisheries, Policy & Advocacy, Pollution, Coastal & Habitat, Education, Restoration, Other). Click a category to filter.
  - *Organization filter* and *Category filter* dropdowns.
  - *Instant search* across titles, descriptions, funders and locations.
  - *Project list* with source links.
  - *"Missing project?"*: report a project we missed. It is emailed to the team and queued for the next Swarm run.
  - *Export GeoJSON* button — exports the projects visible in this mode.

### 2) Marinas (red)
- **Map**: red-tinted markers grouped into clusters, showing marinas and berthing points curated from OpenStreetMap and other open sources.
- **Popup**: marina name, tags (fuel · water · haul-out · shore power · repair), coordinates and source link. Enriched fields (VHF channel, phone, website) appear once the enrichment batch has been run.
- **Left sidebar**: search by name, filter by tag, marina list.
- *Export GeoJSON* button — exports the marinas visible in this mode.
- All batch actions (build, enrich) are triggered from the Audit hub (see below), not from the sidebar.

### 3) Formalities (amber)
- **Map**: world choropleth of the ~285 Exclusive Economic Zones (EEZ, Marine Regions/VLIZ v12) coloured by generation status, plus amber markers for every extracted official Port of Entry (pleasure craft). Click an EEZ to open its sheet.
- **Left sidebar**: searchable list of all EEZs (flag, sovereign, status, PoE count), a status filter and the permanent amber disclaimer ("Indicative information — verify with the authorities before departure").
- **EEZ sheet (map popup)**: status pill, PoE count, generation date, official sources used (clickable), and a Generate / Regenerate button that runs the full pipeline for that zone.
- **Status of a zone** (4 possible values):
  - `not generated` — grey, no AI content yet.
  - `AI · official sources` — amber, the sources passed the auto-generated government-domain whitelist.
  - `AI · no official source` — amber dashed, content extracted but no whitelisted official domain could be captured.
  - `error` — red, no port of entry could be extracted (typical for disputed rocks or landlocked claims).
- **Port of Entry popup**: name, town, note, geocoding source, and a spatial-validation badge (inside the EEZ / outside with distance).
- **Stale flag**: any zone older than 180 days shows a clock badge inviting a refresh. Re-extraction only happens when the source content changed (MD5 monitoring).
- *Export GeoJSON* button — exports all extracted Ports of Entry.

## Global donations pot
The header shows a single donation CTA. Click it, pick an amount (5–100 €) and pay through Stripe. All donations feed one single global pot shown next to the button (running total in euros + donor count). No per-project donation button anywhere in the map or the sidebars.

## Swarm Intelligence Audit (header toggle)
Operator console reserved for the crew / admin. It groups **all batch triggers** in one place (the "Swarm Intelligence Hub"):
- **Projects — Swarm**: Test mode (3 foundations) or Full mode (all MasterSeeds + DeepLinkCache), "clear DB before start", Deploy / Stop buttons, live log stream, per-agent live view.
- **Marinas — Build & Enrich batch**: rebuild the marinas dataset from open sources, then enrich N marinas at a time (VHF, phone, website) with live progress and per-item status.
- **Formalities — EEZ referential & PoE batch**: build/refresh the world EEZ referential (VLIZ Marine Regions), then generate the Ports of Entry per zone in batches (5/10/25/all), with live logs, per-zone results and a Stop button.
- **KPIs, telemetry table, failed extractions** for the projects pipeline, with Force Extract (TinyFish) per URL or global.

## Settings (right panel, gear icon)
- **Documentation**: download this manual (EN/FR).
- **Data**: Import GeoJSON (validates coordinates, counts and merges duplicates), Export GeoJSON, Clear all projects.
- **Marine filtering**: max coast distance (km), minimum marine score.
- **Extraction**: parallel TinyFish agents (1–2), extraction concurrency (1–20), **extraction engine selector** (Gemini · Claude · OpenRouter), model per stage (Gatekeeper / Extraction+Scoring), Follow the Money toggle, Auto-Stop limit.
- **Map**: minimum zoom, max markers.
- **API keys**: TinyFish and LLM (stored server-side, never exposed).

## Pipeline (how it works)
1. **Discovery**: TinyFish web agents navigate foundation portals (SSE live streaming, polling fallback, HTTP crawler fallback).
2. **Extraction**: Readability cleans the page → LLM Gatekeeper rejects terrestrial/freshwater projects → LLM extracts title, description (<250 chars), location, category, partners and S_ocean score.
3. **Geocoding**: extracted GPS → Nominatim → LLM smart geocoding → Point-in-Ocean test → coastal snapping when inland.
4. **Deduplication**: URL match, spatial proximity (<500 m) + title similarity (>90%) → funders merged.
5. **Ports of Entry pipeline (Formalities mode)**: search engines (SearXNG, Google-grounded Gemini) find the official customs/immigration sources of each EEZ; a whitelist of government domains (auto-generated from ISO codes + Public Suffix List + exceptions file) filters them; the pages/PDFs are parsed (trafilatura / PyMuPDF); a light LLM extracts the official PoE list as strict JSON; each port is geocoded (Nominatim/GeoNames) and spatially validated inside its EEZ polygon (shapely). MD5 hashes of the sources prevent useless re-extraction. The pipeline never invents content.
""",
    "fr": """# Blue Intelligence — Manuel utilisateur

## Vue d'ensemble
Blue Intelligence transforme le web vivant des données maritimes en base géospatiale exploitable. L'application propose trois modes complémentaires, une console Audit opérateur, des exports GeoJSON contextuels et une cagnotte de dons globale unique. Les contenus produits par IA le sont via un pipeline de synthèse OpenRouter + Gemini (fallback) ; le moteur d'extraction du swarm est configurable dans les Paramètres (Gemini par défaut · Claude · OpenRouter).

## Trois modes (bascule dans l'en-tête)
La pastille de l'en-tête permet de basculer entre trois modes. Chaque mode habille l'app avec sa teinte d'accent propre (cyan · rouge · ambre) et affiche son bandeau et sa couche de carte dédiés.

### 1) Projets (cyan)
- **Carte mondiale** : carte Leaflet à monde unique, bascule fond clair/sombre dans l'en-tête. Marqueurs de projets colorés par catégorie et regroupés en clusters. La route Berry-Mappemonde est tracée sous les clusters sous forme d'une polyline neutre.
- **Popup** : cliquer un marqueur → photo, titre, financeur, catégorie, description, score S_ocean et lien « Voir le projet ». Pas de bouton donner par projet — les dons sont globaux (voir ci-dessous). L'encadré reste toujours entièrement visible sans déplacer la carte.
- **Bandeau gauche** :
  - *Légende* : 9 catégories colorées (Conservation, Recherche, Pêcheries, Politique & Plaidoyer, Pollution, Côtes & Habitats, Éducation, Restauration, Autre). Cliquer une catégorie filtre la carte.
  - Menus *Filtre par organisation* et *Filtre par catégorie*.
  - *Recherche instantanée* sur titres, descriptions, financeurs et lieux.
  - *Liste des projets* avec liens sources.
  - *« Projet manquant ? »* : signaler un projet oublié. Un email est envoyé à l'équipe et le projet est mis en file pour le prochain run du Swarm.
  - Bouton *Export GeoJSON* — exporte les projets visibles dans ce mode.

### 2) Marinas (rouge)
- **Carte** : marqueurs teintés rouge regroupés en clusters, représentant les marinas et points d'amarrage curatés depuis OpenStreetMap et d'autres sources ouvertes.
- **Popup** : nom, tags (carburant · eau · levage · courant à quai · réparation), coordonnées et lien source. Les champs enrichis (canal VHF, téléphone, site web) apparaissent une fois le batch d'enrichissement lancé.
- **Bandeau gauche** : recherche par nom, filtre par tag, liste des marinas.
- Bouton *Export GeoJSON* — exporte les marinas visibles dans ce mode.
- Toutes les actions batch (build, enrichissement) sont déclenchées depuis le hub Audit (voir plus bas), plus depuis le bandeau.

### 3) Formalités (ambre)
- **Carte** : choroplèthe mondiale des ~285 Zones Économiques Exclusives (ZEE, Marine Regions/VLIZ v12) colorées par statut de génération, plus des marqueurs ambre pour chaque Port d'Entrée officiel extrait (plaisance). Cliquez une ZEE pour ouvrir sa fiche.
- **Bandeau gauche** : liste de toutes les ZEE avec recherche (drapeau, souverain, statut, nombre de PoE), un filtre par statut et le disclaimer ambre permanent (« Informations indicatives — à vérifier auprès des autorités avant le départ »).
- **Fiche ZEE (popup carte)** : pastille de statut, nombre de PoE, date de génération, sources officielles utilisées (cliquables), et un bouton Générer / Régénérer qui exécute le pipeline complet pour cette zone.
- **Statut d'une zone** (4 valeurs possibles) :
  - `non générée` — gris, aucun contenu IA pour l'instant.
  - `IA · sources officielles` — ambre, les sources passent la whitelist auto-générée de domaines gouvernementaux.
  - `IA · sans source officielle` — ambre pointillé, contenu extrait mais aucun domaine officiel whitelisté n'a pu être capté.
  - `erreur` — rouge, aucun port d'entrée n'a pu être extrait (typique des rochers disputés ou zones sans port).
- **Popup Port d'Entrée** : nom, ville, note, source de géocodage, et un badge de validation spatiale (dans la ZEE / hors ZEE avec distance).
- **Flag stale** : toute zone datant de plus de 180 jours affiche un badge horloge invitant au rafraîchissement. La ré-extraction n'a lieu que si le contenu source a changé (monitoring MD5).
- Bouton *Export GeoJSON* — exporte tous les Ports d'Entrée extraits.

## Cagnotte de dons globale
L'en-tête affiche un unique CTA de don. Cliquez, choisissez un montant (5–100 €) et payez via Stripe. Tous les dons alimentent une seule cagnotte globale affichée à côté du bouton (total courant en euros + nombre de donateurs). Aucun bouton donner par projet, ni dans la carte ni dans les bandeaux.

## Audit Swarm Intelligence (bascule dans l'en-tête)
Console opérateur réservée à l'équipage / admin. Elle regroupe **tous les déclencheurs batch** au même endroit (le « Swarm Intelligence Hub ») :
- **Projets — Swarm** : mode Test (3 fondations) ou Complet (tous les MasterSeeds + DeepLinkCache), « vider la base avant de démarrer », boutons Déployer / Arrêter, flux de logs en direct, live view par agent.
- **Marinas — Build & Enrich batch** : reconstruit le jeu marinas depuis les sources ouvertes, puis enrichit N marinas à la fois (VHF, téléphone, site web) avec progression en direct et statut par item.
- **Formalités — Référentiel ZEE & batch PoE** : construit/rafraîchit le référentiel mondial des ZEE (VLIZ Marine Regions), puis génère les Ports d'Entrée zone par zone en lots (5/10/25/toutes), avec logs live, résultats par zone et bouton Stop.
- **KPIs, table de télémétrie, extractions échouées** pour le pipeline projets, avec Force Extract (TinyFish) par URL ou global.

## Paramètres (bandeau droit, icône engrenage)
- **Documentation** : télécharger ce manuel (EN/FR).
- **Données** : Importer GeoJSON (validation des coordonnées, comptage et fusion des doublons), Exporter GeoJSON, Effacer tous les projets.
- **Filtrage marin** : distance max à la côte (km), score marin minimum.
- **Extraction** : agents TinyFish en parallèle (1–2), concurrence des extractions (1–20), **sélecteur de moteur d'extraction** (Gemini · Claude · OpenRouter), modèle par étape (Gatekeeper / Extraction+Scoring), interrupteur Follow the Money, limite Auto-Stop.
- **Carte** : zoom minimum, marqueurs max.
- **Clés API** : TinyFish et LLM (stockées côté serveur, jamais exposées).

## Pipeline (fonctionnement)
1. **Découverte** : les agents web TinyFish naviguent sur les portails des fondations (flux SSE en direct, repli polling, repli crawler HTTP).
2. **Extraction** : Readability nettoie la page → un LLM Gatekeeper rejette les projets terrestres/eau douce → un LLM extrait titre, description (<250 caractères), lieu, catégorie, partenaires et score S_ocean.
3. **Géocodage** : GPS extrait → Nominatim → géocodage intelligent par LLM → test Point-in-Ocean → recalage côtier si à l'intérieur des terres.
4. **Déduplication** : URL identique, proximité spatiale (<500 m) + similarité de titre (>90 %) → financeurs fusionnés.
5. **Pipeline Ports d'Entrée (mode Formalités)** : des moteurs de recherche (SearXNG, Gemini avec grounding Google) trouvent les sources officielles douanes/immigration de chaque ZEE ; une whitelist de domaines gouvernementaux (auto-générée depuis les codes ISO + Public Suffix List + fichier d'exceptions) les filtre ; les pages/PDF sont parsés (trafilatura / PyMuPDF) ; un LLM léger extrait la liste des PoE officiels en JSON strict ; chaque port est géocodé (Nominatim/GeoNames) puis validé spatialement dans son polygone ZEE (shapely). Les hash MD5 des sources évitent toute ré-extraction inutile. Le pipeline n'invente jamais de contenu.
""",
}


@router.get("/manual")
async def manual(lang: str = "en"):
    text = MANUALS.get(lang, MANUALS["en"])
    # Phase 7bis — serve Markdown with a semantic content-type so browsers /
    # editors / IDEs render it correctly. The frontend Manual EN/FR buttons
    # still work (they window.open() the URL — no Accept header check).
    return PlainTextResponse(
        text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=blue_intelligence_manual_{lang}.md"},
    )


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


# ---------- ZEE Detection (Phase 8) ----------

class ZeeComputeState:
    """État de la tâche de calcul ZEE. In-memory; la dernière snapshot complète
    est persistée dans MongoDB (collection zee_crossings, _id="latest")."""
    def __init__(self):
        self.running: bool = False
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.error: str | None = None
        self.logs: list[str] = []
        self.result: dict | None = None

    def log(self, msg: str):
        self.logs.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        if len(self.logs) > 600:
            self.logs = self.logs[-600:]


ZEE_COMPUTE_STATE = ZeeComputeState()


@router.get("/zee/crossings")
async def zee_get_crossings(french_only: bool = False):
    """
    Traversées ZEE calculées pour la route Berry-Mappemonde (cache MongoDB).
    404 si aucun calcul n'a encore été lancé (POST /api/zee/compute).
    `french_only=true` ne garde que les ZEE françaises (territory_code non null).
    """
    cached = await db.zee_crossings.find_one({"_id": "latest"})
    if not cached:
        raise HTTPException(404, "No ZEE crossings computed yet. Call POST /api/zee/compute first.")
    crossings: list[dict] = cached.get("crossings") or []
    if french_only:
        crossings = filter_french_territories(crossings)
    return {
        "computed_at": cached.get("computed_at"),
        "eez_source": cached.get("eez_source"),
        "detection_method": cached.get("detection_method"),
        "summary": zee_crossings_summary(crossings),
        "crossings": crossings,
    }


class ZeeComputeBody(BaseModel):
    force_download: bool = False
    use_point_api_fallback: bool = True


@router.post("/zee/compute")
async def zee_compute(body: ZeeComputeBody | None = None):
    """
    Lance le calcul des traversées ZEE en tâche de fond :
      1. charge les polygones EEZ (fichier local MarineRegions v12, sinon WFS),
      2. intersecte les segments maritimes (shapely, thread),
      3. persiste dans MongoDB (zee_crossings, _id="latest").
    409 si un calcul est déjà en cours ; suivre via GET /api/zee/compute/status.
    """
    if ZEE_COMPUTE_STATE.running:
        raise HTTPException(409, "A ZEE computation is already running")
    body = body or ZeeComputeBody()

    ZEE_COMPUTE_STATE.running = True
    ZEE_COMPUTE_STATE.started_at = time.time()
    ZEE_COMPUTE_STATE.finished_at = None
    ZEE_COMPUTE_STATE.error = None
    ZEE_COMPUTE_STATE.logs = []
    ZEE_COMPUTE_STATE.result = None

    async def _runner():
        try:
            crossings = await run_build_zee_crossings(
                route_path=ROUTE_FILE,
                eez_path=EEZ_FILE,
                force_download=body.force_download,
                use_point_api_fallback=body.use_point_api_fallback,
                logger=ZEE_COMPUTE_STATE.log,
            )
            summary = zee_crossings_summary(crossings)
            method = crossings[0]["detection_method"] if crossings else "none"
            eez_source = (
                "MarineRegions Maritime Boundaries v12 (local, CC-BY 4.0)"
                if EEZ_FILE.exists() else "MarineRegions REST API"
            )
            doc = {
                "_id": "latest",
                "computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "eez_source": eez_source,
                "detection_method": method,
                "crossings": crossings,
                "summary": summary,
            }
            await db.zee_crossings.replace_one({"_id": "latest"}, doc, upsert=True)
            ZEE_COMPUTE_STATE.result = doc
            ZEE_COMPUTE_STATE.log(
                f"ZEE compute complete — {summary['total_crossings']} crossings, "
                f"{summary['unique_territories']} unique FR territories: {summary['territory_codes']}"
            )
        except Exception as exc:
            ZEE_COMPUTE_STATE.error = f"{type(exc).__name__}: {exc}"
            ZEE_COMPUTE_STATE.log(f"FATAL: {ZEE_COMPUTE_STATE.error}")
        finally:
            ZEE_COMPUTE_STATE.finished_at = time.time()
            ZEE_COMPUTE_STATE.running = False

    asyncio.create_task(_runner())
    return {
        "started": True,
        "force_download": body.force_download,
        "use_point_api_fallback": body.use_point_api_fallback,
    }


@router.get("/zee/compute/status")
async def zee_compute_status():
    s = ZEE_COMPUTE_STATE
    return {
        "running": s.running,
        "started_at": s.started_at,
        "finished_at": s.finished_at,
        "error": s.error,
        "logs_tail": s.logs[-60:],
        "result_summary": s.result.get("summary") if s.result else None,
    }


@router.delete("/zee/crossings")
async def zee_clear_crossings(delete_eez_file: bool = False):
    """Supprime le cache crossings (et optionnellement le fichier EEZ local)."""
    res = await db.zee_crossings.delete_one({"_id": "latest"})
    eez_deleted = False
    if delete_eez_file and EEZ_FILE.exists():
        try:
            EEZ_FILE.unlink()
            eez_deleted = True
        except Exception:
            pass
    return {"cache_deleted": res.deleted_count > 0, "eez_file_deleted": eez_deleted}


poe_routes.init(db)
app.include_router(poe_routes.router)
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


@app.on_event("startup")
async def _startup_poe():
    """
    Refactor 2026-06 — mode Formalités = pipeline [ZEE mondiale -> Ports d'Entrée].
    Crée les index des collections eez_zones / poe_ports et purge les
    collections héritées (formalities, mpa_cache).
    """
    try:
        await db.eez_zones.create_index("mrgid", unique=True)
        await db.poe_ports.create_index("dedup_key", unique=True)
        await db.poe_ports.create_index("mrgid")
    except Exception as e:
        print(f"[startup] poe index creation failed (non-fatal): {e}")
    try:
        existing = await db.list_collection_names()
        for legacy in ("formalities", "mpa_cache"):
            if legacy in existing:
                await db.drop_collection(legacy)
                print(f"[startup] dropped legacy {legacy} collection")
    except Exception as e:
        print(f"[startup] legacy collection drop failed (non-fatal): {e}")
    # Rafraîchissement automatique : zones périmées re-vérifiées (monitoring MD5)
    # et erreurs re-tentées, sans action manuelle.
    poe_routes.start_auto_refresh()
