"""Ingest NGA World Port Index (Pub 150) → backend/data/wpi_ports.json.

Ne touche pas poe_ports / poe_seed_ports. Pas de seeds/build.

Usage:
  python scripts/ingest_wpi.py /chemin/UpdatedPub150.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.wpi_ports import ingest_wpi_csv, write_wpi_snapshot  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv", type=Path, help="UpdatedPub150.csv (NGA, domaine public US)")
    p.add_argument("-o", "--out", type=Path, default=None, help="wpi_ports.json")
    args = p.parse_args()
    if not args.csv.is_file():
        print(f"fichier introuvable: {args.csv}", file=sys.stderr)
        return 2
    doc = ingest_wpi_csv(args.csv)
    dest = write_wpi_snapshot(doc, args.out)
    print(
        f"WPI ingest {doc['n']} ports → {dest} "
        f"(wpi_commercial = contre-liste, 0 preuve PoE, 0 écriture Atlas)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
