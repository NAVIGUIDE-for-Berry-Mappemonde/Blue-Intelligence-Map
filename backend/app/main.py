"""
app.main — Application FastAPI Blue Intelligence.

Assemble les routers par domaine, les middlewares (gzip, CORS) et les
événements de démarrage (index Mongo, rafraîchissement automatique des PoE).
Point d'entrée : `uvicorn server:app` (shim) ou `uvicorn app.main:app`.

Quand ``frontend/build/`` existe (ou ``SERVE_FRONTEND=1``), sert aussi le
bundle React sur ``/`` pour un accès preview unifié (API + UI sur le port 8001).
"""
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.db import client
from app.routers import amp, capitaineries, exports, formalities, marinas, misc, ml, project_runs, projects, review, runs, swarm

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

# ---------------------------------------------------------------------------
# Garde admin — quand ADMIN_KEY est définie (production), toutes les écritures
# /api/* et les lectures sensibles (review, admin) exigent le header
# X-Admin-Key. Sans ADMIN_KEY (dev / tests), tout reste ouvert.
# ---------------------------------------------------------------------------
_PUBLIC_WRITE_PATHS = {"/api/report-project"}   # signalement public de projets
_ADMIN_GET_PREFIXES = ("/api/review", "/api/admin")


@app.middleware("http")
async def _admin_gate(request, call_next):
    admin_key = os.environ.get("ADMIN_KEY", "").strip()
    if admin_key:
        path = request.url.path
        needs_key = False
        if path.startswith("/api/"):
            if (request.method in ("POST", "PUT", "PATCH", "DELETE")
                    and path not in _PUBLIC_WRITE_PATHS):
                needs_key = True
            elif path.startswith(_ADMIN_GET_PREFIXES):
                needs_key = True
        if needs_key:
            provided = request.headers.get("x-admin-key", "")
            if not secrets.compare_digest(provided, admin_key):
                return JSONResponse({"detail": "Admin key required"}, status_code=401)
    return await call_next(request)


for module in (project_runs, projects, swarm, marinas, capitaineries, formalities, amp, runs, review, ml, misc, exports):
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
        await db.capitaineries.create_index("osm_id", unique=True, sparse=True)
        await db.capitaineries.create_index("shom_id", unique=True, sparse=True)
        await db.capitaineries.create_index("name")
        await db.capitaineries.create_index("source")
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
        from app.services.isolated_runs import ensure_indexes as ensure_isolated_indexes
        await ensure_isolated_indexes(db)
    except Exception as e:
        print(f"[startup] project run index creation failed (non-fatal): {e}")
    try:
        from app.services.review_queue import ensure_review_indexes
        await ensure_review_indexes(db)
    except Exception as e:
        print(f"[startup] review comment index creation failed (non-fatal): {e}")
    try:
        existing = await db.list_collection_names()
        for legacy in ("formalities", "mpa_cache"):
            if legacy in existing:
                await db.drop_collection(legacy)
                print(f"[startup] dropped legacy {legacy} collection")
    except Exception as e:
        print(f"[startup] legacy collection drop failed (non-fatal): {e}")
    try:
        from app.services.amp import ensure_amp_indexes
        await ensure_amp_indexes(db)
    except Exception as e:
        print(f"[startup] amp index creation failed (non-fatal): {e}")
    # Rafraîchissement automatique : zones périmées re-vérifiées (monitoring MD5)
    # et erreurs re-tentées, sans action manuelle.
    formalities.start_auto_refresh()
    # Reprise automatique des tâches de fond interrompues (validation OSM)
    formalities.schedule_job_resume()
    # Préchauffage du dump GeoJSON marinas (plusieurs minutes sur Mongo distant).
    try:
        marinas.start_marinas_fc_warmup()
    except Exception as e:
        print(f"[startup] marinas cache warmup failed (non-fatal): {e}")


@app.on_event("shutdown")
async def _shutdown():
    from app.core.render import shutdown_render
    await shutdown_render()
    client.close()


if _SERVE_FRONTEND:
    _RESERVED_ROOT = {"api", "docs", "redoc", "openapi.json"}

    def _spa_index_response() -> FileResponse:
        # no-cache : le navigateur revalide index.html à chaque déploiement,
        # sinon il peut garder un vieux bundle qui référence des chunks disparus.
        return FileResponse(
            _FRONTEND_BUILD / "index.html",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/", include_in_schema=False)
    async def spa_index():
        return _spa_index_response()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_assets(full_path: str):
        head = full_path.split("/", 1)[0] if full_path else ""
        if head in _RESERVED_ROOT:
            raise HTTPException(404, detail="Not Found")
        try:
            candidate = (_FRONTEND_BUILD / full_path).resolve()
        except (OSError, ValueError):
            raise HTTPException(404, detail="Not Found")
        if not candidate.is_relative_to(_FRONTEND_BUILD):
            raise HTTPException(404, detail="Not Found")
        if candidate.is_file():
            return FileResponse(candidate)
        if head == "static":
            # Asset fingerprinté absent = bundle client périmé : un 404 franc
            # vaut mieux qu'index.html servi à la place d'un fichier JS.
            raise HTTPException(404, detail="Not Found")
        return _spa_index_response()
