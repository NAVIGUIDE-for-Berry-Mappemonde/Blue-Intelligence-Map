"""Applique docs/data/poe-name-only-33-verifications.json sur Atlas.

N'écrit pas poe_ports. Ne lance pas seeds/build.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo import MongoClient

from app.services.poe_name_only_review import apply_review, load_review


def main() -> None:
    uri = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not uri or not db_name:
        raise SystemExit("MONGO_URL et DB_NAME requis")
    client = MongoClient(uri, serverSelectionTimeoutMS=20000)
    db = client[db_name]
    before_ports = db.poe_ports.count_documents({})
    review = load_review()
    out = apply_review(db.poe_seed_ports, db.poe_ports, review)
    after_ports = db.poe_ports.count_documents({})
    assert after_ports == before_ports == out["poe_ports"]
    log = Path("/opt/cursor/artifacts/name_only_review_applied.json")
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    except OSError:
        Path("/tmp/name_only_review_applied.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("reviewed_at", "applied", "total",
                                          "poe_ports", "wrote_poe_ports")},
                     ensure_ascii=False))
    fails = [r for r in out["results"] if not r["ok"]]
    if fails:
        print("FAILS", fails)
        raise SystemExit(1)
    client.close()


if __name__ == "__main__":
    main()
