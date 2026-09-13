#!/usr/bin/env python3
"""Roses 8 secteurs depuis CMEMS wind MY L4 horaire, sous-échantillon 6 h.

Un mois calendaire × années 1994–2020. Jamais le cube mondial en RAM.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cmems_auth import open_dataset

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "backend" / "data" / "climatology" / "wind"

PRODUCT = "WIND_GLO_PHY_L4_MY_012_006"
DATASET = "cmems_obs-wind_glo_phy_my_l4_0.25deg_PT1H"
PERIOD = "1994-2020"
DOI = "10.48670/moi-00183"
MS_TO_KN = 1.94384
SECTORS = 8


def sector_index(dir_from_deg, n=SECTORS):
    step = 360.0 / n
    return int((float(dir_from_deg) + step / 2.0) % 360.0 // step)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", type=int, required=True)
    ap.add_argument("--year-start", type=int, default=1994)
    ap.add_argument("--year-end", type=int, default=2020)
    ap.add_argument("--spacing", type=float, default=0.5)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    if args.month < 1 or args.month > 12:
        raise SystemExit("month 1–12")
    try:
        import numpy as np
    except ImportError as exc:
        raise SystemExit(
            "Prérequis : pip install copernicusmarine xarray netCDF4 numpy"
        ) from exc

    args.out.mkdir(parents=True, exist_ok=True)
    # Accumulators filled after the first subset (unknown shape until then).
    acc = None
    for year in range(args.year_start, args.year_end + 1):
        start = f"{year}-{args.month:02d}-01T00:00:00"
        # Fin exclusive : mois suivant
        if args.month == 12:
            end = f"{year + 1}-01-01T00:00:00"
        else:
            end = f"{year}-{args.month + 1:02d}-01T00:00:00"
        print("subset", year, args.month, file=__import__("sys").stderr)
        ds = open_dataset(
            dataset_id=DATASET,
            variables=["eastward_wind", "northward_wind"],
            start_datetime=start,
            end_datetime=end,
        )
        # alias u/v
        u_name = "eastward_wind" if "eastward_wind" in ds else "u10"
        v_name = "northward_wind" if "northward_wind" in ds else "v10"
        # 6 h
        ds = ds.isel(time=slice(None, None, 6))
        if args.spacing > 0.25:
            step = max(1, int(round(args.spacing / 0.25)))
            lat_name = "latitude" if "latitude" in ds.dims else "lat"
            lon_name = "longitude" if "longitude" in ds.dims else "lon"
            ds = ds.isel({lat_name: slice(None, None, step), lon_name: slice(None, None, step)})
        u = ds[u_name].values
        v = ds[v_name].values
        lat_name = "latitude" if "latitude" in ds.coords else "lat"
        lon_name = "longitude" if "longitude" in ds.coords else "lon"
        lats = ds[lat_name].values.astype("float32")
        lons = ds[lon_name].values.astype("float32")
        if acc is None:
            ny, nx = u.shape[-2], u.shape[-1]
            acc = {
                "lats": lats,
                "lons": lons,
                "count": np.zeros((ny, nx), dtype="int32"),
                "calm": np.zeros((ny, nx), dtype="int32"),
                "gale": np.zeros((ny, nx), dtype="int32"),
                "sec_n": np.zeros((ny, nx, SECTORS), dtype="int32"),
                "sec_spd": np.zeros((ny, nx, SECTORS), dtype="float64"),
                "u_sum": np.zeros((ny, nx), dtype="float64"),
                "v_sum": np.zeros((ny, nx), dtype="float64"),
            }
        # u,v : (time, y, x)
        spd = np.hypot(u, v) * MS_TO_KN
        coming = (np.degrees(np.arctan2(-u, -v)) + 360.0) % 360.0
        valid = np.isfinite(spd)
        acc["count"] += valid.sum(axis=0).astype("int32")
        acc["calm"] += ((spd <= 3) & valid).sum(axis=0).astype("int32")
        acc["gale"] += ((spd >= 34) & valid).sum(axis=0).astype("int32")
        acc["u_sum"] += np.nansum(u, axis=0)
        acc["v_sum"] += np.nansum(v, axis=0)
        sec = ((coming + 22.5) % 360.0 // 45.0).astype("int16")
        for k in range(SECTORS):
            mask = valid & (sec == k)
            acc["sec_n"][:, :, k] += mask.sum(axis=0).astype("int32")
            acc["sec_spd"][:, :, k] += np.nansum(np.where(mask, spd, 0.0), axis=0)
        del ds, u, v, spd, coming

    n = np.maximum(acc["count"], 1)
    pct = acc["sec_n"] * 100.0 / n[:, :, None]
    spd_mean = np.divide(acc["sec_spd"], np.maximum(acc["sec_n"], 1), where=acc["sec_n"] > 0)
    pct[pct < 2.5] = 0.0
    sea = acc["count"] > 20
    dest = args.out / f"wind-{args.month:02d}.npz"
    np.savez_compressed(
        dest,
        lats=acc["lats"],
        lons=acc["lons"],
        sector_pct=pct.astype("float32"),
        sector_spd=spd_mean.astype("float32"),
        calm_pct=(acc["calm"] * 100.0 / n).astype("float32"),
        gale_pct=(acc["gale"] * 100.0 / n).astype("float32"),
        u_mean=(acc["u_sum"] / n).astype("float32"),
        v_mean=(acc["v_sum"] / n).astype("float32"),
        sample_count=acc["count"],
        sea_mask=sea,
    )
    sidecar = {
        "kind": "climatology",
        "month": args.month,
        "period": PERIOD,
        "source_ids": [PRODUCT],
        "doi": DOI,
        "dataset": DATASET,
        "subsample": "6h",
        "grid_spacing_deg": args.spacing,
        "years": f"{args.year_start}-{args.year_end}",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (args.out / f"wind-{args.month:02d}.atlas.json").write_text(
        json.dumps(sidecar, indent=2), encoding="utf-8"
    )
    print("wrote", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
