"""Re-géocode inland_far / ambiguous. Pas les confirmed ok, pas seeds/build.

  python3 scripts/regeocode_inland_far.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient

from app.config import DB_NAME, MONGO_URL  # noqa: F401
from app.services.poe_seed_enrich import (
    _needs_geocode, _zone_cache, attach_geocode_context, geocode_one,
)


async def main() -> None:
    client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=20000)
    db = client[os.environ["DB_NAME"]]
    before_ports = await db.poe_ports.count_documents({})
    before_seeds = await db.poe_seed_ports.count_documents({})
    before_confirmed = await db.poe_seed_ports.count_documents(
        {"verify_verdict": "confirmed"})
    ports = await db.poe_seed_ports.find({}).to_list(20000)
    attach_geocode_context(ports)
    todo = [
        p for p in ports
        if _needs_geocode(p)
        and (p.get("verify_verdict") or "") != "confirmed"
        and (p.get("verify_verdict") or "") != "name_only"
        and p.get("lat") is not None
    ]
    print(json.dumps({"todo": len(todo), "keys": [p.get("dedup_key") for p in todo]},
                     ensure_ascii=False))
    mrgids = {int(p["mrgid"]) for p in todo if p.get("mrgid") is not None}
    zones = await _zone_cache(db, mrgids)
    ok = miss = err = 0
    results = []
    for doc in todo:
        zone = zones.get(int(doc["mrgid"])) if doc.get("mrgid") is not None else None
        if not zone:
            err += 1
            results.append({"key": doc.get("dedup_key"), "status": "no_zone"})
            continue
        prev = {"lat": doc.get("lat"), "lon": doc.get("lon")}
        try:
            upd = await geocode_one(doc, zone, lambda m: None)
        except Exception as e:
            err += 1
            results.append({"key": doc.get("dedup_key"), "status": "error",
                            "error": f"{type(e).__name__}: {e}"[:160]})
            continue
        verdict = doc.get("verify_verdict")
        upd.pop("verify_verdict", None)
        if "lat" in upd and upd.get("has_coords") and not upd.get("geocode_kept_previous"):
            ok += 1
            status = "updated"
        else:
            miss += 1
            status = upd.get("geocode_arbitration") or "kept"
            upd = {k: v for k, v in upd.items() if k not in ("lat", "lon")}
        await db.poe_seed_ports.update_one({"_id": doc["_id"]}, {"$set": upd})
        fresh = await db.poe_seed_ports.find_one({"_id": doc["_id"]})
        results.append({
            "key": doc.get("dedup_key"), "name": doc.get("name"),
            "status": status, "verdict": verdict,
            "before": prev,
            "after": {"lat": fresh.get("lat"), "lon": fresh.get("lon"),
                      "source": fresh.get("geocode_source"),
                      "kind": fresh.get("spatial_kind")},
        })
        print(f"  {status:12} {doc.get('dedup_key')}  "
              f"{prev['lat']},{prev['lon']} -> {fresh.get('lat')},{fresh.get('lon')}")
    after_ports = await db.poe_ports.count_documents({})
    after_seeds = await db.poe_seed_ports.count_documents({})
    after_confirmed = await db.poe_seed_ports.count_documents(
        {"verify_verdict": "confirmed"})
    assert after_ports == before_ports
    assert after_seeds == before_seeds
    assert after_confirmed == before_confirmed
    summary = {
        "todo": len(todo), "updated": ok, "kept_or_miss": miss, "err": err,
        "poe_ports": after_ports, "poe_seed_ports": after_seeds,
        "n_confirmed": after_confirmed, "seeds_build": False,
        "results": results,
    }
    print(json.dumps({k: summary[k] for k in (
        "todo", "updated", "kept_or_miss", "err", "poe_ports",
        "poe_seed_ports", "n_confirmed", "seeds_build")}, ensure_ascii=False))
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
