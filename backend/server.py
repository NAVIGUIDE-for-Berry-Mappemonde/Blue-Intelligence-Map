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

from fastapi import APIRouter, Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel

from ai import extract_project, gatekeeper_check
from categories import CATEGORY_GROUPS, normalize_category
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
    "saturation_limit": 50,
    "rescan_after_days": 7,
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
                await db.projects.update_one({"_id": dup["_id"]}, {"$set": {"funders": funders}})
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
                "category": p.get("category"), "engine": "GeoJSON Import", "created_at": now_iso(),
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
