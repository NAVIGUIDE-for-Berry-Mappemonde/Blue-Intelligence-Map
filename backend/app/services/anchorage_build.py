"""
Anchorages layer — Phase 8 (Mouillages).

Découvre les mouillages naturels et postes de mouillage le long de la route
Berry-Mappemonde avec la même logique de corridor ±25 NM que les marinas
(buffer spatial réel : bbox-batched + post-filtre de bande exacte).

Source : OpenStreetMap via Overpass uniquement.
  * Pas de SHOM (pas de couche mouillages dans le WFS public).
  * Pas de seed curated (features naturelles, pas de base maintenue).
  * Pas d'enrichissement TinyFish (pas de site officiel pour une baie).

Tags OSM requêtés :
  - seamark:type = anchorage      (zone de mouillage S-57)
  - seamark:type = anchor_berth   (poste de mouillage individuel)
  - natural      = bay            (baie naturelle — gardée seulement si nommée)
  - leisure      = anchorage      (tag non standard mais répandu)
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Iterable

import httpx

from app.services.marina_build import (
    METERS_PER_NM,
    OVERPASS_ENDPOINTS,
    USER_AGENT,
    BuildState,
    dedup_key,
    fetch_corridor_band,
    flush_docs_incremental,
    haversine_nm,
    load_route,
    overpass_await_slot,
    priority_for,
    sample_corridor,
)

# ---------------------------------------------------------------------------
# Tags OSM conservés sur le document mouillage
# ---------------------------------------------------------------------------

KEPT_TAGS = (
    "seamark:type",
    "seamark:name",
    "seamark:anchorage:category",
    "seamark:anchorage:restriction",
    "seamark:anchorage:depth",
    "seamark:anchorage:holding_ground",
    "seamark:anchorage:radius",
    "natural",
    "leisure",
    "description",
    "name",
    "name:fr",
    "name:en",
    "depth",
    "max_depth",
    "holding_ground",
    "shelter",
    "website",
    "contact:website",
    "url",
    "operator",
    "access",
    "fee",
    "charge",
    "addr:city",
    "addr:country",
)

# Catégorie S-57 (catach) → libellés
ANCHORAGE_CAT_LABELS = {
    "1": "Non restreint",
    "2": "Réservé",
    "3": "Restreint",
    "4": "Travaux en cours",
    "5": "Eau profonde",
    "6": "Explosifs",
    "7": "Quarantaine",
}


# ---------------------------------------------------------------------------
# Overpass QL builders (around + bbox)
# ---------------------------------------------------------------------------

def _anchorage_query_body(lat: float, lon: float, radius_m: int) -> str:
    r = int(radius_m)
    return f"""[out:json][timeout:60];
(
  node["seamark:type"="anchorage"](around:{r},{lat:.5f},{lon:.5f});
  way["seamark:type"="anchorage"](around:{r},{lat:.5f},{lon:.5f});
  relation["seamark:type"="anchorage"](around:{r},{lat:.5f},{lon:.5f});
  node["seamark:type"="anchor_berth"](around:{r},{lat:.5f},{lon:.5f});
  way["seamark:type"="anchor_berth"](around:{r},{lat:.5f},{lon:.5f});
  node["natural"="bay"]["name"](around:{r},{lat:.5f},{lon:.5f});
  way["natural"="bay"]["name"](around:{r},{lat:.5f},{lon:.5f});
  relation["natural"="bay"]["name"](around:{r},{lat:.5f},{lon:.5f});
  node["leisure"="anchorage"](around:{r},{lat:.5f},{lon:.5f});
  way["leisure"="anchorage"](around:{r},{lat:.5f},{lon:.5f});
);
out center tags;
""".strip()


def anchorage_bbox_body(south: float, west: float, north: float, east: float) -> str:
    """Requête bbox groupée pour la couverture corridor (buffer réel)."""
    bb = f"{south:.5f},{west:.5f},{north:.5f},{east:.5f}"
    return f"""[out:json][timeout:120];
(
  node["seamark:type"="anchorage"]({bb});
  way["seamark:type"="anchorage"]({bb});
  relation["seamark:type"="anchorage"]({bb});
  node["seamark:type"="anchor_berth"]({bb});
  way["seamark:type"="anchor_berth"]({bb});
  node["natural"="bay"]["name"]({bb});
  way["natural"="bay"]["name"]({bb});
  relation["natural"="bay"]["name"]({bb});
  node["leisure"="anchorage"]({bb});
  way["leisure"="anchorage"]({bb});
);
out center tags;
""".strip()


async def overpass_fetch_anchorages(
    lat: float,
    lon: float,
    radius_m: int,
    client: httpx.AsyncClient,
    max_retries: int = 3,
    logger=None,
) -> list[dict]:
    """Comme marinas.overpass_fetch mais avec la requête mouillages."""
    body = _anchorage_query_body(lat, lon, radius_m)
    last_err: Exception | None = None
    for attempt in range(max_retries):
        endpoint = OVERPASS_ENDPOINTS[attempt % len(OVERPASS_ENDPOINTS)]
        try:
            if endpoint.startswith("https://overpass-api.de"):
                ok = await overpass_await_slot(client, logger=logger)
                if not ok and logger:
                    logger("[overpass-anchorages] proceeding despite no reported slot")
            r = await client.post(
                endpoint,
                data={"data": body},
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=httpx.Timeout(connect=10.0, read=90.0, write=15.0, pool=8.0),
            )
            if r.status_code == 200:
                return r.json().get("elements") or []
            if r.status_code == 429:
                sleep_s = int(r.headers.get("Retry-After") or 30)
                if logger:
                    logger(f"[overpass-anchorages] 429 on {endpoint}, Retry-After={sleep_s}s")
                await asyncio.sleep(sleep_s)
                continue
            if r.status_code in (500, 502, 503, 504):
                sleep_s = 5 * (attempt + 1)
                if logger:
                    logger(f"[overpass-anchorages] {r.status_code} on {endpoint}, backoff {sleep_s}s")
                await asyncio.sleep(sleep_s)
                continue
            last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            last_err = e
            if logger and attempt == 0:
                logger(f"[overpass-anchorages] {type(e).__name__} on {endpoint}: {str(e)[:60]}")
            await asyncio.sleep(3)
    if last_err:
        raise last_err
    return []


# ---------------------------------------------------------------------------
# OSM element → anchorage document
# ---------------------------------------------------------------------------

def _overpass_elem_to_anchorage(elem: dict) -> dict | None:
    tags = elem.get("tags") or {}
    typ = elem.get("type")

    if typ == "node":
        lat, lon = elem.get("lat"), elem.get("lon")
    else:
        center = elem.get("center") or {}
        lat, lon = center.get("lat"), center.get("lon")
    if lat is None or lon is None:
        return None

    seamark_type = tags.get("seamark:type", "")
    natural_tag = tags.get("natural", "")
    if seamark_type == "anchor_berth":
        anchorage_type = "anchor_berth"
    elif seamark_type == "anchorage":
        anchorage_type = "anchorage"
    elif natural_tag == "bay":
        anchorage_type = "bay"
    else:
        anchorage_type = "anchorage"

    name = (
        tags.get("seamark:name")
        or tags.get("name")
        or tags.get("name:fr")
        or tags.get("name:en")
        or tags.get("official_name")
        or tags.get("alt_name")
    )
    if not name:
        # Baies anonymes = bruit → écartées. Les mouillages seamark anonymes
        # sont volontairement cartographiés, on les garde avec un nom fallback.
        if anchorage_type == "bay":
            return None
        if anchorage_type == "anchor_berth":
            name = f"Poste de mouillage @ {lat:.3f},{lon:.3f}"
        else:
            name = f"Mouillage @ {lat:.3f},{lon:.3f}"

    raw_cat = str(tags.get("seamark:anchorage:category") or "").strip()
    cat_label = ANCHORAGE_CAT_LABELS.get(raw_cat) if raw_cat else None

    kept = {k: v for k, v in tags.items() if k in KEPT_TAGS or k.startswith("seamark:anchorage:")}
    if cat_label:
        kept["anchorage_category_label"] = cat_label

    return {
        "name": str(name)[:120],
        "lat": float(lat),
        "lon": float(lon),
        "anchorage_type": anchorage_type,
        "source": "openstreetmap",
        "osm_id": f"{typ}/{elem.get('id')}",
        "tags": kept,
    }


def _anchorage_doc(cand: dict, wps, now_iso: str) -> dict:
    """Build the canonical anchorage document for a candidate."""
    prio, nearest_wp, dist_nm = priority_for(cand["lat"], cand["lon"], wps)
    return {
        "_id": str(uuid.uuid4()),
        "name": cand["name"],
        "lat": cand["lat"],
        "lon": cand["lon"],
        "anchorage_type": cand["anchorage_type"],
        "source": cand["source"],
        "osm_id": cand.get("osm_id"),
        "tags": cand.get("tags") or {},
        "priority": prio,
        "nearest_waypoint": {
            "id": nearest_wp.id,
            "name": nearest_wp.name,
            "kind": nearest_wp.kind,
            "distance_nm": round(dist_nm, 2),
        },
        "dedup_key": dedup_key(cand["name"], cand["lat"], cand["lon"]),
        "fetched_at": now_iso,
        "enriched": False,   # jamais d'enrichissement pour les mouillages
        "stale": False,
    }


# ---------------------------------------------------------------------------
# Build orchestrator
# ---------------------------------------------------------------------------

async def build_anchorages(
    *,
    anchorages_coll,
    route_path: Path,
    radius_nm: float,
    state: BuildState,
    include_corridor: bool = True,
    corridor_step_nm: float = 25.0,
    corridor_radius_nm: float = 25.0,
) -> dict:
    """
    Build complet : OSM autour de chaque waypoint + bande corridor
    ±corridor_radius_nm (bbox-batched, fallback per-point), dedup,
    upsert dans `anchorages_coll`. Retourne un résumé.
    """
    state.running = True
    state.started_at = time.time()
    state.finished_at = None
    state.error = None
    state.logs = []
    state.summary = None

    try:
        wps, maritime_lines = load_route(route_path)
        corridor = sample_corridor(maritime_lines, step_nm=corridor_step_nm) if include_corridor else []

        state.total = len(wps)
        state.progress = 0
        state.log(
            f"Mouillages build — {len(wps)} waypoints "
            f"({sum(1 for w in wps if w.kind=='escale')} escales, "
            f"{sum(1 for w in wps if w.kind=='intermediate')} intermediates), "
            f"{len(maritime_lines)} maritime segments → {len(corridor)} corridor points "
            f"(step={corridor_step_nm} NM, corridor={'on' if include_corridor else 'off'})"
        )
        state.log(
            f"Waypoint radius = {radius_nm:.1f} NM  |  corridor buffer = ±{corridor_radius_nm:.0f} NM "
            f"({corridor_radius_nm*2:.0f} NM total band)"
        )

        candidates: list[dict] = []
        radius_m = int(radius_nm * METERS_PER_NM)
        overpass_errors = 0
        now_build_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Indexes up-front so incremental flushes benefit from dedup_key lookups
        try:
            await anchorages_coll.create_index("dedup_key", unique=True)
            await anchorages_coll.create_index([("priority", 1), ("name", 1)])
            await anchorages_coll.create_index("anchorage_type")
        except Exception:
            pass

        async with httpx.AsyncClient() as client:
            # ---- Waypoint pass (per-point around:, AUP-compliant) ----
            for w in wps:
                label = f"wp:{w.name}"
                try:
                    elements = await overpass_fetch_anchorages(w.lat, w.lon, radius_m, client, logger=state.log)
                    n_kept = 0
                    for elem in elements:
                        a = _overpass_elem_to_anchorage(elem)
                        if a:
                            candidates.append(a)
                            n_kept += 1
                    if n_kept:
                        state.log(f"OSM {label} ({w.lat:.3f},{w.lon:.3f}): {n_kept} candidates")
                        # Crash-safe: persist this waypoint's finds immediately
                        await flush_docs_incremental(
                            anchorages_coll,
                            [_anchorage_doc(c, wps, now_build_iso) for c in candidates[-n_kept:]],
                        )
                except Exception as e:
                    overpass_errors += 1
                    state.log(f"OSM {label}: {type(e).__name__}: {str(e)[:70]}")
                state.progress += 1
                await asyncio.sleep(3.0)

            # ---- Corridor band pass (true ±corridor_radius_nm buffer) ----
            corridor_bboxes = 0
            if include_corridor and corridor:
                async def _persist_anchorage_batch(batch: list[dict]):
                    docs = []
                    for elem in batch:
                        a = _overpass_elem_to_anchorage(elem)
                        if a:
                            docs.append(_anchorage_doc(a, wps, now_build_iso))
                    if docs:
                        await flush_docs_incremental(anchorages_coll, docs)

                corr_elements, corr_errors = await fetch_corridor_band(
                    corridor,
                    corridor_radius_nm,
                    client,
                    state=state,
                    bbox_body_builder=anchorage_bbox_body,
                    point_fetcher=overpass_fetch_anchorages,
                    on_batch=_persist_anchorage_batch,
                )
                overpass_errors += corr_errors
                n_kept = 0
                for elem in corr_elements:
                    a = _overpass_elem_to_anchorage(elem)
                    if a:
                        candidates.append(a)
                        n_kept += 1
                state.log(f"Corridor band total: {n_kept} anchorage candidates")

        # ---- Dedup + priority + upsert ----
        by_key: dict[str, dict] = {}
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for cand in candidates:
            new_doc = _anchorage_doc(cand, wps, now_iso)
            key = new_doc["dedup_key"]
            existing = by_key.get(key)
            if existing is None or new_doc["nearest_waypoint"]["distance_nm"] < existing["nearest_waypoint"]["distance_nm"]:
                by_key[key] = new_doc

        deduped = list(by_key.values())
        dup_count = len(candidates) - len(deduped)

        inserted = updated = 0
        for doc in deduped:
            existing_doc = await anchorages_coll.find_one({"dedup_key": doc["dedup_key"]}, {"_id": 1})
            if existing_doc:
                doc["_id"] = existing_doc["_id"]
                await anchorages_coll.replace_one({"_id": existing_doc["_id"]}, doc)
                updated += 1
            else:
                await anchorages_coll.insert_one(doc)
                inserted += 1

        try:
            await anchorages_coll.create_index("dedup_key", unique=True)
            await anchorages_coll.create_index([("priority", 1), ("name", 1)])
            await anchorages_coll.create_index("anchorage_type")
        except Exception:
            pass

        by_prio = {1: 0, 2: 0, 3: 0}
        by_type: dict[str, int] = {}
        for d in deduped:
            by_prio[d["priority"]] = by_prio.get(d["priority"], 0) + 1
            t = d.get("anchorage_type", "anchorage")
            by_type[t] = by_type.get(t, 0) + 1

        summary = {
            "queried_points": state.total,
            "found_raw": len(candidates),
            "unique_after_dedup": len(deduped),
            "duplicates_merged": dup_count,
            "inserted": inserted,
            "updated": updated,
            "by_priority": by_prio,
            "by_type": by_type,
            "overpass_errors": overpass_errors,
            "radius_nm": radius_nm,
            "corridor_step_nm": corridor_step_nm if include_corridor else None,
            "corridor_radius_nm": corridor_radius_nm if include_corridor else None,
            "corridor_band_nm": corridor_radius_nm * 2 if include_corridor else None,
        }
        state.summary = summary
        state.log(f"Mouillages build complete: {json.dumps(summary)}")
        return summary

    except Exception as e:
        state.error = f"{type(e).__name__}: {e}"
        state.log(f"FATAL: {state.error}")
        raise
    finally:
        state.finished_at = time.time()
        state.running = False


# ---------------------------------------------------------------------------
# GeoJSON serialiser
# ---------------------------------------------------------------------------

def anchorages_to_geojson(docs: Iterable[dict]) -> dict:
    feats = []
    for d in docs:
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(d["lon"]), float(d["lat"])]},
            "properties": {
                "id": d.get("_id"),
                "name": d.get("name"),
                "anchorage_type": d.get("anchorage_type"),
                "source": d.get("source"),
                "osm_id": d.get("osm_id"),
                "priority": d.get("priority"),
                "nearest_waypoint": d.get("nearest_waypoint") or {},
                "tags": d.get("tags") or {},
                "fetched_at": d.get("fetched_at"),
                "stale": bool(d.get("stale")),
            },
        })
    return {"type": "FeatureCollection", "features": feats}
