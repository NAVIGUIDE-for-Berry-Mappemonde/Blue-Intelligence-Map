"""Dump mondial des capitaineries OSM (harbour_master) + overlay SHOM CATSCF=6.

Contrat :
  * objet = bureau de capitainerie, pas le plan d'eau, pas la marina
  * identité OSM = osm_id (type/id) ; SHOM orphelin = shom:{fid}
  * pas de rattachement aux marinas
  * pas de purge (upsert)
  * job tuilé Overpass reprenable, puis overlay SHOM
  * téléphone / VHF lus d'abord dans les tags, jamais inventés
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Awaitable, Callable, Iterable
from urllib.parse import quote_plus

import httpx

from app.core.geo import haversine_km
from app.services.marina_build import (
    KEPT_TAGS,
    SHOM_CATSCF_LABELS,
    SHOM_WFS,
    USER_AGENT,
    _merc_to_wgs84,
    overpass_fetch_bbox,
)
from app.services.marina_world import (
    MIN_TILE_DEG,
    OVERPASS_THROTTLE_S,
    OVERPASS_TILE_TIMEOUT_S,
    WORLD_TILES,
    element_latlon,
    element_name,
    merge_website,
    osm_website_from_tags,
    split_bbox,
    tile_key,
)

SCHEMA = "capitainerie_world_v1"
CURSOR_ID = "world_harbour_master"
SHOM_CATSCF = "6"
SHOM_MERGE_KM = 0.25
OSM_SOURCE = "openstreetmap"
SHOM_SOURCE = "shom"
MERGED_SOURCE = "osm+shom"

# Bboxes WGS84 (south, west, north, east) où le WFS SHOM a des SMCFAC.
SHOM_BBOXES: tuple[tuple[float, float, float, float], ...] = (
    (41.0, -6.0, 52.0, 10.0),       # métropole + Corse
    (14.0, -62.0, 18.6, -60.5),     # Antilles
    (-21.6, 55.0, -20.7, 56.1),     # Réunion
    (-13.1, 44.9, -12.5, 45.4),     # Mayotte
    (-23.0, 163.0, -19.5, 168.6),   # Nouvelle-Calédonie
    (-18.2, -152.0, -7.8, -134.0),  # Polynésie
    (46.7, -56.5, 47.2, -56.0),     # Saint-Pierre-et-Miquelon
    (-14.5, -178.3, -13.0, -176.0), # Wallis-et-Futuna
)

PRESERVE_ON_UPDATE = (
    "enriched",
    "enrichment_source",
    "enriched_at",
    "stale",
    "telephone",
    "canal_vhf",
    "shom_id",
    "sources",
    "image",
)

SLIM_PROJECTION = {
    "_id": 1,
    "name": 1,
    "lat": 1,
    "lon": 1,
    "osm_id": 1,
    "shom_id": 1,
    "source": 1,
    "sources": 1,
    "website": 1,
    "website_status": 1,
    "website_source": 1,
    "telephone": 1,
    "canal_vhf": 1,
    "fetched_at": 1,
}

PHONE_TAG_KEYS = (
    "phone", "contact:phone", "telephone", "contact:telephone",
    "contact:mobile", "mobile",
)
VHF_TAG_KEYS = (
    "vhf", "vhf_channel", "channel", "harbour:vhf", "communication:vhf",
    "seamark:communication:channel", "seamark:harbour:vhf", "comcha",
    "shom:comcha",
)
INFO_TAG_KEYS = (
    "description", "seamark:information", "seamark:information:fr",
    "inform", "ninfom", "shom:inform", "shom:ninfom", "note",
)

_VHF_RE = re.compile(
    r"(?:vhf|canal|channel|ch\.?)\s*[:n°#]?\s*(\d{1,2}(?:\s*[/;&]\s*\d{1,2})?)",
    re.I,
)
_PHONE_RE = re.compile(
    r"(?:\+|00)?\d[\d.\s()/]{7,18}\d",
)

FetchTile = Callable[
    [httpx.AsyncClient, tuple[float, float, float, float]],
    Awaitable[list[dict]],
]
FetchShom = Callable[
    [httpx.AsyncClient, tuple[float, float, float, float]],
    Awaitable[list[dict]],
]


def google_maps_url(name: str | None, lat: float, lon: float) -> str:
    if name and str(name).strip():
        q = f"{str(name).strip()} {lat:.5f},{lon:.5f}"
    else:
        q = f"{lat:.5f},{lon:.5f}"
    return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(q)


def is_harbour_master(tags: dict | None) -> bool:
    tags = tags or {}
    if tags.get("office") == "harbour_master":
        return True
    if tags.get("seamark:building:function") == "harbour_master":
        return True
    if tags.get("harbour") == "harbour_master":
        return True
    return False


def harbour_master_bbox_ql(
    south: float, west: float, north: float, east: float,
    timeout: int = OVERPASS_TILE_TIMEOUT_S,
) -> str:
    bbox = f"({south:.4f},{west:.4f},{north:.4f},{east:.4f})"
    return (
        f"[out:json][timeout:{int(timeout)}];\n"
        f"(\n"
        f"  nwr[\"office\"=\"harbour_master\"]{bbox};\n"
        f"  nwr[\"seamark:building:function\"=\"harbour_master\"]{bbox};\n"
        f"  nwr[\"harbour\"=\"harbour_master\"]{bbox};\n"
        f");\n"
        f"out center tags;"
    )


def kept_tags(tags: dict | None) -> dict[str, str]:
    tags = tags or {}
    out: dict[str, str] = {}
    extra = ("office", "harbour", "building")
    for k, v in tags.items():
        if v is None or isinstance(v, (dict, list)):
            continue
        if (
            k in KEPT_TAGS or k in extra or k in PHONE_TAG_KEYS or k in VHF_TAG_KEYS
            or k.startswith("seamark:") or k.startswith("name") or k.startswith("contact:")
            or k.startswith("shom:")
        ):
            out[str(k)] = str(v)[:240]
    return out


def _clean_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text or text.lower() in ("no", "none", "null"):
        return None
    m = _PHONE_RE.search(text)
    if not m:
        digits = re.sub(r"[^\d+]", "", text)
        if len(re.sub(r"\D", "", digits)) < 8:
            return None
        return text[:40]
    return re.sub(r"\s+", " ", m.group(0)).strip()[:40]


def _norm_vhf_part(part: str) -> str | None:
    if not part.isdigit():
        return None
    n = int(part)
    if 1 <= n <= 28:
        return str(n)
    return None


def _clean_vhf(raw: str | None) -> str | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text or text.lower() in ("no", "none", "null"):
        return None
    m = _VHF_RE.search(text)
    candidate = m.group(1) if m else text
    parts = [p.strip() for p in re.split(r"[;/,]", candidate) if p.strip()]
    nums = [n for p in parts if (n := _norm_vhf_part(p))]
    if nums:
        return "/".join(nums)[:20]
    return None


def contact_from_tags(tags: dict | None) -> tuple[str | None, str | None]:
    """Téléphone et canal VHF lus dans les tags OSM/SHOM. Jamais inventés."""
    tags = tags or {}
    phone = None
    for key in PHONE_TAG_KEYS:
        phone = _clean_phone(tags.get(key))
        if phone:
            break
    vhf = None
    for key in VHF_TAG_KEYS:
        vhf = _clean_vhf(tags.get(key))
        if vhf:
            break
    if not phone or not vhf:
        blobs = [str(tags.get(k) or "") for k in INFO_TAG_KEYS]
        blob = " ".join(b for b in blobs if b)
        if blob:
            phone = phone or _clean_phone(blob)
            vhf = vhf or _clean_vhf(blob)
    return phone, vhf


def fill_contact(doc: dict, phone: str | None, vhf: str | None) -> dict:
    """Remplit seulement les champs vides."""
    if phone and not doc.get("telephone"):
        doc["telephone"] = phone
    if vhf and not doc.get("canal_vhf"):
        doc["canal_vhf"] = vhf
    return doc


def capitainerie_from_overpass(elem: dict) -> dict | None:
    typ = elem.get("type")
    eid = elem.get("id")
    if not typ or eid is None:
        return None
    coords = element_latlon(elem)
    if coords is None:
        return None
    lat, lon = coords
    tags = elem.get("tags") or {}
    if not is_harbour_master(tags):
        return None
    kept = kept_tags(tags)
    phone, vhf = contact_from_tags(tags)
    return {
        "osm_id": f"{typ}/{eid}",
        "name": element_name(tags),
        "lat": lat,
        "lon": lon,
        "source": OSM_SOURCE,
        "sources": [OSM_SOURCE],
        "tags": kept,
        "website": osm_website_from_tags(tags),
        "telephone": phone,
        "canal_vhf": vhf,
    }


def is_catscf_harbour_master(catscf: Any) -> bool:
    return str(catscf or "").strip() == SHOM_CATSCF


def shom_feature_id(feat: dict, props: dict, lat: float, lon: float) -> str:
    raw = feat.get("id") or props.get("gml_id") or props.get("id") or props.get("fid")
    if raw not in (None, "", "null"):
        return f"shom:{raw}"
    return f"shom:{lat:.5f}:{lon:.5f}"


def capitainerie_from_shom(feat: dict) -> dict | None:
    geom = feat.get("geometry") or {}
    props = feat.get("properties") or {}
    if not is_catscf_harbour_master(props.get("catscf")):
        return None
    coords = geom.get("coordinates")
    if geom.get("type") == "Point" and coords:
        x, y = coords[:2]
    elif geom.get("type") == "MultiPoint" and coords:
        x, y = coords[0][:2]
    else:
        return None
    try:
        xf, yf = float(x), float(y)
    except (TypeError, ValueError):
        return None
    if abs(xf) > 180 or abs(yf) > 90:
        lat, lon = _merc_to_wgs84(xf, yf)
    else:
        lon, lat = xf, yf
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    cat_label = SHOM_CATSCF_LABELS.get(SHOM_CATSCF, "Capitainerie")
    name = (
        str(props.get("objnam") or "").strip()
        or str(props.get("nobjnm") or "").strip()
        or str(props.get("inform") or "").strip()
        or str(props.get("toponyme") or "").strip()
        or cat_label
    )
    tags = {"shom:catscf": SHOM_CATSCF, "shom:category": cat_label}
    for k, v in props.items():
        if v is None or isinstance(v, (dict, list)):
            continue
        val = str(v).strip()
        if not val or val in ("null", "None"):
            continue
        tags[f"shom:{k}"] = val[:120]
    phone, vhf = contact_from_tags(tags)
    shom_id = shom_feature_id(feat, props, lat, lon)
    return {
        "shom_id": shom_id,
        "osm_id": None,
        "name": name[:120],
        "lat": lat,
        "lon": lon,
        "source": SHOM_SOURCE,
        "sources": [SHOM_SOURCE],
        "tags": tags,
        "website": None,
        "telephone": phone,
        "canal_vhf": vhf,
    }


def nearest_osm(lat: float, lon: float, osm_pts: list[dict], radius_km: float = SHOM_MERGE_KM):
    best = None
    best_d = radius_km
    for doc in osm_pts:
        try:
            d = haversine_km(lat, lon, float(doc["lat"]), float(doc["lon"]))
        except (TypeError, ValueError, KeyError):
            continue
        if d <= best_d:
            best_d = d
            best = doc
    return best


def slim_feature(doc: dict) -> dict:
    lat = float(doc["lat"])
    lon = float(doc["lon"])
    name = doc.get("name") or ""
    website = doc.get("website") or osm_website_from_tags(doc.get("tags") or {})
    sources = doc.get("sources") or ([doc.get("source")] if doc.get("source") else [])
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "id": doc.get("_id"),
            "kind": "capitainerie",
            "name": name,
            "osm_id": doc.get("osm_id"),
            "shom_id": doc.get("shom_id"),
            "source": doc.get("source") or OSM_SOURCE,
            "sources": sources,
            "website": website,
            "telephone": doc.get("telephone"),
            "canal_vhf": doc.get("canal_vhf"),
            "maps_url": google_maps_url(name, lat, lon),
            "fetched_at": doc.get("fetched_at"),
        },
    }


def to_slim_geojson(docs: Iterable[dict]) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            slim_feature(d) for d in docs
            if d.get("lat") is not None and d.get("lon") is not None
        ],
        "attribution": (
            "© OpenStreetMap contributors (ODbL) · SHOM INFORMATIONS_PORTUAIRES "
            "(Licence Ouverte Etalab)"
        ),
    }


def _merge_sources(*groups: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    for group in groups:
        for src in group or []:
            if src and src not in out and src != MERGED_SOURCE:
                out.append(src)
    return out


def _source_label(sources: list[str]) -> str:
    if OSM_SOURCE in sources and SHOM_SOURCE in sources:
        return MERGED_SOURCE
    if SHOM_SOURCE in sources and OSM_SOURCE not in sources:
        return SHOM_SOURCE
    return OSM_SOURCE


async def upsert_osm(coll, cand: dict, now_iso: str) -> str:
    osm_id = cand["osm_id"]
    existing = await coll.find_one({"osm_id": osm_id})
    if existing is None:
        existing = await coll.find_one({"_id": osm_id})
    website, status, wsrc = merge_website(existing, cand.get("website"))
    sources = _merge_sources(
        (existing or {}).get("sources"),
        cand.get("sources"),
        [OSM_SOURCE],
    )
    patch: dict[str, Any] = {
        "name": cand.get("name") or "",
        "lat": cand["lat"],
        "lon": cand["lon"],
        "source": _source_label(sources),
        "sources": sources,
        "osm_id": osm_id,
        "tags": cand.get("tags") or {},
        "website": website,
        "website_status": status,
        "website_source": wsrc,
        "fetched_at": now_iso,
        "schema": SCHEMA,
    }
    if existing:
        for field in PRESERVE_ON_UPDATE:
            if existing.get(field) not in (None, "", [], {}):
                patch[field] = existing[field]
        fill_contact(patch, cand.get("telephone"), cand.get("canal_vhf"))
        await coll.update_one({"_id": existing["_id"]}, {"$set": patch})
        return "updated"
    patch["_id"] = osm_id
    patch["enriched"] = False
    patch["stale"] = False
    fill_contact(patch, cand.get("telephone"), cand.get("canal_vhf"))
    await coll.insert_one(patch)
    return "inserted"


async def upsert_shom(coll, cand: dict, now_iso: str, osm_pts: list[dict]) -> str:
    """Fusionne sur un OSM à ≤ 250 m, sinon insère un point SHOM orphelin."""
    hit = nearest_osm(cand["lat"], cand["lon"], osm_pts)
    if hit:
        sources = _merge_sources(hit.get("sources"), [OSM_SOURCE, SHOM_SOURCE])
        tags = dict(hit.get("tags") or {})
        tags.update(cand.get("tags") or {})
        patch: dict[str, Any] = {
            "shom_id": cand["shom_id"],
            "source": MERGED_SOURCE,
            "sources": sources,
            "tags": tags,
            "fetched_at": now_iso,
            "schema": SCHEMA,
        }
        if cand.get("name") and not (hit.get("name") or "").strip():
            patch["name"] = cand["name"]
        fill_contact(patch, cand.get("telephone"), cand.get("canal_vhf"))
        if not hit.get("telephone") and cand.get("telephone"):
            patch["telephone"] = cand["telephone"]
        if not hit.get("canal_vhf") and cand.get("canal_vhf"):
            patch["canal_vhf"] = cand["canal_vhf"]
        await coll.update_one({"_id": hit["_id"]}, {"$set": patch})
        hit.update(patch)
        return "merged"
    shom_id = cand["shom_id"]
    existing = await coll.find_one({"_id": shom_id}) or await coll.find_one({"shom_id": shom_id})
    patch = {
        "name": cand.get("name") or "",
        "lat": cand["lat"],
        "lon": cand["lon"],
        "source": SHOM_SOURCE,
        "sources": [SHOM_SOURCE],
        "shom_id": shom_id,
        "osm_id": None,
        "tags": cand.get("tags") or {},
        "website": None,
        "fetched_at": now_iso,
        "schema": SCHEMA,
    }
    if existing:
        for field in PRESERVE_ON_UPDATE:
            if existing.get(field) not in (None, "", [], {}):
                patch[field] = existing[field]
        fill_contact(patch, cand.get("telephone"), cand.get("canal_vhf"))
        await coll.update_one({"_id": existing["_id"]}, {"$set": patch})
        return "updated"
    patch["_id"] = shom_id
    patch["enriched"] = False
    patch["stale"] = False
    fill_contact(patch, cand.get("telephone"), cand.get("canal_vhf"))
    await coll.insert_one(patch)
    return "inserted"


async def load_done_tiles(cursor_coll) -> list[str]:
    doc = await cursor_coll.find_one({"_id": CURSOR_ID}) or {}
    return list(doc.get("done_tiles") or [])


async def mark_tile_done(cursor_coll, key: str, now_iso: str) -> None:
    done = await load_done_tiles(cursor_coll)
    if key not in done:
        done.append(key)
    payload = {"_id": CURSOR_ID, "done_tiles": done, "updated_at": now_iso, "schema": SCHEMA}
    existing = await cursor_coll.find_one({"_id": CURSOR_ID})
    if existing:
        await cursor_coll.replace_one({"_id": CURSOR_ID}, payload)
    else:
        await cursor_coll.insert_one(payload)


async def reset_cursor(cursor_coll) -> None:
    existing = await cursor_coll.find_one({"_id": CURSOR_ID})
    if existing:
        await cursor_coll.replace_one(
            {"_id": CURSOR_ID},
            {"_id": CURSOR_ID, "done_tiles": [], "updated_at": None, "schema": SCHEMA},
        )


async def ensure_indexes(coll) -> None:
    try:
        await coll.create_index("osm_id", unique=True, sparse=True)
        await coll.create_index("shom_id", unique=True, sparse=True)
        await coll.create_index("name")
        await coll.create_index("source")
    except Exception:
        pass


def _throttle_s(explicit: float | None) -> float:
    if explicit is not None:
        return float(explicit)
    try:
        from app.core.run_rules import get_rule
        return float(get_rule("marinas.overpass_throttle_s", OVERPASS_THROTTLE_S))
    except Exception:
        return OVERPASS_THROTTLE_S


async def fetch_tile_harbour_masters(
    client: httpx.AsyncClient,
    tile: tuple[float, float, float, float],
    *,
    logger=None,
    timeout: int = OVERPASS_TILE_TIMEOUT_S,
    min_span: float = MIN_TILE_DEG,
) -> list[dict]:
    south, west, north, east = tile
    body = harbour_master_bbox_ql(south, west, north, east, timeout=timeout)
    try:
        return await overpass_fetch_bbox(
            south, west, north, east, client, logger=logger, body=body,
        )
    except Exception as exc:
        span = max(north - south, east - west)
        if span > min_span:
            if logger:
                logger(f"Tuile trop lourde {tile} ({type(exc).__name__}) — split")
            out: list[dict] = []
            for sub in split_bbox(south, west, north, east):
                await asyncio.sleep(1.2)
                out.extend(await fetch_tile_harbour_masters(
                    client, sub, logger=logger, timeout=timeout, min_span=min_span,
                ))
            return out
        raise


async def shom_fetch_catscf6(
    client: httpx.AsyncClient,
    bbox: tuple[float, float, float, float],
    logger=None,
) -> list[dict]:
    """WFS SHOM smcfac_point filtré CATSCF=6. CQL d'abord, sinon filtre local."""
    s, w, n, e = bbox
    bbox_str = f"{w:.6f},{s:.6f},{e:.6f},{n:.6f},EPSG:4326"
    typename = "INFORMATIONS_PORTUAIRES_BDD_WFS:smcfac_point"
    out: list[dict] = []
    start = 0
    page = 1000
    used_cql = True
    while True:
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typenames": typename,
            "bbox": bbox_str,
            "outputFormat": "application/json",
            "count": str(page),
            "startIndex": str(start),
        }
        if used_cql:
            params["CQL_FILTER"] = "catscf='6'"
        try:
            r = await client.get(
                SHOM_WFS,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=60,
            )
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            if logger:
                logger(f"SHOM {bbox_str}: {type(exc).__name__}: {str(exc)[:80]}")
            break
        ct = (r.headers.get("content-type") or "").lower()
        if r.status_code != 200 or "json" not in ct:
            if used_cql:
                used_cql = False
                start = 0
                if logger:
                    logger(f"SHOM CQL refusé ({r.status_code}) — repli filtre local")
                continue
            if logger:
                logger(f"SHOM {typename}: HTTP {r.status_code}")
            break
        fc = r.json()
        feats = fc.get("features") or []
        for feat in feats:
            cand = capitainerie_from_shom(feat)
            if cand:
                out.append(cand)
        if len(feats) < page:
            break
        start += page
        if start > 20000:
            break
    if logger:
        logger(f"SHOM CATSCF=6 {bbox_str}: {len(out)} capitaineries")
    return out


async def _all_docs(coll) -> list[dict]:
    fake = getattr(coll, "docs", None)
    if isinstance(fake, list):
        return list(fake)
    cur = coll.find({})
    if hasattr(cur, "to_list"):
        return await cur.to_list(50000)
    return [doc async for doc in cur]


async def overlay_shom(
    coll,
    *,
    client: httpx.AsyncClient,
    logger=None,
    fetch_shom: FetchShom | None = None,
    bboxes: tuple[tuple[float, float, float, float], ...] | None = None,
) -> dict:
    osm_pts = [
        d for d in await _all_docs(coll)
        if d.get("osm_id") and d.get("lat") is not None
    ]
    inserted = merged = updated = fetched = 0
    seen: set[str] = set()
    for bbox in (bboxes or SHOM_BBOXES):
        try:
            if fetch_shom:
                cands = await fetch_shom(client, bbox)
            else:
                cands = await shom_fetch_catscf6(client, bbox, logger=logger)
        except Exception as exc:
            if logger:
                logger(f"SHOM overlay {bbox}: {type(exc).__name__}: {str(exc)[:80]}")
            continue
        fetched += len(cands)
        for cand in cands:
            sid = cand.get("shom_id")
            if sid in seen:
                continue
            seen.add(sid)
            result = await upsert_shom(coll, cand, time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
            ), osm_pts)
            if result == "inserted":
                inserted += 1
            elif result == "merged":
                merged += 1
            else:
                updated += 1
    return {
        "fetched": fetched,
        "inserted": inserted,
        "merged": merged,
        "updated": updated,
        "unique": len(seen),
    }


async def build_world_capitaineries(
    *,
    coll,
    cursor_coll,
    state,
    resume: bool = True,
    tiles: tuple[tuple[float, float, float, float], ...] | None = None,
    client: httpx.AsyncClient | None = None,
    throttle_s: float | None = None,
    fetch_tile: FetchTile | None = None,
    fetch_shom: FetchShom | None = None,
    shom_bboxes: tuple[tuple[float, float, float, float], ...] | None = None,
    skip_shom: bool = False,
) -> dict:
    """Dump OSM harbour_master (tuiles) puis overlay SHOM CATSCF=6."""
    state.running = True
    state.started_at = time.time()
    state.finished_at = None
    state.error = None
    state.logs = []
    state.summary = None
    state.cancel = False

    grid = tiles or WORLD_TILES
    pause = _throttle_s(throttle_s)
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    try:
        await ensure_indexes(coll)
        if not resume:
            await reset_cursor(cursor_coll)
            state.log("Reprise désactivée — curseur tuiles remis à zéro (pas de purge)")

        done = set(await load_done_tiles(cursor_coll)) if resume else set()
        state.total = len(grid) + (0 if skip_shom else 1)
        state.progress = 0
        state.log(
            f"Dump mondial harbour_master : {len(grid)} tuiles, "
            f"{len(done)} déjà faites, throttle={pause:.1f}s"
        )

        inserted = updated = fetched_raw = errors = skipped = 0
        named = unnamed = with_phone = with_vhf = 0
        own_client = client is None
        http = client or httpx.AsyncClient(headers={"User-Agent": USER_AGENT})
        try:
            for tile in grid:
                if state.cancel:
                    state.log("Stop demandé — dump OSM interrompu")
                    break
                key = tile_key(tile)
                if key in done:
                    skipped += 1
                    state.progress += 1
                    state.log(f"Tuile {key} déjà faite — skip")
                    continue
                try:
                    if fetch_tile:
                        elements = await fetch_tile(http, tile)
                    else:
                        elements = await fetch_tile_harbour_masters(http, tile, logger=state.log)
                except Exception as exc:
                    errors += 1
                    state.log(f"Tuile {key} : {type(exc).__name__}: {str(exc)[:80]}")
                    state.progress += 1
                    await asyncio.sleep(pause)
                    continue

                fetched_raw += len(elements)
                tile_ins = tile_upd = 0
                for elem in elements:
                    cand = capitainerie_from_overpass(elem)
                    if not cand:
                        continue
                    result = await upsert_osm(coll, cand, now_iso)
                    if result == "inserted":
                        inserted += 1
                        tile_ins += 1
                    else:
                        updated += 1
                        tile_upd += 1
                    if cand["name"]:
                        named += 1
                    else:
                        unnamed += 1
                    if cand.get("telephone"):
                        with_phone += 1
                    if cand.get("canal_vhf"):
                        with_vhf += 1

                await mark_tile_done(cursor_coll, key, now_iso)
                state.progress += 1
                state.log(
                    f"Tuile {key} : {len(elements)} brut → +{tile_ins} / ~{tile_upd}"
                )
                await asyncio.sleep(pause)

            shom_summary = {
                "fetched": 0, "inserted": 0, "merged": 0, "updated": 0, "unique": 0,
            }
            if not skip_shom and not state.cancel:
                state.log("Overlay SHOM CATSCF=6 (capitainerie)")
                shom_summary = await overlay_shom(
                    coll, client=http, logger=state.log,
                    fetch_shom=fetch_shom, bboxes=shom_bboxes,
                )
                state.progress += 1
                state.log(
                    f"SHOM : {shom_summary['unique']} uniques, "
                    f"+{shom_summary['inserted']} / fusion {shom_summary['merged']}"
                )
        finally:
            if own_client:
                await http.aclose()

        summary = {
            "schema": SCHEMA,
            "tiles_total": len(grid),
            "tiles_skipped": skipped,
            "tiles_errors": errors,
            "fetched_raw": fetched_raw,
            "inserted": inserted,
            "updated": updated,
            "named": named,
            "unnamed": unnamed,
            "with_phone_tag": with_phone,
            "with_vhf_tag": with_vhf,
            "shom": shom_summary,
            "resume": resume,
        }
        state.summary = summary
        state.log(f"Dump capitaineries terminé: {json.dumps(summary)}")
        return summary
    except Exception as exc:
        state.error = f"{type(exc).__name__}: {exc}"
        state.log(f"FATAL: {state.error}")
        raise
    finally:
        state.finished_at = time.time()
        state.running = False
