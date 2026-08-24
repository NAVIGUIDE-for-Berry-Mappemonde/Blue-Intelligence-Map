"""
Marinas layer — Phase 2.

Data sources:
  - OpenStreetMap via the Overpass API (worldwide)
  - SHOM WFS (metropolitan France + French overseas territories where available)

Build pipeline:
  * Queries around each waypoint of the Berry-Mappemonde official route
  * Corridor pass every ~25 NM along maritime segments
  * Dedup key = normalize(name[:25]) + geohash(precision=6) → newest wins
  * Enrichment placeholder: `enriched=false` (Phase 3 will fill this with TinyFish/OpenRouter)

No third-party heavy deps: geohash + haversine + Overpass QL client are all local.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import httpx

# ------------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------------

NM_PER_METER = 1.0 / 1852.0
METERS_PER_NM = 1852.0

# Metropolitan France + Corsica bbox — SHOM only queries within this envelope
# (SHOM has territorial data outside this, but it is patchy; keep it tight and clear.)
FRANCE_METRO_BBOX = (41.0, -6.0, 52.0, 10.0)  # (south, west, north, east)

# Public Overpass endpoints — round-robin on failure.
# NB: overpass-api.de and .ru are often blocked from cloud/CI IPs; kumi.systems is the most
# reliable public mirror. We keep it first, then fall back.
OVERPASS_ENDPOINTS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]

SHOM_WFS = "https://services.data.shom.fr/INSPIRE/wfs"

CURATED_SEED_FILE = Path(__file__).parent / "data" / "curated_marinas.json"

USER_AGENT = "BlueIntelligenceMap/2.0 (contact: berry-mappemonde)"

# Tags we keep on the marina document (raw useful OSM tags)
KEPT_TAGS = (
    "vhf_channel", "vhf", "seamark:harbour:category", "seamark:type",
    "phone", "contact:phone", "email", "contact:email",
    "website", "contact:website", "url",
    "opening_hours", "operator", "operator:type",
    "capacity", "capacity:persons", "seamark:harbour:capacity",
    "max_depth", "depth", "seamark:harbour:draught",
    "fee", "charge",
    "shower", "toilets", "drinking_water", "electricity", "fuel",
    "sanitary_dump_station", "pumpout", "waste_disposal",
    "wheelchair", "harbour", "harbour:type", "mooring", "leisure",
    "shop", "restaurant", "wifi", "internet_access",
    "addr:city", "addr:street", "addr:postcode", "addr:country",
    "description",
)


# ------------------------------------------------------------------------
# Small utils — geohash + haversine + name normalisation
# ------------------------------------------------------------------------

_GEOHASH_ALPHABET = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash_encode(lat: float, lon: float, precision: int = 6) -> str:
    """Standard geohash (base32) encoding. Precision 6 ~= 1.2 km × 0.61 km at the equator."""
    lat_range = [-90.0, 90.0]
    lon_range = [-180.0, 180.0]
    bit = 0
    ch = 0
    even = True  # start with longitude bit
    out = []
    while len(out) < precision:
        if even:
            mid = (lon_range[0] + lon_range[1]) / 2
            if lon >= mid:
                ch |= 1 << (4 - bit)
                lon_range[0] = mid
            else:
                lon_range[1] = mid
        else:
            mid = (lat_range[0] + lat_range[1]) / 2
            if lat >= mid:
                ch |= 1 << (4 - bit)
                lat_range[0] = mid
            else:
                lat_range[1] = mid
        even = not even
        bit += 1
        if bit == 5:
            out.append(_GEOHASH_ALPHABET[ch])
            bit = 0
            ch = 0
    return "".join(out)


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    R = 6371008.8  # WGS-84 mean earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    d_m = 2 * R * math.asin(math.sqrt(a))
    return d_m * NM_PER_METER


def normalize_name(s: str) -> str:
    """
    Aggressive normalisation for dedup: strip accents, lowercase, remove
    punctuation, collapse whitespace, cap length.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", " ", s).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s[:25]


def dedup_key(name: str, lat: float, lon: float) -> str:
    return f"{normalize_name(name)}@{geohash_encode(lat, lon, 6)}"


def in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float]) -> bool:
    s, w, n, e = bbox
    return s <= lat <= n and w <= lon <= e


# ------------------------------------------------------------------------
# Overpass QL client — polite, sequential
# ------------------------------------------------------------------------


def _overpass_query_body(lat: float, lon: float, radius_m: int) -> str:
    """
    Build a bulk Overpass QL query covering:
      - leisure=marina (nodes/ways/relations)
      - harbour=yes
      - seamark:type=harbour
    All within a circle of radius_m meters around (lat, lon).
    Emits `out center;` so ways/relations get a computed centroid.
    """
    r = int(radius_m)
    return f"""[out:json][timeout:60];
(
  node["leisure"="marina"](around:{r},{lat:.5f},{lon:.5f});
  way["leisure"="marina"](around:{r},{lat:.5f},{lon:.5f});
  relation["leisure"="marina"](around:{r},{lat:.5f},{lon:.5f});
  node["harbour"="yes"](around:{r},{lat:.5f},{lon:.5f});
  way["harbour"="yes"](around:{r},{lat:.5f},{lon:.5f});
  node["seamark:type"="harbour"](around:{r},{lat:.5f},{lon:.5f});
);
out center tags;
""".strip()


def _overpass_bbox_body(south: float, west: float, north: float, east: float) -> str:
    """
    Bulk Overpass QL query for marinas/harbours inside a bbox.
    Much more efficient than many small `around:` queries when we need to cover
    a whole coastal region (e.g. metropolitan France).
    """
    return f"""[out:json][timeout:120];
(
  node["leisure"="marina"]({south:.5f},{west:.5f},{north:.5f},{east:.5f});
  way["leisure"="marina"]({south:.5f},{west:.5f},{north:.5f},{east:.5f});
  relation["leisure"="marina"]({south:.5f},{west:.5f},{north:.5f},{east:.5f});
  node["harbour"="yes"]({south:.5f},{west:.5f},{north:.5f},{east:.5f});
  way["harbour"="yes"]({south:.5f},{west:.5f},{north:.5f},{east:.5f});
  node["seamark:type"="harbour"]({south:.5f},{west:.5f},{north:.5f},{east:.5f});
);
out center tags;
""".strip()


async def overpass_fetch_bbox(
    south: float,
    west: float,
    north: float,
    east: float,
    client: httpx.AsyncClient,
    max_retries: int = 5,
    logger=None,
) -> list[dict]:
    """
    Fetch all marina/harbour features inside a bbox. Retries across endpoints.
    Returns raw Overpass `elements` list.
    """
    body = _overpass_bbox_body(south, west, north, east)
    last_err: Exception | None = None
    for attempt in range(max_retries):
        endpoint = OVERPASS_ENDPOINTS[attempt % len(OVERPASS_ENDPOINTS)]
        try:
            r = await client.post(
                endpoint,
                data={"data": body},
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=httpx.Timeout(connect=10.0, read=120.0, write=15.0, pool=8.0),
            )
            if r.status_code == 200:
                return (r.json().get("elements") or [])
            if r.status_code in (429, 502, 503, 504):
                sleep_s = 3 * (2 ** min(attempt, 3))
                if logger:
                    logger(f"Overpass bbox {r.status_code} on {endpoint}, backoff {sleep_s}s")
                await asyncio.sleep(sleep_s)
                continue
            last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            last_err = e
            if logger and attempt < 2:
                logger(f"Overpass bbox {type(e).__name__} on {endpoint}: {str(e)[:60]}")
            await asyncio.sleep(2)
    if last_err:
        raise last_err
    return []


def cluster_points_to_bboxes(
    points: list[tuple[float, float, str]],
    radius_nm: float,
    max_bbox_span_nm: float = 500.0,
) -> list[dict]:
    """
    Greedy clustering of (lat, lon, label) points into a list of bounding boxes.
    Each bbox spans at most `max_bbox_span_nm` NM in either direction and pads by
    `radius_nm` NM. Returns list of {south,west,north,east,labels,pt_count}.
    Purpose: replace hundreds of `around:` queries with a handful of bbox queries.
    """
    pad_deg = radius_nm / 60.0
    max_span_deg = max_bbox_span_nm / 60.0
    unassigned = list(points)
    clusters: list[list[tuple[float, float, str]]] = []
    while unassigned:
        seed = unassigned.pop(0)
        cluster = [seed]
        s_lat, s_lon, _ = seed
        i = 0
        while i < len(unassigned):
            la, lo, lb = unassigned[i]
            # accept the point if adding it keeps the bbox within max_span
            all_lats = [p[0] for p in cluster] + [la]
            all_lons = [p[1] for p in cluster] + [lo]
            span_lat = max(all_lats) - min(all_lats)
            span_lon = max(all_lons) - min(all_lons)
            if span_lat <= max_span_deg and span_lon <= max_span_deg:
                cluster.append(unassigned.pop(i))
            else:
                i += 1
        clusters.append(cluster)
    out = []
    for cl in clusters:
        lats = [p[0] for p in cl]
        lons = [p[1] for p in cl]
        out.append({
            "south": max(-90.0, min(lats) - pad_deg),
            "west": max(-180.0, min(lons) - pad_deg),
            "north": min(90.0, max(lats) + pad_deg),
            "east": min(180.0, max(lons) + pad_deg),
            "labels": [p[2] for p in cl],
            "pt_count": len(cl),
        })
    return out


async def overpass_fetch(
    lat: float,
    lon: float,
    radius_m: int,
    client: httpx.AsyncClient,
    max_retries: int = 2,
    logger=None,
) -> list[dict]:
    """
    POST an Overpass QL query, rotating through endpoints on failure, with
    exponential backoff on 429/504/timeout. Returns the raw `elements` list.
    Aggressive short timeouts so a blocked endpoint doesn't stall the whole build.
    """
    body = _overpass_query_body(lat, lon, radius_m)
    last_err: Exception | None = None
    for attempt in range(max_retries):
        endpoint = OVERPASS_ENDPOINTS[attempt % len(OVERPASS_ENDPOINTS)]
        try:
            r = await client.post(
                endpoint,
                data={"data": body},
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=httpx.Timeout(connect=8.0, read=45.0, write=15.0, pool=8.0),
            )
            if r.status_code == 200:
                data = r.json()
                return data.get("elements") or []
            if r.status_code in (429, 502, 503, 504):
                sleep_s = 2 * (2 ** attempt)
                if logger:
                    logger(f"Overpass {r.status_code} on {endpoint}, backoff {sleep_s}s")
                await asyncio.sleep(sleep_s)
                continue
            last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            last_err = e
            if logger and attempt == 0:
                logger(f"Overpass {type(e).__name__} on {endpoint}: {str(e)[:60]}")
            await asyncio.sleep(1)
    if last_err:
        raise last_err
    return []


def _overpass_elem_to_marina(elem: dict) -> dict | None:
    """Convert one Overpass element into a marina candidate. Returns None if unusable."""
    tags = elem.get("tags") or {}
    typ = elem.get("type")
    if typ == "node":
        lat = elem.get("lat")
        lon = elem.get("lon")
    else:
        center = elem.get("center") or {}
        lat = center.get("lat")
        lon = center.get("lon")
    if lat is None or lon is None:
        return None
    name = (
        tags.get("name")
        or tags.get("name:fr")
        or tags.get("name:en")
        or tags.get("official_name")
        or tags.get("alt_name")
    )
    if not name:
        # Try a fallback: harbour tag with the road/addr name
        name = (
            tags.get("addr:city")
            or tags.get("harbour:name")
            or f"Marina @ {lat:.3f},{lon:.3f}"
        )
    # Only keep useful tag subset
    kept = {k: v for k, v in tags.items() if k in KEPT_TAGS or k.startswith("seamark:")}
    return {
        "name": str(name)[:120],
        "lat": float(lat),
        "lon": float(lon),
        "source": "openstreetmap",
        "osm_id": f"{typ}/{elem.get('id')}",
        "tags": kept,
    }


# ------------------------------------------------------------------------
# SHOM WFS client (best-effort; failures are non-fatal)
# ------------------------------------------------------------------------

# SHOM public typenames (INSPIRE profile). SMCFAC = "Signalisation Maritime et Culturelle
# et Facilités portuaires". We try several candidate layers — SHOM's public schema has
# rotated over the years; if none respond we log and return [].
SHOM_TYPENAMES = [
    "SMCFAC_TS_PORT_HARBOUR_BDD_WFS",
    "smcfac:smcfac_point",
    "MOUILLAGE_FR_WFS",
    "MOUILLAGE_ORGANISE_FR_WFS",
]


async def shom_fetch(
    bbox: tuple[float, float, float, float],
    client: httpx.AsyncClient,
    logger=None,
) -> list[dict]:
    """
    Query SHOM WFS for port/harbour points inside `bbox`.
    Returns list of dicts {name, lat, lon, source='shom', tags{}}.
    Silently returns [] on any error — SHOM is best-effort.
    """
    s, w, n, e = bbox
    bbox_str = f"{s},{w},{n},{e},EPSG:4326"
    for typename in SHOM_TYPENAMES:
        try:
            params = {
                "service": "WFS",
                "version": "2.0.0",
                "request": "GetFeature",
                "typenames": typename,
                "bbox": bbox_str,
                "outputFormat": "application/json",
                "srsName": "EPSG:4326",
                "count": "500",
            }
            r = await client.get(
                SHOM_WFS,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=45,
            )
            if r.status_code != 200 or "json" not in r.headers.get("content-type", "").lower():
                if logger:
                    logger(f"SHOM {typename}: HTTP {r.status_code}, ct={r.headers.get('content-type')}")
                continue
            fc = r.json()
            feats = fc.get("features") or []
            if not feats:
                continue
            out = []
            for f in feats:
                geom = f.get("geometry") or {}
                props = f.get("properties") or {}
                if geom.get("type") == "Point":
                    lon, lat = geom["coordinates"][:2]
                elif geom.get("type") == "MultiPoint" and geom.get("coordinates"):
                    lon, lat = geom["coordinates"][0][:2]
                else:
                    continue
                name = (
                    props.get("nom") or props.get("name") or props.get("libelle")
                    or props.get("TOPONYME") or props.get("PORT_NAME")
                    or f"SHOM @ {lat:.3f},{lon:.3f}"
                )
                out.append({
                    "name": str(name)[:120],
                    "lat": float(lat),
                    "lon": float(lon),
                    "source": "shom",
                    "osm_id": None,
                    "tags": {f"shom:{k}": str(v)[:80] for k, v in props.items() if v and not isinstance(v, (dict, list))},
                })
            if logger:
                logger(f"SHOM {typename}: {len(out)} features returned")
            return out
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as e:
            if logger:
                logger(f"SHOM {typename}: {type(e).__name__}: {str(e)[:80]}")
            continue
    if logger:
        logger("SHOM: no typename returned data — continuing with OSM only")
    return []


# ------------------------------------------------------------------------
# Route helpers — waypoints, corridor sampling, priority assignment
# ------------------------------------------------------------------------


@dataclass
class Waypoint:
    id: str
    name: str
    lat: float
    lon: float
    kind: str  # "escale" | "intermediate"


@dataclass
class CorridorPoint:
    lat: float
    lon: float


def load_route(route_path: Path) -> tuple[list[Waypoint], list[list[tuple[float, float]]]]:
    """
    Return (waypoints, maritime_segments).
    - waypoints: 17 escales + 19 intermediates, in file order.
    - maritime_segments: list of polylines [(lat, lon), ...] for maritime segments only.
    """
    data = json.loads(route_path.read_text(encoding="utf-8"))
    wps: list[Waypoint] = []
    lines: list[list[tuple[float, float]]] = []
    for f in data.get("features") or []:
        g = f.get("geometry") or {}
        p = f.get("properties") or {}
        if g.get("type") == "Point":
            lon, lat = g["coordinates"][:2]
            wps.append(Waypoint(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"berry-wp:{p.get('name','')}")),
                name=str(p.get("name") or "waypoint"),
                lat=float(lat), lon=float(lon),
                kind=str(p.get("point_type") or "intermediate"),
            ))
        elif g.get("type") == "LineString" and p.get("type") == "maritime":
            lines.append([(float(la), float(lo)) for lo, la in g["coordinates"]])
    return wps, lines


def sample_corridor(lines: list[list[tuple[float, float]]], step_nm: float = 25.0) -> list[CorridorPoint]:
    """Walk each maritime polyline and drop a point every step_nm nautical miles."""
    out: list[CorridorPoint] = []
    step_m = step_nm * METERS_PER_NM
    for poly in lines:
        acc = 0.0
        for i in range(len(poly) - 1):
            la1, lo1 = poly[i]
            la2, lo2 = poly[i + 1]
            seg_nm = haversine_nm(la1, lo1, la2, lo2)
            seg_m = seg_nm * METERS_PER_NM
            if seg_m == 0:
                continue
            # advance in fractions
            t = 0.0
            while acc + (1 - t) * seg_m >= step_m:
                # distance we need on this segment starting from current t
                need = step_m - acc
                # fraction of the segment we still need to travel
                dt = need / seg_m
                t += dt
                lat = la1 + (la2 - la1) * t
                lon = lo1 + (lo2 - lo1) * t
                out.append(CorridorPoint(lat=lat, lon=lon))
                acc = 0.0
            acc += (1 - t) * seg_m
    return out


def priority_for(lat: float, lon: float, wps: list[Waypoint]) -> tuple[int, Waypoint, float]:
    """
    Return (priority, nearest_waypoint, distance_nm).
    Priority: 1 if within 15 NM of an escale, 2 if within 15 NM of an intermediate, else 3 (corridor).
    """
    best_wp: Waypoint | None = None
    best_d = math.inf
    for w in wps:
        d = haversine_nm(lat, lon, w.lat, w.lon)
        if d < best_d:
            best_d = d
            best_wp = w
    assert best_wp is not None
    if best_d <= 15 and best_wp.kind == "escale":
        prio = 1
    elif best_d <= 15 and best_wp.kind == "intermediate":
        prio = 2
    else:
        prio = 3
    return prio, best_wp, best_d


# ------------------------------------------------------------------------
# Build orchestrator (async task-friendly). Stateless — takes a Mongo collection
# and a logger callback. State/progress is held by the caller.
# ------------------------------------------------------------------------


@dataclass
class BuildState:
    running: bool = False
    started_at: float | None = None
    finished_at: float | None = None
    progress: int = 0
    total: int = 0
    logs: list[str] = field(default_factory=list)
    summary: dict | None = None
    error: str | None = None

    def log(self, msg: str):
        self.logs.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        # keep last 200 lines
        if len(self.logs) > 200:
            self.logs = self.logs[-200:]


def load_curated_marinas() -> list[dict]:
    """
    Load the curated fallback list of well-known marinas.
    Used as an "always on" data source so the UI has something to show even
    when OSM/Overpass is unreachable. Marked source='curated' so it's clear.
    """
    if not CURATED_SEED_FILE.exists():
        return []
    try:
        data = json.loads(CURATED_SEED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for m in data.get("marinas", []):
        out.append({
            "name": m.get("name") or "",
            "lat": float(m["lat"]),
            "lon": float(m["lon"]),
            "source": "curated",
            "osm_id": None,
            "tags": m.get("tags") or {},
        })
    return out


async def build_marinas(
    *,
    marinas_coll,
    route_path: Path,
    radius_nm: float,
    state: BuildState,
    include_corridor: bool = True,
    corridor_step_nm: float = 100.0,
) -> dict:
    """
    Full build: query OSM (bbox-batched) + SHOM around every waypoint + corridor sample,
    dedup, upsert into `marinas_coll`. Returns summary.
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

        # Small-radius `around:` queries for each waypoint (+ optional corridor points).
        # We tried bbox-batched queries (5-8° spans) but the public Overpass mirrors
        # 502 on them consistently. Sticking to per-point `around:` (18-20 km radius)
        # gives the servers something they can handle quickly.
        query_targets: list[tuple[str, float, float, str]] = []
        for w in wps:
            query_targets.append((f"wp:{w.name}", w.lat, w.lon, "waypoint"))
        for i, cp in enumerate(corridor):
            query_targets.append((f"corridor:{i}", cp.lat, cp.lon, "corridor"))

        state.total = len(query_targets)
        state.log(
            f"Loaded route: {len(wps)} waypoints "
            f"({sum(1 for w in wps if w.kind=='escale')} escales, {sum(1 for w in wps if w.kind=='intermediate')} intermediates), "
            f"{len(maritime_lines)} maritime segments → {len(corridor)} corridor points (step={corridor_step_nm} NM, corridor={'on' if include_corridor else 'off'})"
        )
        state.log(f"Query targets: {state.total}  |  radius = {radius_nm:.1f} NM ({radius_nm*METERS_PER_NM:.0f} m)")

        candidates: list[dict] = []
        radius_m = int(radius_nm * METERS_PER_NM)
        overpass_errors = 0

        # ---- Curated seed pass (always) — provides fallback marinas at every escale ----
        curated = load_curated_marinas()
        candidates.extend(curated)
        state.log(f"Curated seed: loaded {len(curated)} known marinas")

        async with httpx.AsyncClient() as client:
            # ---- OSM pass: sequential per-point around: queries.
            # Bounded concurrency via a semaphore keeps us polite (max 2 in flight).
            sem = asyncio.Semaphore(2)
            counter = {"done": 0}

            async def _one(label: str, lat: float, lon: float, _kind: str):
                async with sem:
                    try:
                        elements = await overpass_fetch(lat, lon, radius_m, client, logger=state.log)
                        n_kept = 0
                        for elem in elements:
                            m = _overpass_elem_to_marina(elem)
                            if m:
                                candidates.append(m)
                                n_kept += 1
                        if n_kept:
                            state.log(f"OSM {label} ({lat:.3f},{lon:.3f}): {n_kept} candidates")
                    except Exception as e:
                        nonlocal overpass_errors
                        overpass_errors += 1
                        state.log(f"OSM {label}: {type(e).__name__}: {str(e)[:60]}")
                    counter["done"] += 1
                    state.progress = counter["done"]
                    # small stagger inside the semaphore
                    await asyncio.sleep(0.3)

            # Launch all — the semaphore keeps only 2 in flight.
            await asyncio.gather(*(_one(*t) for t in query_targets))

            # ---- SHOM pass (best-effort, metropolitan France only) ----
            shom_errors = 0
            fr_wps = [w for w in wps if in_bbox(w.lat, w.lon, FRANCE_METRO_BBOX)]
            if fr_wps:
                lats = [w.lat for w in fr_wps]
                lons = [w.lon for w in fr_wps]
                pad = radius_nm / 60.0
                bbox = (
                    max(-90.0, min(lats) - pad),
                    max(-180.0, min(lons) - pad),
                    min(90.0, max(lats) + pad),
                    min(180.0, max(lons) + pad),
                )
                state.log(f"SHOM WFS bbox {bbox} — {len(fr_wps)} France-metro waypoints in scope")
                try:
                    shom_pts = await shom_fetch(bbox, client, logger=state.log)
                    for sp in shom_pts:
                        if any(haversine_nm(sp["lat"], sp["lon"], w.lat, w.lon) <= radius_nm for w in wps):
                            candidates.append(sp)
                    state.log(f"SHOM: {len(shom_pts)} raw → filtered by {radius_nm} NM radius from waypoints")
                except Exception as e:
                    shom_errors += 1
                    state.log(f"SHOM error: {type(e).__name__}: {str(e)[:80]}")

        # ---- Dedup + priority + upsert ----
        by_key: dict[str, dict] = {}
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for cand in candidates:
            prio, nearest_wp, dist_nm = priority_for(cand["lat"], cand["lon"], wps)
            key = dedup_key(cand["name"], cand["lat"], cand["lon"])
            existing_cand = by_key.get(key)
            new_doc = {
                "_id": str(uuid.uuid4()),
                "name": cand["name"],
                "lat": cand["lat"],
                "lon": cand["lon"],
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
                "dedup_key": key,
                "fetched_at": now_iso,
                "enriched": False,
                "stale": False,
            }
            if existing_cand:
                # Source preference: openstreetmap > shom > curated (curated is our fallback).
                src_rank = {"openstreetmap": 3, "shom": 2, "curated": 1}
                new_rank = src_rank.get(cand["source"], 0)
                old_rank = src_rank.get(existing_cand["source"], 0)
                if new_rank > old_rank:
                    by_key[key] = new_doc
                elif new_rank == old_rank:
                    # same rank → keep the one closer to a waypoint
                    if new_doc["nearest_waypoint"]["distance_nm"] < existing_cand["nearest_waypoint"]["distance_nm"]:
                        by_key[key] = new_doc
                # else: existing wins
            else:
                by_key[key] = new_doc

        deduped = list(by_key.values())
        dup_count = len(candidates) - len(deduped)

        inserted = updated = 0
        for doc in deduped:
            existing_doc = await marinas_coll.find_one({"dedup_key": doc["dedup_key"]}, {"_id": 1, "fetched_at": 1})
            if existing_doc:
                doc["_id"] = existing_doc["_id"]
                await marinas_coll.replace_one({"_id": existing_doc["_id"]}, doc)
                updated += 1
            else:
                await marinas_coll.insert_one(doc)
                inserted += 1

        try:
            await marinas_coll.create_index("dedup_key", unique=True)
            await marinas_coll.create_index([("priority", 1), ("name", 1)])
        except Exception:
            pass

        by_prio = {1: 0, 2: 0, 3: 0}
        by_src = {"openstreetmap": 0, "shom": 0, "curated": 0}
        for d in deduped:
            by_prio[d["priority"]] = by_prio.get(d["priority"], 0) + 1
            by_src[d["source"]] = by_src.get(d["source"], 0) + 1

        summary = {
            "queried_points": state.total,
            "found_raw": len(candidates),
            "unique_after_dedup": len(deduped),
            "duplicates_merged": dup_count,
            "inserted": inserted,
            "updated": updated,
            "by_priority": by_prio,
            "by_source": by_src,
            "overpass_errors": overpass_errors,
            "shom_errors": shom_errors,
            "radius_nm": radius_nm,
            "corridor_step_nm": corridor_step_nm if include_corridor else None,
        }
        state.summary = summary
        state.log(f"Build complete: {json.dumps(summary)}")
        return summary

    except Exception as e:
        state.error = f"{type(e).__name__}: {e}"
        state.log(f"FATAL: {state.error}")
        raise
    finally:
        state.finished_at = time.time()
        state.running = False


# ------------------------------------------------------------------------
# GeoJSON serialiser
# ------------------------------------------------------------------------


def marinas_to_geojson(docs: Iterable[dict]) -> dict:
    feats = []
    for d in docs:
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(d["lon"]), float(d["lat"])]},
            "properties": {
                "id": d.get("_id"),
                "name": d.get("name"),
                "source": d.get("source"),
                "priority": d.get("priority"),
                "nearest_waypoint": d.get("nearest_waypoint") or {},
                "tags": d.get("tags") or {},
                "osm_id": d.get("osm_id"),
                "enriched": bool(d.get("enriched")),
                "fetched_at": d.get("fetched_at"),
            },
        })
    return {"type": "FeatureCollection", "features": feats}
