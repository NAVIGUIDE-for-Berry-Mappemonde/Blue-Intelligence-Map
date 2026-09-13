#!/usr/bin/env python3
"""Étape D + E (hors Complet) : scinder/exclure les noms collés, rafraîchir la file.

D reclasse les faux composés (un seul organisme avec « and »), scinde les
listes (`A and B`, `X, Y, Z`) vers des graines existantes ou nouvelles
(`source=split`, hors Complet tant que la home n'est pas officielle), et
met la source scindée en `queue=skip`.

E recalcule `queue` : Complet = home officielle ou page-liste, nom simple.
N'écrit pas `projects`.

    python3 scripts/split_compound_seeds.py --dry-run
    python3 scripts/split_compound_seeds.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ["MONGO_URL"] = "mongodb://127.0.0.1:27017"
os.environ.setdefault("DB_NAME", "bi_compound_splits_unused")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.master_seeds import MASTER_SEEDS_PATH, now_iso, seeds_for_run  # noqa: E402
from app.services.seed_catalog import (  # noqa: E402
    AUDIT_PATH, SPLITS_REPORT_PATH, apply_compound_splits, catalog_summary,
    persist_catalog, refresh_catalog_queues,
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    p = argparse.ArgumentParser(description="Scinde les noms composés et rafraîchit la file Complet")
    p.add_argument("--seeds", type=Path, default=MASTER_SEEDS_PATH)
    p.add_argument("--audit-out", type=Path, default=AUDIT_PATH)
    p.add_argument("--report", type=Path, default=SPLITS_REPORT_PATH)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    data = _load(args.seeds)
    seeds = data.get("seeds") or []
    before = catalog_summary(seeds)
    report = apply_compound_splits(seeds)
    refresh_catalog_queues(seeds)
    after = catalog_summary(seeds)
    queued = seeds_for_run(seeds)
    counts = report["counts"]
    print(
        f"D : reclasse={counts['reclassified_ok']} fusion={counts['merged']} "
        f"créés={counts['created']} sources_skip={counts['split_sources']} "
        f"intacts={counts['unsplittable']}"
    )
    print(
        f"E : crawl {before['n_crawl']} → {after['n_crawl']}  "
        f"resolve {before['n_resolve']} → {after['n_resolve']}  "
        f"skip {before['n_skip']} → {after['n_skip']}  "
        f"n {before['n']} → {after['n']}"
    )
    print(f"  file Complet = {len(queued)} (queue=crawl, is_crawl_ready)")
    if report["reclassified_ok"][:8]:
        print("  reclassés ok :")
        for name in report["reclassified_ok"][:8]:
            print(f"    · {name[:80]}")
    if report["created"][:8]:
        print("  nouveaux (resolve, home à trouver) :")
        for row in report["created"][:8]:
            print(f"    · {row['name'][:50]}  ← {row['from'][:40]}")
    if args.dry_run or not args.apply:
        print("Relancer avec --apply pour écrire catalogue + audit + rapport.")
        return 0
    payload = {
        "generated_at": now_iso(),
        "before": before,
        "after": after,
        "counts": counts,
        "reclassified_ok": report["reclassified_ok"],
        "merged": report["merged"],
        "created": report["created"],
        "split_sources": report["split_sources"],
        "unsplittable": report["unsplittable"],
    }
    args.report.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    persist_catalog(
        seeds, args.seeds, args.audit_out,
        source=str(args.seeds) + "+name-splits",
    )
    print(f"Conservé : {args.seeds}")
    print(f"Conservé : {args.report}")
    print(f"Conservé : {args.audit_out} + {args.audit_out.with_suffix('.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
