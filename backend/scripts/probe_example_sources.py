"""Run ciblé : FR hexagone, MX, VE, NU, NZ, NC, Sint Maarten.

1) collecte les graines / pages d'entrée + pièces jointes (preuve découverte)
2) option --run : upsert les ZEE depuis eez_world_map.geojson puis
   execute_run isolé (poe_run_* uniquement).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.core.extract import extract_structured_ports  # noqa: E402
from app.services import poe_pipeline as poe  # noqa: E402
from app.services.poe_pipeline import _collect_texts  # noqa: E402

EXAMPLE_ZONES = {
    5677: {
        "iso2": "FR", "sov_iso2": "FR", "name": "France", "sovereign": "France",
        "pol_type": "200NM", "mrgid": 5677,
    },
    8429: {
        "iso2": "MX", "sov_iso2": "MX", "name": "Mexico", "sovereign": "Mexico",
        "pol_type": "200NM", "mrgid": 8429,
    },
    8433: {
        "iso2": "VE", "sov_iso2": "VE", "name": "Venezuela", "sovereign": "Venezuela",
        "pol_type": "200NM", "mrgid": 8433,
    },
    8447: {
        "iso2": "NU", "sov_iso2": "NZ", "name": "Niue", "sovereign": "New Zealand",
        "pol_type": "200NM", "mrgid": 8447,
    },
    8455: {
        "iso2": "NZ", "sov_iso2": "NZ", "name": "New Zealand", "sovereign": "New Zealand",
        "pol_type": "200NM", "mrgid": 8455,
    },
    8312: {
        "iso2": "NC", "sov_iso2": "FR", "name": "New Caledonia", "sovereign": "France",
        "pol_type": "200NM", "mrgid": 8312,
    },
    21803: {
        "iso2": "SX", "sov_iso2": "NL", "name": "Sint-Maarten", "sovereign": "Netherlands",
        "pol_type": "200NM", "mrgid": 21803,
    },
}
PINNED_NEEDLES = {
    5677: ["vous-naviguez-en-provenance"],
    8429: ["puertos-y-terminales"],
    8433: ["Ley-de-Marinas-y-Actividades-Conexas.pdf",
           "CAPITANIAS-DE-PUERTO"],
    8447: ["niue_laws_vol4_part1"],
    8455: ["places-of-first-arrival-seaports",
           "sailing-to-new-zealand-this-small-craft-season"],
    8312: ["formalites-douanieres-pour-les-navires-de-plaisance"],
    21803: ["sintmaartengov.org", "Pages/Customs.aspx"],
}

FR_PDF_NEEDLES = (
    "Liste-ports-de-plaisance-eligibles.pdf",
    "carte-PPF-maritimes.pdf",
)
TARGET_MRGIDS = (5677, 8429, 8433, 8447, 8455, 8312, 21803)
SOV_ISO2 = {5677: "FR", 8429: "MX", 8433: "VE", 8447: "NZ", 8455: "NZ",
            8312: "FR", 21803: "NL"}


def _blob(rows: list[dict]) -> str:
    return " ".join((r.get("url") or "") for r in rows)


async def probe_zone(zone: dict) -> dict:
    pinned = poe.seed_url_candidates(zone) + poe.landing_url_candidates(zone)
    logs: list[str] = []
    texts, hashes, used, _ = await _collect_texts(pinned, logs.append, max_fetch=8)
    found = _blob(pinned + used)
    needles = list(PINNED_NEEDLES[zone["mrgid"]])
    if zone["mrgid"] == 5677:
        needles.extend(FR_PDF_NEEDLES)
    missing = [n for n in needles if n not in found]
    ports = extract_structured_ports("\n\n".join(texts))
    return {
        "mrgid": zone["mrgid"],
        "name": zone.get("name"),
        "iso2": zone.get("iso2"),
        "pinned": [c["url"] for c in pinned],
        "used": [c.get("url") for c in used],
        "fetched_chars": sum(len(t) for t in texts),
        "needles_ok": not missing,
        "missing": missing,
        "ports": [p.get("name") for p in ports],
        "n_ports": len(ports),
        "logs": logs,
    }


async def upsert_example_zones(db) -> int:
    path = BACKEND / "data" / "eez_world_map.geojson"
    data = json.loads(path.read_text(encoding="utf-8"))
    want = set(TARGET_MRGIDS)
    n = 0
    for feat in data.get("features") or []:
        props = feat.get("properties") or {}
        try:
            mid = int(props.get("mrgid"))
        except (TypeError, ValueError):
            continue
        if mid not in want:
            continue
        doc = {
            "mrgid": mid,
            "name": props.get("name"),
            "geoname": props.get("geoname"),
            "iso2": props.get("iso2"),
            "sovereign": props.get("sovereign"),
            "sov_iso2": SOV_ISO2[mid],
            "pol_type": props.get("pol_type"),
            "geometry": feat.get("geometry"),
            "updated_at": poe.now_iso(),
        }
        await db.eez_zones.update_one(
            {"mrgid": mid},
            {"$set": doc, "$setOnInsert": {
                "status": "non_generee", "poe_count": 0,
                "sources": [], "source_hashes": {}, "last_error": None,
            }},
            upsert=True,
        )
        n += 1
    return n


async def run_isolated(db, label: str, variant: str) -> dict:
    from app.core.tasks import TaskState
    from app.services import poe_runs
    state = TaskState(max_logs=4000)
    state.start()
    rid = poe_runs.new_run_id()
    summary = await poe_runs.execute_run(
        db, state, rid, label=label, only_zones=list(TARGET_MRGIDS),
        concurrency=1, variant=variant)
    state.finish()
    return {"run_id": rid, "summary": summary, "logs": state.logs,
            "results": state.results, "error": state.error}


async def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--run", action="store_true",
                   help="upsert les 6 ZEE et lancer un run isolé")
    p.add_argument("--variant", default="v2")
    p.add_argument("--label", default="example-official-sources")
    args = p.parse_args(argv)

    print("=== collecte ciblée (graines + PJ) ===")
    reports = []
    for mid in TARGET_MRGIDS:
        rep = await probe_zone(EXAMPLE_ZONES[mid])
        reports.append(rep)
        flag = "OK" if rep["needles_ok"] else "MANQUE"
        print(f"[{flag}] {rep['name']} ({mid}) used={len(rep['used'])} "
              f"chars={rep['fetched_chars']} ports={rep['n_ports']} "
              f"missing={rep['missing']}")
        for u in rep["used"]:
            print(f"    {u}")
        for name in (rep.get("ports") or [])[:12]:
            print(f"      · {name}")

    out = {"probes": reports}
    if args.run:
        from app.db import db
        n = await upsert_example_zones(db)
        print(f"=== upsert {n} ZEE — run {args.variant} ===")
        out["run"] = await run_isolated(db, args.label, args.variant)
        print("run_id", out["run"]["run_id"])
        for line in out["run"]["logs"][-40:]:
            print(line)
        if out["run"]["results"]:
            print("results", out["run"]["results"])

    dest = Path("/opt/cursor/artifacts/example_sources_probe.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    print("wrote", dest)
    return 0 if all(r["needles_ok"] for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
