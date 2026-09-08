"""
Gold Dataset — publication carte.

Les bases v1 (`projects`, `poe_ports`, `eez_zones`, `marinas`) ne sont
jamais écrites. Seule `review_gold` porte les overrides (on / off + snapshot).

Projets / marinas : interrupteur. Formalités : Gold = publier la fiche
(snapshot des TD / PoE gardés). Le polygone pré-Gold reste visible ; après
Gold, la carte lit le snapshot au lieu de `poe_ports`.
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone

from app.core.geo import haversine_km, ocean_fallback_coords
from app.services.poe_stable import STABLE_REVIEW_MRGIDS
from app.services.review_choices import (
    GOLD_INCOMPLETE,
    build_gold_snapshot,
    finalize_choices,
    get_choices,
    gold_ready,
    save_choices_doc,
    snapshot_port_docs,
)


class GoldNotReady(ValueError):
    """Gold Formalités cliqué trop tôt — TD / PoE pas encore tranchés."""

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


def eez_is_published(override: dict | None) -> bool:
    """Gold Formalités = override allumé ET snapshot de fiche."""
    return bool(override and override.get("on") and override.get("snapshot"))


def eez_on_map(mid: int, pre: set[int], override: dict | None) -> bool:
    """Polygone visible : publié, ou pré-Gold (sauf hide legacy sans snapshot)."""
    if eez_is_published(override):
        return True
    if mid in pre:
        if (override is not None and override.get("on") is False
                and not override.get("snapshot")):
            return False
        return True
    if override is not None and override.get("on"):
        return True
    return False


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


async def best_productive_stable_zones(db) -> dict[int, dict]:
    """Meilleure fiche productive de chaque polygone des 11 (max ports, puis run récent)."""
    prod = await production_poe_runs(db)
    by_id = {_sid(d.get("_id")): d for d in prod if _sid(d.get("_id"))}
    if not by_id:
        return {}
    try:
        zones = await db.poe_run_zones.find(
            {
                "run_id": {"$in": list(by_id)},
                "mrgid": {"$in": list(STABLE_REVIEW_MRGIDS)},
            },
            {"mrgid": 1, "run_id": 1, "name": 1, "geoname": 1, "sovereign": 1,
             "iso2": 1, "sov_iso2": 1, "pol_type": 1, "poe_count": 1,
             "status": 1, "sources": 1, "sources_official": 1},
        ).to_list(400)
    except Exception:
        return {}
    best: dict[int, dict] = {}
    best_key: dict[int, tuple] = {}
    for z in zones:
        if not eez_extraction_is_productive(z):
            continue
        try:
            mid = int(z.get("mrgid") or 0)
        except (TypeError, ValueError):
            continue
        if not mid:
            continue
        rid = _sid(z.get("run_id"))
        try:
            n = int(z.get("poe_count") or 0)
        except (TypeError, ValueError):
            n = 0
        created = str((by_id.get(rid) or {}).get("created_at") or "")
        key = (n, created)
        if mid not in best or key > best_key[mid]:
            best[mid] = z
            best_key[mid] = key
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
    if kind == "capitainerie":
        return True
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
        if eez_on_map(mid, pre, overrides.get(str(mid))):
            visible.add(mid)
    return visible


async def published_snapshots(db) -> dict[int, dict]:
    overrides = await overrides_map(db, "eez")
    out: dict[int, dict] = {}
    for eid, ov in overrides.items():
        if not eez_is_published(ov):
            continue
        try:
            mid = int(eid)
        except (TypeError, ValueError):
            continue
        snap = ov.get("snapshot")
        if isinstance(snap, dict):
            out[mid] = snap
    return out


async def visible_poe_port_docs(db, mrgid: int | None = None,
                                  country: str | None = None) -> list[dict]:
    """Ports carte Formalités : snapshot Gold s'il est publié, sinon v1."""
    allowed = await visible_eez_mrgids(db)
    snaps = await published_snapshots(db)
    if mrgid is not None:
        try:
            mid = int(mrgid)
        except (TypeError, ValueError):
            return []
        if mid not in allowed:
            return []
        allowed = {mid}
    iso = (country or "").strip().upper()
    q: dict = {}
    if mrgid is not None:
        q["mrgid"] = int(mrgid)
    if iso:
        q["country_iso2"] = iso
    try:
        docs = await db.poe_ports.find(q).to_list(10000)
    except Exception:
        docs = []
    out: list[dict] = []
    for d in docs:
        try:
            mid = int(d.get("mrgid") or 0)
        except (TypeError, ValueError):
            continue
        if mid not in allowed or mid in snaps:
            continue
        out.append(d)
    for mid in allowed:
        snap = snaps.get(mid)
        if not snap:
            continue
        for doc in snapshot_port_docs(mid, snap):
            if iso and str(doc.get("country_iso2") or "").upper() != iso:
                continue
            out.append(doc)
    return out


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
                mid = int(d.get("mrgid") or eid)
            except (TypeError, ValueError):
                continue
            if eez_on_map(mid, pre_eez or set(), overrides.get(str(mid))):
                out.append(d)
            continue
        else:
            pre = False
        if gold_pressed(pre, overrides.get(eid)):
            out.append(d)
    return out


async def toggle_gold(db, kind: str, entity_id: str, *,
                      run_id: str | None = None,
                      snapshot: dict | None = None,
                      fiche: dict | None = None,
                      comment: str = "",
                      choices: dict | None = None) -> dict:
    if kind not in GOLD_KINDS:
        raise ValueError("kind must be project|eez|marina")
    eid = _sid(entity_id)
    if not eid:
        raise ValueError("id required")
    if kind == "eez":
        return await _toggle_eez_gold(
            db, eid, run_id=run_id, fiche=fiche, comment=comment, choices=choices)

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


async def _toggle_eez_gold(db, eid: str, *, run_id: str | None,
                           fiche: dict | None, comment: str,
                           choices: dict | None) -> dict:
    pre = await is_pre_gold_entity(db, "eez", eid, None)
    override = await get_override(db, "eez", eid)
    cid = gold_key("eez", eid)
    if eez_is_published(override):
        payload = {
            "_id": cid, "kind": "eez", "entity_id": eid,
            "on": False, "run_id": run_id, "updated_at": now_iso(),
        }
        if override.get("snapshot"):
            payload["snapshot"] = override["snapshot"]
        await db.review_gold.update_one({"_id": cid}, {"$set": payload}, upsert=True)
        ch = choices if choices is not None else await get_choices(db, "eez", eid)
        return {
            "kind": "eez",
            "id": eid,
            "gold_on": False,
            "pre_gold": pre,
            "choices": ch,
            "gold_ready": gold_ready(fiche, ch) if fiche is not None else True,
            "wrote_projects": False,
            "wrote_poe_ports": False,
            "wrote_marinas": False,
        }

    if fiche is None:
        from app.services.poe_zone_fiche import build_zone_fiche
        try:
            mid = int(eid)
        except (TypeError, ValueError) as e:
            raise ValueError("id required") from e
        fiche = await build_zone_fiche(db, mid, union=True)
    if not fiche:
        raise ValueError("fiche not found")
    ch = choices if choices is not None else await get_choices(db, "eez", eid)
    if not gold_ready(fiche, ch):
        raise GoldNotReady(GOLD_INCOMPLETE)
    ch = finalize_choices(fiche, ch)
    await save_choices_doc(db, "eez", eid, ch)
    snap = build_gold_snapshot(fiche, ch, comment)
    payload = {
        "_id": cid, "kind": "eez", "entity_id": eid,
        "on": True, "run_id": run_id, "updated_at": now_iso(),
        "snapshot": snap,
    }
    await db.review_gold.update_one({"_id": cid}, {"$set": payload}, upsert=True)
    return {
        "kind": "eez",
        "id": eid,
        "gold_on": True,
        "pre_gold": pre,
        "choices": ch,
        "gold_ready": True,
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
