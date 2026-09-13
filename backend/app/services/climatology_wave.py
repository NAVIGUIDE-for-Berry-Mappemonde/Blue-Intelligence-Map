"""Houle mensuelle P50 / P90 (WAVERYS). Interdit de labeller une moyenne P90."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.services.climatology_common import (
    KIND,
    LICENSE_CMEMS,
    SOURCE_IDS,
    WAVE_PERIOD,
    climatology_dir,
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


def wave_dir() -> Path:
    return climatology_dir() / "wave"


def wave_npz_path(month: int) -> Path:
    return wave_dir() / f"wave-{int(month):02d}.npz"


def has_snapshot(month: int | None = None) -> bool:
    if month is None:
        return wave_npz_path(1).is_file()
    return wave_npz_path(month).is_file()


@lru_cache(maxsize=12)
def _load_month(month: int):
    if np is None:
        return None
    path = wave_npz_path(month)
    if not path.is_file():
        return None
    data = np.load(path, allow_pickle=False)
    return {k: data[k] for k in data.files}


def _nearest_index(arr, value) -> int:
    return int(abs(arr - value).argmin())


def wave_at(lat: float, lon: float, month: int) -> dict | None:
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
    p50 = bundle.get("hs_p50")
    p90 = bundle.get("hs_p90")
    mean = bundle.get("hs_mean")
    if p50 is None and mean is None:
        return None
    def _val(arr):
        if arr is None:
            return None
        v = float(arr[i, j])
        if np is not None and np.isnan(v):
            return None
        return v

    hs_p50 = _val(p50)
    hs_p90 = _val(p90)
    hs_mean = _val(mean)
    # Un snapshot V0 (P1M mean) n'a pas le droit de s'appeler P90.
    stat = str(bundle["stat"][0]) if "stat" in bundle else (
        "p50_p90" if hs_p90 is not None else "mean"
    )
    if stat == "mean":
        if hs_mean is None:
            return None
        return {
            "hs_p50_m": None,
            "hs_p90_m": None,
            "hs_mean_m": round(hs_mean, 2),
            "period_s": _round(_val(bundle.get("period"))),
            "dir_deg": _round(_val(bundle.get("dir"))),
            "stat": "mean",
            "period": WAVE_PERIOD,
        }
    if hs_p50 is None:
        return None
    if hs_p90 is not None and hs_p90 < hs_p50:
        hs_p90 = hs_p50
    return {
        "hs_p50_m": round(hs_p50, 2),
        "hs_p90_m": None if hs_p90 is None else round(hs_p90, 2),
        "hs_mean_m": None,
        "period_s": _round(_val(bundle.get("period"))),
        "dir_deg": _round(_val(bundle.get("dir"))),
        "stat": "p50_p90",
        "period": WAVE_PERIOD,
    }


def _round(v):
    return None if v is None else round(float(v), 1)


def is_wave_hazard(lat: float, lon: float, month: int) -> bool | None:
    """True si Hs P90 > seuil. ``None`` si le P90 n'est pas disponible (pas un mean déguisé)."""
    w = wave_at(lat, lon, month)
    if not w or w.get("stat") != "p50_p90" or w.get("hs_p90_m") is None:
        return None
    nogo = float(rule("climatology.wave_nogo_m", 2.5))
    return w["hs_p90_m"] > nogo


def wave_geojson(month: int, stat: str = "p90", spacing_deg: float = 1.0) -> dict:
    month = parse_month(month)
    want = (stat or "p90").lower()
    if want not in ("p50", "p90", "mean"):
        want = "p90"
    spacing = max(0.5, min(4.0, float(spacing_deg)))
    features: list[dict] = []
    snapshot_stat = None
    if np is not None and has_snapshot(month):
        bundle = _load_month(month)
        if bundle is not None:
            snapshot_stat = str(bundle["stat"][0]) if "stat" in bundle else None
            lats, lons = bundle["lats"], bundle["lons"]
            step = max(1, int(round(spacing / max(0.25, float(abs(lats[1] - lats[0]) if len(lats) > 1 else 0.5)))))
            field_name = {
                "p50": "hs_p50",
                "p90": "hs_p90",
                "mean": "hs_mean",
            }[want]
            # Jamais servir une moyenne sous le nom P90.
            if want == "p90" and (field_name not in bundle or snapshot_stat == "mean"):
                field_name = None
            arr = bundle.get(field_name) if field_name else None
            if arr is not None:
                for i in range(0, len(lats), step):
                    for j in range(0, len(lons), step):
                        lat, lon = float(lats[i]), float(lons[j])
                        if is_land(lat, lon):
                            continue
                        v = float(arr[i, j])
                        if np.isnan(v) or v <= 0:
                            continue
                        features.append({
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [round(lon, 4), round(lat, 4)]},
                            "properties": {
                                "kind": KIND,
                                "month": month,
                                "stat": want if want != "p90" or snapshot_stat != "mean" else "mean",
                                "hs_m": round(v, 2),
                            },
                        })
    return {
        "type": "FeatureCollection",
        "features": features,
        "attribution": f"{LICENSE_CMEMS} · {product_meta('wave')['provenance']}",
        "_climatology": {
            "kind": KIND,
            "month": month,
            "period": WAVE_PERIOD,
            "source_ids": [SOURCE_IDS["wave"]],
            "doi": product_meta("wave")["doi"],
            "grid_spacing_deg": spacing,
            "snapshot_present": has_snapshot(month),
            "stat": want,
            "snapshot_stat": snapshot_stat,
        },
    }
