"""
Gold Dataset — interrupteur de publication carte.

Les bases v1 (`projects`, `poe_ports`, `eez_zones`, `marinas`) ne sont
jamais écrites. Seule `review_gold` porte les overrides (on / off).

Règle de visibilité carte :
    sur_la_carte = override.on  si un override existe
                 = pré-Gold     sinon
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from app.core.dedup import normalize_name
from app.core.geo import haversine_km, ocean_fallback_coords

GOLD_KINDS = ("project", "eez", "marina")
FALLBACK_SOURCES = frozenset({
    "ocean-region-fallback", "ocean_fallback", "ocean-fallback",
    "fallback", "ocean_region_fallback",
})
OSM_SOURCES = frozenset({"openstreetmap", "osm"})
JACCARD_MIN = 0.7
FALLBACK_KM = 50.0
_TEST_LABEL = re.compile(
    r"^(canary|smoke|seed-enrich|test|debug)(?:[-_].*)?$",
    re.I,
)

_eez_pre_gold_cache: tuple[float, frozenset[int]] | None = None
_EEZ_CACHE_TTL_S = 60.0


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
    label = str(doc.get("label") or "").strip()
    return bool(label and _TEST_LABEL.match(label))


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


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _norm_url(url: str) -> str:
    return (url or "").strip().split("#", 1)[0].rstrip("/").lower()


def _td_url(zone: dict | None) -> str:
    if not zone:
        return ""
    for raw in zone.get("sources") or []:
        if isinstance(raw, dict):
            url = raw.get("url") or ""
        else:
            url = str(raw or "")
        cleaned = _norm_url(url)
        if cleaned.startswith("http"):
            return cleaned
    return ""


def _port_names(ports: list[dict]) -> set[str]:
    names: set[str] = set()
    for p in ports or []:
        key = normalize_name(p.get("name") or "")
        if key:
            names.add(key)
    return names


def reset_eez_pre_gold_cache() -> None:
    global _eez_pre_gold_cache
    _eez_pre_gold_cache = None


async def production_poe_runs(db) -> list[dict]:
    try:
        docs = await db.poe_runs.find({}).to_list(200)
    except Exception:
        return []
    return [d for d in docs if not is_test_run(d)]


async def pre_gold_eez_mrgids(db) -> set[int]:
    """mrgid stables : v1 + runs prod, Jaccard ports ≥ 0.7 ou même URL TD."""
    global _eez_pre_gold_cache
    now = time.time()
    if _eez_pre_gold_cache and now - _eez_pre_gold_cache[0] < _EEZ_CACHE_TTL_S:
        return set(_eez_pre_gold_cache[1])

    origins: list[dict[int, tuple[set[str], str]]] = []

    v1_ports: dict[int, list[dict]] = {}
    try:
        for p in await db.poe_ports.find({}, {"name": 1, "mrgid": 1}).to_list(20000):
            try:
                mid = int(p.get("mrgid") or 0)
            except (TypeError, ValueError):
                continue
            if mid:
                v1_ports.setdefault(mid, []).append(p)
    except Exception:
        v1_ports = {}
    v1_td: dict[int, str] = {}
    try:
        for z in await db.eez_zones.find({}, {"mrgid": 1, "sources": 1}).to_list(500):
            try:
                mid = int(z.get("mrgid") or 0)
            except (TypeError, ValueError):
                continue
            if mid:
                v1_td[mid] = _td_url(z)
    except Exception:
        v1_td = {}
    if v1_ports or v1_td:
        mrgids = set(v1_ports) | set(v1_td)
        origins.append({
            mid: (_port_names(v1_ports.get(mid) or []), v1_td.get(mid) or "")
            for mid in mrgids
        })

    for run in await production_poe_runs(db):
        rid = _sid(run.get("_id"))
        if not rid:
            continue
        by_ports: dict[int, list[dict]] = {}
        try:
            for p in await db.poe_run_ports.find(
                {"run_id": rid}, {"name": 1, "mrgid": 1},
            ).to_list(20000):
                try:
                    mid = int(p.get("mrgid") or 0)
                except (TypeError, ValueError):
                    continue
                if mid:
                    by_ports.setdefault(mid, []).append(p)
        except Exception:
            by_ports = {}
        by_td: dict[int, str] = {}
        try:
            for z in await db.poe_run_zones.find(
                {"run_id": rid}, {"mrgid": 1, "sources": 1},
            ).to_list(500):
                try:
                    mid = int(z.get("mrgid") or 0)
                except (TypeError, ValueError):
                    continue
                if mid:
                    by_td[mid] = _td_url(z)
        except Exception:
            by_td = {}
        mrgids = set(by_ports) | set(by_td)
        if not mrgids:
            continue
        origins.append({
            mid: (_port_names(by_ports.get(mid) or []), by_td.get(mid) or "")
            for mid in mrgids
        })

    hits: set[int] = set()
    all_ids: set[int] = set()
    for origin in origins:
        all_ids |= set(origin)
    for mid in all_ids:
        sigs = [origin[mid] for origin in origins if mid in origin]
        if len(sigs) < 2:
            continue
        ok = False
        for i in range(len(sigs)):
            for j in range(i + 1, len(sigs)):
                names_a, url_a = sigs[i]
                names_b, url_b = sigs[j]
                if url_a and url_b and url_a == url_b:
                    ok = True
                    break
                if _jaccard(names_a, names_b) >= JACCARD_MIN:
                    ok = True
                    break
            if ok:
                break
        if ok:
            hits.add(mid)

    _eez_pre_gold_cache = (now, frozenset(hits))
    return hits


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
