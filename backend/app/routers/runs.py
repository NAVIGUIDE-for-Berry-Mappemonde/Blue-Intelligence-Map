"""
app.routers.runs — Endpoints des runs versionnés du pipeline PoE.

POST /api/poe/runs                     démarre (ou reprend) un run from scratch
GET  /api/poe/runs                     liste des runs
GET  /api/poe/runs/{id}/status         méta + logs live
POST /api/poe/runs/{id}/cancel         annulation propre
GET  /api/poe/runs/{id}/ports          GeoJSON des ports du run
GET  /api/poe/runs/{id}/events         journal structuré (filtrable)
GET  /api/poe/runs/{id}/diff           comparaison port par port vs base v1
GET  /api/poe/runs/{id}/report         rapport quantitatif (json | markdown)
"""
import asyncio
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.core.tasks import TaskState
from app.db import db as _db
from app.services import poe_pipeline as poe
from app.services import poe_runs
from app.services.poe_diff import diff_run_vs_baseline
from app.services.poe_report import build_run_report, report_to_markdown

router = APIRouter(prefix="/api")

RUN_STATE = TaskState(max_logs=2000)
ACTIVE_RUN_ID: str | None = None


class RunBody(BaseModel):
    label: str = ""
    limit: int = 0                      # 0 = toutes les zones
    concurrency: int = 2
    zones: list[int] | None = None      # restreindre à certains mrgids
    resume_run_id: str | None = None    # reprendre un run interrompu


@router.post("/poe/runs", status_code=202)
async def poe_run_start(body: RunBody | None = None):
    global ACTIVE_RUN_ID
    if RUN_STATE.running:
        raise HTTPException(409, f"Run {ACTIVE_RUN_ID} already running")
    body = body or RunBody()
    resume = bool(body.resume_run_id)
    if resume:
        existing = await _db.poe_runs.find_one({"_id": body.resume_run_id})
        if not existing:
            raise HTTPException(404, f"Run {body.resume_run_id} unknown — cannot resume")
        run_id = body.resume_run_id
        label = body.label or existing.get("label") or ""
        params = existing.get("params") or {}
        limit = int(params.get("limit") or 0)
        zones = params.get("only_zones")
        concurrency = int(params.get("concurrency") or body.concurrency)
    else:
        run_id = poe_runs.new_run_id()
        label, limit, zones, concurrency = body.label, body.limit, body.zones, body.concurrency

    RUN_STATE.start()
    ACTIVE_RUN_ID = run_id

    async def _runner():
        global ACTIVE_RUN_ID
        try:
            RUN_STATE.summary = await poe_runs.execute_run(
                _db, RUN_STATE, run_id, label=label, limit=limit,
                only_zones=zones, concurrency=concurrency, resume=resume)
        except Exception as e:
            RUN_STATE.error = f"{type(e).__name__}: {e}"
            RUN_STATE.log(f"FATAL: {RUN_STATE.error}")
            await _db.poe_runs.update_one({"_id": run_id}, {"$set": {
                "state": "failed", "error": RUN_STATE.error,
                "finished_at": poe.now_iso()}})
        finally:
            RUN_STATE.finish()
            ACTIVE_RUN_ID = None

    asyncio.create_task(_runner())
    return {"status": "started", "run_id": run_id, "resume": resume}


@router.get("/poe/runs")
async def poe_runs_list():
    docs = await _db.poe_runs.find({}).sort("created_at", -1).to_list(100)
    return {"count": len(docs), "active_run_id": ACTIVE_RUN_ID, "items": docs}


@router.get("/poe/runs/{run_id}/status")
async def poe_run_status(run_id: str):
    doc = await _db.poe_runs.find_one({"_id": run_id})
    if not doc:
        raise HTTPException(404, f"Run {run_id} unknown")
    out = {"run": doc}
    if ACTIVE_RUN_ID == run_id:
        out["live"] = RUN_STATE.status()
    return out


@router.post("/poe/runs/{run_id}/cancel")
async def poe_run_cancel(run_id: str):
    if not RUN_STATE.running or ACTIVE_RUN_ID != run_id:
        raise HTTPException(409, f"Run {run_id} is not running")
    RUN_STATE.cancel = True
    RUN_STATE.log("Annulation demandée — les zones restantes ne démarreront pas")
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
