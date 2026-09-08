"""Run isolé des 11 polygones revus, variant=tinyfish."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import importlib.util  # noqa: E402

from app.core.tasks import TaskState  # noqa: E402
from app.db import db  # noqa: E402
from app.services import poe_runs  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "probe_example_sources", BACKEND / "scripts" / "probe_example_sources.py")
_ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ex)
TARGET_MRGIDS = _ex.TARGET_MRGIDS
upsert_example_zones = _ex.upsert_example_zones


async def main() -> int:
    n = await upsert_example_zones(db)
    print(f"upserted {n} zones", flush=True)
    missing = []
    for mid in TARGET_MRGIDS:
        z = await db.eez_zones.find_one({"mrgid": mid}, {"mrgid": 1, "name": 1, "iso2": 1})
        if not z:
            missing.append(mid)
        else:
            print(f"  ready {mid} {z.get('iso2')} {z.get('name')}", flush=True)
    if missing:
        print("MISSING", missing, flush=True)
        return 2
    state = TaskState(max_logs=12000)
    state.start()
    rid = poe_runs.new_run_id()
    Path("/opt/cursor/artifacts/serper_11_run_id.txt").write_text(rid)
    print("run_id", rid, flush=True)
    summary = await poe_runs.execute_run(
        db, state, rid, label="serper-11-tinyfish",
        only_zones=list(TARGET_MRGIDS), concurrency=2, variant="tinyfish")
    state.finish()
    out = {
        "run_id": rid,
        "summary": summary,
        "results": state.results,
        "error": state.error,
        "logs_tail": state.logs[-80:],
    }
    dest = Path("/opt/cursor/artifacts/serper_11_run.json")
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    print("SUMMARY", json.dumps(summary, default=str), flush=True)
    print("wrote", dest, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
