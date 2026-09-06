#!/usr/bin/env python3
"""Dump le catalogue Taginfo/wiki (pas d'Overpass mondial)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.osm_seeds import taginfo_snapshot  # noqa: E402


def main() -> int:
    live = "--offline" not in sys.argv
    snap = taginfo_snapshot(live=live)
    dest = Path("/opt/cursor/artifacts/osm_taginfo_inventory.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")
    print("écrit", dest)
    print(json.dumps(snap.get("how_many_ports"), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
