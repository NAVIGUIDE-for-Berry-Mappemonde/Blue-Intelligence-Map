#!/usr/bin/env python3
"""Construit data/master_seeds.json : union des financeurs v1 + 21 listings curés.

Usage (depuis la racine du repo ou backend/) :
  python backend/scripts/export_master_seeds.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.static_data.seeds import CURATED_SEEDS  # noqa: E402

GEOJSON = ROOT / "seed" / "projects.geojson"
OUT = BACKEND / "data" / "master_seeds.json"
SKIP = {"unknown", "community report", ""}


def _domain(url: str) -> str:
    try:
        host = (urlparse(url).netloc or "").lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _key(name: str) -> str:
    return " ".join((name or "").lower().split())


def collect_v1(path: Path) -> dict[str, dict]:
    fc = json.loads(path.read_text(encoding="utf-8"))
    by_name: dict[str, dict] = {}
    for feat in fc.get("features") or []:
        p = feat.get("properties") or {}
        name = (p.get("funder") or "").strip()
        if _key(name) in SKIP:
            continue
        rec = by_name.setdefault(name, {"n": 0, "domains": Counter()})
        rec["n"] += 1
        url = (p.get("url") or "").strip()
        d = _domain(url)
        if d:
            rec["domains"][d] += 1
    return by_name


def infer_url(domains: Counter) -> tuple[str, str]:
    if not domains:
        return "", "unknown"
    host, _n = domains.most_common(1)[0]
    return f"https://{host}/", "domain_inferred"


def main() -> int:
    if not GEOJSON.exists():
        print(f"missing {GEOJSON}", file=sys.stderr)
        return 1
    v1 = collect_v1(GEOJSON)
    curated_by_key = {_key(s["name"]): s for s in CURATED_SEEDS}

    seeds = []
    seen = set()
    for s in CURATED_SEEDS:
        seen.add(_key(s["name"]))
        extra = v1.get(s["name"]) or {}
        seeds.append({
            "name": s["name"],
            "url": s.get("url") or "",
            "priority": 1,
            "listing_kind": "projects_index",
            "country": s.get("country"),
            "category": s.get("category"),
            "v1_count": extra.get("n", 0),
        })

    rest = []
    for name, rec in v1.items():
        if _key(name) in seen:
            continue
        if _key(name) in curated_by_key:
            continue
        url, kind = infer_url(rec["domains"])
        rest.append({
            "name": name,
            "url": url,
            "priority": 2,
            "listing_kind": kind,
            "country": None,
            "v1_count": rec["n"],
        })
    rest.sort(key=lambda r: (-int(r.get("v1_count") or 0), r["name"].lower()))
    seeds.extend(rest)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "seed/projects.geojson + curated 21",
        "count": len(seeds),
        "priority_1": sum(1 for s in seeds if s["priority"] == 1),
        "priority_2": sum(1 for s in seeds if s["priority"] == 2),
        "with_url": sum(1 for s in seeds if s.get("url")),
        "seeds": seeds,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT} — {payload['count']} seeds "
          f"(p1={payload['priority_1']} p2={payload['priority_2']} "
          f"url={payload['with_url']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
