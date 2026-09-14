#!/usr/bin/env python3
"""Trait de côte MNDWI à partir d'un L2R ACOLITE (Mac, env acolite).

N'invente aucune profondeur. Sortie : GeoJSON brut (pas encore tamponné).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from corridor import default_bbox  # noqa: E402

GREEN_HINTS = ("561", "560", "559")
SWIR_HINTS = ("1612", "1614", "1610", "1613")


def pick_band(names: list[str], hints: tuple[str, ...]) -> str | None:
    for name in names:
        if any(h in name for h in hints):
            return name
    return None


def as_float(raw) -> np.ndarray:
    if hasattr(raw, "filled"):
        return np.array(raw.filled(np.nan), dtype=float)
    return np.array(raw, dtype=float)


def ensure_2d(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if lon.ndim == 1 and lat.ndim == 1:
        return np.meshgrid(lon, lat)
    if lon.shape != lat.shape:
        raise SystemExit("lon et lat n'ont pas la même forme")
    return lon, lat


def mndwi(green: np.ndarray, swir: np.ndarray) -> np.ndarray:
    den = green + swir
    out = np.full(green.shape, np.nan, dtype=float)
    ok = np.isfinite(den) & (np.abs(den) > 1e-8)
    out[ok] = (green[ok] - swir[ok]) / den[ok]
    return out


def crop_to_bbox(
    lon: np.ndarray,
    lat: np.ndarray,
    z: np.ndarray,
    bbox: list[float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    west, south, east, north = bbox
    inside = (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)
    if not np.any(inside):
        raise SystemExit("aucun pixel dans l'emprise La Rochelle")
    rows, cols = np.where(inside)
    sl = np.s_[rows.min() : rows.max() + 1, cols.min() : cols.max() + 1]
    return lon[sl], lat[sl], z[sl]


def downsample(lon: np.ndarray, lat: np.ndarray, z: np.ndarray, max_side: int = 900):
    ny, nx = z.shape
    step = max(1, int(np.ceil(max(ny, nx) / max_side)))
    if step == 1:
        return lon, lat, z
    return lon[::step, ::step], lat[::step, ::step], z[::step, ::step]


def _crossing(p0, p1, v0, v1) -> tuple[float, float]:
    t = 0.5 if v1 == v0 else v0 / (v0 - v1)
    t = min(1.0, max(0.0, float(t)))
    return (p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1]))


def zero_segments(lon: np.ndarray, lat: np.ndarray, z: np.ndarray):
    """Segments du contour 0 (eau / terre), cellules 2×2."""
    segs = []
    ny, nx = z.shape
    for i in range(ny - 1):
        for j in range(nx - 1):
            corners = ((i, j), (i, j + 1), (i + 1, j + 1), (i + 1, j))
            vals = [z[r, c] for r, c in corners]
            if not all(np.isfinite(v) for v in vals):
                continue
            pts = []
            for a in range(4):
                b = (a + 1) % 4
                va, vb = vals[a], vals[b]
                r0, c0 = corners[a]
                p0 = (float(lon[r0, c0]), float(lat[r0, c0]))
                if va == 0:
                    pts.append(p0)
                    continue
                if va * vb < 0:
                    r1, c1 = corners[b]
                    p1 = (float(lon[r1, c1]), float(lat[r1, c1]))
                    pts.append(_crossing(p0, p1, va, vb))
            if len(pts) >= 2:
                segs.append((pts[0], pts[1]))
            if len(pts) >= 4:
                segs.append((pts[2], pts[3]))
    return segs


def stitch(segs, min_pts: int = 12) -> list[list[list[float]]]:
    def key(p, nd=6):
        return (round(p[0], nd), round(p[1], nd))

    adj = defaultdict(list)
    for i, (a, b) in enumerate(segs):
        adj[key(a)].append((i, 0))
        adj[key(b)].append((i, 1))
    used = [False] * len(segs)
    lines = []
    for i, (a, b) in enumerate(segs):
        if used[i]:
            continue
        used[i] = True
        line = [a, b]
        for start in (False, True):
            while True:
                k = key(line[0] if start else line[-1])
                found = False
                for j, end in adj[k]:
                    if used[j]:
                        continue
                    used[j] = True
                    p0, p1 = segs[j]
                    other = p1 if end == 0 else p0
                    if start:
                        line.insert(0, other)
                    else:
                        line.append(other)
                    found = True
                    break
                if not found:
                    break
        if len(line) >= min_pts:
            lines.append([[float(x), float(y)] for x, y in line])
    return lines


def lines_to_geojson(lines: list[list[list[float]]], props: dict) -> dict:
    feats = []
    for i, coords in enumerate(lines):
        item_props = dict(props)
        item_props["id"] = f"mndwi-{i}"
        feats.append({
            "type": "Feature",
            "properties": item_props,
            "geometry": {"type": "LineString", "coordinates": coords},
        })
    return {"type": "FeatureCollection", "features": feats}


def find_l2r(path: Path) -> Path:
    if path.is_file():
        return path
    files = sorted(path.glob("*L2R*.nc"))
    if not files:
        raise SystemExit(f"aucun L2R.nc dans {path}")
    return files[0]


def load_l2r(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, str, str]:
    try:
        from netCDF4 import Dataset
    except ImportError as exc:
        raise SystemExit("netCDF4 manquant : conda activate acolite") from exc
    ds = Dataset(path)
    try:
        names = list(ds.variables)
        green_name = pick_band(names, GREEN_HINTS)
        swir_name = pick_band(names, SWIR_HINTS)
        if not green_name or not swir_name:
            raise SystemExit(f"bandes vert/SWIR introuvables dans {names}")
        lon_name = "lon" if "lon" in ds.variables else "longitude"
        lat_name = "lat" if "lat" in ds.variables else "latitude"
        if lon_name not in ds.variables or lat_name not in ds.variables:
            raise SystemExit("pas de lon/lat dans le L2R")
        lon, lat = ensure_2d(as_float(ds[lon_name][:]), as_float(ds[lat_name][:]))
        green = as_float(ds[green_name][:])
        swir = as_float(ds[swir_name][:])
    finally:
        ds.close()
    if green.shape != lon.shape:
        raise SystemExit("la bande et lon/lat n'ont pas la même taille")
    return lon, lat, mndwi(green, swir), green_name, swir_name


def extract_lines(lon, lat, z, bbox: list[float]) -> list[list[list[float]]]:
    lon, lat, z = crop_to_bbox(lon, lat, z, bbox)
    lon, lat, z = downsample(lon, lat, z)
    return stitch(zero_segments(lon, lat, z))


def main() -> int:
    p = argparse.ArgumentParser(description="Trait de côte MNDWI (L2R ACOLITE)")
    p.add_argument(
        "--in",
        dest="src",
        type=Path,
        default=Path.home() / "Desktop" / "sentinel-pilot" / "acolite",
    )
    p.add_argument(
        "--out",
        dest="dst",
        type=Path,
        default=Path.home() / "Desktop" / "sentinel-pilot" / "coastline-raw.geojson",
    )
    args = p.parse_args()
    nc = find_l2r(args.src)
    lon, lat, z, green_name, swir_name = load_l2r(nc)
    bbox = default_bbox()
    lines = extract_lines(lon, lat, z, bbox)
    if not lines:
        print("aucun trait de côte (seuil 0)", file=sys.stderr)
        return 1
    props = {
        "method": "mndwi",
        "green": green_name,
        "swir": swir_name,
        "l2r": nc.name,
    }
    fc = lines_to_geojson(lines, props)
    args.dst.parent.mkdir(parents=True, exist_ok=True)
    args.dst.write_text(json.dumps(fc, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(lines)} ligne(s) → {args.dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
