#!/usr/bin/env python3
"""Canari : un pays déjà catalogué + N graines aux extraits déjà payés.

Fetch des judge_sources uniquement (0 Search). N'écrit pas poe_ports.
Par défaut n'écrit pas non plus poe_seed_ports (--write pour persister).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.tinyfish import tf_api_key, tf_fetch
from app.services.poe_seed_enrich import (
    apply_judge_verdict, catalog_cache_from_zone, judge_one, paid_fetch_urls,
)


NZ_FIVE = (
    "Port of Tauranga",
    "Lyttelton",
    "CentrePort Container Terminal",
    "Viaduct Marina",
    "Tiwai Point",
)


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--iso", default="NZ", choices=("NZ", "MA"))
    p.add_argument("--mrgid", type=int, default=0)
    p.add_argument("--write", action="store_true")
    p.add_argument("--out", default="/opt/cursor/artifacts/canary_nz_paid5.json")
    args = p.parse_args()
    mrgid = args.mrgid or (8455 if args.iso == "NZ" else 8367)
    names = list(NZ_FIVE) if args.iso == "NZ" else []

    from motor.motor_asyncio import AsyncIOMotorClient
    from app.db import get_settings

    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    ports_before = await db.poe_ports.count_documents({})
    zone = await db.eez_zones.find_one(
        {"mrgid": mrgid},
        {"mrgid": 1, "name": 1, "geoname": 1, "iso2": 1, "sov_iso2": 1,
         "sovereign": 1, "catalog_bu": 1, "sources_bu": 1},
    )
    if not zone:
        raise SystemExit(f"ZEE {mrgid} introuvable")
    cache = catalog_cache_from_zone(zone)
    if not cache.get("sufficient"):
        raise SystemExit(f"ZEE {mrgid} sans catalogue suffisant")

    q = {"mrgid": mrgid, "judge_sources.0": {"$exists": True}}
    if names:
        q["name"] = {"$in": names}
    seeds = await db.poe_seed_ports.find(q).to_list(20)
    if names:
        by = {s.get("name"): s for s in seeds}
        seeds = [by[n] for n in names if n in by]
    if len(seeds) < 5 and not names:
        seeds = seeds[:5]
    if len(seeds) != 5:
        raise SystemExit(f"attendu 5 graines, obtenu {len(seeds)}: "
                         f"{[s.get('name') for s in seeds]}")

    settings = {}
    try:
        settings = await get_settings()
    except Exception:
        pass
    key = tf_api_key(settings) or (os.environ.get("TINYFISH_API_KEY") or "")
    wanted = []
    for s in seeds:
        wanted.extend(paid_fetch_urls(s, cap=4))
    urls = list(dict.fromkeys(wanted))
    print(f"canary {args.iso} mrgid={mrgid}: {len(seeds)} graines · "
          f"{len(urls)} URL (0 Search, write={args.write})", flush=True)

    fetched = {}
    if key and urls:
        fetched = await tf_fetch(urls, key, log=print) or {}

    rows = []
    search = False
    for doc in seeds:
        logs = []
        judged = await judge_one(
            doc, zone, settings, logs.append,
            use_agent=False, db=None, catalog_cache=cache,
            persist_memory=False, reuse_paid_sources=True,
            prefetched=fetched)
        prev = {
            "judge_status": doc.get("judge_status"),
            "judge_engine": doc.get("judge_engine"),
            "judge_kind": doc.get("judge_kind"),
            "judge_confidence": doc.get("judge_confidence"),
        }
        next_v = apply_judge_verdict(doc, judged)
        row = {
            "name": doc.get("name"),
            "previous": prev,
            "now": {
                "judge_status": judged.get("judge_status"),
                "judge_engine": judged.get("judge_engine"),
                "judge_kind": judged.get("judge_kind"),
                "judge_confidence": judged.get("judge_confidence"),
                "judge_reason": judged.get("judge_reason"),
                "official_name": judged.get("official_name"),
                "verify_verdict_if_applied": next_v,
            },
            "logs": logs,
            "paid_urls": paid_fetch_urls(doc, cap=4),
        }
        rows.append(row)
        print(json.dumps({"name": row["name"], "previous": prev,
                          "now": row["now"]}, ensure_ascii=False), flush=True)
        if args.write:
            judged["verify_verdict"] = next_v
            await db.poe_seed_ports.update_one({"_id": doc["_id"]}, {"$set": judged})

    ports_after = await db.poe_ports.count_documents({})
    report = {
        "iso": args.iso,
        "mrgid": mrgid,
        "zone": zone.get("name"),
        "catalog_n": len(cache.get("ports") or []),
        "search": search,
        "wrote_poe_ports": False,
        "wrote_seeds": bool(args.write),
        "poe_ports_before": ports_before,
        "poe_ports_after": ports_after,
        "urls_fetched": urls,
        "rows": rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "iso", "mrgid", "catalog_n", "search", "wrote_poe_ports",
        "wrote_seeds", "poe_ports_before", "poe_ports_after")},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
