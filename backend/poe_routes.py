"""
poe_routes.py — Endpoints FastAPI du mode Formalités refactoré [ZEE -> Ports d'Entrée].
Injecté dans l'app principale via poe_routes.init(db) + app.include_router(poe_routes.router).
"""
import asyncio
import os
import time

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import poe
import osm_validate

router = APIRouter(prefix="/api")
_db = None


def init(db):
    global _db
    _db = db


def _keys() -> tuple[str | None, str | None]:
    return (
        (os.environ.get("GEMINI_API_KEY") or "").strip() or None,
        (os.environ.get("EMERGENT_LLM_KEY") or "").strip() or None,
    )


class TaskState:
    def __init__(self):
        self.running = False
        self.started_at = None
        self.finished_at = None
        self.progress = 0
        self.total = 0
        self.results: list[dict] = []
        self.logs: list[str] = []
        self.error = None
        self.summary = None
        self.cancel = False

    def log(self, msg: str):
        self.logs.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        if len(self.logs) > 800:
            self.logs = self.logs[-800:]

    def reset(self):
        self.__init__()

    def status(self):
        return {
            "running": self.running, "started_at": self.started_at, "finished_at": self.finished_at,
            "progress": self.progress, "total": self.total, "results": self.results[-40:],
            "logs_tail": self.logs[-60:], "error": self.error, "summary": self.summary,
            "cancelling": self.cancel and self.running,
        }


REF_STATE = TaskState()
BATCH_STATE = TaskState()
GEN_TASKS: dict[int, dict] = {}
GEN_LOCKS: set[int] = set()


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
    gem, emg = _keys()
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
        if mrgid in GEN_LOCKS or BATCH_STATE.running or REF_STATE.running:
            _auto_log(f"[{z.get('name')}] SKIP (verrou ou batch manuel en cours)")
            continue
        GEN_LOCKS.add(mrgid)
        prev_gen = z.get("generated_at")
        try:
            doc = await asyncio.wait_for(
                poe.generate_zone_poe(_db, mrgid, gem, emg,
                                      logger=lambda m, n=z.get("name"): _auto_log(f"[{n}] {m}"),
                                      force=force),
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
        busy = REF_STATE.running or BATCH_STATE.running
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


# ---------------------------------------------------------------------------
# Génération PoE — unitaire
# ---------------------------------------------------------------------------
@router.post("/poe/zones/{mrgid}/generate", status_code=202)
async def poe_generate(mrgid: int, force: bool = False):
    zone = await _db.eez_zones.find_one({"mrgid": mrgid})
    if not zone:
        raise HTTPException(404, f"EEZ mrgid={mrgid} unknown")
    if mrgid in GEN_LOCKS:
        raise HTTPException(409, "Generation already running for this EEZ")
    for k in [k for k, v in GEN_TASKS.items() if v.get("finished_at") and time.time() - v["finished_at"] > 3600]:
        GEN_TASKS.pop(k, None)
    GEN_LOCKS.add(mrgid)
    GEN_TASKS[mrgid] = {"state": "running", "started_at": time.time(), "finished_at": None,
                        "result": None, "error": None, "logs": []}
    gem, emg = _keys()

    async def _runner():
        task = GEN_TASKS[mrgid]

        def log_fn(msg):
            task["logs"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
            if len(task["logs"]) > 300:
                task["logs"] = task["logs"][-300:]

        try:
            doc = await asyncio.wait_for(
                poe.generate_zone_poe(_db, mrgid, gem, emg, logger=log_fn, force=force),
                timeout=360,
            )
            task["result"] = poe.zone_to_item(doc) if doc else None
            task["state"] = "done"
        except Exception as e:
            task["error"] = f"{type(e).__name__}: {e}"
            task["state"] = "error"
            log_fn(f"FATAL: {task['error']}")
        finally:
            task["finished_at"] = time.time()
            GEN_LOCKS.discard(mrgid)

    asyncio.create_task(_runner())
    return {"status": "started", "mrgid": mrgid}


@router.get("/poe/zones/{mrgid}/generate/status")
async def poe_generate_status(mrgid: int):
    task = GEN_TASKS.get(mrgid)
    if not task:
        return {"state": "idle", "mrgid": mrgid}
    return {"state": task["state"], "mrgid": mrgid, "started_at": task["started_at"],
            "finished_at": task["finished_at"], "result": task["result"],
            "error": task["error"], "logs_tail": task["logs"][-40:]}


# ---------------------------------------------------------------------------
# Génération PoE — batch
# ---------------------------------------------------------------------------
class PoeBatchBody(BaseModel):
    limit: int = 10          # 0 = toutes
    only_missing: bool = True
    force: bool = False


@router.post("/poe/generate-batch")
async def poe_generate_batch(body: PoeBatchBody | None = None):
    if BATCH_STATE.running:
        raise HTTPException(409, "A PoE batch is already running")
    body = body or PoeBatchBody()
    q = {"status": "non_generee"} if body.only_missing else {}
    docs = await _db.eez_zones.find(q, {"geometry": 0}).to_list(500)
    docs.sort(key=lambda d: (d.get("name") or "").lower())
    if body.limit > 0:
        docs = docs[: body.limit]
    if not docs:
        raise HTTPException(400, "No candidate EEZ (build the referential or uncheck only_missing)")

    gem, emg = _keys()
    BATCH_STATE.reset()
    BATCH_STATE.running = True
    BATCH_STATE.started_at = time.time()
    BATCH_STATE.total = len(docs)

    async def _runner():
        try:
            BATCH_STATE.log(f"{len(docs)} ZEE sélectionnées (concurrency=2, only_missing={body.only_missing})")
            sem = asyncio.Semaphore(2)
            counter = {"i": 0}

            async def _one(d):
                mrgid = d["mrgid"]
                async with sem:
                    if BATCH_STATE.cancel:
                        BATCH_STATE.log(f"SKIP {d.get('name')} (batch annulé)")
                        return
                    if mrgid in GEN_LOCKS:
                        BATCH_STATE.log(f"SKIP {d.get('name')} (déjà verrouillée)")
                        return
                    GEN_LOCKS.add(mrgid)
                    try:
                        doc = await asyncio.wait_for(
                            poe.generate_zone_poe(
                                _db, mrgid, gem, emg,
                                logger=lambda m: BATCH_STATE.log(f"[{d.get('name')}] {m}"),
                                force=body.force,
                            ),
                            timeout=360,
                        )
                        BATCH_STATE.results.append({
                            "mrgid": mrgid, "name": d.get("name"),
                            "status": (doc or {}).get("status"),
                            "poe_count": (doc or {}).get("poe_count", 0),
                        })
                    except Exception as e:
                        BATCH_STATE.log(f"[{d.get('name')}] FAILED: {type(e).__name__}: {e}")
                        BATCH_STATE.results.append({"mrgid": mrgid, "name": d.get("name"),
                                                    "error": f"{type(e).__name__}: {e}"})
                    finally:
                        GEN_LOCKS.discard(mrgid)
                        counter["i"] += 1
                        BATCH_STATE.progress = counter["i"]

            await asyncio.gather(*(_one(d) for d in docs))
            by = {}
            for r in BATCH_STATE.results:
                s = r.get("status") or "error"
                by[s] = by.get(s, 0) + 1
            BATCH_STATE.summary = by
            BATCH_STATE.log(f"Batch terminé. Statuts: {by}")
        except Exception as e:
            BATCH_STATE.error = f"{type(e).__name__}: {e}"
            BATCH_STATE.log(f"FATAL: {BATCH_STATE.error}")
        finally:
            BATCH_STATE.finished_at = time.time()
            BATCH_STATE.running = False

    asyncio.create_task(_runner())
    return {"started": True, "selected": len(docs), "concurrency": 2}


@router.get("/poe/generate-batch/status")
async def poe_generate_batch_status():
    return BATCH_STATE.status()


@router.post("/poe/generate-batch/cancel")
async def poe_generate_batch_cancel():
    if not BATCH_STATE.running:
        raise HTTPException(409, "No PoE batch running")
    BATCH_STATE.cancel = True
    BATCH_STATE.log("Annulation demandée — les ZEE restantes ne démarreront pas")
    return {"cancelling": True}


# ---------------------------------------------------------------------------
# Validation Bottom-Up des PoE existants via Overpass OSM (tâche de fond)
# — enrichit osm_confidence / osm_tags SANS toucher nom, coordonnées ni texte.
# ---------------------------------------------------------------------------
OSM_STATE = TaskState()


class OsmValidateBody(BaseModel):
    only_unchecked: bool = True
    limit: int = 0          # 0 = tous
    radius_m: int = 3000


@router.post("/poe/validate-osm", status_code=202)
async def poe_validate_osm(body: OsmValidateBody | None = None):
    if OSM_STATE.running:
        raise HTTPException(409, "OSM validation already running")
    body = body or OsmValidateBody()
    OSM_STATE.reset()
    OSM_STATE.running = True
    OSM_STATE.started_at = time.time()

    async def _runner():
        try:
            OSM_STATE.summary = await osm_validate.validate_ports(
                _db, OSM_STATE, only_unchecked=body.only_unchecked,
                limit=body.limit, radius_m=body.radius_m)
        except Exception as e:
            OSM_STATE.error = f"{type(e).__name__}: {e}"
            OSM_STATE.log(f"FATAL: {OSM_STATE.error}")
        finally:
            OSM_STATE.finished_at = time.time()
            OSM_STATE.running = False

    asyncio.create_task(_runner())
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
