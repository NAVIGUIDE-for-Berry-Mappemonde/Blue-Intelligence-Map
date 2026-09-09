"""import_v1_runs — écrit les runs « v1 » en base (Atlas).

- Projets : importe un GeoJSON (export carte) comme run isolé `v1` dans
  `project_runs` / `project_run_projects` (la collection live `projects`
  n'est pas touchée).
- AMP : copie la collection live `amp_sites` comme run isolé `v1` dans
  `amp_runs` / `amp_run_sites` (la collection live n'est pas touchée).

Idempotent : relancer le script met à jour le même run `v1`.

Usage :
    python scripts/import_v1_runs.py --projects-geojson /path/to/projects.geojson --amp

Garde-fou : refuse un MONGO_URL localhost (base éphémère d'un pod Cloud
Agent) sauf si --allow-local est passé explicitement.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

RUN_ID = "v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def mongo_kind(url: str) -> str:
    u = (url or "").lower()
    if "mongodb+srv" in u or "mongodb.net" in u:
        return "atlas"
    if "localhost" in u or "127.0.0.1" in u:
        return "local"
    return "other" if u else "empty"


def feature_to_run_project(feat: dict) -> dict | None:
    """Feature GeoJSON export carte → document project_run_projects."""
    props = feat.get("properties") or {}
    coords = (feat.get("geometry") or {}).get("coordinates") or []
    if len(coords) != 2:
        return None
    pid = str(props.get("id") or "").strip()
    url = (props.get("url") or "").strip()
    if not pid or not url:
        return None
    funder = props.get("funder") or ""
    return {
        "_id": f"{RUN_ID}:{pid}",
        "run_id": RUN_ID,
        "source_id": pid,
        "title": props.get("title"),
        "url": url,
        "description": props.get("description") or "",
        "funder": funder,
        "funders": [f.strip() for f in funder.split(",") if f.strip()],
        "location": props.get("location"),
        "s_ocean": props.get("s_ocean"),
        "snapped": bool(props.get("snapped")),
        "image": props.get("image"),
        "category": props.get("category"),
        "category_group": props.get("category_group"),
        "lon": float(coords[0]),
        "lat": float(coords[1]),
        "verdict": "site",
        "geo_source": "import_v1",
        "wrote_projects": False,
        "updated_at": now_iso(),
    }


def amp_site_to_run_doc(doc: dict) -> dict:
    """Document amp_sites live → document amp_run_sites (run v1)."""
    sid = str(doc.get("site_id") or doc.get("_id"))
    out = {k: v for k, v in doc.items() if k != "_id"}
    out["_id"] = f"{RUN_ID}:{sid}"
    out["run_id"] = RUN_ID
    out["source_id"] = sid
    out["wrote_amp_sites"] = False
    return out


def _run_meta(*, label: str, kind: str, wrote_flag: str, summary: dict) -> dict:
    return {
        "_id": RUN_ID,
        "label": label,
        "kind": kind,
        "mode": "import",
        "state": "done",
        wrote_flag: False,
        "params": {"kind": kind, "label": label, wrote_flag: False},
        "summary": {"run_id": RUN_ID, wrote_flag: False, **summary},
        "created_at": now_iso(),
        "started_at": now_iso(),
        "finished_at": now_iso(),
        "error": None,
    }


async def import_projects(db, geojson_path: Path) -> dict:
    from app.services.project_runs import ensure_run_indexes

    fc = json.loads(geojson_path.read_text())
    feats = fc.get("features") or []
    docs = [d for d in (feature_to_run_project(f) for f in feats) if d]
    with_image = sum(1 for d in docs if d.get("image"))

    await ensure_run_indexes(db)
    n = 0
    for d in docs:
        payload = {k: v for k, v in d.items() if k != "_id"}
        await db.project_run_projects.update_one(
            {"run_id": RUN_ID, "url": d["url"]},
            {"$set": payload, "$setOnInsert": {"_id": d["_id"], "created_at": now_iso()}},
            upsert=True,
        )
        n += 1
    summary = {"items": n, "with_image": with_image,
               "source": geojson_path.name, "features_in_file": len(feats)}
    meta = _run_meta(label="v1", kind="import", wrote_flag="wrote_projects",
                     summary=summary)
    meta["counters"] = {"sites": n, "unlocated": 0, "rejected": 0, "failed": 0,
                        "merged_v1": 0, "merged_run": 0, "seen_v1": 0}
    await db.project_runs.replace_one({"_id": RUN_ID}, meta, upsert=True)
    stored = await db.project_run_projects.count_documents({"run_id": RUN_ID})
    stored_img = await db.project_run_projects.count_documents(
        {"run_id": RUN_ID, "image": {"$nin": [None, ""]}})
    return {**summary, "stored": stored, "stored_with_image": stored_img}


async def import_amp(db) -> dict:
    from app.services import isolated_runs

    await isolated_runs.ensure_indexes(db, "amp")
    live = await db.amp_sites.find({}).to_list(20000)
    n = 0
    for doc in live:
        run_doc = amp_site_to_run_doc(doc)
        payload = {k: v for k, v in run_doc.items() if k != "_id"}
        await db.amp_run_sites.update_one(
            {"run_id": RUN_ID, "source_id": run_doc["source_id"]},
            {"$set": payload, "$setOnInsert": {"_id": run_doc["_id"]}},
            upsert=True,
        )
        n += 1
    summary = {"items": n, "source": "amp_sites (live)"}
    meta = _run_meta(label="v1", kind="import", wrote_flag="wrote_amp_sites",
                     summary=summary)
    await db.amp_runs.replace_one({"_id": RUN_ID}, meta, upsert=True)
    stored = await db.amp_run_sites.count_documents({"run_id": RUN_ID})
    return {**summary, "stored": stored}


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects-geojson", type=Path,
                        help="GeoJSON des projets à importer comme run v1")
    parser.add_argument("--amp", action="store_true",
                        help="copie amp_sites (live) comme run v1")
    parser.add_argument("--allow-local", action="store_true",
                        help="autorise un MONGO_URL localhost (éphémère)")
    args = parser.parse_args()
    if not args.projects_geojson and not args.amp:
        parser.error("rien à faire — passer --projects-geojson et/ou --amp")

    from dotenv import dotenv_values
    vals = dotenv_values(BACKEND / ".env")
    import os
    mongo_url = os.environ.get("MONGO_URL") or vals.get("MONGO_URL") or ""
    db_name = os.environ.get("DB_NAME") or vals.get("DB_NAME") or ""
    kind = mongo_kind(mongo_url)
    print(f"MONGO_URL: {kind} · DB_NAME: {db_name}")
    if kind != "atlas" and not args.allow_local:
        print("REFUS : MONGO_URL n'est pas Atlas — les données seraient "
              "perdues à l'arrêt du pod. Utiliser --allow-local pour forcer.")
        return 2

    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=15000)
    db = client[db_name]

    if args.projects_geojson:
        res = await import_projects(db, args.projects_geojson)
        print(f"projects run v1 : {json.dumps(res, ensure_ascii=False)}")
    if args.amp:
        res = await import_amp(db)
        print(f"amp run v1      : {json.dumps(res, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
