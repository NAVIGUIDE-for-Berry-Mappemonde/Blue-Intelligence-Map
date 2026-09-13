#!/usr/bin/env python3
"""GLORYS12 climatology_P1M-m → current-MM.npz (surface uo/vo).

À lancer sur le Mac (`copernicusmarine login`). Un subset surface, 12 pas.
Jamais le cube 3D en RAM.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "backend" / "data" / "climatology" / "current"

PRODUCT = "GLOBAL_MULTIYEAR_PHY_001_030"
DATASET = "cmems_mod_glo_phy_my_0.083deg-climatology_P1M-m"
PERIOD = "1993-2016"
DOI = "10.48670/moi-00021"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--spacing", type=float, default=0.25, help="maille stockée (°)")
    args = ap.parse_args()
    try:
        import copernicusmarine
        import numpy as np
        import xarray as xr
    except ImportError as exc:
        raise SystemExit(
            "Prérequis Mac : pip install copernicusmarine xarray netCDF4 numpy"
        ) from exc

    args.out.mkdir(parents=True, exist_ok=True)
    print("subset", DATASET, file=__import__("sys").stderr)
    ds = copernicusmarine.open_dataset(
        dataset_id=DATASET,
        variables=["uo", "vo"],
        minimum_depth=0.0,
        maximum_depth=1.0,
    )
    # Premier niveau ~0,494 m
    if "depth" in ds.dims:
        ds = ds.isel(depth=0)
    if args.spacing > 0.083:
        step = max(1, int(round(args.spacing / 0.083)))
        ds = ds.isel(latitude=slice(None, None, step), longitude=slice(None, None, step))

    time_name = "time" if "time" in ds.dims else "month"
    n = int(ds.sizes[time_name])
    for i in range(min(12, n)):
        sl = ds.isel({time_name: i})
        u = sl["uo"].values.astype("float32")
        v = sl["vo"].values.astype("float32")
        lats = sl["latitude"].values.astype("float32")
        lons = sl["longitude"].values.astype("float32")
        sea = ~(np.isnan(u) | np.isnan(v))
        month = i + 1
        dest = args.out / f"current-{month:02d}.npz"
        np.savez_compressed(dest, lats=lats, lons=lons, uo=u, vo=v, sea_mask=sea)
        meta = {
            "kind": "climatology",
            "month": month,
            "period": PERIOD,
            "source_ids": [PRODUCT],
            "doi": DOI,
            "dataset": DATASET,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        (args.out / f"current-{month:02d}.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        print("wrote", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
