#!/usr/bin/env python3
"""Recharge osm_port_seeds depuis Overpass, puis mesure l'union (v1+runs+OSM+listing).

Hérite MONGO_URL / DB_NAME du process uvicorn s'ils pointent vers Atlas
(install.sh aligne aussi backend/.env : localhost → Atlas si le secret est là).
N'écrit jamais dans poe_ports.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def _inherit_uvicorn_mongo() -> None:
    current = os.environ.get("MONGO_URL", "")
    if "mongodb.net" in current:
        return
    proc = Path("/proc")
    if not proc.is_dir():
        return
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmd = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode()
        except OSError:
            continue
        if "uvicorn" not in cmd or "server:app" not in cmd:
            continue
        try:
            raw = (entry / "environ").read_bytes().split(b"\0")
        except OSError:
            continue
        for item in raw:
            if not item or b"=" not in item:
                continue
            key, _, val = item.partition(b"=")
            try:
                k, v = key.decode(), val.decode()
            except UnicodeDecodeError:
                continue
            if k in ("MONGO_URL", "DB_NAME") and v:
                os.environ[k] = v
        break


_inherit_uvicorn_mongo()

from app.db import db  # noqa: E402
from app.services.osm_seeds import osm_inventory, refresh_osm_cache  # noqa: E402
from app.services.poe_seeds import collect_seed_report, public_seed_view  # noqa: E402


async def main() -> int:
    do_refresh = "--skip-refresh" not in sys.argv
    print("inventory avant :")
    before = await osm_inventory(db)
    print(json.dumps(before, indent=2, default=str)[:4000])
    if do_refresh:
        print("refresh Overpass…", flush=True)
        stats = await refresh_osm_cache(db, log=print)
        print("cache :", json.dumps(stats, indent=2, default=str))
    else:
        print("refresh sauté (--skip-refresh)")
    print("union v1 + 5 mondiaux + OSM + listing…", flush=True)
    report = await collect_seed_report(
        db, include_v1=True, include_listing=True, include_osm=True,
        use_default_mondials=True)
    view = public_seed_view(report)
    out = {
        "osm_inventory": await osm_inventory(db),
        "union": view,
    }
    dest = Path("/opt/cursor/artifacts/seed_union_with_osm.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print("écrit", dest)
    print(json.dumps({
        "summary": view.get("summary"),
        "osm": view.get("osm"),
    }, indent=2, default=str))
    v1 = await db.poe_ports.count_documents({})
    print("poe_ports (v1, ne pas toucher) :", v1)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
