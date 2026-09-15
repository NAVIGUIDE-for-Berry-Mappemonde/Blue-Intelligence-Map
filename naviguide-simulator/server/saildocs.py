"""Dernier GRIB2 autour du bateau (Saildocs + Open-Meteo). Pas un GRIB globe.

Zone : couloir ~200 nm autour du trait horloge entre maintenant et
l’arrivée du bateau à l’ETA du prochain téléchargement (prochain cycle
GFS prêt, ~6 h). Toujours le dernier fichier, jamais de climatologie.
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from voyage_clock import OFFICIAL_VOYAGE_ID, parse_iso, sample_clock_at_time, to_iso

DAILY_RADIUS_NM = 200.0
DAILY_LEAD_HOURS = 72
DAILY_STEP_HOURS = 6
NEXT_DOWNLOAD_HOURS = 6
TRACK_STEP_HOURS = 6
MAX_BBOX_LAT_SPAN = 12.0
MAX_BBOX_LON_SPAN = 20.0
GRIB_MISSING = "dernière prévision absente"

# NOAA GFS / GFS-Wave : 00, 06, 12, 18 UTC. Produits 0–72 h prêts ~cycle+4 h.
GFS_CYCLE_HOURS = (0, 6, 12, 18)
CYCLE_READY_LAG_H = 4.0
MIN_DEST_HORIZON_H = 1.0

# 3 familles GRIB2 NOAA gratuites utiles au large (pas NAM/HRRR US).
GRIB_PRODUCTS: List[Dict[str, Any]] = [
    {
        "id": "gfs",
        "model": "GFS",
        "saildocs": "GFS",
        "params": ["WIND", "PRMSL", "RAIN"],
        "grid": "0.25,0.25",
        "step": 6,
        "hours": 72,
        "role": "vent, pression, pluie",
    },
    {
        "id": "gfswave",
        "model": "WW3",
        "saildocs": "WW3",
        "params": ["HTSGW", "DIRPW", "PERPW"],
        "grid": "0.25,0.25",
        "step": 6,
        "hours": 72,
        "role": "vagues (GFS-Wave / WW3)",
    },
    {
        "id": "rtofs",
        "model": "RTOFS",
        "saildocs": "RTOFS",
        "params": ["CURRENT"],
        "grid": "0.2,0.2",
        "step": 3,
        "hours": 72,
        "role": "courants",
    },
]

GRIB_DIR = Path(os.environ.get(
    "NAVIGUIDE_GRIB_DIR",
    str(Path(__file__).resolve().parent / "grib_data"),
))
INBOX_DIR = Path(os.environ.get(
    "NAVIGUIDE_SAILDOCS_INBOX",
    str(Path(__file__).resolve().parent / "saildocs_inbox"),
))


def utc_day(when: Optional[datetime] = None) -> str:
    dt = when or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _aware(when: Optional[datetime] = None) -> datetime:
    dt = when or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def last_ready_cycle(when: Optional[datetime] = None) -> datetime:
    """Dernier cycle GFS 00/06/12/18 dont les champs 0–72 h sont attendus."""
    now = _aware(when)
    t = now.replace(minute=0, second=0, microsecond=0)
    for _ in range(48):
        if t.hour in GFS_CYCLE_HOURS:
            ready_at = t + timedelta(hours=CYCLE_READY_LAG_H)
            if ready_at <= now:
                return t
        t -= timedelta(hours=1)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def next_download_at(when: Optional[datetime] = None) -> datetime:
    """Prochain instant où un nouveau cycle GFS est attendu (cycle + 4 h)."""
    now = _aware(when)
    cursor = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=12)
    for add in range(0, 48):
        cycle = cursor + timedelta(hours=add)
        if cycle.hour in GFS_CYCLE_HOURS:
            ready = cycle + timedelta(hours=CYCLE_READY_LAG_H)
            if ready > now:
                return ready
    return now + timedelta(hours=6)


def dest_eta_at_next_download(when: Optional[datetime] = None) -> datetime:
    """ETA du bateau au prochain fetch ; si < 2 h, on prend le fetch d’après."""
    now = _aware(when)
    nxt = next_download_at(now)
    if (nxt - now) < timedelta(hours=MIN_DEST_HORIZON_H):
        nxt = next_download_at(nxt + timedelta(minutes=1))
    return nxt


def product_by_saildocs(code: str) -> Optional[Dict[str, Any]]:
    key = (code or "").upper()
    for item in GRIB_PRODUCTS:
        if item["saildocs"] == key or item["model"] == key or item["id"].upper() == key:
            return item
    return None


def _unwrap_lon(lon: float, ref: float) -> float:
    while lon - ref > 180:
        lon -= 360
    while lon - ref < -180:
        lon += 360
    return lon


def _wrap_lon(lon: float) -> float:
    while lon > 180:
        lon -= 360
    while lon < -180:
        lon += 360
    return lon


def _disk_delta(lat: float, radius_nm: float) -> Tuple[float, float]:
    dlat = radius_nm / 60.0
    cos_lat = max(0.2, math.cos(math.radians(lat)))
    dlon = radius_nm / (60.0 * cos_lat)
    return dlat, dlon


def bbox_around(lat: float, lon: float, radius_nm: float = DAILY_RADIUS_NM) -> Tuple[float, float, float, float]:
    """(south, north, west, east) — disque autour d’un point, pas le globe."""
    dlat, dlon = _disk_delta(lat, radius_nm)
    south = max(-90.0, lat - dlat)
    north = min(90.0, lat + dlat)
    west = lon - dlon
    east = lon + dlon
    return (round(south, 4), round(north, 4), round(west, 4), round(east, 4))


def _clamp_span(
    lo: float,
    hi: float,
    core_lo: float,
    core_hi: float,
    max_span: float,
) -> Tuple[float, float]:
    if hi - lo <= max_span:
        return lo, hi
    core_span = core_hi - core_lo
    if core_span >= max_span:
        mid = (core_lo + core_hi) / 2.0
        return mid - max_span / 2.0, mid + max_span / 2.0
    pad = (max_span - core_span) / 2.0
    return core_lo - pad, core_hi + pad


def _as_latlon(item: Any) -> Optional[Tuple[float, float]]:
    if item is None:
        return None
    if isinstance(item, dict):
        if item.get("lat") is None or item.get("lon") is None:
            return None
        return (float(item["lat"]), float(item["lon"]))
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        return (float(item[0]), float(item[1]))
    return None


def points_from_around(around: Optional[dict]) -> List[Tuple[float, float]]:
    if not around:
        return []
    pts: List[Tuple[float, float]] = []
    here = _as_latlon(around)
    if here:
        pts.append(here)
    for raw in around.get("waypoints") or []:
        pt = _as_latlon(raw)
        if pt:
            pts.append(pt)
    dest = _as_latlon(around.get("dest"))
    if dest:
        pts.append(dest)
    return pts


def bbox_along_track(
    points: Sequence[Tuple[float, float]],
    radius_nm: float = DAILY_RADIUS_NM,
) -> Tuple[float, float, float, float]:
    """Union des disques autour du trait (ici → demain), pas le globe."""
    if not points:
        raise ValueError("bbox ou around requis")
    if len(points) == 1:
        return bbox_around(points[0][0], points[0][1], radius_nm)

    ref_lon = points[0][1]
    souths: List[float] = []
    norths: List[float] = []
    wests: List[float] = []
    easts: List[float] = []
    raw_lats: List[float] = []
    raw_lons: List[float] = []
    for lat, lon in points:
        dlat, dlon = _disk_delta(lat, radius_nm)
        unwrapped = _unwrap_lon(lon, ref_lon)
        souths.append(lat - dlat)
        norths.append(lat + dlat)
        wests.append(unwrapped - dlon)
        easts.append(unwrapped + dlon)
        raw_lats.append(lat)
        raw_lons.append(unwrapped)

    south, north = _clamp_span(
        max(-90.0, min(souths)),
        min(90.0, max(norths)),
        min(raw_lats),
        max(raw_lats),
        MAX_BBOX_LAT_SPAN,
    )
    west_u, east_u = _clamp_span(
        min(wests),
        max(easts),
        min(raw_lons),
        max(raw_lons),
        MAX_BBOX_LON_SPAN,
    )
    return (
        round(south, 4),
        round(north, 4),
        round(_wrap_lon(west_u), 4),
        round(_wrap_lon(east_u), 4),
    )


def bbox_from_around(
    around: dict,
    radius_nm: float = DAILY_RADIUS_NM,
) -> Tuple[float, float, float, float]:
    return bbox_along_track(points_from_around(around), radius_nm)


def track_from_clock(
    clock: Optional[dict],
    when: datetime,
    *,
    horizon_hours: Optional[int] = None,
    step_hours: int = TRACK_STEP_HOURS,
) -> Optional[Dict[str, Any]]:
    """Position horloge maintenant + arrivée à l’ETA du prochain download."""
    if not clock:
        return None
    when = _aware(when)
    dest_t = dest_eta_at_next_download(when)
    if horizon_hours is None:
        horizon_hours = max(1, int(round((dest_t - when).total_seconds() / 3600.0)))
    else:
        dest_t = when + timedelta(hours=horizon_hours)
    times: List[datetime] = []
    cursor = when
    while cursor < dest_t:
        times.append(cursor)
        cursor += timedelta(hours=step_hours)
    times.append(dest_t)
    samples: List[Dict[str, Any]] = []
    for t in times:
        sample = sample_clock_at_time(clock, t)
        if sample and sample.get("lat") is not None and sample.get("lon") is not None:
            samples.append({
                "lat": float(sample["lat"]),
                "lon": float(sample["lon"]),
                "t": to_iso(t),
            })
    if not samples:
        return None
    dest = samples[-1]
    waypoints = samples[1:-1] if len(samples) > 2 else []
    return {
        "lat": samples[0]["lat"],
        "lon": samples[0]["lon"],
        "at": samples[0]["t"],
        "dest": {"lat": dest["lat"], "lon": dest["lon"], "t": dest["t"]},
        "waypoints": waypoints,
        "nextDownloadAt": dest["t"],
        "horizonHours": horizon_hours,
        "cycle": to_iso(last_ready_cycle(when)),
    }


def lon_span(west: float, east: float) -> float:
    span = abs(east - west)
    if span > 180:
        span = 360 - span
    return span


def assert_corridor_not_globe(bbox: Tuple[float, float, float, float]) -> None:
    south, north, west, east = bbox
    if (north - south) > MAX_BBOX_LAT_SPAN:
        raise ValueError("bbox trop large : GRIB globe interdit")
    if lon_span(west, east) > MAX_BBOX_LON_SPAN:
        raise ValueError("bbox trop large : GRIB globe interdit")


def _hem_lat(v: float) -> str:
    return f"{abs(v):.1f}{'N' if v >= 0 else 'S'}"


def _hem_lon(v: float) -> str:
    return f"{abs(v):.1f}{'E' if v >= 0 else 'W'}"


def saildocs_query(
    lat: float,
    lon: float,
    *,
    dest: Any = None,
    waypoints: Optional[Iterable[Any]] = None,
    radius_nm: float = DAILY_RADIUS_NM,
    model: str = "GFS",
    hours: int = DAILY_LEAD_HOURS,
    step: int = DAILY_STEP_HOURS,
    params: Optional[Sequence[str]] = None,
    grid: Optional[str] = None,
) -> str:
    """Requête Saildocs skipper sur le couloir ici → prochain fetch, pas le monde."""
    spec = product_by_saildocs(model)
    params = list(params or (spec["params"] if spec else ["WIND", "PRMSL", "RAIN"]))
    grid = grid or (spec["grid"] if spec else "0.25,0.25")
    if spec:
        hours = int(spec.get("hours") or hours)
        step = int(spec.get("step") or step)
    around = {"lat": lat, "lon": lon, "dest": dest, "waypoints": list(waypoints or [])}
    south, north, west, east = bbox_from_around(around, radius_nm)
    assert_corridor_not_globe((south, north, west, east))
    window = f"0,{step}..{hours}"
    code = spec["saildocs"] if spec else model
    return (
        f"{code}:{_hem_lat(north)},{_hem_lat(south)},"
        f"{_hem_lon(west)},{_hem_lon(east)}|{grid}|{window}|{','.join(params)}"
    )


def saildocs_queries(
    lat: float,
    lon: float,
    *,
    dest: Any = None,
    waypoints: Optional[Iterable[Any]] = None,
    radius_nm: float = DAILY_RADIUS_NM,
) -> List[Dict[str, str]]:
    """Les 3 requêtes NOAA gratuites : GFS, WW3 / GFS-Wave, RTOFS."""
    out: List[Dict[str, str]] = []
    for spec in GRIB_PRODUCTS:
        out.append({
            "id": spec["id"],
            "model": spec["model"],
            "role": spec["role"],
            "query": saildocs_query(
                lat,
                lon,
                dest=dest,
                waypoints=waypoints,
                radius_nm=radius_nm,
                model=spec["saildocs"],
                params=spec["params"],
                grid=spec["grid"],
                hours=int(spec["hours"]),
                step=int(spec["step"]),
            ),
        })
    return out


def grib_dir() -> Path:
    GRIB_DIR.mkdir(parents=True, exist_ok=True)
    return GRIB_DIR


def inbox_dir() -> Path:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    return INBOX_DIR


def _safe_id(voyage_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", voyage_id)


def daily_path(voyage_id: str, day: str) -> Path:
    return grib_dir() / f"{_safe_id(voyage_id)}_{day}.json"


def latest_path(voyage_id: str) -> Path:
    return grib_dir() / f"{_safe_id(voyage_id)}_latest.json"


def load_daily(voyage_id: str, day: Optional[str] = None) -> Optional[Dict[str, Any]]:
    dest = daily_path(voyage_id, day or utc_day())
    if not dest.exists():
        return None
    return json.loads(dest.read_text(encoding="utf-8"))


def load_latest(voyage_id: str, day: Optional[str] = None) -> Optional[Dict[str, Any]]:
    dest = latest_path(voyage_id)
    if dest.exists():
        return json.loads(dest.read_text(encoding="utf-8"))
    return load_daily(voyage_id, day)


def save_daily(record: Dict[str, Any]) -> Dict[str, Any]:
    dest = daily_path(record["voyageId"], record["day"])
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(dest)
    latest = latest_path(record["voyageId"])
    latest_tmp = latest.with_suffix(".tmp")
    latest_tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_tmp.replace(latest)
    return record


def knots_from_uv(u: float, v: float) -> Tuple[float, float]:
    speed_ms = math.hypot(u, v)
    knots = speed_ms * 1.943844
    # meteorological from-direction
    coming = (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0
    return round(knots, 2), round(coming, 1)


def wind_at_daily(record: Optional[dict], lat: float, lon: float, when: datetime) -> Optional[Dict[str, Any]]:
    if not record or record.get("status") != "ready":
        return None
    samples = record.get("samples") or []
    if not samples:
        return None
    when_iso = to_iso(when) if isinstance(when, datetime) else str(when)
    best = None
    best_d = None
    for s in samples:
        d = (float(s.get("lat") or 0) - lat) ** 2 + (float(s.get("lon") or 0) - lon) ** 2
        t = str(s.get("t") or s.get("iso") or "")
        if t and abs(parse_iso(t).timestamp() - parse_iso(when_iso).timestamp()) > 12 * 3600:
            continue
        if best_d is None or d < best_d:
            best_d = d
            best = s
    if best is None:
        best = samples[0]
    knots = best.get("windKnots")
    direction = best.get("dirFromDeg")
    if knots is None and best.get("u") is not None and best.get("v") is not None:
        knots, direction = knots_from_uv(float(best["u"]), float(best["v"]))
    if knots is None:
        return None
    return {
        "windKnots": float(knots),
        "dirFromDeg": float(direction) if direction is not None else None,
        "pressHpa": best.get("pressHpa"),
        "rainMm": best.get("rainMm"),
        "hs": best.get("hs"),
        "waveDirDeg": best.get("waveDirDeg"),
        "currentKnots": best.get("currentKnots"),
        "currentDirDeg": best.get("currentDirDeg"),
        "model": record.get("model") or "GFS",
        "waveModel": record.get("waveModel") or best.get("waveModel"),
        "currentModel": record.get("currentModel") or best.get("currentModel"),
        "kind": "forecast",
        "t": best.get("t"),
    }


def _parse_bbox(raw: Any, around: Optional[dict], radius_nm: float) -> Tuple[float, float, float, float]:
    if raw and len(raw) == 4:
        return (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
    pts = points_from_around(around)
    if pts:
        return bbox_along_track(pts, radius_nm)
    raise ValueError("bbox ou around requis")


def ingest_daily(
    voyage_id: str,
    payload: Dict[str, Any],
    *,
    around: Optional[dict] = None,
) -> Dict[str, Any]:
    day = payload.get("day") or utc_day()
    radius = float(payload.get("radiusNm") or DAILY_RADIUS_NM)
    if radius > DAILY_RADIUS_NM * 1.5:
        raise ValueError("rayon trop large : pas un GRIB globe")
    here = around or payload.get("around")
    bbox = _parse_bbox(payload.get("bbox"), here, radius)
    assert_corridor_not_globe(bbox)
    model = str(payload.get("model") or "GFS")
    queries = payload.get("queries")
    query = payload.get("query")
    if here and not queries:
        queries = saildocs_queries(
            float(here["lat"]),
            float(here["lon"]),
            dest=here.get("dest"),
            waypoints=here.get("waypoints"),
            radius_nm=radius,
        )
    if not query and queries:
        query = queries[0]["query"]
    if not query and here:
        query = saildocs_query(
            float(here["lat"]),
            float(here["lon"]),
            dest=here.get("dest"),
            waypoints=here.get("waypoints"),
            radius_nm=radius,
            model=model,
        )
    issued = payload.get("issued") or to_iso(datetime.now(timezone.utc))
    cycle = payload.get("cycle") or to_iso(last_ready_cycle())
    products = payload.get("products") or [{
        "id": (product_by_saildocs(model) or GRIB_PRODUCTS[0])["id"],
        "model": model,
        "status": "ready",
    }]
    record = {
        "voyageId": voyage_id,
        "day": day,
        "status": "ready",
        "model": model,
        "waveModel": payload.get("waveModel"),
        "currentModel": payload.get("currentModel"),
        "source": payload.get("source") or "saildocs",
        "issued": issued,
        "cycle": cycle,
        "products": products,
        "bbox": list(bbox),
        "radiusNm": radius,
        "around": here,
        "dest": (here or {}).get("dest") if here else None,
        "nextDownloadAt": (here or {}).get("nextDownloadAt") if here else None,
        "horizonHours": (here or {}).get("horizonHours") if here else None,
        "query": query,
        "queries": queries,
        "samples": payload.get("samples") or [],
        "warning": None,
    }
    return save_daily(record)


def absent_payload(voyage_id: str, day: Optional[str] = None, around: Optional[dict] = None) -> Dict[str, Any]:
    here = around or {}
    query = None
    bbox = None
    queries = None
    if here.get("lat") is not None and here.get("lon") is not None:
        bbox = list(bbox_from_around(here))
        queries = saildocs_queries(
            float(here["lat"]),
            float(here["lon"]),
            dest=here.get("dest"),
            waypoints=here.get("waypoints"),
        )
        query = queries[0]["query"]
    return {
        "voyageId": voyage_id,
        "day": day or utc_day(),
        "status": "absent",
        "model": None,
        "source": "openmeteo",
        "bbox": bbox,
        "radiusNm": DAILY_RADIUS_NM,
        "around": here or None,
        "dest": here.get("dest") or None,
        "nextDownloadAt": here.get("nextDownloadAt") or to_iso(dest_eta_at_next_download()),
        "horizonHours": here.get("horizonHours"),
        "cycle": to_iso(last_ready_cycle()),
        "query": query,
        "queries": queries,
        "products": [
            {"id": p["id"], "model": p["model"], "status": "absent", "role": p["role"]}
            for p in GRIB_PRODUCTS
        ],
        "samples": [],
        "warning": GRIB_MISSING,
    }


def public_grib(record: Optional[dict], voyage_id: str = OFFICIAL_VOYAGE_ID,
                around: Optional[dict] = None, when: Optional[datetime] = None) -> Dict[str, Any]:
    day = utc_day(when)
    if not record:
        body = absent_payload(voyage_id, day, around)
    else:
        body = {
            "voyageId": record.get("voyageId", voyage_id),
            "day": record.get("day", day),
            "status": record.get("status") or "ready",
            "model": record.get("model"),
            "waveModel": record.get("waveModel"),
            "currentModel": record.get("currentModel"),
            "source": record.get("source") or "saildocs",
            "issued": record.get("issued"),
            "cycle": record.get("cycle"),
            "products": record.get("products"),
            "bbox": record.get("bbox"),
            "radiusNm": record.get("radiusNm") or DAILY_RADIUS_NM,
            "around": record.get("around") or around,
            "dest": record.get("dest") or (around or {}).get("dest") if around else record.get("dest"),
            "nextDownloadAt": record.get("nextDownloadAt") or (around or {}).get("nextDownloadAt"),
            "horizonHours": record.get("horizonHours") or (around or {}).get("horizonHours"),
            "query": record.get("query"),
            "queries": record.get("queries"),
            "warning": record.get("warning"),
        }
    wind = None
    if around and record and around.get("lat") is not None and around.get("lon") is not None:
        wind = wind_at_daily(
            record,
            float(around["lat"]),
            float(around["lon"]),
            when or datetime.now(timezone.utc),
        )
    body["wind"] = wind
    if body["status"] != "ready":
        body["warning"] = GRIB_MISSING
    return body


def scan_inbox(voyage_id: str, day: Optional[str] = None, around: Optional[dict] = None) -> Optional[Dict[str, Any]]:
    """Lit un JSON Saildocs du jour dans l’inbox (YYYYMMDD*.json)."""
    d = day or utc_day()
    stamp = d.replace("-", "")
    folder = inbox_dir()
    matches: List[Path] = sorted(folder.glob(f"{stamp}*.json"))
    if not matches:
        matches = sorted(folder.glob(f"*{stamp}*.json"))
    for path in matches:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if around and not payload.get("around"):
            payload["around"] = around
        try:
            return ingest_daily(voyage_id, payload, around=payload.get("around") or around)
        except ValueError:
            continue
    return None
