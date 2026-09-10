"""
Dump mondial des marinas OSM (leisure=marina).

Palier 1 — contrat :
  * identité = osm_id (type/id), pas nom@geohash
  * pas de corridor Berry-Mappemonde, pas de priorité d'escale
  * pas de purge (upsert, les fiches existantes / enrichies restent)
  * job tuilé et reprenable
  * site OSM recopié tel quel (website_status=unchecked) — vérif = palier 2
  * maps_url calculé, jamais stocké comme vérité Google
  * pas de mélange avec les PoE / graines Formalités
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Awaitable, Callable, Iterable
from urllib.parse import quote_plus

import httpx

from app.services.marina_build import (
    KEPT_TAGS,
    USER_AGENT,
    overpass_fetch_bbox,
)
from app.services.osm_seeds import MIN_TILE_DEG, WORLD_TILES

SCHEMA = "marina_world_v1"
CURSOR_ID = "world_leisure_marina"
OVERPASS_THROTTLE_S = 3.0
OVERPASS_TILE_TIMEOUT_S = 180
# Tuiles monde ~30×90° : Overpass public lâche ou ne rend jamais.
# On découpe avant l'appel dès que le plus grand côté dépasse ça.
SPLIT_BEFORE_DEG = 40.0
UPSERT_HEARTBEAT = 250

# Statuts que le palier 2 posera ; le dump ne les écrase pas.
LOCKED_WEBSITE_STATUSES = frozenset({"osm_ok", "tinyfish_ok"})

PRESERVE_ON_UPDATE = (
    "enriched",
    "enrichment_source",
    "enriched_at",
    "stale",
    "canal_vhf",
    "places_visiteurs",
    "tirant_eau_max_metres",
    "score_protection_meteo",
    "services_disponibles",
    "telephone_capitainerie",
    "resume_avis",
    "image",
    "priority",
    "nearest_waypoint",
    "dedup_key",
    "maps_place_url",
    "maps_place_status",
    "maps_place_source",
    "maps_place_checked_at",
)

SLIM_PROJECTION = {
    "_id": 1,
    "name": 1,
    "lat": 1,
    "lon": 1,
    "osm_id": 1,
    "source": 1,
    "website": 1,
    "website_status": 1,
    "website_source": 1,
    "image": 1,
    "fetched_at": 1,
    "tags": 1,
    "maps_place_url": 1,
    "maps_place_status": 1,
}

FetchTile = Callable[
    [httpx.AsyncClient, tuple[float, float, float, float]],
    Awaitable[list[dict]],
]


def tile_key(tile: tuple[float, float, float, float]) -> str:
    south, west, north, east = tile
    return f"{south:.4f},{west:.4f},{north:.4f},{east:.4f}"


def tile_span_deg(tile: tuple[float, float, float, float]) -> float:
    south, west, north, east = tile
    return max(north - south, east - west)


def should_split_before_overpass(
    tile: tuple[float, float, float, float],
    *,
    min_span: float = MIN_TILE_DEG,
    max_span: float = SPLIT_BEFORE_DEG,
) -> bool:
    span = tile_span_deg(tile)
    return span > max_span and span > min_span


def split_bbox(
    south: float, west: float, north: float, east: float,
) -> list[tuple[float, float, float, float]]:
    mid_lat = (south + north) / 2.0
    mid_lon = (west + east) / 2.0
    return [
        (south, west, mid_lat, mid_lon),
        (south, mid_lon, mid_lat, east),
        (mid_lat, west, north, mid_lon),
        (mid_lat, mid_lon, north, east),
    ]


def leisure_marina_bbox_ql(
    south: float, west: float, north: float, east: float,
    timeout: int = OVERPASS_TILE_TIMEOUT_S,
) -> str:
    """Uniquement leisure=marina — pas harbour=yes / seamark commercial."""
    return (
        f"[out:json][timeout:{int(timeout)}];\n"
        f"(\n"
        f"  nwr[\"leisure\"=\"marina\"]({south:.4f},{west:.4f},{north:.4f},{east:.4f});\n"
        f");\n"
        f"out center tags;"
    )


def google_maps_url(name: str | None, lat: float, lon: float) -> str:
    """Lien de recherche Maps déterministe — pas une fiche Places."""
    if name and str(name).strip():
        q = f"{str(name).strip()} {lat:.5f},{lon:.5f}"
    else:
        q = f"{lat:.5f},{lon:.5f}"
    return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(q)


def osm_website_from_tags(tags: dict | None) -> str | None:
    tags = tags or {}
    for key in ("website", "contact:website", "url"):
        raw = str(tags.get(key) or "").strip()
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw[:500]
    return None


def element_name(tags: dict | None) -> str:
    """Nom OSM réel, ou vide — on n'invente pas « Marina @ lat,lon »."""
    tags = tags or {}
    for key in ("name", "name:fr", "name:en", "official_name", "alt_name"):
        val = str(tags.get(key) or "").strip()
        if val:
            return val[:120]
    return ""


def element_latlon(elem: dict) -> tuple[float, float] | None:
    if elem.get("type") == "node":
        lat, lon = elem.get("lat"), elem.get("lon")
    else:
        center = elem.get("center") or {}
        lat, lon = center.get("lat"), center.get("lon")
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
        return None
    if lat_f == 0.0 and lon_f == 0.0:
        return None
    return lat_f, lon_f


def kept_tags(tags: dict | None) -> dict[str, str]:
    tags = tags or {}
    out: dict[str, str] = {}
    for k, v in tags.items():
        if v is None or isinstance(v, (dict, list)):
            continue
        if k in KEPT_TAGS or k.startswith("seamark:") or k.startswith("name"):
            out[str(k)] = str(v)[:240]
    return out


def marina_from_overpass(elem: dict) -> dict | None:
    typ = elem.get("type")
    eid = elem.get("id")
    if not typ or eid is None:
        return None
    coords = element_latlon(elem)
    if coords is None:
        return None
    lat, lon = coords
    tags = elem.get("tags") or {}
    if tags.get("leisure") != "marina":
        return None
    return {
        "osm_id": f"{typ}/{eid}",
        "name": element_name(tags),
        "lat": lat,
        "lon": lon,
        "source": "openstreetmap",
        "tags": kept_tags(tags),
        "website": osm_website_from_tags(tags),
    }


def merge_website(existing: dict | None, raw_site: str | None) -> tuple[str | None, str | None, str | None]:
    existing = existing or {}
    status = existing.get("website_status")
    if status in LOCKED_WEBSITE_STATUSES and existing.get("website"):
        return existing.get("website"), status, existing.get("website_source")
    if raw_site:
        return raw_site, "unchecked", "osm_tag"
    if existing.get("website"):
        return (
            existing.get("website"),
            existing.get("website_status") or "unchecked",
            existing.get("website_source"),
        )
    return None, None, None


def _apply_osm_google_place(patch: dict, website: str | None, existing: dict | None) -> None:
    """Si le tag OSM est déjà une URL /maps/place/, on la signale sans TinyFish."""
    raw = (website or "").strip()
    if "/maps/place/" not in raw or "/maps/search/" in raw:
        return
    if "google." not in raw.lower():
        return
    if existing and existing.get("maps_place_url"):
        return
    patch["maps_place_url"] = raw[:400]
    patch["maps_place_status"] = "found"
    patch["maps_place_source"] = "osm_tag"


def official_website(doc: dict) -> str | None:
    if doc.get("website"):
        return doc["website"]
    return osm_website_from_tags(doc.get("tags") or {})


# ------------------------------------------------------------------------
# Badges services — inspiration UX Open Waters: Seamap (« poi badges ») :
# la couleur du badge répond à une question du plaisancier (puis-je m'amarrer ?
# m'avitailler ? sortir le bateau ? trouver des services à terre ?), le détail
# vient des tags OSM conservés par kept_tags(). Aucune invention : un badge
# n'apparaît que si au moins un tag l'atteste.
# ------------------------------------------------------------------------

_FALSY_TAG_VALUES = frozenset({"no", "none", "0", "false"})

# tag conservé → question (berth / supply / tech / shore)
SERVICE_TAG_QUESTIONS = {
    "mooring": "berth",
    "capacity": "berth",
    "seamark:harbour:capacity": "berth",
    "max_depth": "berth",
    "depth": "berth",
    "seamark:harbour:draught": "berth",
    "fuel": "supply",
    "drinking_water": "supply",
    "electricity": "supply",
    "shop": "supply",
    "pumpout": "tech",
    "sanitary_dump_station": "tech",
    "waste_disposal": "tech",
    "shower": "shore",
    "toilets": "shore",
    "restaurant": "shore",
    "wifi": "shore",
    "internet_access": "shore",
    "wheelchair": "shore",
}

# valeurs de seamark:small_craft_facility:category → question
_SCF_QUESTIONS = {
    "visitor_berth": "berth", "visitors_berth": "berth", "berth": "berth",
    "fuel_station": "supply", "fuel": "supply", "chandler": "supply",
    "water_tap": "supply", "electricity": "supply", "provisions": "supply",
    "slipway": "tech", "boat_hoist": "tech", "crane": "tech",
    "boatyard": "tech", "pump_out": "tech", "sewerage": "tech",
    "toilets": "shore", "showers": "shore", "shower": "shore",
    "laundrette": "shore", "laundry": "shore", "refuse_bin": "shore",
}

_SCF_KEY_RE = re.compile(r"^seamark:small_craft_facility(?::\d+)?:category$")

SERVICE_QUESTIONS = ("berth", "supply", "tech", "shore")
_MAX_EVIDENCE_PER_QUESTION = 6


def marina_services(tags: dict | None) -> dict[str, list[str]]:
    """Résume les tags OSM en quatre questions : berth / supply / tech / shore.

    Retourne ``question → preuves « clé=valeur »`` (6 max par question) ;
    les questions sans preuve sont omises. Un tag à valeur négative
    (``no``/``none``/``0``) ne compte jamais.
    """
    tags = tags or {}
    out: dict[str, list[str]] = {}

    def add(question: str, key: str, value: str) -> None:
        bucket = out.setdefault(question, [])
        if len(bucket) >= _MAX_EVIDENCE_PER_QUESTION:
            return
        evidence = f"{key}={value[:40]}"
        if evidence not in bucket:
            bucket.append(evidence)

    for key, raw in tags.items():
        value = str(raw or "").strip()
        if not value or value.lower() in _FALSY_TAG_VALUES:
            continue
        question = SERVICE_TAG_QUESTIONS.get(key)
        if question:
            add(question, key, value)
            continue
        if _SCF_KEY_RE.match(key):
            for part in re.split(r"[;,]", value):
                cat = part.strip().lower()
                q = _SCF_QUESTIONS.get(cat)
                if q:
                    add(q, key, cat)
    return {q: out[q] for q in SERVICE_QUESTIONS if q in out}


def slim_feature(doc: dict) -> dict:
    lat = float(doc["lat"])
    lon = float(doc["lon"])
    name = doc.get("name") or ""
    website = official_website(doc)
    props = {
        "id": doc.get("_id"),
        "name": name,
        "osm_id": doc.get("osm_id"),
        "source": doc.get("source") or "openstreetmap",
        "website": website,
        "website_status": doc.get("website_status"),
        "website_source": doc.get("website_source"),
        "image": doc.get("image"),
        "maps_url": google_maps_url(name, lat, lon),
        "maps_place_url": doc.get("maps_place_url") or None,
        "has_google_place": bool(
            doc.get("maps_place_url")
            and "/maps/place/" in str(doc.get("maps_place_url"))
        ),
        "fetched_at": doc.get("fetched_at"),
    }
    svc = marina_services(doc.get("tags"))
    if svc:
        props["svc"] = svc
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": props,
    }


def marinas_to_slim_geojson(docs: Iterable[dict]) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [slim_feature(d) for d in docs if d.get("lat") is not None and d.get("lon") is not None],
        "attribution": "© OpenStreetMap contributors (ODbL)",
    }


async def upsert_world_marina(coll, cand: dict, now_iso: str) -> str:
    from app.services.isolated_runs import current_run_id, identity_query, run_doc_id, stamp
    osm_id = cand["osm_id"]
    existing = await coll.find_one(identity_query("osm_id", osm_id))
    website, status, wsrc = merge_website(existing, cand.get("website"))
    patch: dict[str, Any] = {
        "name": cand.get("name") or "",
        "lat": cand["lat"],
        "lon": cand["lon"],
        "source": "openstreetmap",
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
    _apply_osm_google_place(patch, website, existing)
    patch = stamp(patch, source_id=osm_id, wrote_flag="wrote_marinas")
    if existing:
        await coll.update_one({"_id": existing["_id"]}, {"$set": patch})
        return "updated"
    patch["_id"] = run_doc_id(osm_id)
    patch["enriched"] = False
    patch["stale"] = False
    await coll.insert_one(patch)
    return "inserted"


def _cursor_key() -> str:
    from app.services.isolated_runs import cursor_id
    return cursor_id(CURSOR_ID)


async def load_done_tiles(cursor_coll) -> list[str]:
    cid = _cursor_key()
    doc = await cursor_coll.find_one({"_id": cid}) or {}
    return list(doc.get("done_tiles") or [])


async def mark_tile_done(cursor_coll, key: str, now_iso: str) -> None:
    from app.services.isolated_runs import current_run_id
    cid = _cursor_key()
    done = await load_done_tiles(cursor_coll)
    if key not in done:
        done.append(key)
    payload = {"_id": cid, "done_tiles": done, "updated_at": now_iso, "schema": SCHEMA}
    rid = current_run_id()
    if rid:
        payload["run_id"] = rid
    existing = await cursor_coll.find_one({"_id": cid})
    if existing:
        await cursor_coll.replace_one({"_id": cid}, payload)
    else:
        await cursor_coll.insert_one(payload)


async def reset_cursor(cursor_coll) -> None:
    cid = _cursor_key()
    existing = await cursor_coll.find_one({"_id": cid})
    if existing:
        await cursor_coll.replace_one(
            {"_id": cid},
            {"_id": cid, "done_tiles": [], "updated_at": None, "schema": SCHEMA},
        )


async def ensure_indexes(marinas_coll, *, isolated: bool = False) -> None:
    try:
        if isolated:
            await marinas_coll.create_index(
                [("run_id", 1), ("osm_id", 1)], unique=True, sparse=True)
            await marinas_coll.create_index("run_id")
            await marinas_coll.create_index("name")
            return
        await marinas_coll.create_index("osm_id", unique=True, sparse=True)
        await marinas_coll.create_index("name")
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


async def _split_and_fetch(
    client: httpx.AsyncClient,
    tile: tuple[float, float, float, float],
    *,
    logger,
    timeout: int,
    min_span: float,
    reason: str,
) -> list[dict]:
    if logger:
        logger(f"Tuile {tile_key(tile)} {reason} — split")
    out: list[dict] = []
    south, west, north, east = tile
    for sub in split_bbox(south, west, north, east):
        await asyncio.sleep(1.2)
        out.extend(await fetch_tile_leisure_marinas(
            client, sub, logger=logger, timeout=timeout, min_span=min_span,
        ))
    return out


async def fetch_tile_leisure_marinas(
    client: httpx.AsyncClient,
    tile: tuple[float, float, float, float],
    *,
    logger=None,
    timeout: int = OVERPASS_TILE_TIMEOUT_S,
    min_span: float = MIN_TILE_DEG,
) -> list[dict]:
    south, west, north, east = tile
    if should_split_before_overpass(tile, min_span=min_span):
        return await _split_and_fetch(
            client, tile, logger=logger, timeout=timeout, min_span=min_span,
            reason=f"trop vaste ({tile_span_deg(tile):.0f}°)",
        )
    if logger:
        logger(f"Overpass {tile_key(tile)} …")
    body = leisure_marina_bbox_ql(south, west, north, east, timeout=timeout)
    try:
        return await overpass_fetch_bbox(
            south, west, north, east, client, logger=logger, body=body,
        )
    except Exception as exc:
        if tile_span_deg(tile) > min_span:
            return await _split_and_fetch(
                client, tile, logger=logger, timeout=timeout, min_span=min_span,
                reason=f"trop lourde ({type(exc).__name__})",
            )
        raise


async def build_world_marinas(
    *,
    marinas_coll,
    cursor_coll,
    state,
    resume: bool = True,
    tiles: tuple[tuple[float, float, float, float], ...] | None = None,
    client: httpx.AsyncClient | None = None,
    throttle_s: float | None = None,
    fetch_tile: FetchTile | None = None,
    run_id: str | None = None,
) -> dict:
    """
    Balaye les tuiles monde, upsert par osm_id, reprend les tuiles déjà faites.
    `fetch_tile` est injectable pour les tests (pas d'Overpass).
    `run_id` : écriture isolée (ne pas passer la collection live).
    """
    from app.services.isolated_runs import bind_run, reset_run

    token = bind_run(run_id) if run_id else None
    state.running = True
    state.started_at = time.time()
    state.finished_at = None
    state.error = None
    state.logs = []
    state.summary = None
    state.run_id = run_id

    grid = tiles or WORLD_TILES
    pause = _throttle_s(throttle_s)
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    try:
        await ensure_indexes(marinas_coll, isolated=bool(run_id))
        if not resume:
            await reset_cursor(cursor_coll)
            state.log("Reprise désactivée — curseur tuiles remis à zéro (pas de purge des fiches)")

        done = set(await load_done_tiles(cursor_coll)) if resume else set()
        state.total = len(grid)
        state.progress = 0
        state.log(
            f"Dump mondial leisure=marina : {len(grid)} tuiles, "
            f"{len(done)} déjà faites, throttle={pause:.1f}s"
        )

        inserted = updated = fetched_raw = errors = skipped = 0
        named = unnamed = with_site = 0
        own_client = client is None
        http = client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(connect=15.0, read=130.0, write=20.0, pool=10.0),
        )
        try:
            for tile in grid:
                key = tile_key(tile)
                if key in done:
                    skipped += 1
                    state.progress += 1
                    state.log(f"Tuile {key} déjà faite — skip")
                    continue
                state.log(f"Tuile {key} — Overpass + upsert…")
                try:
                    if fetch_tile:
                        elements = await fetch_tile(http, tile)
                    else:
                        elements = await fetch_tile_leisure_marinas(http, tile, logger=state.log)
                except Exception as exc:
                    errors += 1
                    state.log(f"Tuile {key} : {type(exc).__name__}: {str(exc)[:80]}")
                    state.progress += 1
                    await asyncio.sleep(pause)
                    continue

                fetched_raw += len(elements)
                state.log(f"Tuile {key} : {len(elements)} éléments Overpass — upsert")
                tile_ins = tile_upd = 0
                seen = 0
                for elem in elements:
                    cand = marina_from_overpass(elem)
                    if not cand:
                        continue
                    result = await upsert_world_marina(marinas_coll, cand, now_iso)
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
                    if cand.get("website"):
                        with_site += 1
                    seen += 1
                    if seen % UPSERT_HEARTBEAT == 0:
                        state.log(
                            f"Tuile {key} upsert {seen}/{len(elements)} "
                            f"(+{tile_ins} / ~{tile_upd})"
                        )

                await mark_tile_done(cursor_coll, key, now_iso)
                state.progress += 1
                state.log(
                    f"Tuile {key} : {len(elements)} brut → +{tile_ins} / ~{tile_upd}"
                )
                await asyncio.sleep(pause)
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
            "with_website_tag": with_site,
            "resume": resume,
        }
        state.summary = summary
        state.log(f"Dump mondial terminé: {json.dumps(summary)}")
        return summary
    except Exception as exc:
        state.error = f"{type(exc).__name__}: {exc}"
        state.log(f"FATAL: {state.error}")
        raise
    finally:
        state.finished_at = time.time()
        state.running = False
        if token is not None:
            reset_run(token)
