"""API revue Projets + Gold (CDC v2, phase D). Monté avant `/projects/{id}`."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.db import db, get_settings
from app.services import project_review as review

router = APIRouter(prefix="/api")


class ReviewEditBody(BaseModel):
    lat: float | None = None
    lon: float | None = None
    site_name: str | None = None
    note: str | None = None


class ReviewAcceptBody(BaseModel):
    lat: float | None = None
    lon: float | None = None
    site_name: str | None = None
    note: str = ""
    write_projects: bool = True
    force: bool = False


class ReviewRejectBody(BaseModel):
    note: str = ""


class ReviewRebuildBody(BaseModel):
    run_id: str | None = None


@router.post("/projects/review/rebuild")
async def review_rebuild(body: ReviewRebuildBody | None = None):
    body = body or ReviewRebuildBody()
    return await review.rebuild_queue(db, run_id=body.run_id)


@router.get("/projects/review/stats")
async def review_stats():
    return await review.review_stats(db)


@router.get("/projects/review")
async def review_list(status: str | None = None, source: str | None = None,
                     run_id: str | None = None, limit: int = 200):
    if status and status not in review.STATUSES:
        raise HTTPException(400, f"status must be {'|'.join(review.STATUSES)}")
    if source and source not in review.SOURCES:
        raise HTTPException(400, f"source must be {'|'.join(review.SOURCES)}")
    return await review.list_review(
        db, status=status, source=source, run_id=run_id, limit=limit)


@router.get("/projects/review/{item_id}")
async def review_get(item_id: str):
    try:
        return review.public_item(await review.get_item(db, item_id))
    except KeyError:
        raise HTTPException(404, f"review item {item_id} unknown")


@router.patch("/projects/review/{item_id}")
async def review_edit(item_id: str, body: ReviewEditBody):
    try:
        return await review.edit_item(
            db, item_id, lat=body.lat, lon=body.lon,
            site_name=body.site_name, note=body.note)
    except KeyError:
        raise HTTPException(404, f"review item {item_id} unknown")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/projects/review/{item_id}/accept")
async def review_accept(item_id: str, body: ReviewAcceptBody | None = None):
    body = body or ReviewAcceptBody()
    settings = await get_settings()
    try:
        return await review.accept_item(
            db, item_id,
            lat=body.lat, lon=body.lon, site_name=body.site_name,
            note=body.note, write_projects=body.write_projects,
            force=body.force, settings=settings)
    except KeyError:
        raise HTTPException(404, f"review item {item_id} unknown")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/projects/review/{item_id}/reject")
async def review_reject(item_id: str, body: ReviewRejectBody | None = None):
    body = body or ReviewRejectBody()
    try:
        return await review.reject_item(db, item_id, note=body.note)
    except KeyError:
        raise HTTPException(404, f"review item {item_id} unknown")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/projects/gold")
async def gold_preview():
    return await review.gold_stats(db)


@router.post("/projects/gold/export")
async def gold_export():
    return await review.export_gold(db)


@router.get("/projects/gold/file")
async def gold_file():
    if not review.GOLD_FILE.exists():
        raise HTTPException(404, "no gold file — POST /api/projects/gold/export first")
    return FileResponse(
        review.GOLD_FILE,
        media_type="application/json",
        filename="project_gold.json",
    )
