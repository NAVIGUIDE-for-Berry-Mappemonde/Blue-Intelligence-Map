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


def _bundle_stat(bundle: dict) -> str:
    if "stat" in bundle:
        raw = bundle["stat"]
        try:
            return str(raw[0])
        except Exception:
            return str(raw)
    if "sector_pct" in bundle:
        return "rose"
    return "average"


def _sample_count(bundle: dict, i: int, j: int) -> int | None:
    count = bundle.get("sample_count")
    if count is None:
        return None
    ndim = getattr(count, "ndim", 2)
    if ndim == 0:
        return int(count)
    n = int(count[i, j])
    return n


def _sample_cell(bundle: dict, lat: float, lon: float) -> dict | None:
    lats = bundle["lats"]
    lons = bundle["lons"]
    lon = wrap_lon(lon)
    i = _nearest_index(lats, lat)
    j = _nearest_index(lons, lon)
    # Refus si la maille est trop loin (terre / trou / hors grille)
    if abs(float(lats[i]) - lat) > 0.75 or abs(wrap_lon(float(lons[j]) - lon)) > 0.75:
        return None
    n = _sample_count(bundle, i, j)
    if n is not None and n <= 0:
        return None
    sea = bundle.get("sea_mask")
    if sea is not None and not bool(sea[i, j]):
        return None
    u = float(bundle["u_mean"][i, j])
    v = float(bundle["v_mean"][i, j])
    if np is not None and (np.isnan(u) or np.isnan(v)):
        return None
    stat = _bundle_stat(bundle)
    if stat == "average" or "sector_pct" not in bundle:
        return {
            "stat": "average",
            "pct": None,
            "spd": None,
            "calm_pct": None,
            "gale_pct": None,
            "u_mean": u,
            "v_mean": v,
            "sample_count": n,
        }
    pct = [float(x) for x in bundle["sector_pct"][i, j]]
    spd = [float(x) for x in bundle["sector_spd"][i, j]]
    if all(p <= 0 for p in pct) and (n is None or n == 0):
        return None
    return {
        "stat": "rose",
        "pct": pct,
        "spd": spd,
        "calm_pct": float(bundle["calm_pct"][i, j]),
        "gale_pct": float(bundle["gale_pct"][i, j]),
        "u_mean": u,
        "v_mean": v,
        "sample_count": n,
    }


def _rose_from_cell(cell: dict) -> dict | None:
    mean_kn, mean_from = wind_from_uv(cell["u_mean"], cell["v_mean"])
    vector_mean = {
        "dir_deg": round(mean_from, 1),
        "speed_knots": round(mean_kn, 1),
    }
    if cell.get("stat") == "average" or cell.get("pct") is None:
        if mean_kn <= 0:
            return None
        return {
            "stat": "average",
            "sectors_deg": SECTOR_DEG,
            "directions_from": [],
            "calm_pct": None,
            "gale_pct": None,
            "most_likely": None,
            "vector_mean": vector_mean,
            "sample_count": cell["sample_count"],
        }
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
    return {
        "stat": "rose",
        "sectors_deg": SECTOR_DEG,
        "directions_from": directions,
        "calm_pct": round(cell["calm_pct"], 1),
        "gale_pct": round(cell["gale_pct"], 1),
        "most_likely": {
            "dir_deg": dominant["dir_deg"],
            "speed_knots": dominant["speed_knots"],
        },
        "vector_mean": vector_mean,
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
    """(kn, dir_from) depuis l'atlas. ``None`` si la grille manque — pas le repli zones.

    Un snapshot V0 ``stat=average`` n'a pas de MOST_LIKELY : on sert le vecteur
    moyen, sans le relabeller rose.
    """
    rose = atlas_at(lat, lon, month)
    if not rose:
        return None
    if rose.get("stat") == "average" or rose.get("most_likely") is None:
        block = rose.get("vector_mean")
    else:
        block = rose["vector_mean"] if mode == "average" else rose["most_likely"]
    if not block:
        return None
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
                    shown = rose["most_likely"] or rose["vector_mean"]
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [round(lon, 4), round(lat, 4)]},
                        "properties": {
                            "kind": KIND,
                            "month": month,
                            "stat": rose.get("stat") or "rose",
                            "wind_speed_knots": shown["speed_knots"],
                            "wind_direction_from_deg": shown["dir_deg"],
                            "calm_pct": rose["calm_pct"],
                            "gale_pct": rose["gale_pct"],
                            "sample_count": rose["sample_count"],
                            "vector_mean_knots": rose["vector_mean"]["speed_knots"],
                            "vector_mean_from_deg": rose["vector_mean"]["dir_deg"],
                            "directions_from": rose["directions_from"],
                        },
                    })
    prod = product_meta("wind")
    side = atlas_sidecar(month) or {}
    stat = side.get("stat") or ("rose" if has_snapshot(month) else None)
    meta_extra = {
        "kind": KIND,
        "month": month,
        "period": WIND_PERIOD,
        "source_ids": [prod["source_id"]],
        "doi": prod["doi"],
        "grid_spacing_deg": spacing,
        "snapshot_present": has_snapshot(month),
        "stat": stat or "most_likely",
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
