"""app.routers.amp — 4e mode : Aires Marines Protégées (ProtectedSeas)."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.run_rules import catalog_default
from app.db import db
from app.services import amp as amp_svc

router = APIRouter(prefix="/api")


class VisitUrlBody(BaseModel):
    url: str | None = None


class RefreshBody(BaseModel):
    bbox: str
    force: bool = True


def _parse_bbox(raw: str):
    try:
        return amp_svc.parse_bbox(raw)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/amp")
async def list_amp(bbox: str = "", force: bool = False):
    """Polygones AMP dans la bbox (minx,miny,maxx,maxy, WGS84)."""
    if not bbox:
        raise HTTPException(400, "bbox required (minx,miny,maxx,maxy)")
    box = _parse_bbox(bbox)
    max_span = float(catalog_default("amp.bbox_max_deg", 8))
    if amp_svc.bbox_span_deg(box) > max_span:
        return amp_svc.to_feature_collection(
            [], extra={"hint": "zoom", "source": "span", "truncated": False})
    docs, meta = await amp_svc.sites_in_bbox(db, box, force=force)
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
    return await amp_svc.resolve_visit_urls(db, limit=min(max(limit, 1), 2000))


@router.get("/export/amp.geojson")
async def export_amp_geojson():
    docs = await db.amp_sites.find({}, amp_svc.SLIM_PROJECTION).to_list(20000)
    return amp_svc.to_feature_collection(docs, geometry=False, extra={
        "name": "amp_sites",
        "note": "centroids + manager_url / visit_url — not official boundaries",
    })
