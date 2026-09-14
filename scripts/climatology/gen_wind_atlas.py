#!/usr/bin/env python3
"""Roses 8 secteurs depuis CMEMS wind MY L4 horaire, sous-échantillon 6 h.

Un mois calendaire × années 1994–2020. Jamais le cube mondial en RAM.
Reprise : si le Mac s'endort ou le réseau coupe, relancer la même commande
reprend l'année suivante (fichier ``wind-MM.partial.npz``).

À lancer sur le Mac (ou une grosse machine), **pas** sur le VPS 8 Go.
"""
from __future__ import annotations

import argparse
import gc
import json
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cmems_auth import login, open_dataset

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "backend" / "data" / "climatology" / "wind"

PRODUCT = "WIND_GLO_PHY_L4_MY_012_006"
# Même produit, deux jeux : 0,25° s'arrête en oct. 2009 ; 0,125° prend la suite.
DATASET_025 = "cmems_obs-wind_glo_phy_my_l4_0.25deg_PT1H"
DATASET_0125 = "cmems_obs-wind_glo_phy_my_l4_0.125deg_PT1H"
PERIOD = "1994-2020"
DOI = "10.48670/moi-00183"
MS_TO_KN = 1.94384
SECTORS = 8
ACC_KEYS = ("lats", "lons", "count", "calm", "gale", "sec_n", "sec_spd", "u_sum", "v_sum")
# CMEMS peut rester figé sur un HTTPS sans timeout ; on tue l'année et on reprend.
YEAR_TIMEOUT_S = 40 * 60


def pick_dataset(year: int, month: int) -> tuple[str, float] | None:
    """None = mois hors archive (ex. janv.–mai 1994)."""
    if (year, month) < (1994, 6):
        return None
    if (year, month) <= (2009, 10):
        return DATASET_025, 0.25
    return DATASET_0125, 0.125


def _sidecar_is_complete_rose(path: Path, year_start: int, year_end: int) -> bool:
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if data.get("stat") != "rose":
        return False
    return data.get("years") == f"{year_start}-{year_end}"


def _month_range(month: int, year: int) -> tuple[str, str]:
    start = f"{year}-{month:02d}-01T00:00:00"
    if month == 12:
        end = f"{year + 1}-01-01T00:00:00"
    else:
        end = f"{year}-{month + 1:02d}-01T00:00:00"
    return start, end


def _is_out_of_bounds(exc: BaseException) -> bool:
    name = type(exc).__name__
    return "OutOfDatasetBounds" in name or "out of bounds" in str(exc).lower()


def _open_year(month: int, year: int, spacing: float, target_lats=None, target_lons=None):
    picked = pick_dataset(year, month)
    if picked is None:
        return None
    dataset_id, native = picked
    start, end = _month_range(month, year)
    last_err = None
    for attempt in range(1, 5):
        try:
            ds = open_dataset(
                dataset_id=dataset_id,
                variables=["eastward_wind", "northward_wind"],
                start_datetime=start,
                end_datetime=end,
            )
            u_name = "eastward_wind" if "eastward_wind" in ds else "u10"
            v_name = "northward_wind" if "northward_wind" in ds else "v10"
            if "time" in ds.dims:
                ds = ds.isel(time=slice(None, None, 6))
            lat_name = "latitude" if "latitude" in ds.dims else "lat"
            lon_name = "longitude" if "longitude" in ds.dims else "lon"
            if target_lats is not None and target_lons is not None:
                ds = ds.sel({lat_name: target_lats, lon_name: target_lons}, method="nearest")
            elif spacing > native:
                step = max(1, int(round(spacing / native)))
                ds = ds.isel({lat_name: slice(None, None, step), lon_name: slice(None, None, step)})
            return ds, u_name, v_name, dataset_id
        except Exception as exc:
            if _is_out_of_bounds(exc):
                print(f"  skip {year}-{month:02d} hors archive ({dataset_id})", file=sys.stderr)
                return None
            last_err = exc
            wait = 4 * (2 ** (attempt - 1))
            print(f"  retry {attempt}/4 dans {wait}s ({type(exc).__name__})", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"échec subset {year}-{month:02d}") from last_err


def _new_acc(u, lats, lons):
    import numpy as np

    ny, nx = u.shape[-2], u.shape[-1]
    return {
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


def _save_partial(path: Path, acc: dict, year_next: int) -> None:
    import numpy as np

    np.savez_compressed(path, year_next=np.int32(year_next), **acc)


def _load_partial(path: Path) -> tuple[dict, int] | None:
    import numpy as np

    if not path.is_file():
        return None
    try:
        data = np.load(path, allow_pickle=False)
        year_next = int(data["year_next"])
        acc = {k: data[k].copy() for k in ACC_KEYS}
    except Exception:
        return None
    return acc, year_next


def _accumulate(acc: dict, u, v) -> None:
    import numpy as np

    spd = np.hypot(u, v) * MS_TO_KN
    coming = (np.degrees(np.arctan2(-u, -v)) + 360.0) % 360.0
    valid = np.isfinite(spd)
    acc["count"] += valid.sum(axis=0).astype("int32")
    acc["calm"] += ((spd <= 3) & valid).sum(axis=0).astype("int32")
    acc["gale"] += ((spd >= 34) & valid).sum(axis=0).astype("int32")
    acc["u_sum"] += np.nansum(u, axis=0)
    acc["v_sum"] += np.nansum(v, axis=0)
    sec = np.zeros(coming.shape, dtype="int16")
    finite_dir = np.isfinite(coming)
    sec[finite_dir] = ((coming[finite_dir] + 22.5) % 360.0 // 45.0).astype("int16")
    for k in range(SECTORS):
        mask = valid & (sec == k)
        acc["sec_n"][:, :, k] += mask.sum(axis=0).astype("int32")
        acc["sec_spd"][:, :, k] += np.nansum(np.where(mask, spd, 0.0), axis=0)


def process_one_year(month: int, year: int, spacing: float, out: Path) -> None:
    """Une année seulement — processus fils, tuable si CMEMS se fige."""
    import numpy as np

    socket.setdefaulttimeout(180)
    partial = out / f"wind-{month:02d}.partial.npz"
    loaded = _load_partial(partial)
    acc = loaded[0] if loaded else None
    picked = pick_dataset(year, month)
    label = picked[0] if picked else "skip"
    print(f"mois {month:02d}  année {year}  {label}", file=sys.stderr)
    opened = _open_year(
        month, year, spacing,
        target_lats=None if acc is None else acc["lats"],
        target_lons=None if acc is None else acc["lons"],
    )
    if opened is None:
        if acc is not None:
            _save_partial(partial, acc, year + 1)
        return
    ds, u_name, v_name, _dataset_id = opened
    u = ds[u_name].values.astype("float32", copy=False)
    v = ds[v_name].values.astype("float32", copy=False)
    lat_name = "latitude" if "latitude" in ds.coords else "lat"
    lon_name = "longitude" if "longitude" in ds.coords else "lon"
    lats = ds[lat_name].values.astype("float32")
    lons = ds[lon_name].values.astype("float32")
    if acc is None:
        acc = _new_acc(u, lats, lons)
    _accumulate(acc, u, v)
    del ds, u, v, np
    gc.collect()
    _save_partial(partial, acc, year + 1)


def _run_year_worker(month: int, year: int, spacing: float, out: Path) -> None:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--month", str(month),
        "--year", str(year),
        "--spacing", str(spacing),
        "--out", str(out),
    ]
    last_err: BaseException | None = None
    for attempt in range(1, 4):
        try:
            subprocess.run(cmd, check=True, timeout=YEAR_TIMEOUT_S)
            return
        except subprocess.TimeoutExpired as exc:
            last_err = exc
            print(
                f"  timeout {YEAR_TIMEOUT_S}s année {year} — retry {attempt}/3",
                file=sys.stderr,
            )
        except subprocess.CalledProcessError as exc:
            last_err = exc
            wait = 4 * (2 ** (attempt - 1))
            print(
                f"  worker exit {exc.returncode} année {year} — retry {attempt}/3 dans {wait}s",
                file=sys.stderr,
            )
            time.sleep(wait)
    raise RuntimeError(f"échec année {year} mois {month:02d}") from last_err


def generate_month(
    month: int,
    year_start: int,
    year_end: int,
    spacing: float,
    out: Path,
) -> Path:
    import numpy as np

    dest = out / f"wind-{month:02d}.npz"
    sidecar = out / f"wind-{month:02d}.atlas.json"
    partial = out / f"wind-{month:02d}.partial.npz"
    years = list(range(year_start, year_end + 1))
    loaded = _load_partial(partial)
    if loaded:
        _acc, year_next = loaded
        todo = [y for y in years if y >= year_next]
        print(f"reprise mois {month:02d} à l'année {year_next}", file=sys.stderr)
    else:
        todo = years

    t0 = time.time()
    for i, year in enumerate(todo, start=1):
        picked = pick_dataset(year, month)
        label = picked[0] if picked else "skip"
        print(f"mois {month:02d}  année {year}  ({i}/{len(todo)})  {label}", file=sys.stderr)
        if picked is None:
            loaded_skip = _load_partial(partial)
            if loaded_skip:
                _save_partial(partial, loaded_skip[0], year + 1)
            continue
        _run_year_worker(month, year, spacing, out)

    loaded = _load_partial(partial)
    acc = loaded[0] if loaded else None
    if acc is None:
        raise SystemExit(f"aucune année téléchargée pour le mois {month}")

    n = np.maximum(acc["count"], 1)
    pct = acc["sec_n"] * 100.0 / n[:, :, None]
    spd_mean = np.zeros_like(acc["sec_spd"], dtype="float64")
    np.divide(
        acc["sec_spd"], np.maximum(acc["sec_n"], 1),
        out=spd_mean, where=acc["sec_n"] > 0,
    )
    pct[pct < 2.5] = 0.0
    sea = acc["count"] > 20
    tmp = dest.with_name(dest.stem + ".tmp.npz")
    np.savez_compressed(
        tmp,
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
        stat=np.array(["rose"]),
    )
    tmp.replace(dest)
    sidecar.write_text(json.dumps({
        "kind": "climatology",
        "month": month,
        "period": PERIOD,
        "source_ids": [PRODUCT],
        "doi": DOI,
        "dataset": [DATASET_025, DATASET_0125],
        "note": "0.25deg Jun 1994–Oct 2009, then 0.125deg to 2020. Jan–May 1994 absent.",
        "stat": "rose",
        "subsample": "6h",
        "grid_spacing_deg": spacing,
        "years": f"{year_start}-{year_end}",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }, indent=2) + "\n", encoding="utf-8")
    if partial.is_file():
        partial.unlink()
    elapsed = int(time.time() - t0)
    print(f"wrote {dest} stat=rose  {elapsed}s")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Roses CMEMS 8 secteurs — un mois ou les 12. Pas sur le VPS."
    )
    ap.add_argument("--month", type=int, default=None, help="1–12 ; omit avec --all")
    ap.add_argument("--all", action="store_true", help="les 12 mois, dans l'ordre")
    ap.add_argument("--skip-existing", action="store_true",
                    help="saute un mois déjà en rose (pas une moyenne AVERAGE)")
    ap.add_argument("--year-start", type=int, default=1994)
    ap.add_argument("--year-end", type=int, default=2020)
    ap.add_argument("--year", type=int, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--spacing", type=float, default=0.5)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    if args.worker:
        if args.month is None or args.year is None:
            raise SystemExit("worker: --month et --year requis")
        login()
        process_one_year(args.month, args.year, args.spacing, args.out)
        return 0
    if args.all:
        months = list(range(1, 13))
    elif args.month is not None:
        if args.month < 1 or args.month > 12:
            raise SystemExit("month 1–12")
        months = [args.month]
    else:
        raise SystemExit("indique --month N ou --all")

    try:
        import numpy as np  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "Prérequis : pip install copernicusmarine xarray netCDF4 numpy python-dotenv"
        ) from exc

    args.out.mkdir(parents=True, exist_ok=True)
    print("login Copernicus…", file=sys.stderr)
    login()
    for month in months:
        sidecar = args.out / f"wind-{month:02d}.atlas.json"
        if args.skip_existing and _sidecar_is_complete_rose(sidecar, args.year_start, args.year_end):
            print(f"mois {month:02d} déjà en rose {args.year_start}-{args.year_end} — skip", file=sys.stderr)
            continue
        generate_month(month, args.year_start, args.year_end, args.spacing, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
