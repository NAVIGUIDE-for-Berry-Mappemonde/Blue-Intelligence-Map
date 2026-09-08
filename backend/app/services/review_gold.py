"""
Gold Dataset — interrupteur de publication carte.

Les bases v1 (`projects`, `poe_ports`, `eez_zones`, `marinas`) ne sont
jamais écrites. Seule `review_gold` porte les overrides (on / off).

Règle de visibilité carte :
    sur_la_carte = override.on  si un override existe
                 = pré-Gold     sinon
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone

from app.core.geo import haversine_km, ocean_fallback_coords
from app.services.poe_stable import STABLE_REVIEW_MRGIDS

GOLD_KINDS = ("project", "eez", "marina")
FALLBACK_SOURCES = frozenset({
    "ocean-region-fallback", "ocean_fallback", "ocean-fallback",
    "fallback", "ocean_region_fallback",
})
OSM_SOURCES = frozenset({"openstreetmap", "osm"})
FALLBACK_KM = 50.0
_TEST_LABEL = re.compile(
    r"^(canary|smoke|seed-enrich|test|debug)(?:[-_].*)?$",
    re.I,
)

_eez_pre_gold_cache: tuple[float, frozenset[int]] | None = None
_EEZ_CACHE_TTL_S = 300.0
_eez_locks: dict[int, asyncio.Lock] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sid(value) -> str:
    return "" if value is None else str(value)


def gold_key(kind: str, entity_id: str) -> str:
    return f"{kind}:{_sid(entity_id)}"


def is_test_run(doc: dict | None) -> bool:
    """Canaris, smokes, seed-enrich — pas les runs mondiaux de prod."""
    if not doc:
        return False
    if str(doc.get("purpose") or "").strip().lower() == "test":
        return True
    for raw in (doc.get("label"), doc.get("_id")):
        text = str(raw or "").strip()
        if text and _TEST_LABEL.match(text):
            return True
    return False


def is_pre_gold_project(doc: dict | None) -> bool:
    """Ni snap_to_ocean, ni point océan hashé (`ocean_fallback_coords`)."""
    if not doc:
        return False
    if doc.get("snapped") or doc.get("snapped_coastal"):
        return False
    geo = str(doc.get("geo_source") or "").strip().lower()
    if geo in FALLBACK_SOURCES:
        return False
    title = str(doc.get("title") or "")
    try:
        lat = float(doc["lat"])
        lon = float(doc["lon"])
    except (KeyError, TypeError, ValueError):
        return True
    if not title:
        return True
    flat, flon = ocean_fallback_coords(title)
    try:
        if haversine_km(lat, lon, flat, flon) < FALLBACK_KM:
            return False
    except Exception:
        return True
    return True


def is_pre_gold_marina(doc: dict | None) -> bool:
    """Pour l'instant : le stock OSM (28k+)."""
    if not doc:
        return False
    src = str(doc.get("source") or "").strip().lower()
    return src in OSM_SOURCES


def gold_pressed(is_pre_gold: bool, override: dict | None) -> bool:
    if override is not None and "on" in override:
        return bool(override["on"])
    return bool(is_pre_gold)


def reset_eez_pre_gold_cache() -> None:
    global _eez_pre_gold_cache
    _eez_pre_gold_cache = None


async def production_poe_runs(db) -> list[dict]:
    try:
        docs = await db.poe_runs.find({}).to_list(200)
    except Exception:
        return []
    return [d for d in docs if not is_test_run(d)]


def _eez_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _eez_locks.get(id(loop))
    if lock is None:
        lock = asyncio.Lock()
        _eez_locks[id(loop)] = lock
    return lock


def _mrgid_set(docs: list[dict]) -> set[int]:
    out: set[int] = set()
    for d in docs or []:
        try:
            mid = int(d.get("mrgid") or 0)
        except (TypeError, ValueError):
            continue
        if mid:
            out.add(mid)
    return out


def eez_extraction_is_productive(doc: dict | None) -> bool:
    """Au moins un port et une source officielle — v1 seul ne suffit pas."""
    if not doc:
        return False
    try:
        n = int(doc.get("poe_count") or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return False
    if doc.get("sources_official"):
        return True
    for src in doc.get("sources") or []:
        if not isinstance(src, dict):
            continue
        if src.get("official"):
            return True
        if str(src.get("kind") or "").strip().lower() == "official":
            return True
    return False


async def pre_gold_eez_mrgids(db) -> set[int]:
    """mrgid extraits de façon productive sur un run Formalités de prod.

    Productif = poe_count > 0 et au moins une source officielle.
    La v1 et les canaris / smokes ne comptent pas : une ZEE seulement
    présente sur la carte publiée (ex. Mayotte sans run) n'est pas pré-Gold.
    Lecture des fiches zone seulement — pas le scan des ports.
    """
    global _eez_pre_gold_cache
    now = time.time()
    if _eez_pre_gold_cache and now - _eez_pre_gold_cache[0] < _EEZ_CACHE_TTL_S:
        return set(_eez_pre_gold_cache[1])

    async with _eez_lock():
        now = time.time()
        if _eez_pre_gold_cache and now - _eez_pre_gold_cache[0] < _EEZ_CACHE_TTL_S:
            return set(_eez_pre_gold_cache[1])

        hits: set[int] = set()
        prod_runs = await production_poe_runs(db)
        rids = [_sid(r.get("_id")) for r in prod_runs if _sid(r.get("_id"))]
        if rids:
            try:
                zones = await db.poe_run_zones.find(
                    {"run_id": {"$in": rids}},
                    {"mrgid": 1, "run_id": 1, "poe_count": 1,
                     "sources": 1, "sources_official": 1},
                ).to_list(8000)
            except Exception:
                zones = []
            for z in zones:
                if eez_extraction_is_productive(z):
                    hits |= _mrgid_set([z])

        _eez_pre_gold_cache = (time.time(), frozenset(hits))
        return hits


async def recommended_eez_run_id(db) -> str | None:
    """Run prod qui couvre le plus des 11 de façon productive, puis le plus récent.

    Un rerun France (1 zone) ne doit pas masquer le run des 11 (FR+NZ+EG…).
    """
    prod = await production_poe_runs(db)
    by_id = {_sid(d.get("_id")): d for d in prod if _sid(d.get("_id"))}
    if not by_id:
        return None
    try:
        zones = await db.poe_run_zones.find(
            {
                "run_id": {"$in": list(by_id)},
                "mrgid": {"$in": list(STABLE_REVIEW_MRGIDS)},
            },
            {"mrgid": 1, "run_id": 1, "poe_count": 1,
             "sources": 1, "sources_official": 1},
        ).to_list(400)
    except Exception:
        return None
    scores: dict[str, int] = {}
    for z in zones:
        if not eez_extraction_is_productive(z):
            continue
        rid = _sid(z.get("run_id"))
        if rid in by_id:
            scores[rid] = scores.get(rid, 0) + 1
    best: str | None = None
    best_score = 0
    best_at = ""
    for rid, n in scores.items():
        created = str((by_id.get(rid) or {}).get("created_at") or "")
        if best is None or n > best_score or (n == best_score and created > best_at):
            best = rid
            best_score = n
            best_at = created
    return best


async def overrides_map(db, kind: str) -> dict[str, dict]:
    try:
        docs = await db.review_gold.find({"kind": kind}).to_list(50000)
    except Exception:
        return {}
    return {_sid(d.get("entity_id")): d for d in docs}


async def get_override(db, kind: str, entity_id: str) -> dict | None:
    try:
        return await db.review_gold.find_one({"_id": gold_key(kind, entity_id)})
    except Exception:
        return None


async def is_pre_gold_entity(db, kind: str, entity_id: str, doc: dict | None = None) -> bool:
    if kind == "project":
        return is_pre_gold_project(doc)
    if kind == "marina":
        return is_pre_gold_marina(doc)
    if kind == "eez":
        try:
            mid = int(entity_id)
        except (TypeError, ValueError):
            return False
        return mid in await pre_gold_eez_mrgids(db)
    return False


async def visible_eez_mrgids(db) -> set[int]:
    pre = await pre_gold_eez_mrgids(db)
    overrides = await overrides_map(db, "eez")
    visible: set[int] = set()
    candidates = set(pre)
    for eid, ov in overrides.items():
        try:
            candidates.add(int(eid))
        except (TypeError, ValueError):
            continue
    for mid in candidates:
        pressed = gold_pressed(mid in pre, overrides.get(str(mid)))
        if pressed:
            visible.add(mid)
    return visible


async def filter_visible(db, kind: str, docs: list[dict], id_fn) -> list[dict]:
    overrides = await overrides_map(db, kind)
    pre_eez = await pre_gold_eez_mrgids(db) if kind == "eez" else None
    out: list[dict] = []
    for d in docs:
        eid = _sid(id_fn(d))
        if not eid:
            continue
        if kind == "project":
            pre = is_pre_gold_project(d)
        elif kind == "marina":
            pre = is_pre_gold_marina(d)
        elif kind == "eez":
            try:
                pre = int(d.get("mrgid") or eid) in (pre_eez or set())
            except (TypeError, ValueError):
                pre = False
        else:
            pre = False
        if gold_pressed(pre, overrides.get(eid)):
            out.append(d)
    return out


async def toggle_gold(db, kind: str, entity_id: str, *,
                      run_id: str | None = None,
                      snapshot: dict | None = None) -> dict:
    if kind not in GOLD_KINDS:
        raise ValueError("kind must be project|eez|marina")
    eid = _sid(entity_id)
    if not eid:
        raise ValueError("id required")
    pre = await is_pre_gold_entity(db, kind, eid, None)
    if kind == "project" or kind == "marina":
        # Re-évaluer avec le doc v1 si possible (pré-Gold dépend du contenu).
        if kind == "project":
            doc = await db.projects.find_one({"_id": eid})
            if not doc:
                doc = await db.projects.find_one({"url": eid})
            pre = is_pre_gold_project(doc)
        else:
            doc = await db.marinas.find_one({"_id": eid})
            pre = is_pre_gold_marina(doc)
    override = await get_override(db, kind, eid)
    currently_on = gold_pressed(pre, override)
    cid = gold_key(kind, eid)
    if currently_on:
        if pre:
            await db.review_gold.update_one(
                {"_id": cid},
                {"$set": {
                    "_id": cid, "kind": kind, "entity_id": eid,
                    "on": False, "run_id": run_id, "updated_at": now_iso(),
                }},
                upsert=True,
            )
        else:
            await db.review_gold.delete_one({"_id": cid})
        pressed = False
    else:
        if pre:
            await db.review_gold.delete_one({"_id": cid})
        else:
            payload = {
                "_id": cid, "kind": kind, "entity_id": eid,
                "on": True, "run_id": run_id, "updated_at": now_iso(),
            }
            if snapshot:
                payload["snapshot"] = snapshot
            await db.review_gold.update_one({"_id": cid}, {"$set": payload}, upsert=True)
        pressed = True
    return {
        "kind": kind,
        "id": eid,
        "gold_on": pressed,
        "pre_gold": pre,
        "wrote_projects": False,
        "wrote_poe_ports": False,
        "wrote_marinas": False,
    }


async def ensure_gold_indexes(db) -> None:
    try:
        await db.review_gold.create_index("kind")
        await db.review_gold.create_index("entity_id")
    except Exception:
        pass
