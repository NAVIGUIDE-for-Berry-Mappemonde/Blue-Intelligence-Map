import asyncio
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel

from ai import extract_project, gatekeeper_check
from geo import haversine_km, is_ocean, ocean_fallback_coords, snap_to_ocean, geocode
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
    docs = await db.projects.find(q).to_list(5000)
    return {"type": "FeatureCollection", "features": [project_to_feature(p) for p in docs]}


@router.get("/funders")
async def get_funders():
    docs = await db.projects.find({}, {"funders": 1}).to_list(5000)
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
    docs = await db.projects.find({}).to_list(5000)
    fc = {"type": "FeatureCollection", "features": [project_to_feature(p) for p in docs]}
    return JSONResponse(fc, headers={"Content-Disposition": "attachment; filename=blue_intelligence_projects.geojson"})


@router.post("/swarm/deploy")
async def deploy(body: DeployBody):
    if body.mode not in ("test", "full"):
        raise HTTPException(400, "mode must be test|full")
    settings = await get_settings()
    try:
        await swarm.deploy(body.mode, body.clear_db, settings)
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


@router.get("/settings")
async def read_settings():
    s = await get_settings()
    s.pop("_id", None)
    if s.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY"):
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

## Swarm Controls (left sidebar)
- **Deploy TinyFish Swarm**: starts the ETL pipeline. Test mode = 3 foundations, Full mode = all MasterSeeds + DeepLinkCache.
- **Clear DB before start**: wipes the project database first.
- **Stop Swarm**: cancels all agents and flushes the queue.
- **Live Swarm Console**: one card per active agent (TinyFish discover / Readability extract) with status and stream logs.

## Map
Leaflet dark map with clustered markers. Click a marker for title, funder, description and project link.

## Audit
KPIs (total extractions, success rate, projects mapped), telemetry table, failed extractions with Force Extract (TinyFish).

## Settings
Marine filtering thresholds, extraction concurrency, Gemini models, map limits, API keys (TinyFish + Gemini).
""",
    "fr": """# Blue Intelligence — Manuel utilisateur

## Vue d'ensemble
Blue Intelligence transforme le web vivant des données maritimes en base géospatiale exploitable.
Les agents TinyFish découvrent les fiches projets sur les portails des fondations ; Readability + Gemini extraient, filtrent (Protocole Gatekeeper) et notent chaque projet (S_ocean) ; les résultats sont cartographiés en direct et exportables en GeoJSON.

## Contrôles du Swarm (barre gauche)
- **Déployer TinyFish Swarm** : lance le pipeline ETL. Mode Test = 3 fondations, mode Complet = tous les MasterSeeds + DeepLinkCache.
- **Vider la base avant de démarrer** : efface la base de projets.
- **Arrêter le Swarm** : annule tous les agents et vide la file.
- **Console Swarm en direct** : une carte par agent actif (découverte TinyFish / extraction Readability) avec statut et logs.

## Carte
Carte Leaflet sombre avec clusters. Un clic sur un marqueur affiche titre, financeur, description et lien.

## Audit
KPIs (extractions totales, taux de succès, projets cartographiés), table de télémétrie, extractions échouées avec Force Extract (TinyFish).

## Paramètres
Seuils de filtrage marin, concurrence d'extraction, modèles Gemini, limites carte, clés API (TinyFish + Gemini).
""",
}


@router.get("/manual")
async def manual(lang: str = "en"):
    text = MANUALS.get(lang, MANUALS["en"])
    return PlainTextResponse(text, headers={"Content-Disposition": f"attachment; filename=blue_intelligence_manual_{lang}.md"})


app.include_router(router)
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
