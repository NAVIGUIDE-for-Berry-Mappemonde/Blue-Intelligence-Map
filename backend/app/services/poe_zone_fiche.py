"""
poe_zone_fiche — Fiche de revue d'une ZEE (lecture seule).

Assemble la liste des PoE publiés et les URLs d'État Top-Down / Bottom-Up
à partir des collections déjà en base. N'écrit jamais poe_ports / eez_zones.
Le WPI n'est pas une source. Noonsite et les forums n'entrent pas.
"""
from __future__ import annotations

import json
from functools import lru_cache
from urllib.parse import urlparse

from app.config import DATA_DIR
from app.services.poe_pipeline import domain_of, list_url_bonus, zone_to_item
from app.services.poe_seeds import SEARCH_EXCLUDE_DOMAINS, url_is_excluded_search

FICHE_URL_CAP = 12


@lru_cache(maxsize=1)
def _community_hosts() -> tuple[str, ...]:
    hosts = {h.lower() for h in SEARCH_EXCLUDE_DOMAINS}
    path = DATA_DIR / "territories.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for h in data.get("blacklist_domains") or []:
            if h:
                hosts.add(str(h).lower().lstrip("."))
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return tuple(sorted(hosts))


def url_is_community(url: str) -> bool:
    """True si Noonsite, wiki, forum, magazine — jamais une preuve d'État."""
    if url_is_excluded_search(url):
        return True
    host = (urlparse(url or "").hostname or "").lower().lstrip(".")
    if not host:
        return False
    for banned in _community_hosts():
        if host == banned or host.endswith("." + banned):
            return True
    return False


def _clean_url(raw) -> str:
    text = str(raw or "").strip()
    if not text.startswith("http"):
        return ""
    return text.split("#", 1)[0].rstrip("/")


def _as_source(raw, arm: str) -> dict | None:
    extra: dict = {}
    if isinstance(raw, str):
        url = _clean_url(raw)
    elif isinstance(raw, dict):
        extra = raw
        url = _clean_url(raw.get("url"))
    else:
        return None
    if not url or url_is_community(url):
        return None
    rec = {
        "url": url,
        "domain": extra.get("domain") or domain_of(url),
        "from_arm": arm,
    }
    if extra.get("official") is not None:
        rec["official"] = bool(extra["official"])
    if extra.get("collected_at"):
        rec["collected_at"] = extra["collected_at"]
    return rec


def _collect(raw_lists, arm: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for group in raw_lists:
        for raw in group or []:
            rec = _as_source(raw, arm)
            if rec is None:
                continue
            out.setdefault(rec["url"], rec)
    return out


def _url_rank(rec: dict) -> float:
    return list_url_bonus(rec.get("url") or "") + (1.0 if rec.get("official") else 0.0)


def _cap_sources(recs: list[dict], limit: int = FICHE_URL_CAP) -> list[dict]:
    """Un URL par domaine, les pages liste/PDF d'abord — comme une fiche projets."""
    by_dom: dict[str, dict] = {}
    for rec in recs or []:
        dom = (rec.get("domain") or domain_of(rec.get("url") or "") or rec.get("url") or "").lower()
        prev = by_dom.get(dom)
        if prev is None or _url_rank(rec) > _url_rank(prev):
            by_dom[dom] = rec
    ranked = sorted(by_dom.values(), key=_url_rank, reverse=True)
    return ranked[:limit]


def _port_row(doc: dict) -> dict | None:
    name = (doc.get("name") or "").strip()
    if not name:
        return None
    urls = []
    seen = set()
    for raw in doc.get("source_urls") or []:
        url = _clean_url(raw)
        if not url or url in seen or url_is_community(url):
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= 6:
            break
    return {
        "id": str(doc.get("_id") or doc.get("id") or name),
        "name": name,
        "city": doc.get("city"),
        "lat": doc.get("lat"),
        "lon": doc.get("lon"),
        "confidence": doc.get("confidence"),
        "spatial_kind": doc.get("spatial_kind"),
        "validated": bool(doc.get("validated")),
        "source_urls": urls,
    }


def _fiche_kind(zone: dict, n_sources: int, n_ports: int) -> str:
    unclos = zone.get("unclos") if isinstance(zone.get("unclos"), dict) else {}
    if n_sources == 0 and n_ports == 0 and unclos.get("code"):
        return "none"
    if n_sources:
        return "general_list"
    return "none"


def assemble_zone_fiche(zone: dict, ports: list[dict], *,
                        seeds: list[dict] | None = None,
                        run_ports: list[dict] | None = None,
                        run_zones: list[dict] | None = None) -> dict:
    """Construit la fiche. 0 écriture Atlas."""
    td_raw = [zone.get("sources"), zone.get("sources_td")]
    bu_raw = [zone.get("sources_bu")]
    for rz in run_zones or []:
        td_raw.append(rz.get("sources"))
        td_raw.append(rz.get("sources_td"))
        bu_raw.append(rz.get("sources_bu"))
    for doc in list(seeds or []) + list(run_ports or []):
        bu_raw.append(doc.get("judge_sources"))
        bu_raw.append(doc.get("sources_bu"))
    td_map = _collect(td_raw, "td")
    bu_map = _collect(bu_raw, "bu")
    union_urls = sorted(set(td_map) | set(bu_map))
    sources_td, sources_bu = [], []
    for url in union_urls:
        in_td = url in td_map
        in_bu = url in bu_map
        arm = "both" if in_td and in_bu else ("td" if in_td else "bu")
        base = dict(td_map.get(url) or bu_map.get(url) or {"url": url})
        base["from_arm"] = arm
        if in_td:
            sources_td.append({**base, "from_arm": arm})
        if in_bu:
            sources_bu.append({**base, "from_arm": arm})
    td_total, bu_total = len(sources_td), len(sources_bu)
    sources_td = _cap_sources(sources_td)
    sources_bu = _cap_sources(sources_bu)
    urls_map: dict[str, dict] = {}
    for rec in sources_td + sources_bu:
        urls_map.setdefault(rec["url"], rec)
    urls = list(urls_map.values())
    rows = []
    for doc in ports or []:
        row = _port_row(doc)
        if row:
            rows.append(row)
    rows.sort(key=lambda p: (p.get("name") or "").lower())
    item = zone_to_item(zone)
    item["sources_td"] = sources_td
    item["sources_bu"] = sources_bu
    item["sources_td_total"] = td_total
    item["sources_bu_total"] = bu_total
    item["urls"] = urls
    item["kind"] = _fiche_kind(zone, td_total + bu_total, len(rows))
    item["ports"] = rows
    item["wrote_poe_ports"] = False
    item["crawled"] = False
    return item


async def _find_mrgid(coll, mrgid: int) -> list[dict]:
    if coll is None:
        return []
    try:
        return await coll.find({"mrgid": mrgid}).to_list(8000)
    except Exception:
        return []


async def build_zone_fiche(db, mrgid: int) -> dict | None:
    """Charge Atlas en lecture seule et assemble la fiche."""
    zone = await db.eez_zones.find_one({"mrgid": int(mrgid)}, {"geometry": 0})
    if not zone:
        return None
    ports = await db.poe_ports.find({"mrgid": int(mrgid)}).to_list(2000)
    seeds = await _find_mrgid(getattr(db, "poe_seed_ports", None), int(mrgid))
    run_ports = await _find_mrgid(getattr(db, "poe_run_ports", None), int(mrgid))
    run_zones = await _find_mrgid(getattr(db, "poe_run_zones", None), int(mrgid))
    return assemble_zone_fiche(
        zone, ports, seeds=seeds, run_ports=run_ports, run_zones=run_zones)
