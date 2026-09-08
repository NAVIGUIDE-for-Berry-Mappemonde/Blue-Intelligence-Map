"""API de l'onglet Review — file de fiches + commentaire + interrupteur Gold.

Lecture des runs / v1. Écrit `review_comments` et `review_gold`.
N'écrit jamais `projects` / `poe_ports` / `eez_zones` / `marinas` / `amp_sites`.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import db
from app.services import review_gold, review_queue
from app.services.poe_zone_fiche import PUBLISHED_RUN

router = APIRouter(prefix="/api")


def _kind_or_400(kind: str) -> str:
    if kind not in review_queue.KINDS:
        raise HTTPException(400, "kind must be project|eez|poe|marina|capitainerie|amp")
    return kind


@router.get("/review/runs")
async def review_runs(kind: str):
    kind = _kind_or_400(kind)
    return await review_queue.list_runs(db, kind)


@router.get("/review/queue")
async def review_queue_get(kind: str, run_id: str = PUBLISHED_RUN,
                           offset: int = 0, limit: int = 500, q: str = "",
                           pre_gold: bool = False, stable: bool = False):
    kind = _kind_or_400(kind)
    return await review_queue.list_queue(
        db, kind, run_id, offset=offset, limit=limit, q=q,
        pre_gold=pre_gold, stable=stable)


@router.get("/review/fiche")
async def review_fiche_get(kind: str, id: str, run_id: str = PUBLISHED_RUN,
                           content_run_id: str | None = None):
    kind = _kind_or_400(kind)
    if not id:
        raise HTTPException(400, "id required")
    out = await review_queue.get_fiche(
        db, kind, run_id, id, content_run_id=content_run_id)
    if out is None:
        raise HTTPException(404, "fiche not found")
    return out


class CommentBody(BaseModel):
    kind: str
    id: str
    run_id: str = PUBLISHED_RUN
    comment: str = Field(default="")


class GoldBody(BaseModel):
    kind: str
    id: str
    run_id: str = PUBLISHED_RUN


@router.put("/review/comment")
async def review_comment_put(body: CommentBody):
    kind = _kind_or_400(body.kind)
    if not body.id:
        raise HTTPException(400, "id required")
    return await review_queue.save_comment(db, kind, body.run_id, body.id, body.comment)


@router.put("/review/gold")
async def review_gold_put(body: GoldBody):
    if body.kind not in review_gold.GOLD_KINDS:
        raise HTTPException(400, "kind must be project|eez|marina")
    if not body.id:
        raise HTTPException(400, "id required")
    try:
        return await review_gold.toggle_gold(
            db, body.kind, body.id, run_id=body.run_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
