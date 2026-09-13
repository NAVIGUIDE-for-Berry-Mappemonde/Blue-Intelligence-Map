"""Atlas de vent mensuel (roses 8 secteurs) — snapshot CMEMS MY, pas NRT.

Tant que ``wind-MM.npz`` manque, on renvoie ``None`` (pas un vent inventé).
Le repli zones de ``climatology.py`` (NAVIGUIDE) n'est **pas** servi ici.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.climatology_common import (
    KIND,
    LICENSE_CMEMS,
    SECTOR_DEG,
    SECTORS,
    SOURCE_IDS,
    WIND_PERIOD,
    climatology_dir,
    is_land,
    parse_month,
    product_meta,
    rule,
    sector_index,
    wind_from_uv,
    wrap_lon,
)

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None  # type: ignore


def wind_dir() -> Path:
    return climatology_dir() / "wind"


def wind_npz_path(month: int) -> Path:
    return wind_dir() / f"wind-{int(month):02d}.npz"


def has_snapshot(month: int | None = None) -> bool:
    if month is None:
        return wind_npz_path(1).is_file()
    return wind_npz_path(month).is_file()


@lru_cache(maxsize=12)
def _load_month(month: int):
    if np is None:
        return None
    path = wind_npz_path(month)
    if not path.is_file():
        return None
    data = np.load(path, allow_pickle=False)
    return {k: data[k] for k in data.files}


def _nearest_index(arr, value) -> int:
    return int(abs(arr - value).argmin())


def _sample_cell(bundle: dict, lat: float, lon: float) -> dict | None:
    lats = bundle["lats"]
    lons = bundle["lons"]
    lon = wrap_lon(lon)
    i = _nearest_index(lats, lat)
    j = _nearest_index(lons, lon)
    # Refus si la maille est trop loin (terre / trou / hors grille)
    if abs(float(lats[i]) - lat) > 0.75 or abs(wrap_lon(float(lons[j]) - lon)) > 0.75:
        return None
    count = bundle.get("sample_count")
    if count is not None:
        n = int(count[i, j])
        if n <= 0:
            return None
    else:
        n = None
    sea = bundle.get("sea_mask")
    if sea is not None and not bool(sea[i, j]):
        return None
    pct = [float(x) for x in bundle["sector_pct"][i, j]]
    spd = [float(x) for x in bundle["sector_spd"][i, j]]
    if all(p <= 0 for p in pct) and (n is None or n == 0):
        return None
    return {
        "pct": pct,
        "spd": spd,
        "calm_pct": float(bundle["calm_pct"][i, j]),
        "gale_pct": float(bundle["gale_pct"][i, j]),
        "u_mean": float(bundle["u_mean"][i, j]),
        "v_mean": float(bundle["v_mean"][i, j]),
        "sample_count": n,
    }


def _rose_from_cell(cell: dict) -> dict:
    min_pct = float(rule("climatology.wind_min_sector_pct", 2.5))
    directions = []
    for k, (pct, spd) in enumerate(zip(cell["pct"], cell["spd"])):
        if pct < min_pct:
            continue
        directions.append({
            "dir_deg": int(k * SECTOR_DEG),
            "pct": round(pct, 1),
            "speed_knots": round(spd, 1),
        })
    if not directions:
        return None
    dominant = max(directions, key=lambda d: (d["pct"], d["speed_knots"]))
    mean_kn, mean_from = wind_from_uv(cell["u_mean"], cell["v_mean"])
    return {
        "sectors_deg": SECTOR_DEG,
        "directions_from": directions,
        "calm_pct": round(cell["calm_pct"], 1),
        "gale_pct": round(cell["gale_pct"], 1),
        "most_likely": {
            "dir_deg": dominant["dir_deg"],
            "speed_knots": dominant["speed_knots"],
        },
        "vector_mean": {
            "dir_deg": round(mean_from, 1),
            "speed_knots": round(mean_kn, 1),
        },
        "sample_count": cell["sample_count"],
    }


def atlas_at(lat: float, lon: float, month: int) -> dict | None:
    """Rose au point, ou ``None`` (terre, NaN, snapshot absent, échantillon pauvre)."""
    month = parse_month(month)
    if is_land(lat, lon):
        return None
    bundle = _load_month(month)
    if bundle is None:
        return None
    cell = _sample_cell(bundle, lat, lon)
    if cell is None:
        return None
    return _rose_from_cell(cell)


def wind_at(lat: float, lon: float, month: int, mode: str = "most_likely") -> tuple[float, float] | None:
    """(kn, dir_from) depuis l'atlas. ``None`` si la grille manque — pas le repli zones."""
    rose = atlas_at(lat, lon, month)
    if not rose:
        return None
    key = "vector_mean" if mode == "average" else "most_likely"
    block = rose[key]
    return float(block["speed_knots"]), float(block["dir_deg"])


def wind_geojson(month: int, spacing_deg: float = 1.0) -> dict:
    """Points MOST_LIKELY pour le pane vectoriel. Collection vide si snapshot absent."""
    month = parse_month(month)
    spacing = max(0.5, min(4.0, float(spacing_deg)))
    features: list[dict] = []
    if np is not None and has_snapshot(month):
        bundle = _load_month(month)
        if bundle is not None:
            lats = bundle["lats"]
            lons = bundle["lons"]
            step = max(1, int(round(spacing / max(0.25, float(abs(lats[1] - lats[0]) if len(lats) > 1 else 0.5)))))
            for i in range(0, len(lats), step):
                for j in range(0, len(lons), step):
                    lat = float(lats[i])
                    lon = float(lons[j])
                    if is_land(lat, lon):
                        continue
                    cell = _sample_cell(bundle, lat, lon)
                    if cell is None:
                        continue
                    rose = _rose_from_cell(cell)
                    if not rose:
                        continue
                    ml = rose["most_likely"]
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [round(lon, 4), round(lat, 4)]},
                        "properties": {
                            "kind": KIND,
                            "month": month,
                            "wind_speed_knots": ml["speed_knots"],
                            "wind_direction_from_deg": ml["dir_deg"],
                            "calm_pct": rose["calm_pct"],
                            "gale_pct": rose["gale_pct"],
                            "sample_count": rose["sample_count"],
                            "vector_mean_knots": rose["vector_mean"]["speed_knots"],
                            "vector_mean_from_deg": rose["vector_mean"]["dir_deg"],
                            "directions_from": rose["directions_from"],
                        },
                    })
    meta_extra = {
        "kind": KIND,
        "month": month,
        "period": WIND_PERIOD,
        "source_ids": [SOURCE_IDS["wind"]],
        "doi": product_meta("wind")["doi"],
        "grid_spacing_deg": spacing,
        "snapshot_present": has_snapshot(month),
        "stat": "most_likely",
    }
    return {
        "type": "FeatureCollection",
        "features": features,
        "attribution": f"{LICENSE_CMEMS} · {product_meta('wind')['provenance']}",
        "_climatology": meta_extra,
    }


def atlas_sidecar(month: int) -> dict[str, Any] | None:
    path = wind_dir() / f"wind-{int(month):02d}.atlas.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
