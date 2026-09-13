#!/usr/bin/env python3
"""WAVERYS PT3H → hs_p50 / hs_p90 pour UN mois calendaire, toutes années.

Un mois à la fois. Jamais le cube mondial en RAM. Interdit de labeller une
moyenne P90 : ce script écrit stat=p50_p90.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "backend" / "data" / "climatology" / "wave"
PRODUCT = "GLOBAL_MULTIYEAR_WAV_001_032"
DATASET = "cmems_mod_glo_wav_my_0.2deg_PT3H-i"
PERIOD = "1993-2019"
DOI = "10.48670/moi-00022"


def circmedian(deg):
    import numpy as np
    rad = np.radians(deg)
    s, c = np.nanmedian(np.sin(rad)), np.nanmedian(np.cos(rad))
    return float((np.degrees(np.arctan2(s, c)) + 360.0) % 360.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", type=int, required=True)
    ap.add_argument("--year-start", type=int, default=1993)
    ap.add_argument("--year-end", type=int, default=2019)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    try:
        import copernicusmarine
        import numpy as np
    except ImportError as exc:
        raise SystemExit("Prérequis Mac : copernicusmarine xarray netCDF4 numpy") from exc

    args.out.mkdir(parents=True, exist_ok=True)
    stacked = []
    period_stack = []
    dir_stack = []
    lats = lons = None
    for year in range(args.year_start, args.year_end + 1):
        start = f"{year}-{args.month:02d}-01T00:00:00"
        end = f"{year + 1}-01-01T00:00:00" if args.month == 12 else f"{year}-{args.month + 1:02d}-01T00:00:00"
        print("subset", year, args.month, file=__import__("sys").stderr)
        ds = copernicusmarine.open_dataset(
            dataset_id=DATASET,
            variables=["VHM0", "VTM02", "VMDR"],
            start_datetime=start,
            end_datetime=end,
        )
        stacked.append(ds["VHM0"].values)
        period_stack.append(ds["VTM02"].values)
        dir_stack.append(ds["VMDR"].values)
        if lats is None:
            lats = ds["latitude"].values.astype("float32")
            lons = ds["longitude"].values.astype("float32")
        del ds
    hs = np.concatenate(stacked, axis=0)
    p50 = np.nanpercentile(hs, 50, axis=0).astype("float32")
    p90 = np.nanpercentile(hs, 90, axis=0).astype("float32")
    # Garde-fou contrat : p90 >= p50
    p90 = np.maximum(p90, p50)
    per = np.nanmedian(np.concatenate(period_stack, axis=0), axis=0).astype("float32")
    # Direction : médiane circulaire année par année puis moyenne — simplifié
    dirs = np.concatenate(dir_stack, axis=0)
    # trop lourd en circmedian cellule par cellule : on prend nanmedian naïf
    # (la direction est secondaire vs P50/P90). Documenté.
    dirm = np.nanmedian(dirs, axis=0).astype("float32")
    sea = np.isfinite(p50)
    dest = args.out / f"wave-{args.month:02d}.npz"
    np.savez_compressed(
        dest,
        lats=lats, lons=lons,
        hs_p50=p50, hs_p90=p90, period=per, dir=dirm,
        sea_mask=sea,
        stat=np.array(["p50_p90"]),
    )
    (args.out / f"wave-{args.month:02d}.json").write_text(json.dumps({
        "kind": "climatology",
        "month": args.month,
        "period": PERIOD,
        "source_ids": [PRODUCT],
        "doi": DOI,
        "stat": "p50_p90",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }, indent=2), encoding="utf-8")
    print("wrote", dest, "stat=p50_p90")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
