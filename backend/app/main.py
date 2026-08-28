"""
app.main — Application FastAPI Blue Intelligence.

Assemble les routers par domaine, les middlewares (gzip, CORS) et les
événements de démarrage (index Mongo, rafraîchissement automatique des PoE).
Point d'entrée : `uvicorn server:app` (shim) ou `uvicorn app.main:app`.
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.db import client
from app.routers import donations, formalities, marinas, misc, ml, projects, runs, swarm

app = FastAPI(title="Blue Intelligence API")

for module in (projects, swarm, marinas, formalities, runs, ml, donations, misc):
    app.include_router(module.router)


# --- OpenAPI exposé sous /api (l'ingress ne route que /api/*) ---
@app.get("/api/openapi.json")
async def openapi_under_api():
    return JSONResponse(app.openapi())


app.add_middleware(GZipMiddleware, minimum_size=1500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup():
    """Index des collections eez_zones / poe_ports, purge des collections
    héritées, puis démarrage des tâches de fond du mode Formalités."""
    from app.db import db
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
    formalities.start_auto_refresh()
    # Reprise automatique des tâches de fond interrompues (validation OSM)
    formalities.schedule_job_resume()


@app.on_event("shutdown")
async def _shutdown():
    from app.core.render import shutdown_render
    await shutdown_render()
    client.close()
