"""Analyse le run des 11 : needles, serper/google_style, graines SX/AL.

Lit d'abord le JSONL local (backend/data/runs/<run_id>.jsonl) pour ne pas
dépendre d'un primary Mongo. Mongo reste un complément si disponible.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

RUN_ID = (Path("/opt/cursor/artifacts/serper_11_run_id.txt").read_text().strip()
          if Path("/opt/cursor/artifacts/serper_11_run_id.txt").exists() else "")

NEEDLES = {
    5677: ["vous-naviguez-en-provenance", "Liste-ports-de-plaisance", "carte-PPF"],
    8429: ["puertos-y-terminales"],
    8433: ["Ley-de-Marinas", "CAPITANIAS", "inea.gob.ve"],
    8447: ["niue_laws"],
    8455: ["places-of-first-arrival", "small-craft"],
    8312: ["formalites-douanieres"],
    21803: ["sintmaartengov.org", "Pages/Customs.aspx"],
    48944: ["JORFTEXT000030235682"],
    5696: ["submit-a-pleasure-craft-report"],
    8490: ["sis.gov.eg", "yacht-tourism"],
    5670: ["dogana.gov.al", "autorizim-per-perjashtimin", "peshkimit"],
}
SEEDS = {
    21803: "sintmaartengov.org",
    5670: "dogana.gov.al",
}
# Plancher poe_count après le correctif catalog_skip (listes sans GPS).
MIN_POE = {
    5677: 10,   # liste PPF
    8429: 10,   # habilitados turística
    8455: 5,    # MPI PoFA
    8490: 4,    # marinas SIS
    5670: 4,    # kartelë Dogana
    21803: 2,   # Simpson + Great Bay
}
PORT_NEEDLES = {
    8490: ["Hurghada", "Marina"],
    5670: ["Durrës", "Shëngjin", "Vlorë", "Sarandë"],
    21803: ["Simpson", "Great"],
    8455: ["Auckland", "Tauranga"],
}
ISO = {
    5677: "FR", 8429: "MX", 8433: "VE", 8447: "NU", 8455: "NZ",
    8312: "NC", 21803: "SX", 48944: "YT", 5696: "GB", 8490: "EG",
    5670: "AL",
}


def _jsonl_path(rid: str) -> Path:
    return BACKEND / "data" / "runs" / f"{rid}.jsonl"


def _load_jsonl(rid: str) -> list[dict]:
    path = _jsonl_path(rid)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _analyze(rid: str, events: list[dict], run_state: str | None = None) -> dict:
    by: dict[int | None, list[dict]] = defaultdict(list)
    for e in events:
        by[e.get("mrgid")].append(e)

    reports = []
    for mid, needles in NEEDLES.items():
        evs = by.get(mid, [])
        srcs = [(e.get("payload") or {}).get("url") or ""
                for e in evs if e.get("step") == "source_used"]
        blob = " ".join(srcs)
        serper = [e for e in evs if e.get("step") == "search"
                  and (e.get("payload") or {}).get("engine") == "serper"]
        gstyle = [e for e in serper
                  if (e.get("payload") or {}).get("round") == "google_style"]
        serper_urls = []
        for e in gstyle:
            for r in (e.get("payload") or {}).get("results") or []:
                serper_urls.append(r.get("url") or "")
        zd = next((e for e in evs if e.get("step") == "zone_done"), None)
        pl = (zd or {}).get("payload") or {}
        seed_hit = (SEEDS[mid] in blob) if mid in SEEDS else None
        port_names = [(e.get("payload") or {}).get("name") or ""
                      for e in evs if e.get("step") == "port"]
        pblob = " ".join(port_names)
        want_ports = PORT_NEEDLES.get(mid, [])
        min_poe = MIN_POE.get(mid)
        poe_n = pl.get("poe_count", 0) or 0
        reports.append({
            "mrgid": mid,
            "name": (evs[0].get("zone") if evs else None),
            "iso2": ISO.get(mid),
            "status": pl.get("status"),
            "poe_count": poe_n,
            "min_poe": min_poe,
            "poe_ok": (True if min_poe is None else poe_n >= min_poe),
            "port_names": port_names[:20],
            "port_needles_hit": [n for n in want_ports if n in pblob],
            "port_needles_miss": [n for n in want_ports if n not in pblob],
            "sources": srcs,
            "needles_hit": [n for n in needles if n in blob],
            "needles_miss": [n for n in needles if n not in blob],
            "serper_events": len(serper),
            "google_style_events": len(gstyle),
            "serper_queries": [(e.get("payload") or {}).get("query") for e in gstyle],
            "needle_in_serper": [n for n in needles
                                 if any(n in u for u in serper_urls)],
            "seed_used": seed_hit,
        })

    n_serper = sum(1 for e in events if e.get("step") == "search"
                   and (e.get("payload") or {}).get("engine") == "serper")
    n_gs = sum(1 for e in events if e.get("step") == "search"
               and (e.get("payload") or {}).get("engine") == "serper"
               and (e.get("payload") or {}).get("round") == "google_style")
    return {
        "run_id": rid,
        "run_state": run_state or (
            "done" if any(e.get("step") == "run_done" for e in events) else "running"),
        "zones": sum(1 for r in reports if r["serper_events"] or r["sources"]),
        "serper_search_events": n_serper,
        "google_style_events": n_gs,
        "all_needles_ok": all(not r["needles_miss"] for r in reports),
        "all_serper_google_style": all(r["google_style_events"] >= 1 for r in reports),
        "all_poe_ok": all(r["poe_ok"] for r in reports),
        "reports": reports,
    }


def main() -> int:
    rid = sys.argv[1] if len(sys.argv) > 1 else RUN_ID
    if not rid:
        print("no run id", file=sys.stderr)
        return 2
    events = _load_jsonl(rid)
    if not events:
        print(f"JSONL introuvable: {_jsonl_path(rid)}", file=sys.stderr)
        return 2
    summary = _analyze(rid, events)
    dest = Path("/opt/cursor/artifacts/serper_11_analysis.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    print(f"run {rid} state={summary['run_state']} zones={summary['zones']} "
          f"serper={summary['serper_search_events']} "
          f"google_style={summary['google_style_events']} "
          f"needles_ok={summary['all_needles_ok']} poe_ok={summary['all_poe_ok']}")
    for r in summary["reports"]:
        miss = ",".join(r["needles_miss"]) or "-"
        seed = "" if r["seed_used"] is None else f" seed={r['seed_used']}"
        floor = "" if r.get("min_poe") is None else f" min={r['min_poe']}"
        pmiss = ",".join(r.get("port_needles_miss") or []) or "-"
        print(f"{(r.get('iso2') or '?'):3} {r.get('status')} poe={r.get('poe_count')}{floor} "
              f"serper={r['serper_events']}/{r['google_style_events']} "
              f"needles={len(r['needles_hit'])}/{len(r['needles_hit'])+len(r['needles_miss'])} "
              f"miss={miss} ports_miss={pmiss} in_serper={r['needle_in_serper'] or '-'}{seed}")
    print("wrote", dest)
    ok = (summary["all_needles_ok"] and summary["all_serper_google_style"]
          and summary["all_poe_ok"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
