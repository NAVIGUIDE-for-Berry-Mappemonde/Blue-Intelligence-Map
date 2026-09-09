"""app.routers.amp — 4e mode : Aires Marines Protégées (ProtectedSeas)."""
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.run_rules import catalog_default
from app.core.tasks import TaskState
from app.db import db
from app.services import amp as amp_svc
from app.services import amp_visit

router = APIRouter(prefix="/api")
VISIT_DISCOVER_STATE = TaskState(max_logs=400)


class VisitUrlBody(BaseModel):
    url: str | None = None


class RefreshBody(BaseModel):
    bbox: str
    force: bool = True


class DiscoverBody(BaseModel):
    limit: int = 200
    skip_search: bool = False
    profile: str | None = None
    rules: dict | None = None


def _parse_bbox(raw: str, **caps):
    try:
        return amp_svc.parse_bbox(raw, **caps)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/amp")
async def list_amp(bbox: str = "", force: bool = False, visible: bool = False,
                   review: bool = False):
    """Polygones AMP dans la bbox (minx,miny,maxx,maxy, WGS84)."""
    if not bbox:
        raise HTTPException(400, "bbox required (minx,miny,maxx,maxy)")
    # Caps monde entier : la vue dézoomée est servie depuis le cache local,
    # seul le rafraîchissement ProtectedSeas garde la limite stricte.
    box = _parse_bbox(bbox, max_w=360.0, max_h=180.0)
    max_span = float(catalog_default("amp.bbox_max_deg", 8))
    span = amp_svc.bbox_span_deg(box)
    if span > max_span:
        # Vue dézoomée : on sert les sites déjà en cache local (aucun appel
        # ProtectedSeas). Au-delà de 60° un polygone bbox dépasse l'hémisphère
        # que Mongo accepte pour $geoIntersects → on liste tout le cache.
        if span >= 60:
            docs = await db.amp_sites.find({}).limit(400).to_list(400)
        else:
            docs = await amp_svc.query_cache(db, box, limit=400)
        if visible or review:
            from app.services.review_gold import filter_visible
            docs = await filter_visible(
                db, "amp", docs,
                lambda d: d.get("site_id") or d.get("_id"))
        return amp_svc.to_feature_collection(docs, extra={
            "hint": "zoom" if not docs else None,
            "source": "cache",
            "truncated": len(docs) >= 400,
            "fetched": 0,
        })
    docs, meta = await amp_svc.sites_in_bbox(db, box, force=force)
    if visible or review:
        from app.services.review_gold import filter_visible
        docs = await filter_visible(
            db, "amp", docs,
            lambda d: d.get("site_id") or d.get("_id"))
    return amp_svc.to_feature_collection(docs, extra={
        "hint": None,
        "source": meta.get("source"),
        "truncated": bool(meta.get("truncated")),
        "fetched": meta.get("fetched") or 0,
        "error": meta.get("error"),
    })


@router.get("/amp/stats")
async def amp_stats():
    return await amp_svc.amp_stats(db)


@router.get("/amp/sites/{site_id}")
async def amp_site(site_id: str):
    doc = await db.amp_sites.find_one({"_id": site_id})
    if not doc:
        doc = await db.amp_sites.find_one({"site_id": site_id})
    if not doc:
        raise HTTPException(404, "AMP not found")
    return {
        "kind": "amp",
        "id": doc.get("site_id") or doc.get("_id"),
        **amp_svc.public_properties(doc),
        "wrote_amp_sites": False,
    }


@router.post("/amp/refresh")
async def amp_refresh(body: RefreshBody):
    box = _parse_bbox(body.bbox)
    docs, meta = await amp_svc.sites_in_bbox(db, box, force=body.force)
    return {
        "status": "ok",
        "count": len(docs),
        **meta,
    }


@router.post("/amp/sites/{site_id}/visit-url")
async def amp_set_visit_url(site_id: str, body: VisitUrlBody):
    doc = await amp_svc.set_visit_url(db, site_id, body.url)
    if not doc:
        raise HTTPException(404, "AMP not found")
    if body.url and amp_svc.urls_equivalent(body.url, doc.get("manager_url")):
        raise HTTPException(
            409,
            "visit_url must differ from ProtectedSeas manager_url",
        )
    return {
        "id": doc.get("site_id") or doc.get("_id"),
        "manager_url": doc.get("manager_url"),
        "visit_url": doc.get("visit_url"),
        "visit_url_status": doc.get("visit_url_status"),
        "visit_url_source": doc.get("visit_url_source"),
    }


@router.post("/amp/resolve-visit-urls")
async def amp_resolve_visit_urls(limit: int = 500):
    """Heuristique synchrone : other_helpful_links seulement."""
    return await amp_svc.resolve_visit_urls(db, limit=min(max(limit, 1), 2000))


@router.post("/amp/discover-visit-urls")
async def amp_discover_visit_start(body: DiscoverBody | None = None):
    """Job de fond : extras ProtectedSeas → Fetch → Search → juge NIM (chaîne json)."""
    if VISIT_DISCOVER_STATE.running:
        raise HTTPException(409, "A visit-URL discover is already running")
    body = body or DiscoverBody()
    limit = min(max(int(body.limit or 200), 1), 2000)
    from app.core.run_rules import RuleError, bind_rules, reset_rules, snapshot_for_run
    from app.db import get_settings
    from app.services import isolated_runs
    settings = await get_settings()
    try:
        rules = snapshot_for_run(
            mode="amp", settings=settings,
            overrides=body.rules, profile=body.profile)
    except RuleError as e:
        raise HTTPException(400, str(e)) from e
    opened = await isolated_runs.open_run(
        db, "amp", kind="discover_visit",
        label="amp-visit", settings=settings,
        extra_params={"limit": limit, "skip_search": bool(body.skip_search),
                      "profile": rules.get("profile")},
        rules_overrides=body.rules, profile=body.profile,
    )
    run_id = opened["run_id"]
    VISIT_DISCOVER_STATE.run_id = run_id
    isolated_runs.reset_run(opened["token"])

    async def _runner():
        rules_token = bind_rules(rules)
        try:
            await amp_visit.discover_visit_urls(
                db,
                state=VISIT_DISCOVER_STATE,
                limit=limit,
                skip_search=bool(body.skip_search),
                run_id=run_id,
            )
            await isolated_runs.finalize_run(
                db, "amp", run_id, extra=VISIT_DISCOVER_STATE.summary)
        except Exception as exc:
            VISIT_DISCOVER_STATE.error = f"{type(exc).__name__}: {exc}"
            await isolated_runs.finalize_run(
                db, "amp", run_id, error=VISIT_DISCOVER_STATE.error)
        finally:
            reset_rules(rules_token)

    asyncio.create_task(_runner())
    return {
        "started": True, "limit": limit, "skip_search": bool(body.skip_search),
        "run_id": run_id, "wrote_amp_sites": False,
        "profile": rules.get("profile"), "rules_hash": rules.get("hash"),
    }


@router.post("/amp/discover-visit-urls/cancel")
async def amp_discover_visit_cancel():
    if not VISIT_DISCOVER_STATE.running:
        raise HTTPException(409, "No visit-URL discover is running")
    VISIT_DISCOVER_STATE.cancel = True
    VISIT_DISCOVER_STATE.log("Stop demandé")
    return {"cancelling": True}


@router.get("/amp/discover-visit-urls/status")
async def amp_discover_visit_status():
    s = VISIT_DISCOVER_STATE
    return {
        "running": s.running,
        "cancelling": s.cancel,
        "started_at": s.started_at,
        "finished_at": s.finished_at,
        "progress": s.progress,
        "total": s.total,
        "summary": s.summary,
        "error": s.error,
        "logs_tail": s.logs[-40:],
        "run_id": s.run_id,
        "wrote_amp_sites": False,
    }


@router.get("/amp/runs")
async def amp_runs_list():
    from app.services import isolated_runs
    items = await isolated_runs.list_meta_runs(db, "amp")
    return {
        "count": len(items),
        "wrote_amp_sites": False,
        "items": items,
    }


@router.get("/amp/runs/{run_id}")
async def amp_run_detail(run_id: str):
    from app.services import isolated_runs
    doc = await isolated_runs.get_meta_run(db, "amp", run_id)
    if not doc:
        raise HTTPException(404, f"Run {run_id} unknown")
    return {**doc, "wrote_amp_sites": False}


@router.get("/amp/runs/{run_id}/geojson")
async def amp_run_geojson(run_id: str):
    """FeatureCollection du run (polygones) — sélecteur de run de la carte."""
    meta = await db.amp_runs.find_one({"_id": run_id})
    if not meta:
        raise HTTPException(404, f"Run {run_id} unknown")
    docs = await db.amp_run_sites.find({"run_id": run_id}).to_list(20000)
    live_fallback = False
    if not docs and meta.get("wrote_amp_sites"):
        docs = await db.amp_sites.find({}).to_list(20000)
        live_fallback = True
    return amp_svc.to_feature_collection(docs, extra={
        "run_id": run_id,
        "live_fallback": live_fallback,
        "hint": None,
        "wrote_amp_sites": False,
    })


@router.get("/export/amp.geojson")
async def export_amp_geojson():
    docs = await db.amp_sites.find({}, amp_svc.SLIM_PROJECTION).to_list(20000)
    return amp_svc.to_feature_collection(docs, geometry=False, extra={
        "name": "amp_sites",
        "note": "centroids + manager_url / visit_url — not official boundaries",
    })
