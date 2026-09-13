#!/usr/bin/env python3
"""Construit l'index IBTrACS compact depuis le CSV officiel since1980.

Ne recopie pas le C++ OpenCPN. TRACK_TYPE == main. Vent : USA_WIND sinon
WMO_WIND (mélange 1 min / 10 min documenté dans wind_source).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

IBTRACS_URL = (
    "https://www.ncei.noaa.gov/data/international-best-track-archive-for-"
    "climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.since1980.list.v04r01.csv"
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "backend" / "data" / "climatology" / "cyclones" / "ibtracs_since1980.json"

# Sous-échantillon : un point toutes les N heures (CSV = 3 h).
KEEP_EVERY = 2  # 6 h
MAX_POINTS = 48


def _f(raw: str) -> float | None:
    raw = (raw or "").strip()
    if not raw or raw == " ":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _simplify(points: list[list[float]]) -> list[list[float]]:
    if len(points) <= MAX_POINTS:
        return points
    step = max(1, len(points) // MAX_POINTS)
    out = points[::step]
    if out[-1] != points[-1]:
        out.append(points[-1])
    return out


def parse_csv(path: Path) -> list[dict]:
    storms: dict[str, dict] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        # Ligne unités IBTrACS
        peek = next(reader)
        if not peek or peek[0].startswith("SID") or (peek[0] and peek[0][0].isdigit()):
            fh.seek(0)
            reader = csv.reader(fh)
            header = next(reader)
        idx = {name: i for i, name in enumerate(header)}

        def col(row, name, default=""):
            i = idx.get(name)
            if i is None or i >= len(row):
                return default
            return row[i]

        n = 0
        for row in reader:
            n += 1
            if n == 1 and row and not row[0][0].isdigit() and row[0] != "1980001S":
                # éventuelle 2e ligne d'unités
                if "units" in ",".join(row).lower() or row[0] in ("", " "):
                    continue
            track_type = col(row, "TRACK_TYPE").strip().lower()
            if track_type and track_type != "main":
                continue
            sid = col(row, "SID").strip()
            if not sid:
                continue
            lat = _f(col(row, "LAT"))
            lon = _f(col(row, "LON"))
            if lat is None or lon is None:
                continue
            if abs(lat) > 90 or abs(lon) > 180:
                continue
            iso = col(row, "ISO_TIME").strip()
            usa = _f(col(row, "USA_WIND"))
            wmo = _f(col(row, "WMO_WIND"))
            if usa is not None:
                wind, src = usa, "USA_WIND"
            elif wmo is not None:
                wind, src = wmo, "WMO_WIND"
            else:
                wind, src = None, None
            month = None
            if iso:
                try:
                    month = datetime.fromisoformat(iso.replace("Z", "+00:00")).month
                except ValueError:
                    try:
                        month = int(iso[5:7])
                    except ValueError:
                        month = None
            rec = storms.setdefault(sid, {
                "sid": sid,
                "name": col(row, "NAME").strip() or None,
                "season": int(_f(col(row, "SEASON")) or 0) or None,
                "basin": col(row, "BASIN").strip() or None,
                "max_wind_kn": 0.0,
                "wind_source": src,
                "start": iso or None,
                "end": iso or None,
                "months": set(),
                "coords": [],
            })
            rec["end"] = iso or rec["end"]
            if not rec["start"]:
                rec["start"] = iso
            if month:
                rec["months"].add(month)
            if wind is not None and wind > rec["max_wind_kn"]:
                rec["max_wind_kn"] = wind
                rec["wind_source"] = src or rec["wind_source"]
            rec["coords"].append([round(lon, 2), round(lat, 2)])

    out = []
    for rec in storms.values():
        coords = rec["coords"][::KEEP_EVERY] or rec["coords"]
        rec["coords"] = _simplify(coords)
        rec["months"] = sorted(rec["months"])
        rec["max_wind_kn"] = round(float(rec["max_wind_kn"] or 0), 1)
        if len(rec["coords"]) < 2:
            continue
        out.append(rec)
    out.sort(key=lambda s: (s.get("season") or 0, s.get("sid") or ""))
    return out


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"download {url}", file=sys.stderr)
    req = urllib.request.Request(url, headers={"User-Agent": "BlueIntelligence/climatology"})
    with urllib.request.urlopen(req, timeout=180) as resp, dest.open("wb") as fh:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            fh.write(chunk)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=None)
    ap.add_argument("--url", default=IBTRACS_URL)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    csv_path = args.csv
    if csv_path is None:
        csv_path = Path("/tmp/ibtracs.since1980.list.v04r01.csv")
        if not csv_path.is_file() or csv_path.stat().st_size < 1_000_000:
            download(args.url, csv_path)
    storms = parse_csv(csv_path)
    payload = {
        "kind": "climatology",
        "source": "IBTrACS v04r01 since1980",
        "period": "1980-present",
        "license": "IBTrACS v04r01, NOAA NCEI — redistribution unrestricted",
        "wind_note": "USA_WIND (1-min) when present, else WMO_WIND (10-min, basin-dependent).",
        "track_type": "main",
        "count": len(storms),
        "storms": storms,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {args.out} ({len(storms)} storms, {args.out.stat().st_size} bytes)")
    # Contrôles A
    by_month_basin = defaultdict(int)
    for s in storms:
        for m in s["months"]:
            by_month_basin[(m, s.get("basin"))] += 1
    print("NA Sep", by_month_basin[(9, "NA")], "NA Feb", by_month_basin[(2, "NA")],
          "SP Jan", by_month_basin[(1, "SP")], "SP Mar", by_month_basin[(3, "SP")])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
