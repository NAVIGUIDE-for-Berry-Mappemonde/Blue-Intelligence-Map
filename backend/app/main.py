"""
app.main — Application FastAPI Blue Intelligence.

Assemble les routers par domaine, les middlewares (gzip, CORS) et les
événements de démarrage (index Mongo, rafraîchissement automatique des PoE).
Point d'entrée : `uvicorn server:app` (shim) ou `uvicorn app.main:app`.

Quand ``frontend/build/`` existe (ou ``SERVE_FRONTEND=1``), sert aussi le
bundle React sur ``/`` pour un accès preview unifié (API + UI sur le port 8001).
"""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.db import client
from app.routers import formalities, marinas, misc, ml, project_review, project_runs, projects, runs, swarm

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND_BUILD = _REPO_ROOT / "frontend" / "build"


def _serve_frontend_enabled() -> bool:
    flag = os.environ.get("SERVE_FRONTEND", "auto").lower()
    if flag in ("0", "false", "no"):
        return False
    if flag in ("1", "true", "yes"):
        return True
    return _FRONTEND_BUILD.is_dir()


_SERVE_FRONTEND = _serve_frontend_enabled()

app = FastAPI(
    title="Blue Intelligence API",
    docs_url="/api/docs" if _SERVE_FRONTEND else "/docs",
    redoc_url="/api/redoc" if _SERVE_FRONTEND else "/redoc",
    openapi_url="/api/openapi.json" if _SERVE_FRONTEND else "/openapi.json",
)

for module in (project_review, project_runs, projects, swarm, marinas, formalities, runs, ml, misc):
    app.include_router(module.router)


if not _SERVE_FRONTEND:
    # Ingress production : seules les routes /api/* sont exposées.
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
        await db.poe_listing_review.create_index("run_id")
        await db.poe_listing_review.create_index([("run_id", 1), ("reason", 1)])
        await db.poe_seed_ports.create_index("dedup_key", unique=True, sparse=True)
        await db.poe_seed_ports.create_index("mrgid")
        await db.poe_seed_ports.create_index("verify_verdict")
    except Exception as e:
        print(f"[startup] poe index creation failed (non-fatal): {e}")
    try:
        from app.core.geo import ensure_geo_indexes
        await ensure_geo_indexes(db)
    except Exception as e:
        print(f"[startup] geocode cache index creation failed (non-fatal): {e}")
    try:
        from app.services.project_runs import ensure_run_indexes
        await ensure_run_indexes(db)
    except Exception as e:
        print(f"[startup] project run index creation failed (non-fatal): {e}")
    try:
        from app.services.project_review import ensure_review_indexes
        await ensure_review_indexes(db)
    except Exception as e:
        print(f"[startup] project review index creation failed (non-fatal): {e}")
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


if _SERVE_FRONTEND:
    _RESERVED_ROOT = {"api", "docs", "redoc", "openapi.json"}

    @app.get("/", include_in_schema=False)
    async def spa_index():
        return FileResponse(_FRONTEND_BUILD / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_assets(full_path: str):
        head = full_path.split("/", 1)[0] if full_path else ""
        if head in _RESERVED_ROOT:
            raise HTTPException(404, detail="Not Found")
        candidate = _FRONTEND_BUILD / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_BUILD / "index.html")
