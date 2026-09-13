"""Courant de surface mensuel (GLORYS12 climatology_P1M-m)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.services.climatology_common import (
    KIND,
    LICENSE_CMEMS,
    SOURCE_IDS,
    CURRENT_PERIOD,
    climatology_dir,
    current_to_uv,
    is_land,
    parse_month,
    product_meta,
    rule,
    wrap_lon,
)

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None  # type: ignore


def current_dir() -> Path:
    return climatology_dir() / "current"


def current_npz_path(month: int) -> Path:
    return current_dir() / f"current-{int(month):02d}.npz"


def has_snapshot(month: int | None = None) -> bool:
    if month is None:
        return current_npz_path(1).is_file()
    return current_npz_path(month).is_file()


@lru_cache(maxsize=12)
def _load_month(month: int):
    if np is None:
        return None
    path = current_npz_path(month)
    if not path.is_file():
        return None
    data = np.load(path, allow_pickle=False)
    return {k: data[k] for k in data.files}


def _nearest_index(arr, value) -> int:
    return int(abs(arr - value).argmin())


def current_at(lat: float, lon: float, month: int) -> dict | None:
    month = parse_month(month)
    if is_land(lat, lon):
        return None
    bundle = _load_month(month)
    if bundle is None:
        return None
    lats, lons = bundle["lats"], bundle["lons"]
    lon = wrap_lon(lon)
    i, j = _nearest_index(lats, lat), _nearest_index(lons, lon)
    if abs(float(lats[i]) - lat) > 0.75 or abs(wrap_lon(float(lons[j]) - lon)) > 0.75:
        return None
    sea = bundle.get("sea_mask")
    if sea is not None and not bool(sea[i, j]):
        return None
    u = float(bundle["uo"][i, j])
    v = float(bundle["vo"][i, j])
    if np is not None and (np.isnan(u) or np.isnan(v)):
        return None
    kn, to_deg = current_to_uv(u, v)
    min_kn = float(rule("climatology.current_min_kn", 0.15))
    below = kn < min_kn
    if below:
        kn, to_deg = 0.0, to_deg
    return {
        "speed_knots": round(kn, 2),
        "direction_to_deg": round(to_deg, 1),
        "below_threshold": below,
        "u_ms": round(u, 4),
        "v_ms": round(v, 4),
        "period": CURRENT_PERIOD,
        "depth_m": float(rule("climatology.current_depth_m", 0.5)),
    }


def current_geojson(month: int, spacing_deg: float = 1.0) -> dict:
    month = parse_month(month)
    spacing = max(0.5, min(4.0, float(spacing_deg)))
    features: list[dict] = []
    if np is not None and has_snapshot(month):
        bundle = _load_month(month)
        if bundle is not None:
            lats, lons = bundle["lats"], bundle["lons"]
            step = max(1, int(round(spacing / max(0.25, float(abs(lats[1] - lats[0]) if len(lats) > 1 else 0.5)))))
            for i in range(0, len(lats), step):
                for j in range(0, len(lons), step):
                    lat, lon = float(lats[i]), float(lons[j])
                    if is_land(lat, lon):
                        continue
                    rec = current_at(lat, lon, month)
                    if rec is None:
                        continue
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [round(lon, 4), round(lat, 4)]},
                        "properties": {
                            "kind": KIND,
                            "month": month,
                            "speed_knots": rec["speed_knots"],
                            "direction_to_deg": rec["direction_to_deg"],
                            "below_threshold": rec["below_threshold"],
                        },
                    })
    return {
        "type": "FeatureCollection",
        "features": features,
        "attribution": f"{LICENSE_CMEMS} · {product_meta('current')['provenance']}",
        "_climatology": {
            "kind": KIND,
            "month": month,
            "period": CURRENT_PERIOD,
            "source_ids": [SOURCE_IDS["current"]],
            "doi": product_meta("current")["doi"],
            "grid_spacing_deg": spacing,
            "snapshot_present": has_snapshot(month),
        },
    }
