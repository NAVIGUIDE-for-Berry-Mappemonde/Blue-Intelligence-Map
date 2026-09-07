"""
app.routers.formalities — Endpoints FastAPI du mode Formalités [ZEE -> Ports d'Entrée].
"""
import asyncio
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.core.tasks import TaskState
from app.db import db as _db
from app.services import poe_pipeline as poe
from app.services import osm_validate

router = APIRouter(prefix="/api")


REF_STATE = TaskState()
GEN_LOCKS: set[int] = set()

# Carte v1 : generate / generate-batch écrasaient poe_ports. 410, pas 404.
GENERATE_GONE = (
    "Retiré : Générer / generate-batch n'écrase plus poe_ports. "
    "Utiliser un run isolé (POST /api/poe/runs) ou l'enrichissement des graines."
)


# ---------------------------------------------------------------------------
# Rafraîchissement automatique (sans action manuelle)
# - Zones générées re-vérifiées après REFRESH_AFTER_DAYS : les sources sont
#   re-téléchargées et comparées par hash MD5 — la ré-extraction LLM+géocodage
#   n'a lieu QUE si le contenu source a changé (géré dans poe.generate_zone_poe).
# - Zones en erreur re-tentées (force) après ERROR_RETRY_DAYS.
# ---------------------------------------------------------------------------
REFRESH_AFTER_DAYS = 30
ERROR_RETRY_DAYS = 7
CYCLE_EVERY_H = 12
MAX_PER_CYCLE = 60

AUTO_STATE = {
    "enabled": True,
    "cycle_running": False,
    "last_cycle_at": None,
    "next_check_at": None,
    "last_summary": None,   # {"checked", "unchanged_md5", "updated", "errors_retried", "failed"}
    "logs": [],
}
_auto_task = None


def _auto_log(msg: str):
    AUTO_STATE["logs"].append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}")
    if len(AUTO_STATE["logs"]) > 300:
        AUTO_STATE["logs"] = AUTO_STATE["logs"][-300:]


def _ts_of(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return time.mktime(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return None


async def _auto_refresh_cycle():
    now = time.time()
    zones = await _db.eez_zones.find({}, {"geometry": 0}).to_list(500)
    stale, errored = [], []
    for z in zones:
        ref = _ts_of(z.get("checked_at")) or _ts_of(z.get("generated_at"))
        if ref is None:
            continue
        st = z.get("status")
        if st in ("ia", "ia_sans_source") and now - ref > REFRESH_AFTER_DAYS * 86400:
            stale.append(z)
        elif st == "erreur" and now - ref > ERROR_RETRY_DAYS * 86400:
            errored.append(z)
    stale.sort(key=lambda z: z.get("generated_at") or "")
    errored.sort(key=lambda z: z.get("generated_at") or "")
    todo = [(z, False) for z in stale] + [(z, True) for z in errored]
    todo = todo[:MAX_PER_CYCLE]
    if not todo:
        _auto_log("cycle: aucune zone à re-vérifier")
        AUTO_STATE["last_summary"] = {"checked": 0, "unchanged_md5": 0, "updated": 0, "errors_retried": 0, "failed": 0}
        return

    _auto_log(f"cycle: {len(stale)} zone(s) périmées (> {REFRESH_AFTER_DAYS} j) + "
              f"{len(errored)} erreur(s) (> {ERROR_RETRY_DAYS} j) — {len(todo)} traitées (cap {MAX_PER_CYCLE})")
    summary = {"checked": 0, "unchanged_md5": 0, "updated": 0, "errors_retried": 0, "failed": 0}
    for z, force in todo:
        mrgid = z["mrgid"]
        if mrgid in GEN_LOCKS or REF_STATE.running:
            _auto_log(f"[{z.get('name')}] SKIP (verrou ou référentiel en cours)")
            continue
        GEN_LOCKS.add(mrgid)
        prev_gen = z.get("generated_at")
        try:
            doc = await asyncio.wait_for(
                poe.generate_zone_poe(_db, mrgid,
                                      logger=lambda m, n=z.get("name"): _auto_log(f"[{n}] {m}"),
                                      force=force, refresh=not force),
                timeout=360,
            )
            summary["checked"] += 1
            if force:
                summary["errors_retried"] += 1
            if doc and doc.get("generated_at") == prev_gen and doc.get("status") == z.get("status"):
                summary["unchanged_md5"] += 1
            else:
                summary["updated"] += 1
        except Exception as e:
            summary["failed"] += 1
            _auto_log(f"[{z.get('name')}] FAILED: {type(e).__name__}: {e}")
        finally:
            GEN_LOCKS.discard(mrgid)
        await asyncio.sleep(2)
    AUTO_STATE["last_summary"] = summary
    _auto_log(f"cycle terminé: {summary}")


async def _auto_refresh_loop():
    await asyncio.sleep(90)  # laisser l'app démarrer
    while True:
        due = (AUTO_STATE["last_cycle_at"] or 0) + CYCLE_EVERY_H * 3600 <= time.time()
        busy = REF_STATE.running
        if AUTO_STATE["enabled"] and due and not busy:
            AUTO_STATE["cycle_running"] = True
            try:
                await _auto_refresh_cycle()
            except Exception as e:
                _auto_log(f"cycle FATAL: {type(e).__name__}: {e}")
            finally:
                AUTO_STATE["cycle_running"] = False
                AUTO_STATE["last_cycle_at"] = time.time()
        AUTO_STATE["next_check_at"] = time.time() + 1800
        await asyncio.sleep(1800)


def start_auto_refresh():
    global _auto_task
    if _auto_task is None or _auto_task.done():
        _auto_task = asyncio.create_task(_auto_refresh_loop())


@router.get("/poe/auto-refresh/status")
async def poe_auto_refresh_status():
    return {
        "enabled": AUTO_STATE["enabled"],
        "cycle_running": AUTO_STATE["cycle_running"],
        "last_cycle_at": AUTO_STATE["last_cycle_at"],
        "next_check_at": AUTO_STATE["next_check_at"],
        "last_summary": AUTO_STATE["last_summary"],
        "config": {
            "refresh_after_days": REFRESH_AFTER_DAYS,
            "error_retry_days": ERROR_RETRY_DAYS,
            "cycle_every_hours": CYCLE_EVERY_H,
            "max_per_cycle": MAX_PER_CYCLE,
        },
        "logs_tail": AUTO_STATE["logs"][-30:],
    }


# ---------------------------------------------------------------------------
# Référentiel ZEE
# ---------------------------------------------------------------------------
@router.post("/poe/referential/build", status_code=202)
async def poe_referential_build():
    if REF_STATE.running:
        raise HTTPException(409, "EEZ referential build already running")
    REF_STATE.reset()
    REF_STATE.running = True
    REF_STATE.started_at = time.time()

    async def _runner():
        try:
            REF_STATE.summary = await poe.build_referential(_db, REF_STATE)
        except Exception as e:
            REF_STATE.error = f"{type(e).__name__}: {e}"
            REF_STATE.log(f"FATAL: {REF_STATE.error}")
        finally:
            REF_STATE.finished_at = time.time()
            REF_STATE.running = False

    asyncio.create_task(_runner())
    return {"status": "started"}


@router.get("/poe/referential/status")
async def poe_referential_status():
    return REF_STATE.status()


@router.get("/poe/zones")
async def poe_zones():
    docs = await _db.eez_zones.find({}, {"geometry": 0}).to_list(500)
    items = sorted((poe.zone_to_item(d) for d in docs), key=lambda z: (z.get("name") or "").lower())
    by_status: dict[str, int] = {}
    for z in items:
        by_status[z["status"]] = by_status.get(z["status"], 0) + 1
    total_ports = await _db.poe_ports.count_documents({})
    return {
        "count": len(items),
        "summary": {"by_status": by_status, "total_ports": total_ports},
        "attribution": poe.EEZ_ATTRIBUTION,
        "items": items,
    }


@router.get("/poe/zones/geojson")
async def poe_zones_geojson():
    if not poe.MAP_FILE.exists():
        raise HTTPException(404, "EEZ map not built yet — POST /api/poe/referential/build first")
    return FileResponse(
        poe.MAP_FILE, media_type="application/geo+json",
        headers={"Cache-Control": "public, max-age=3600", "X-EEZ-Source": "Marine Regions (VLIZ) v12 CC-BY 4.0"},
    )


@router.get("/poe/zones/{mrgid}")
async def poe_zone_fiche(mrgid: int):
    """Fiche de revue d'une ZEE : PoE + URLs TD/BU. Lecture seule, pas de Générer."""
    from app.services.poe_zone_fiche import build_zone_fiche

    fiche = await build_zone_fiche(_db, mrgid)
    if fiche is None:
        raise HTTPException(404, f"ZEE {mrgid} inconnue")
    return fiche


# ---------------------------------------------------------------------------
# Génération PoE carte — retirée (ne plus upsert poe_ports)
# ---------------------------------------------------------------------------
@router.post("/poe/zones/{mrgid}/generate")
async def poe_generate(mrgid: int, force: bool = False):
    raise HTTPException(410, GENERATE_GONE)


@router.get("/poe/zones/{mrgid}/generate/status")
async def poe_generate_status(mrgid: int):
    raise HTTPException(410, GENERATE_GONE)


@router.post("/poe/generate-batch")
async def poe_generate_batch():
    raise HTTPException(410, GENERATE_GONE)


@router.get("/poe/generate-batch/status")
async def poe_generate_batch_status():
    raise HTTPException(410, GENERATE_GONE)


@router.post("/poe/generate-batch/cancel")
async def poe_generate_batch_cancel():
    raise HTTPException(410, GENERATE_GONE)


@router.get("/poe/claude-usage")
async def poe_claude_usage():
    from app.core.claude import usage_public
    from app.db import get_settings
    return usage_public(await get_settings())


# ---------------------------------------------------------------------------
# Validation Bottom-Up des PoE existants via Overpass OSM (tâche de fond)
# — enrichit osm_confidence / osm_tags SANS toucher nom, coordonnées ni texte.
# ---------------------------------------------------------------------------
OSM_STATE = TaskState()


class OsmValidateBody(BaseModel):
    only_unchecked: bool = True
    limit: int = 0          # 0 = tous
    radius_m: int = 3000


def _start_osm_task(only_unchecked: bool, limit: int, radius_m: int, resumed: bool = False):
    """Démarre la validation Overpass et persiste l'état du job dans db.jobs
    (reprise automatique après kill/reload du serveur)."""
    OSM_STATE.reset()
    OSM_STATE.running = True
    OSM_STATE.started_at = time.time()
    if resumed:
        OSM_STATE.log("Reprise automatique — job interrompu par un redémarrage du serveur")

    async def _runner():
        try:
            await _db.jobs.update_one(
                {"_id": "osm_validation"},
                {"$set": {"desired": True, "resumed": resumed, "started_at": poe.now_iso(),
                          "params": {"only_unchecked": only_unchecked, "limit": limit,
                                     "radius_m": radius_m}}},
                upsert=True)
            OSM_STATE.summary = await osm_validate.validate_ports(
                _db, OSM_STATE, only_unchecked=only_unchecked, limit=limit, radius_m=radius_m)
            await _db.jobs.update_one({"_id": "osm_validation"}, {"$set": {
                "desired": False, "finished_at": poe.now_iso(),
                "cancelled": OSM_STATE.cancel, "summary": OSM_STATE.summary}})
        except Exception as e:
            # desired reste True en base → nouvelle tentative au prochain démarrage
            OSM_STATE.error = f"{type(e).__name__}: {e}"
            OSM_STATE.log(f"FATAL: {OSM_STATE.error} — reprise auto au prochain démarrage")
        finally:
            OSM_STATE.finished_at = time.time()
            OSM_STATE.running = False

    asyncio.create_task(_runner())


def schedule_job_resume(delay_s: float = 20.0):
    """Reprise automatique des jobs de fond interrompus (appelé au startup).
    Le délai évite de relancer pendant une rafale de hot-reloads."""
    async def _resume():
        await asyncio.sleep(delay_s)
        try:
            job = await _db.jobs.find_one({"_id": "osm_validation"})
            if not job or not job.get("desired") or OSM_STATE.running:
                return
            params = job.get("params") or {}
            only_unchecked = bool(params.get("only_unchecked", True))
            q = {"lat": {"$ne": None}}
            if only_unchecked:
                q["osm_checked_at"] = {"$exists": False}
            remaining = await _db.poe_ports.count_documents(q)
            if remaining == 0:
                await _db.jobs.update_one({"_id": "osm_validation"}, {"$set": {
                    "desired": False, "finished_at": poe.now_iso(),
                    "note": "reprise inutile: tous les PoE déjà vérifiés"}})
                return
            print(f"[resume] validation OSM interrompue détectée — reprise auto ({remaining} PoE restants)")
            _start_osm_task(only_unchecked, int(params.get("limit") or 0),
                            int(params.get("radius_m") or 3000), resumed=True)
        except Exception as e:
            print(f"[resume] échec de la reprise automatique: {e}")

    asyncio.create_task(_resume())


@router.post("/poe/validate-osm", status_code=202)
async def poe_validate_osm(body: OsmValidateBody | None = None):
    if OSM_STATE.running:
        raise HTTPException(409, "OSM validation already running")
    body = body or OsmValidateBody()
    _start_osm_task(body.only_unchecked, body.limit, body.radius_m)
    return {"status": "started", "only_unchecked": body.only_unchecked,
            "limit": body.limit, "radius_m": body.radius_m}


@router.get("/poe/validate-osm/status")
async def poe_validate_osm_status():
    st = OSM_STATE.status()
    if _db is not None:
        st["osm_checked_total"] = await _db.poe_ports.count_documents({"osm_checked_at": {"$exists": True}})
        st["high_confidence_total"] = await _db.poe_ports.count_documents({"osm_confidence": {"$gte": 0.5}})
    return st


@router.post("/poe/validate-osm/cancel")
async def poe_validate_osm_cancel():
    if not OSM_STATE.running:
        raise HTTPException(409, "No OSM validation running")
    OSM_STATE.cancel = True
    OSM_STATE.log("Annulation demandée — arrêt propre après le PoE en cours")
    return {"cancelling": True}


# ---------------------------------------------------------------------------
# Qualification juridique UNCLOS des ZEE sans PoE (logique métier, instantané)
# ---------------------------------------------------------------------------
@router.post("/poe/qualify-unclos")
async def poe_qualify_unclos():
    zones = await _db.eez_zones.find({}, {"mrgid": 1, "name": 1, "geoname": 1, "pol_type": 1,
                                          "anchor": 1, "poe_count": 1, "unclos": 1}).to_list(1000)
    counts: dict = {}
    qualified = cleared = 0
    for z in zones:
        q = poe.qualify_unclos(z)
        if q:
            q["qualified_at"] = poe.now_iso()
            await _db.eez_zones.update_one({"_id": z["_id"]}, {"$set": {"unclos": q}})
            counts[q["code"]] = counts.get(q["code"], 0) + 1
            qualified += 1
        elif z.get("unclos"):
            await _db.eez_zones.update_one({"_id": z["_id"]}, {"$unset": {"unclos": ""}})
            cleared += 1
    return {"zones_scanned": len(zones), "qualified": qualified, "cleared": cleared, "by_code": counts}


# ---------------------------------------------------------------------------
# Ports & exports
# ---------------------------------------------------------------------------
@router.get("/poe/ports")
async def poe_ports(mrgid: int | None = None, country: str | None = None):
    q: dict = {}
    if mrgid is not None:
        q["mrgid"] = mrgid
    if country:
        q["country_iso2"] = country.upper()
    docs = await _db.poe_ports.find(q).to_list(10000)
    return poe.ports_to_geojson(docs)


@router.get("/export/poe.geojson")
async def export_poe_geojson():
    docs = await _db.poe_ports.find({}).to_list(10000)
    return JSONResponse(
        poe.ports_to_geojson(docs),
        headers={"Content-Disposition": "attachment; filename=ports_of_entry.geojson"},
    )
