"""Juge de lieu d'action (CDC Projets v2, phase C).

Un toponyme n'est publiable que s'il désigne un lieu marin visitable
(récif, AMP, baie, côte, île), pas un siège d'ONG ni une région trop vague.
Géocodage : Nominatim puis GeoNames, plus une requête « marine protected area »
si le nom y ressemble. Aucun snap, aucun fallback océanique, aucun GPS inventé.
"""
from __future__ import annotations

import re

from app.core.geo import geocode
from app.core.project_geo import site_publishable, valid_coords

HQ_WORDS = (
    "headquarters", "head office", "head-office", "siege social", "siège social",
    "siège", "registered office", "global office", "regional office",
    "based in washington", "washington, d.c.", "washington dc",
)
HQ_WORD_RE = re.compile(
    r"\b(hq|headquarters|offices?|bureau|si[eè]ge)\b",
    re.I,
)

# Villes-sièges fréquentes : refusées seulement si le toponyme EST la ville
# (sans mot marin). « Olympic Coast, Washington » passe.
HQ_CITIES = {
    "washington", "washington dc", "washington d c",
    "new york", "new york city", "nyc",
    "london", "paris", "brussels", "bruxelles",
    "geneva", "genève", "geneve",
    "rome", "berlin", "amsterdam",
    "arlington", "bethesda",
}

GENERIC_REGIONS = {
    "global", "worldwide", "world", "international", "earth", "planet",
    "the ocean", "ocean", "oceans", "sea", "high seas",
    "pacific", "atlantic", "indian ocean", "southern ocean", "arctic",
    "pacific ocean", "atlantic ocean",
}

MARINE_TOPONYM = (
    "reef", "coral", "bay", "gulf", "lagoon", "atoll", "mangrove",
    "seagrass", "estuary", "seamount", "mpa", "marine protected",
    "hope spot", "hope-spot", "coast", "coastal", "island", "isle",
    "archipelago", "harbour", "harbor", "fjord", "sound", "strait",
    "channel", "cape", "peninsula", "shoal", "bank", "amp",
    "aire marine", "réserve marine", "reserve marine",
)

_NON_ALNUM = re.compile(r"[^a-z0-9\s]+")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", _NON_ALNUM.sub(" ", (s or "").lower())).strip()


def has_marine_toponym(*parts: str) -> bool:
    blob = " ".join(p or "" for p in parts).lower()
    return any(w in blob for w in MARINE_TOPONYM)


def looks_like_hq(name: str = "", location: str = "", evidence: str = "",
                  funder: str = "") -> tuple[bool, str]:
    """True si le toponyme est un siège / ville HQ, pas un lieu d'action."""
    blob = f"{name} {location} {evidence}".lower()
    if any(w in blob for w in HQ_WORDS) or HQ_WORD_RE.search(blob):
        if not has_marine_toponym(name, location, evidence):
            return True, "hq_keyword"
    loc = _norm(location or name)
    if loc in HQ_CITIES or loc.replace(" ", "") in {c.replace(" ", "") for c in HQ_CITIES}:
        if not has_marine_toponym(name, location, evidence):
            return True, "hq_city"
    # « Pew Charitable Trusts, Washington » : le financeur + une capitale
    funder_l = (funder or "").lower()
    if funder_l and loc in HQ_CITIES and not has_marine_toponym(name, location, evidence):
        return True, "hq_funder_city"
    return False, ""


def looks_generic(name: str = "", location: str = "") -> bool:
    loc = _norm(location or name)
    return loc in GENERIC_REGIONS


def normalize_extracted_sites(proj: dict) -> list[dict]:
    """sites[] du LLM, sinon un site unique depuis location / lat / lon."""
    out: list[dict] = []
    raw = proj.get("sites")
    if isinstance(raw, list):
        for s in raw:
            if not isinstance(s, dict):
                continue
            name = str(s.get("name") or s.get("location") or "").strip()
            loc = str(s.get("location") or s.get("name") or "").strip() or None
            if not name and not loc:
                continue
            lat = s.get("lat") if s.get("lat") is not None else s.get("latitude")
            lon = s.get("lon") if s.get("lon") is not None else s.get("longitude")
            out.append({
                "name": (name or loc or "")[:200],
                "location": loc or name,
                "lat": lat,
                "lon": lon,
                "evidence": str(s.get("evidence") or "")[:400],
            })
    if out:
        return out[:20]
    loc = proj.get("location")
    lat, lon = proj.get("latitude"), proj.get("longitude")
    if loc or valid_coords(lat, lon):
        return [{
            "name": str(loc or proj.get("title") or "")[:200],
            "location": loc,
            "lat": lat,
            "lon": lon,
            "evidence": "",
        }]
    return []


def heuristic_judge(site: dict, funder: str = "", settings: dict | None = None) -> dict:
    name = site.get("name") or ""
    loc = site.get("location") or ""
    ev = site.get("evidence") or ""
    hq, why = looks_like_hq(name, loc, ev, funder)
    if hq:
        return {"accepted": False, "reason": why, "kind": "hq", "engine": "heuristic"}
    if looks_generic(name, loc):
        return {"accepted": False, "reason": "generic_region", "kind": "generic",
                "engine": "heuristic"}
    ok, kind = site_publishable(site.get("lat"), site.get("lon"), settings)
    if ok:
        return {"accepted": True, "reason": kind, "kind": kind, "engine": "heuristic"}
    return {"accepted": False, "reason": kind, "kind": kind, "engine": "heuristic"}


async def geocode_action_site(site: dict) -> dict:
    """Nominatim → GeoNames. Tentative AMP si le nom y ressemble. Pas de LLM GPS."""
    loc = (site.get("location") or site.get("name") or "").strip()
    name = (site.get("name") or loc).strip()
    queries = []
    if loc:
        queries.append(loc)
    if name and name != loc:
        queries.append(name)
    if name and any(w in name.lower() for w in ("mpa", "protected", "reserve", "hope spot", "amp")):
        queries.append(f"{name} marine protected area")
    elif loc:
        queries.append(f"{loc} marine protected area")
    seen = set()
    for q in queries:
        key = q.lower()
        if not q or key in seen:
            continue
        seen.add(key)
        coords = await geocode(q)
        if coords:
            return {"lat": coords[0], "lon": coords[1], "geo_source": "geocoded",
                    "query": q}
    return {"lat": None, "lon": None, "geo_source": None, "query": None}


async def llm_judge_site(site: dict, funder: str, settings: dict | None) -> dict | None:
    """Veto / confirmation. N'invente jamais de GPS."""
    from app.core.llm import ask_json, has_llm
    if not has_llm(settings):
        return None
    prompt = f"""You judge whether a toponym is a visitable marine ACTION site
(boat-accessible reef, MPA, bay, coast, island, hope spot) or something we must refuse
(NGO headquarters, funder city, generic ocean/region, inland office).

Funder: {funder or 'unknown'}
Site name: {site.get('name') or ''}
Location: {site.get('location') or ''}
Evidence from the page: {site.get('evidence') or ''}
Coordinates if any: {site.get('lat')}, {site.get('lon')}

Return JSON:
{{"action_site": true/false, "kind": "ocean|coastal|hq|generic|inland|unlocated",
  "reason": "<short>"}}
action_site=true ONLY if a skipper could theoretically go see the work there.
false for Washington/Paris/London HQ, "global", "Pacific Ocean" without an island, offices."""
    try:
        out = await ask_json(prompt, settings=settings, max_tokens=250)
        accepted = bool(out.get("action_site"))
        kind = str(out.get("kind") or ("ocean" if accepted else "unlocated"))
        return {
            "accepted": accepted,
            "reason": str(out.get("reason") or "")[:240],
            "kind": kind,
            "engine": "openrouter-judge",
        }
    except Exception:
        return None


async def resolve_sites(proj: dict, funder: str = "", settings: dict | None = None,
                        log=None) -> dict:
    """Géocode + juge chaque site. Retourne ok[] / rejected[] / verdict."""
    log = log or (lambda m: None)
    settings = settings or {}
    sites = normalize_extracted_sites(proj)
    if not sites:
        return {"ok": [], "rejected": [], "verdict": "unlocated", "reason": "no_sites"}

    ok, rejected = [], []
    for site in sites:
        if not valid_coords(site.get("lat"), site.get("lon")):
            geo = await geocode_action_site(site)
            site["lat"], site["lon"] = geo.get("lat"), geo.get("lon")
            site["geo_source"] = geo.get("geo_source")
        else:
            site["geo_source"] = site.get("geo_source") or "extracted"

        judged = heuristic_judge(site, funder, settings)
        if judged["kind"] in ("hq", "generic"):
            site["verdict"] = judged["kind"]
            site["judge"] = judged
            rejected.append(site)
            log(f"juge: {site.get('name')[:50]} → {judged['kind']}")
            continue

        if not judged["accepted"] and judged["kind"] != "no_coords":
            llm = await llm_judge_site(site, funder, settings)
            if llm and not llm["accepted"]:
                judged = llm
            elif llm and llm["accepted"] and site_publishable(
                    site.get("lat"), site.get("lon"), settings)[0]:
                judged = llm

        pub_ok, kind = site_publishable(site.get("lat"), site.get("lon"), settings)
        if judged["accepted"] and pub_ok and judged["kind"] not in ("hq", "generic"):
            site["verdict"] = "site_ok"
            site["geo_kind"] = kind
            site["judge"] = judged
            ok.append(site)
            log(f"juge: {site.get('name')[:50]} → site_ok ({kind})")
        else:
            site["verdict"] = judged.get("kind") or kind or "unlocated"
            site["geo_kind"] = kind
            site["judge"] = judged
            rejected.append(site)
            log(f"juge: {site.get('name')[:50]} → {site['verdict']}")

    if ok:
        return {"ok": ok, "rejected": rejected, "verdict": "site", "reason": None}
    reason = (rejected[0].get("verdict") if rejected else "no_sites")
    return {"ok": [], "rejected": rejected, "verdict": "unlocated", "reason": reason}
