"""URLs officielles curées (territories.json) rattachées à un polygone VLIZ.

Lecture seule. Ne pas importer zee_crossings (WFS / shapely) depuis la fiche.
Le mapping MRGID → code est le même que dans zee_crossings.MRGID_TO_TERRITORY.
"""
from __future__ import annotations

import json
from functools import lru_cache

from app.config import DATA_DIR

# VLIZ v12 → territories.json (vérifié 2026-06, même table que zee_crossings).
MRGID_TO_TERRITORY: dict[int, str | None] = {
    5677: "france_metropolitaine",
    48966: "france_metropolitaine",
    48976: "france_metropolitaine",
    8440: "polynesie_francaise",
    8312: "nouvelle_caledonie",
    48948: "nouvelle_caledonie",
    33178: "martinique",
    33177: "guadeloupe",
    48952: "saint_barthelemy",
    8495: "saint_martin",
    8462: "guyane",
    8454: "wallis_et_futuna",
    8338: "la_reunion",
    48944: "mayotte",
    8494: "saint_pierre_et_miquelon",
    48946: "taaf",
    48945: "taaf",
    8341: "taaf",
    8339: "taaf",
    8340: "taaf",
    8386: "taaf",
    8385: "taaf",
    8387: "taaf",
    8401: None,
}


@lru_cache(maxsize=1)
def _territories() -> dict[str, dict]:
    path = DATA_DIR / "territories.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    out: dict[str, dict] = {}
    for rec in data.get("territories") or []:
        code = rec.get("code")
        if code:
            out[str(code)] = rec
    return out


def _territory_for_mrgid(mrgid) -> dict:
    try:
        mid = int(mrgid or 0)
    except (TypeError, ValueError):
        return {}
    code = MRGID_TO_TERRITORY.get(mid)
    if not code:
        return {}
    return _territories().get(code) or {}


def curated_landing_urls(mrgid) -> list[dict]:
    """Page d'État de CE polygone — point d'entrée crawl, pas un PDF figé.

    Les PDF liés changent (liste plaisance 2025 → 2026). On part de la page
    et on suit les pièces jointes courantes. Jamais les ref_url des ports
    (elles pinent un fichier périmé).
    """
    raw = (_territory_for_mrgid(mrgid).get("ref_url") or "").strip()
    if not raw.startswith("http"):
        return []
    return [{"url": raw, "official": True, "from_arm": "landing"}]


def curated_td_urls(mrgid) -> list[dict]:
    """Pages / PDF d'État curés pour CE polygone — pas l'agrégat souverain."""
    terr = _territory_for_mrgid(mrgid)
    if not terr:
        return []
    urls: list[str] = []
    for port in terr.get("ports_of_entry") or []:
        if isinstance(port, dict) and port.get("ref_url"):
            urls.append(str(port["ref_url"]))
    if terr.get("ref_url"):
        urls.append(str(terr["ref_url"]))
    seen: set[str] = set()
    out: list[dict] = []
    for raw in urls:
        u = raw.strip()
        if not u.startswith("http") or u in seen:
            continue
        seen.add(u)
        out.append({"url": u, "official": True, "from_arm": "td"})
    return out
