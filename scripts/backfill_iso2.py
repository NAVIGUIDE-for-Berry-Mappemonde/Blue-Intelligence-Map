"""
backfill_iso2.py — Complète le country_iso2 manquant des poe_ports depuis leur ZEE.

38 ports historiques ont été insérés sans code pays (invisibles au filtre
?country= de l'API). Le code est repris de la zone (iso2, sinon sov_iso2).

Usage : python3 scripts/backfill_iso2.py
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
from dotenv import load_dotenv

load_dotenv(BACKEND / ".env")
from pymongo import MongoClient

client = MongoClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]


def backfill():
    zones = {z["mrgid"]: (z.get("iso2") or z.get("sov_iso2"))
             for z in db.eez_zones.find({}, {"mrgid": 1, "iso2": 1, "sov_iso2": 1})}
    missing = list(db.poe_ports.find(
        {"$or": [{"country_iso2": None}, {"country_iso2": {"$exists": False}}]},
        {"mrgid": 1, "name": 1}))
    fixed = unresolved = 0
    for p in missing:
        iso2 = zones.get(p.get("mrgid"))
        if iso2:
            db.poe_ports.update_one({"_id": p["_id"]}, {"$set": {"country_iso2": iso2}})
            fixed += 1
        else:
            unresolved += 1
    print(f"poe_ports sans country_iso2: {len(missing)} — corrigés: {fixed}, "
          f"sans zone/iso2 connu: {unresolved}")


if __name__ == "__main__":
    backfill()
