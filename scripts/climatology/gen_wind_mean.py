#!/usr/bin/env python3
"""Vent AVERAGE mensuel depuis WIND_GLO_PHY_CLIMATE_L4_MY_012_003.

Ce n'est PAS une rose MOST_LIKELY. Overlay V0 : une flèche par maille
(moyenne 1994–2020 de ``eastward_wind`` / ``northward_wind``). Les roses
8 secteurs restent le travail de ``gen_wind_atlas.py`` (MY 6 h).
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
PRODUCT = "WIND_GLO_PHY_CLIMATE_L4_MY_012_003"
DATASET = "cmems_obs-wind_glo_phy_my_l4_P1M"
PERIOD = "1994-2020"
# Citer le product ID. Le DOI CMEMS de 012_003 n'est pas recopié ici
# tant qu'il n'est pas lu depuis la fiche produit.
DOI = None


def _subsample(ds, spacing: float, native: float = 0.25):
    if spacing <= native:
        return ds
    step = max(1, int(round(spacing / native)))
    lat_name = "latitude" if "latitude" in ds.dims else "lat"
    lon_name = "longitude" if "longitude" in ds.dims else "lon"
    return ds.isel({lat_name: slice(None, None, step), lon_name: slice(None, None, step)})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", type=int, default=None)
    ap.add_argument("--year-start", type=int, default=1994)
    ap.add_argument("--year-end", type=int, default=2020)
    ap.add_argument("--spacing", type=float, default=0.5)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    try:
        import numpy as np
    except ImportError as exc:
        raise SystemExit("Prérequis : numpy xarray netCDF4 copernicusmarine") from exc

    args.out.mkdir(parents=True, exist_ok=True)
    print("open", DATASET, file=sys.stderr)
    ds = open_dataset(
        dataset_id=DATASET,
        variables=["eastward_wind", "northward_wind"],
        start_datetime=f"{args.year_start}-01-01T00:00:00",
        end_datetime=f"{args.year_end}-12-31T23:59:59",
    )
    ds = _subsample(ds, args.spacing)
    u_name = "eastward_wind" if "eastward_wind" in ds else "u10"
    v_name = "northward_wind" if "northward_wind" in ds else "v10"
    lat_name = "latitude" if "latitude" in ds.coords else "lat"
    lon_name = "longitude" if "longitude" in ds.coords else "lon"
    months = range(1, 13) if args.month is None else [args.month]
    time_months = ds["time"].dt.month
    for month in months:
        sl = ds.sel(time=time_months == month)
        n_times = int(sl.sizes.get("time", 0))
        if n_times < 5:
            raise SystemExit(f"trop peu de pas de temps pour le mois {month}: {n_times}")
        u = sl[u_name].mean("time").values.astype("float32")
        v = sl[v_name].mean("time").values.astype("float32")
        finite = np.isfinite(u) & np.isfinite(v)
        sample = np.isfinite(sl[u_name].values).sum(axis=0).astype("int32")
        lats = sl[lat_name].values.astype("float32")
        lons = sl[lon_name].values.astype("float32")
        dest = args.out / f"wind-{month:02d}.npz"
        np.savez_compressed(
            dest,
            lats=lats,
            lons=lons,
            u_mean=u,
            v_mean=v,
            sea_mask=finite,
            sample_count=sample,
            stat=np.array(["average"]),
        )
        sidecar = {
            "kind": "climatology",
            "month": month,
            "period": PERIOD,
            "source_ids": [PRODUCT],
            "doi": DOI,
            "dataset": DATASET,
            "stat": "average",
            "note": "V0 AVERAGE arrows — not a rose. Roses need gen_wind_atlas.py (6 h MY).",
            "grid_spacing_deg": args.spacing,
            "years": f"{args.year_start}-{args.year_end}",
            "n_months_used": n_times,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        (args.out / f"wind-{month:02d}.atlas.json").write_text(
            json.dumps(sidecar, indent=2), encoding="utf-8"
        )
        print("wrote", dest, "stat=average n=", n_times)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
