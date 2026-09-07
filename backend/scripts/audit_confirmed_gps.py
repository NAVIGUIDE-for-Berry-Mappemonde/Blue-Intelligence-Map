"""Audit GPS des confirmed dans Atlas. Pas de seeds/build.

  python3 scripts/audit_confirmed_gps.py              # dry-run (défaut)
  python3 scripts/audit_confirmed_gps.py --dry-run
  python3 scripts/audit_confirmed_gps.py --persist    # corrige les cas évidents
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo import MongoClient

from app.config import DB_NAME  # noqa: F401  — charge le .env
from app.services.poe_confirmed_gps_audit import (
    audit_confirmed_seeds, persist_gps_audit,
)

REPORT_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "data" / "poe-confirmed-gps-audit.json"
)


def _mongo_uri() -> str:
    return os.environ.get("MONGO_URI") or os.environ.get("MONGO_URL") or ""


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", default=False,
                   help="Imprime le rapport sans écrire (défaut si pas --persist)")
    p.add_argument("--persist", action="store_true",
                   help="Écrit gps_audit_* et corrige les GPS évidents")
    args = p.parse_args()
    dry_run = (not args.persist) or args.dry_run
    if args.persist:
        dry_run = False
    uri = _mongo_uri()
    db_name = os.environ.get("DB_NAME")
    if not uri or not db_name:
        raise SystemExit("MONGO_URI/MONGO_URL et DB_NAME requis")
    client = MongoClient(uri, serverSelectionTimeoutMS=20000)
    db = client[db_name]
    before_ports = db.poe_ports.count_documents({})
    before_seeds = db.poe_seed_ports.count_documents({})
    before_confirmed = db.poe_seed_ports.count_documents({"verify_verdict": "confirmed"})
    seeds = list(db.poe_seed_ports.find({"verify_verdict": "confirmed"}))
    report = audit_confirmed_seeds(seeds)
    persist_info = None
    if not dry_run:
        persist_info = persist_gps_audit(db, report, seeds=seeds)
        report["persist"] = persist_info
        report["dry_run"] = False
        report["wrote_poe_ports"] = bool(persist_info.get("wrote_poe_ports"))
        report["n_corrected"] = persist_info.get("corrected")
    else:
        report["persist"] = None
        report["dry_run"] = True
    after_ports = db.poe_ports.count_documents({})
    after_seeds = db.poe_seed_ports.count_documents({})
    after_confirmed = db.poe_seed_ports.count_documents({"verify_verdict": "confirmed"})
    assert after_ports == before_ports
    assert after_seeds == before_seeds
    assert after_confirmed == before_confirmed
    report["poe_ports"] = after_ports
    report["poe_seed_ports"] = after_seeds
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8")
    art = Path("/opt/cursor/artifacts/poe_confirmed_gps_audit.json")
    try:
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8")
    except OSError:
        Path("/tmp/poe_confirmed_gps_audit.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8")
    slim = {
        "audited_at": report.get("audited_at"),
        "dry_run": report.get("dry_run"),
        "n_confirmed": report.get("n_confirmed"),
        "n_flagged": report.get("n_flagged"),
        "n_high": report.get("n_high"),
        "n_medium": report.get("n_medium"),
        "n_will_correct": report.get("n_will_correct"),
        "poe_ports": after_ports,
        "poe_seed_ports": after_seeds,
        "wrote_poe_ports": (persist_info or {}).get("wrote_poe_ports", False),
        "seeds_build": False,
        "persist": None if persist_info is None else {
            k: persist_info[k] for k in (
                "flagged", "corrected", "ok", "poe_ports", "poe_seed_ports",
                "n_confirmed", "poe_ports_patched", "wrote_poe_ports",
                "seeds_build")
            if k in persist_info
        },
    }
    print(json.dumps(slim, ensure_ascii=False))
    print("CORRECT:")
    for s in report.get("flags") or []:
        if not s.get("will_correct"):
            continue
        print(f"  {s['key']}  {s['name']!r}  {s['reasons']}  "
              f"gps={s['lat']},{s['lon']}  -> {s.get('correction')}")
    print("FLAGGED:")
    for s in report.get("flags") or []:
        if s.get("will_correct"):
            continue
        if s.get("severity") != "high":
            continue
        print(f"  {s['key']}  {s['name']!r}  {s['reasons']}  "
              f"gps={s['lat']},{s['lon']}  suggest={s.get('suggested_lat')},{s.get('suggested_lon')}")
    client.close()


if __name__ == "__main__":
    main()
