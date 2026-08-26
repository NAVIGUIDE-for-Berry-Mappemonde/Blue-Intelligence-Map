"""
ml_routes.py — Endpoints FastAPI du Bootstrapping ML (weak supervision, anomalies, NER).
Injecté via ml_routes.init(db) + app.include_router(ml_routes.router).
"""
import asyncio
import time

from fastapi import APIRouter, Body, HTTPException

import ml_core
from poe_routes import TaskState

router = APIRouter(prefix="/api/ml")
_db = None

TRAIN_STATE = TaskState()
ANOM_STATE = TaskState()


def init(db):
    global _db
    _db = db


@router.get("/status")
async def ml_status():
    import rag_core
    return {
        "dataset": await ml_core.dataset_stats(_db),
        "models": ml_core.models_status(),
        "embedding_backend": rag_core.embedding_backend(),
    }


# --- Classifieur de pertinence (Gatekeeper local) ---------------------------
@router.post("/train/gatekeeper", status_code=202)
async def train_gatekeeper():
    if TRAIN_STATE.running:
        raise HTTPException(409, "Training already running")
    TRAIN_STATE.reset()
    TRAIN_STATE.running = True
    TRAIN_STATE.started_at = time.time()

    async def _runner():
        try:
            TRAIN_STATE.summary = await ml_core.train_gatekeeper(_db, log=TRAIN_STATE.log)
        except Exception as e:
            TRAIN_STATE.error = f"{type(e).__name__}: {e}"
            TRAIN_STATE.log(f"FATAL: {TRAIN_STATE.error}")
        finally:
            TRAIN_STATE.finished_at = time.time()
            TRAIN_STATE.running = False

    asyncio.create_task(_runner())
    return {"status": "started"}


@router.get("/train/status")
async def train_status():
    return TRAIN_STATE.status()


@router.post("/gatekeeper/predict")
async def gatekeeper_predict(body: dict = Body(...)):
    text = str(body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "body must contain 'text'")
    pred = ml_core.predict_relevance(text)
    if pred is None:
        raise HTTPException(404, "no trained gatekeeper model — POST /api/ml/train/gatekeeper first")
    return pred


# --- Anomalies spatiales des PoE --------------------------------------------
@router.post("/anomalies/scan", status_code=202)
async def anomalies_scan(body: dict | None = Body(default=None)):
    if ANOM_STATE.running:
        raise HTTPException(409, "Anomaly scan already running")
    contamination = float((body or {}).get("contamination", 0.05))
    ANOM_STATE.reset()
    ANOM_STATE.running = True
    ANOM_STATE.started_at = time.time()

    async def _runner():
        try:
            ANOM_STATE.summary = await ml_core.scan_poe_anomalies(_db, state=ANOM_STATE,
                                                                  contamination=contamination)
        except Exception as e:
            ANOM_STATE.error = f"{type(e).__name__}: {e}"
            ANOM_STATE.log(f"FATAL: {ANOM_STATE.error}")
        finally:
            ANOM_STATE.finished_at = time.time()
            ANOM_STATE.running = False

    asyncio.create_task(_runner())
    return {"status": "started"}


@router.get("/anomalies/status")
async def anomalies_status():
    return ANOM_STATE.status()


@router.get("/anomalies/report")
async def anomalies_report():
    if not ml_core.ANOMALY_REPORT_FILE.exists():
        raise HTTPException(404, "no anomaly report — POST /api/ml/anomalies/scan first")
    import json
    return json.loads(ml_core.ANOMALY_REPORT_FILE.read_text())


# --- Dataset NER (préparation spaCy) -----------------------------------------
@router.post("/ner/export-dataset")
async def ner_export():
    return await ml_core.export_ner_dataset(_db)
