#!/usr/bin/env python3
"""WAVERYS climatology_P1M-m → wave-MM.npz avec stat: mean.

Ce n'est PAS un P90. Overlay V0 seulement.
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
OUT = ROOT / "backend" / "data" / "climatology" / "wave"
PRODUCT = "GLOBAL_MULTIYEAR_WAV_001_032"
DATASET = "cmems_mod_glo_wav_my_0.2deg-climatology_P1M-m"
PERIOD = "1993-2019"
DOI = "10.48670/moi-00022"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", type=int, default=None)
    ap.add_argument("--spacing", type=float, default=0.4, help="maille stockée (°)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    try:
        import numpy as np
    except ImportError as exc:
        raise SystemExit("Prérequis : copernicusmarine xarray netCDF4 numpy") from exc

    args.out.mkdir(parents=True, exist_ok=True)
    # Le P1M climatologique n'a pas VMDR (direction) — on n'invente pas.
    ds = open_dataset(
        dataset_id=DATASET,
        variables=["VHM0", "VTM02"],
    )
    if args.spacing > 0.2:
        step = max(1, int(round(args.spacing / 0.2)))
        lat_name = "latitude" if "latitude" in ds.dims else "lat"
        lon_name = "longitude" if "longitude" in ds.dims else "lon"
        ds = ds.isel({lat_name: slice(None, None, step), lon_name: slice(None, None, step)})
    time_name = "time" if "time" in ds.dims else "month"
    months = range(1, 13) if args.month is None else [args.month]
    for month in months:
        sl = ds.isel({time_name: month - 1})
        hs = sl["VHM0"].values.astype("float32")
        period = sl["VTM02"].values.astype("float32")
        lats = sl["latitude"].values.astype("float32")
        lons = sl["longitude"].values.astype("float32")
        sea = ~np.isnan(hs)
        dest = args.out / f"wave-{month:02d}.npz"
        np.savez_compressed(
            dest,
            lats=lats, lons=lons,
            hs_mean=hs, period=period,
            sea_mask=sea,
            stat=np.array(["mean"]),
        )
        (args.out / f"wave-{month:02d}.json").write_text(json.dumps({
            "kind": "climatology",
            "month": month,
            "period": PERIOD,
            "source_ids": [PRODUCT],
            "doi": DOI,
            "stat": "mean",
            "note": "V0 mean overlay — not a P90. Direction absent from P1M climatology.",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }, indent=2), encoding="utf-8")
        print("wrote", dest, "stat=mean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
