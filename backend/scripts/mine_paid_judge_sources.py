"""Mine les judge_sources déjà payés (Fetch, 0 Search), puis juge le résidu.

N'écrit jamais poe_ports. Ne lance pas seeds/build.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.tasks import TaskState
from app.services.poe_seed_enrich import mine_paid_sources


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--fetch-cap", type=int, default=150)
    p.add_argument("--residue-limit", type=int, default=0)
    p.add_argument("--no-residue", action="store_true")
    p.add_argument("--no-memory", action="store_true")
    p.add_argument("--no-runs", action="store_true")
    args = p.parse_args()

    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    state = TaskState(max_logs=4000)
    state.start()
    try:
        summary = await mine_paid_sources(
            db, state,
            fetch_cap=args.fetch_cap,
            persist_memory=not args.no_memory,
            mark_named=True,
            judge_residue=not args.no_residue,
            residue_limit=args.residue_limit,
            include_runs=not args.no_runs,
            concurrency=2,
            use_agent=False,
        )
    finally:
        state.finish()
    print(json.dumps({
        "counts": summary.get("counts"),
        "eez_catalog": summary.get("eez_catalog"),
        "urls_catalog": summary.get("urls_catalog"),
        "residue": summary.get("residue"),
        "wrote_poe_ports": summary.get("wrote_poe_ports"),
        "search": summary.get("search"),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
