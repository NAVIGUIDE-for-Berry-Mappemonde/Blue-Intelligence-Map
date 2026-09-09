"""API de l'onglet Review — file de fiches + commentaire + interrupteur Gold.

Lecture des runs / v1. Écrit `review_comments`, `review_gold`, `review_choices`.
N'écrit jamais `projects` / `poe_ports` / `eez_zones` / `marinas` /
`capitaineries` / `amp_sites`.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.db import db
from app.services import review_gold, review_queue
from app.services.review_choices import gold_ready, save_choice
from app.services.review_gold import GoldNotReady
from app.services.review_report import REPORT_KINDS, build_report, report_markdown
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


@router.get("/review/report")
async def review_report_get(kind: str = "all", format: str = "json"):
    """Rapport de review : commentaires + choix + Gold, lecture seule."""
    if kind != "all" and kind not in REPORT_KINDS:
        raise HTTPException(
            400, "kind must be all|eez|project|marina|capitainerie|amp")
    report = await build_report(db, kind)
    if format == "md":
        return PlainTextResponse(
            report_markdown(report),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition":
                     f"attachment; filename=review_report_{kind}.md"},
        )
    return report


class CommentBody(BaseModel):
    kind: str
    id: str
    run_id: str = PUBLISHED_RUN
    comment: str = Field(default="")


class GoldBody(BaseModel):
    kind: str
    id: str
    run_id: str = PUBLISHED_RUN


class ChoiceBody(BaseModel):
    kind: str
    id: str
    target: str
    action: str
    url: str | None = None
    port_id: str | None = None
    site_id: str | None = None
    field: str | None = None
    lat: float | None = None
    lon: float | None = None


@router.put("/review/comment")
async def review_comment_put(body: CommentBody):
    kind = _kind_or_400(body.kind)
    if not body.id:
        raise HTTPException(400, "id required")
    return await review_queue.save_comment(db, kind, body.run_id, body.id, body.comment)


@router.put("/review/choice")
async def review_choice_put(body: ChoiceBody):
    kind = _kind_or_400(body.kind)
    if kind not in ("eez", "project", "marina", "capitainerie", "amp"):
        raise HTTPException(400, "choice is not for this kind")
    if not body.id:
        raise HTTPException(400, "id required")
    try:
        out = await save_choice(
            db, kind, body.id, body.target, body.action,
            url=body.url, port_id=body.port_id, site_id=body.site_id,
            field=body.field, lat=body.lat, lon=body.lon)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    payload = await review_queue.get_fiche(db, kind, PUBLISHED_RUN, body.id)
    fiche = (payload or {}).get("fiche") if payload else None
    out["gold_ready"] = gold_ready(fiche, out.get("choices"), kind=kind)
    out["gold_on"] = bool(payload and payload.get("gold_on")) if payload else False
    return out


@router.put("/review/gold")
async def review_gold_put(body: GoldBody):
    if body.kind not in review_gold.GOLD_KINDS:
        raise HTTPException(400, "kind must be project|eez|marina|capitainerie|amp")
    if not body.id:
        raise HTTPException(400, "id required")
    payload = await review_queue.get_fiche(db, body.kind, body.run_id, body.id)
    if payload is None:
        raise HTTPException(404, "fiche not found")
    fiche = payload.get("fiche")
    comment = payload.get("comment") or ""
    choices = payload.get("choices")
    try:
        return await review_gold.toggle_gold(
            db, body.kind, body.id, run_id=body.run_id,
            fiche=fiche, comment=comment, choices=choices)
    except GoldNotReady as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
