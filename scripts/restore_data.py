"""
restore_data.py — Restauration NON-DESTRUCTIVE des sauvegardes GeoJSON.

Usage:
  python3 scripts/restore_data.py poe /tmp/poe_backup.geojson
  python3 scripts/restore_data.py zones          # backfill statuts après build référentiel
Les projets se restaurent via l'endpoint existant POST /api/import/geojson.
"""
import json
import os
import sys
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
from dotenv import load_dotenv

load_dotenv(BACKEND / ".env")
from pymongo import MongoClient
from app.core.dedup import normalize_name

client = MongoClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]


def restore_poe(path: str):
    fc = json.load(open(path, encoding="utf-8"))
    ins = skip = 0
    for f in fc.get("features", []):
        p = f.get("properties") or {}
        geom = f.get("geometry") or {}
        if geom.get("type") != "Point" or not p.get("name") or p.get("mrgid") is None:
            continue
        lon, lat = float(geom["coordinates"][0]), float(geom["coordinates"][1])
        dk = f"{p['mrgid']}:{normalize_name(p['name'])}"
        if db.poe_ports.find_one({"dedup_key": dk}):
            skip += 1
            continue
        db.poe_ports.insert_one({
            "_id": p.get("id") or str(uuid.uuid4()),
            "mrgid": int(p["mrgid"]), "zone_name": p.get("zone_name"),
            "country_iso2": p.get("country_iso2"),
            "name": p["name"], "city": p.get("city"), "note": p.get("note"),
            "lat": lat, "lon": lon, "geocode_source": p.get("geocode_source"),
            "validated": bool(p.get("validated")), "distance_km": p.get("distance_km"),
            "source_urls": p.get("source_urls") or [],
            "extracted_at": p.get("extracted_at"),
            "dedup_key": dk,
        })
        ins += 1
    print(f"poe_ports: {ins} insérés, {skip} déjà présents, total {db.poe_ports.count_documents({})}")


def backfill_zones():
    """À lancer APRÈS le build du référentiel ZEE : statut + poe_count depuis les ports restaurés."""
    updated = 0
    for row in db.poe_ports.aggregate([
        {"$group": {"_id": "$mrgid", "n": {"$sum": 1}, "last": {"$max": "$extracted_at"}}}
    ]):
        r = db.eez_zones.update_one(
            {"mrgid": row["_id"], "status": "non_generee"},
            {"$set": {"status": "ia", "poe_count": row["n"], "generated_at": row["last"]}})
        updated += r.modified_count
        db.eez_zones.update_one(
            {"mrgid": row["_id"], "poe_count": {"$ne": row["n"]}},
            {"$set": {"poe_count": row["n"]}})
    print(f"eez_zones: {updated} zones backfillées (status=ia), poe_counts synchronisés")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "poe":
        restore_poe(sys.argv[2])
    elif cmd == "zones":
        backfill_zones()
    else:
        print(__doc__)
