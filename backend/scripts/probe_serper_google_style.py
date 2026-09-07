"""Probe Serper : phrase courte + TLD sur les 11 polygones, puis les autres ZEE.

Usage :
  python scripts/probe_serper_google_style.py
  python scripts/probe_serper_google_style.py --limit 80
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import importlib.util  # noqa: E402

from app.core.serper import serper_api_key, serper_search  # noqa: E402
from app.services import poe_pipeline as poe  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "probe_example_sources", BACKEND / "scripts" / "probe_example_sources.py")
_ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ex)
EXAMPLE_ZONES = _ex.EXAMPLE_ZONES
PINNED_NEEDLES = _ex.PINNED_NEEDLES
TARGET_MRGIDS = _ex.TARGET_MRGIDS

INDEX = BACKEND / "data" / "listing_control" / "eez_index.json"


def _zone_from_index(row: dict) -> dict:
    z = dict(row)
    z.setdefault("sov_iso2", z.get("iso2") or "")
    return z


def _officialish(hits: list[dict], zone: dict) -> list[dict]:
    wl = poe.build_whitelist(zone.get("iso2"), zone.get("sov_iso2"))
    out = []
    for h in hits:
        u = h.get("url") or ""
        if poe.url_allowed(u, wl) or poe.OFFICIAL_TOKENS.search(h.get("domain") or u):
            out.append(h)
    return out


async def probe_zone(zone: dict, key: str) -> dict:
    iso = poe.zone_search_location(zone)
    shots = poe.google_style_shots(zone)
    all_hits: list[dict] = []
    shot_rows = []
    for lang, q in shots:
        hits = await serper_search(q, key, gl=iso, hl=lang)
        all_hits.extend(hits)
        shot_rows.append({"lang": lang, "query": q, "n": len(hits),
                          "domains": [h.get("domain") for h in hits[:8]]})
        if not hits and lang == shots[-1][0]:
            # 402 / clé vide : le client renvoie [] — on le signale en haut.
            pass
    seen, merged = set(), []
    for h in all_hits:
        u = h.get("url") or ""
        if u and u not in seen:
            seen.add(u)
            merged.append(h)
    official = _officialish(merged, zone)
    blob = " ".join((h.get("url") or "") for h in merged)
    needles = list(PINNED_NEEDLES.get(zone.get("mrgid") or 0) or [])
    needles_hit = [n for n in needles if n in blob]
    return {
        "mrgid": zone.get("mrgid"),
        "name": zone.get("name"),
        "iso2": zone.get("iso2"),
        "shots": shot_rows,
        "n_hits": len(merged),
        "n_officialish": len(official),
        "official_domains": sorted({h.get("domain") for h in official if h.get("domain")}),
        "needles": needles,
        "needles_hit": needles_hit,
        "top_urls": [h.get("url") for h in official[:6] or merged[:4]],
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="Plafond de ZEE hors des 11 (0 = toutes)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    key = serper_api_key()
    if not key:
        print("SERPER_API_KEY absente", file=sys.stderr)
        return 2

    index = json.loads(INDEX.read_text()) if INDEX.exists() else {"zones": []}
    extra = []
    seen = set(TARGET_MRGIDS)
    for row in index.get("zones") or []:
        mid = row.get("mrgid")
        if not mid or mid in seen:
            continue
        if poe.UNINHABITED_RE.search(row.get("name") or ""):
            continue
        extra.append(_zone_from_index(row))
        seen.add(mid)
        if args.limit and len(extra) >= args.limit:
            break

    ordered = [EXAMPLE_ZONES[mid] for mid in TARGET_MRGIDS] + extra
    reports = []
    for z in ordered:
        rep = await probe_zone(z, key)
        reports.append(rep)
        mark = "OK" if (rep["n_officialish"] or rep["needles_hit"]) else "—"
        print(f"{mark} {rep['iso2']:3} {rep['name'][:28]:28} "
              f"hits={rep['n_hits']:2} official={rep['n_officialish']:2} "
              f"needles={len(rep['needles_hit'])}/{len(rep['needles'])} "
              f"{','.join(rep['official_domains'][:4])}")
        if rep["n_hits"] == 0 and all(s["n"] == 0 for s in rep["shots"]):
            print("stop: Serper vide (crédits ou erreur)", file=sys.stderr)
            break

    summary = {
        "n_zones": len(reports),
        "n_with_official": sum(1 for r in reports if r["n_officialish"]),
        "n_needles_ok": sum(1 for r in reports if r["needles"] and r["needles_hit"]),
        "reports": reports,
    }
    out = args.out or (Path("/opt/cursor/artifacts") / "serper_google_style_probe.json")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"wrote {out}")
    except OSError:
        fallback = BACKEND / "data" / "serper_google_style_probe.json"
        fallback.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"wrote {fallback}")
    print(f"zones={summary['n_zones']} officialish={summary['n_with_official']} "
          f"needles_ok={summary['n_needles_ok']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
