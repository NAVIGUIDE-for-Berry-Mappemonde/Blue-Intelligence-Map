#!/usr/bin/env python3
"""
Audit des tags observés dans les données vs catalogue documenté.

Inspiration Open Waters: Seamap (`bin/audit-tags.ts`) : comparer ce que les
données contiennent réellement avec ce que nous documentons et exploitons
(`backend/data/seamark_catalog.json`). Deux choses en sortent : les clés
`seamark:*` jamais documentées (candidates au catalogue), et la couverture
réelle de chaque clé exploitée.

C'est un RAPPORT, pas un contrôle : la liste bouge quand OSM bouge, un
contributeur qui invente un tag ne doit jamais faire échouer une CI.
Le script sort toujours avec le code 0 (sauf erreur de connexion).

Usage :
  python scripts/audit_tags.py                              # audit Mongo (marinas + capitaineries)
  python scripts/audit_tags.py --out docs/audits/tags.md    # écrit le rapport Markdown
  python scripts/audit_tags.py --geojson export1.geojson …  # couverture des champs, sans Mongo (CI)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO_ROOT / "backend" / "data" / "seamark_catalog.json"

TOP_N = 25


def load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- Mongo mode

def collect_tag_stats(tag_dicts) -> dict:
    """Compte clés, familles seamark et valeurs de seamark:type."""
    key_counts: Counter = Counter()
    seamark_types: Counter = Counter()
    seamark_subkeys: dict[str, set] = {}
    docs = 0
    docs_with_tags = 0
    for tags in tag_dicts:
        docs += 1
        if not tags:
            continue
        docs_with_tags += 1
        for key, value in tags.items():
            key_counts[key] += 1
            if key == "seamark:type":
                seamark_types[str(value)] += 1
                continue
            if key.startswith("seamark:"):
                segs = key.split(":")[1:]
                typ = segs[0]
                if typ.isdigit() or not segs:
                    continue
                seamark_types[typ] += 0  # présence de la famille, sans double compte
                sub = next((s for s in reversed(segs[1:]) if not s.isdigit()), None)
                if sub:
                    seamark_subkeys.setdefault(sub, set()).add(typ)
    return {
        "docs": docs,
        "docs_with_tags": docs_with_tags,
        "key_counts": key_counts,
        "seamark_types": seamark_types,
        "seamark_subkeys": seamark_subkeys,
    }


def audit_mongo(mongo_url: str, db_name: str, catalog: dict) -> list[str]:
    from pymongo import MongoClient
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=8000)
    db = client[db_name]
    lines: list[str] = []

    documented_keys = {e["key"] for e in catalog["exact_keys"]}
    key_status = {e["key"]: e["status"] for e in catalog["exact_keys"]}
    documented_types = {t["type"]: t["status"] for t in catalog["seamark_types"]}
    documented_subkeys = set(catalog["seamark_subkeys_documented"])
    prefixes = tuple(catalog.get("prefixes_documented") or [])

    for coll_name in ("marinas", "capitaineries"):
        cursor = db[coll_name].find({}, {"tags": 1, "_id": 0})
        stats = collect_tag_stats((d.get("tags") or {}) for d in cursor)
        docs = stats["docs"]
        lines.append(f"\n## Collection `{coll_name}`")
        lines.append(f"\n{docs} documents, {stats['docs_with_tags']} avec tags.")
        if not docs:
            continue

        lines.append("\n### Couverture des clés exploitées (catalogue)\n")
        lines.append("| clé | docs | % |")
        lines.append("|---|---:|---:|")
        exploited = [e["key"] for e in catalog["exact_keys"] if e["status"] == "exploite"]
        covered = [(k, stats["key_counts"].get(k, 0)) for k in exploited]
        for key, count in sorted(covered, key=lambda kv: -kv[1]):
            if count:
                lines.append(f"| `{key}` | {count} | {100.0 * count / docs:.1f} |")
        absent = [k for k, c in covered if not c]
        if absent:
            lines.append(f"\nJamais observées ici : {', '.join('`' + k + '`' for k in sorted(absent))}.")

        if stats["seamark_types"]:
            lines.append("\n### Familles seamark observées\n")
            lines.append("| seamark:type / famille | occurrences | statut catalogue |")
            lines.append("|---|---:|---|")
            for typ, count in stats["seamark_types"].most_common():
                status = documented_types.get(typ, "HORS CATALOGUE — candidat ?")
                lines.append(f"| `{typ}` | {count} | {status} |")

        undocumented_sub = sorted(
            ((sub, types) for sub, types in stats["seamark_subkeys"].items()
             if sub not in documented_subkeys),
            key=lambda kv: -len(kv[1]),
        )
        if undocumented_sub:
            lines.append("\n### Sous-clés seamark non documentées (candidates)\n")
            for sub, types in undocumented_sub[:TOP_N]:
                lines.append(f"- `seamark:*:{sub}` — portée par {len(types)} famille(s) : {', '.join(sorted(types))}")
            if len(undocumented_sub) > TOP_N:
                lines.append(f"- … et {len(undocumented_sub) - TOP_N} de plus")

        others = [
            (k, c) for k, c in stats["key_counts"].most_common()
            if k not in documented_keys and not k.startswith("seamark:")
            and not any(k.startswith(p) for p in prefixes)
        ]
        if others:
            lines.append("\n### Clés hors catalogue les plus fréquentes (candidates)\n")
            for key, count in others[:TOP_N]:
                rare = " *(rare)*" if count <= 2 else ""
                lines.append(f"- `{key}` × {count}{rare}")
            if len(others) > TOP_N:
                lines.append(f"- … et {len(others) - TOP_N} de plus")
    return lines


# -------------------------------------------------------------- GeoJSON mode

def audit_geojson(paths: list[str]) -> list[str]:
    lines: list[str] = []
    for raw in paths:
        path = Path(raw)
        lines.append(f"\n## Export `{path.name}`")
        try:
            fc = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # fichier absent / invalide : on le dit, on continue
            lines.append(f"\nIllisible : {e}")
            continue
        feats = fc.get("features") or []
        meta = fc.get("metadata") or {}
        version = meta.get("version") or "non versionné"
        lines.append(f"\n{len(feats)} features — version `{version}`.")
        if not feats:
            continue
        filled: Counter = Counter()
        svc_questions: Counter = Counter()
        for f in feats:
            props = f.get("properties") or {}
            for k, v in props.items():
                if v not in (None, "", [], {}):
                    filled[k] += 1
            for q in (props.get("svc") or {}):
                svc_questions[q] += 1
        lines.append("\n| propriété | remplie | % |")
        lines.append("|---|---:|---:|")
        for key, count in filled.most_common(30):
            lines.append(f"| `{key}` | {count} | {100.0 * count / len(feats):.1f} |")
        if svc_questions:
            lines.append("\nBadges services (`svc`) : "
                         + ", ".join(f"{q}={c}" for q, c in svc_questions.most_common()))
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-url", default=os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))
    parser.add_argument("--db", default=os.environ.get("DB_NAME", "blue_intelligence"))
    parser.add_argument("--geojson", nargs="+", help="Audite des exports GeoJSON au lieu de Mongo")
    parser.add_argument("--out", help="Écrit le rapport Markdown dans ce fichier (défaut stdout)")
    args = parser.parse_args()

    catalog = load_catalog()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = [
        "# Audit des tags — Blue Intelligence",
        f"\nGénéré le {now} · catalogue v{catalog.get('version')} "
        f"(`backend/data/seamark_catalog.json`)",
        "\nRapport, pas contrôle : les candidats demandent un œil humain avant "
        "d'entrer au catalogue (les données OSM réelles contiennent des typos).",
    ]
    if args.geojson:
        body = audit_geojson(args.geojson)
    else:
        body = audit_mongo(args.mongo_url, args.db, catalog)
    report = "\n".join(header + body) + "\n"

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"rapport écrit → {out_path}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
