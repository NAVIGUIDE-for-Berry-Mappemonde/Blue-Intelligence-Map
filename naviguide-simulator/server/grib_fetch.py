"""Dernier GFS / GFS-Wave autour du couloir (Open-Meteo). Pas un GRIB globe.

RTOFS brut n’est pas parsé ici (binaire NOAA). La requête Saildocs RTOFS
reste prête ; le courant n’entre que s’il est déposé (inbox / POST).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from saildocs import (
    GRIB_PRODUCTS,
    dest_eta_at_next_download,
    ingest_daily,
    last_ready_cycle,
    load_latest,
    points_from_around,
    saildocs_queries,
    utc_day,
)
from voyage_clock import parse_iso, to_iso

log = logging.getLogger("naviguide-simulator.grib")

GFS_MODEL_NAME = "GFS 0.25° (Open-Meteo)"
WAVE_MODEL_NAME = "GFS-Wave 0.25° (Open-Meteo)"
FORECAST_HOURS = 72
STEP_HOURS = 6
STALE_RETRY_S = 10 * 60
FETCH_TIMEOUT_S = 20.0

_last_try: Dict[str, datetime] = {}


def auto_enabled() -> bool:
    if os.environ.get("NAVIGUIDE_GRIB_AUTO", "1").lower() in ("0", "false", "no"):
        return False
    if (os.environ.get("NAVIGUIDE_FORECAST_BACKEND") or "").lower() == "synthetic":
        return False
    return True


def is_stale(record: Optional[dict], when: Optional[datetime] = None) -> bool:
    if not record or record.get("status") != "ready":
        return True
    now = when or datetime.now(timezone.utc)
    raw = record.get("cycle") or record.get("issued")
    if not raw:
        return True
    try:
        stored = parse_iso(raw)
    except Exception:
        return True
    return stored < last_ready_cycle(now) - timedelta(minutes=5)


def _iso_hour(raw: str) -> str:
    if raw.endswith("Z") or "+" in raw[10:]:
        return to_iso(parse_iso(raw if "Z" in raw or "+" in raw else raw + "Z"))
    if len(raw) == 16:
        return f"{raw}:00Z"
    return f"{raw}Z"


def _index_times(times: List[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for i, raw in enumerate(times):
        try:
            out[to_iso(parse_iso(_iso_hour(raw)))] = i
        except Exception:
            continue
    return out


def _at(series: List[Any], index: Dict[str, int], iso: str) -> Optional[float]:
    i = index.get(iso)
    if i is None or i >= len(series):
        return None
    val = series[i]
    if val is None:
        return None
    return float(val)


def _fetch_gfs_point(client: httpx.Client, lat: float, lon: float) -> Optional[dict]:
    resp = client.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "hourly": "wind_speed_10m,wind_direction_10m,pressure_msl,rain",
            "wind_speed_unit": "kn",
            "models": "gfs_global",
            "forecast_days": 4,
            "timezone": "UTC",
        },
    )
    resp.raise_for_status()
    hourly = (resp.json() or {}).get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return None
    return {
        "times": times,
        "speedKnots": hourly.get("wind_speed_10m") or [],
        "dirFromDeg": hourly.get("wind_direction_10m") or [],
        "pressHpa": hourly.get("pressure_msl") or [],
        "rainMm": hourly.get("rain") or [],
    }


def _fetch_wave_point(client: httpx.Client, lat: float, lon: float) -> Optional[dict]:
    resp = client.get(
        "https://marine-api.open-meteo.com/v1/marine",
        params={
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "hourly": "wave_height,wave_direction,wave_period",
            "models": "ncep_gfswave025",
            "forecast_days": 4,
            "timezone": "UTC",
        },
    )
    resp.raise_for_status()
    hourly = (resp.json() or {}).get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return None
    return {
        "times": times,
        "hs": hourly.get("wave_height") or [],
        "waveDirDeg": hourly.get("wave_direction") or [],
        "wavePeriodS": hourly.get("wave_period") or [],
    }


def _lead_times(when: datetime) -> List[str]:
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    start = when.replace(minute=0, second=0, microsecond=0)
    return [to_iso(start + timedelta(hours=h)) for h in range(0, FORECAST_HOURS + 1, STEP_HOURS)]


def fetch_latest_payload(around: dict, when: Optional[datetime] = None) -> Dict[str, Any]:
    now = when or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    pts = points_from_around(around)
    if not pts:
        raise ValueError("around sans position")
    leads = _lead_times(now)
    samples: List[dict] = []
    gfs_ok = False
    wave_ok = False
    with httpx.Client(timeout=FETCH_TIMEOUT_S) as client:
        for lat, lon in pts:
            gfs = None
            wave = None
            try:
                gfs = _fetch_gfs_point(client, lat, lon)
            except Exception as exc:
                log.warning("GFS Open-Meteo %s,%s: %s", lat, lon, exc)
            try:
                wave = _fetch_wave_point(client, lat, lon)
            except Exception as exc:
                log.warning("GFS-Wave Open-Meteo %s,%s: %s", lat, lon, exc)
            if gfs:
                gfs_ok = True
            if wave:
                wave_ok = True
            g_idx = _index_times(gfs["times"]) if gfs else {}
            w_idx = _index_times(wave["times"]) if wave else {}
            for iso in leads:
                row: Dict[str, Any] = {"lat": lat, "lon": lon, "t": iso}
                if gfs:
                    spd = _at(gfs["speedKnots"], g_idx, iso)
                    direc = _at(gfs["dirFromDeg"], g_idx, iso)
                    if spd is not None:
                        row["windKnots"] = round(spd, 2)
                    if direc is not None:
                        row["dirFromDeg"] = round(direc, 1)
                    press = _at(gfs["pressHpa"], g_idx, iso)
                    rain = _at(gfs["rainMm"], g_idx, iso)
                    if press is not None:
                        row["pressHpa"] = round(press, 1)
                    if rain is not None:
                        row["rainMm"] = round(rain, 2)
                if wave:
                    hs = _at(wave["hs"], w_idx, iso)
                    wdir = _at(wave["waveDirDeg"], w_idx, iso)
                    if hs is not None:
                        row["hs"] = round(hs, 2)
                        row["waveModel"] = WAVE_MODEL_NAME
                    if wdir is not None:
                        row["waveDirDeg"] = round(wdir, 1)
                if "windKnots" in row or "hs" in row:
                    samples.append(row)
    if not gfs_ok:
        raise RuntimeError("GFS Open-Meteo indisponible")
    products = []
    for spec in GRIB_PRODUCTS:
        if spec["id"] == "gfs":
            products.append({
                "id": "gfs",
                "model": GFS_MODEL_NAME,
                "status": "ready",
                "role": spec["role"],
            })
        elif spec["id"] == "gfswave":
            products.append({
                "id": "gfswave",
                "model": WAVE_MODEL_NAME,
                "status": "ready" if wave_ok else "absent",
                "role": spec["role"],
            })
        else:
            products.append({
                "id": spec["id"],
                "model": spec["model"],
                "status": "absent",
                "role": spec["role"],
            })
    queries = saildocs_queries(
        float(around["lat"]),
        float(around["lon"]),
        dest=around.get("dest"),
        waypoints=around.get("waypoints"),
    )
    return {
        "model": GFS_MODEL_NAME,
        "waveModel": WAVE_MODEL_NAME if wave_ok else None,
        "currentModel": None,
        "source": "openmeteo",
        "day": utc_day(now),
        "issued": to_iso(now.replace(minute=0, second=0, microsecond=0)),
        "cycle": to_iso(last_ready_cycle(now)),
        "products": products,
        "queries": queries,
        "query": queries[0]["query"],
        "around": around,
        "nextDownloadAt": around.get("nextDownloadAt") or to_iso(dest_eta_at_next_download(now)),
        "samples": samples,
    }


def refresh_latest(voyage_id: str, around: dict, when: Optional[datetime] = None) -> Dict[str, Any]:
    payload = fetch_latest_payload(around, when)
    return ingest_daily(voyage_id, payload, around=around)


def maybe_refresh_official(
    voyage_id: str,
    around: Optional[dict],
    when: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    if not around or around.get("lat") is None:
        return load_latest(voyage_id)
    now = when or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    latest = load_latest(voyage_id)
    if not auto_enabled():
        return latest
    prev = _last_try.get(voyage_id)
    if prev and (now - prev).total_seconds() < STALE_RETRY_S and latest and not is_stale(latest, now):
        return latest
    if latest and not is_stale(latest, now):
        return latest
    _last_try[voyage_id] = now
    try:
        return refresh_latest(voyage_id, around, now)
    except Exception as exc:
        log.warning("refresh GRIB officiel: %s", exc)
        return latest
