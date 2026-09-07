"""app.routers.swarm — Pilotage du swarm de découverte, KPIs, télémétrie,
extractions échouées (Force Extract TinyFish)."""
import asyncio
import os
import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.geo import geocode
from app.core.project_geo import site_publishable
from app.core.tinyfish import EXTRACT_SCHEMA, extract_goal, tf_run_sync
from app.db import db, get_settings
from app.services.swarm_pipeline import Swarm, now_iso
from app.state import swarm

router = APIRouter(prefix="/api")

class DeployBody(BaseModel):
    mode: str = "test"
    clear_db: bool = False
    force_rescan: bool = False

@router.post("/swarm/deploy")
async def deploy(body: DeployBody):
    if body.mode not in ("test", "full"):
        raise HTTPException(400, "mode must be test|full")
    if body.clear_db:
        raise HTTPException(400, "clear_db is disabled")
    settings = await get_settings()
    try:
        await swarm.deploy(body.mode, False, settings, body.force_rescan)
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
    # Moteur LLM unique : OpenRouter (badge dynamique côté UI).
    st["engine"] = "openrouter"
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
        ok, kind = site_publishable(lat, lon, settings)
        if not ok:
            raise ValueError(f"unlocated:{kind}")
        snapped = False
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
