"""
poe_zone_fiche — Fiche de revue d'un polygone VLIZ (lecture seule).

Contrat UI : 1 URL Top-Down (page/PDF d'État listant les PoE) + liste des
PoE + 1 URL Bottom-Up par port. N'écrit jamais poe_ports / eez_zones.
Le WPI n'est pas une source. Noonsite et les forums n'entrent pas.
"""
from __future__ import annotations

import json
from functools import lru_cache
from urllib.parse import urlparse

from app.config import DATA_DIR
from app.core.dedup import normalize_name
from app.services.poe_pipeline import domain_of, list_url_bonus, zone_to_item
from app.services.poe_zone_label import attach_zone_labels
from app.services.poe_seeds import SEARCH_EXCLUDE_DOMAINS, url_is_excluded_search

# Revue : une URL TD (la liste officielle) + une URL BU par PoE.
FICHE_TD_URL_CAP = 1


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


def _cap_sources(recs: list[dict], limit: int = FICHE_TD_URL_CAP) -> list[dict]:
    """Un URL par domaine, les pages liste/PDF d'abord — comme une fiche projets."""
    by_dom: dict[str, dict] = {}
    for rec in recs or []:
        dom = (rec.get("domain") or domain_of(rec.get("url") or "") or rec.get("url") or "").lower()
        prev = by_dom.get(dom)
        if prev is None or _url_rank(rec) > _url_rank(prev):
            by_dom[dom] = rec
    ranked = sorted(by_dom.values(), key=_url_rank, reverse=True)
    return ranked[:limit]


def _best_one(recs: list[dict]) -> dict | None:
    capped = _cap_sources(recs, limit=1)
    return capped[0] if capped else None


def bu_by_port_name(docs: list[dict] | None) -> dict[str, dict]:
    """Meilleure URL d'État trouvée en cherchant CE port (juge / sources_bu)."""
    by: dict[str, dict] = {}
    for doc in docs or []:
        key = normalize_name(doc.get("name") or "")
        if not key:
            continue
        recs: list[dict] = []
        for raw in list(doc.get("judge_sources") or []) + list(doc.get("sources_bu") or []):
            rec = _as_source(raw, "bu")
            if rec:
                recs.append(rec)
        best = _best_one(recs)
        if not best:
            continue
        prev = by.get(key)
        if prev is None or _url_rank(best) > _url_rank(prev):
            by[key] = best
    return by


def _port_row(doc: dict, url_bu: dict | None = None) -> dict | None:
    name = (doc.get("name") or "").strip()
    if not name:
        return None
    row = {
        "id": str(doc.get("_id") or doc.get("id") or name),
        "name": name,
        "city": doc.get("city"),
        "lat": doc.get("lat"),
        "lon": doc.get("lon"),
        "confidence": doc.get("confidence"),
        "spatial_kind": doc.get("spatial_kind"),
        "validated": bool(doc.get("validated")),
        "url_bu": url_bu,
    }
    if url_bu and url_bu.get("url"):
        row["source_urls"] = [url_bu["url"]]
    else:
        row["source_urls"] = []
    return row


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
    """Construit la fiche de revue. 0 écriture Atlas.

    Contrat UI : 1 URL TD (page/PDF d'État listant les PoE) + la liste des
    PoE + 1 URL BU par port (page ouverte en cherchant ce nom).
    """
    td_raw = [zone.get("sources"), zone.get("sources_td")]
    for rz in run_zones or []:
        td_raw.append(rz.get("sources"))
        td_raw.append(rz.get("sources_td"))
    td_map = _collect(td_raw, "td")
    bu_by_name = bu_by_port_name(list(seeds or []) + list(run_ports or []))

    rows = []
    bu_seen: dict[str, dict] = {}
    for doc in ports or []:
        key = normalize_name(doc.get("name") or "")
        url_bu = bu_by_name.get(key)
        row = _port_row(doc, url_bu)
        if not row:
            continue
        rows.append(row)
        if url_bu and url_bu.get("url"):
            bu_seen.setdefault(url_bu["url"], url_bu)
    rows.sort(key=lambda p: (p.get("name") or "").lower())

    td_list = list(td_map.values())
    td_total = len(td_list)
    url_td = _best_one(td_list)
    if url_td:
        td_url = url_td["url"]
        if td_url in bu_seen:
            url_td = {**url_td, "from_arm": "both"}
            for row in rows:
                bu = row.get("url_bu") or {}
                if bu.get("url") == td_url:
                    row["url_bu"] = {**bu, "from_arm": "both"}
                    bu_seen[td_url] = row["url_bu"]
        sources_td = [url_td]
    else:
        sources_td = []

    sources_bu = list(bu_seen.values())
    item = zone_to_item(zone)
    item["url_td"] = url_td
    item["sources_td"] = sources_td
    item["sources_bu"] = sources_bu
    item["sources_td_total"] = td_total
    item["sources_bu_total"] = len(sources_bu)
    item["urls"] = ([url_td] if url_td else []) + [
        rec for rec in sources_bu if not url_td or rec.get("url") != url_td.get("url")
    ]
    item["kind"] = _fiche_kind(zone, td_total + len(sources_bu), len(rows))
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


_LABEL_PROJ = {
    "_id": 0, "mrgid": 1, "name": 1, "geoname": 1, "sovereign": 1,
    "iso2": 1, "sov_iso2": 1, "pol_type": 1,
}


async def _label_zone(db, zone: dict) -> dict:
    """Une fiche = ce mrgid. Le libellé tient compte des autres polygones du souverain."""
    sov = (zone.get("sovereign") or "").strip()
    if not sov:
        attach_zone_labels([zone])
        return zone
    try:
        sibs = await db.eez_zones.find({"sovereign": sov}, _LABEL_PROJ).to_list(500)
    except Exception:
        sibs = []
    if not sibs:
        sibs = [{k: zone.get(k) for k in (
            "mrgid", "name", "geoname", "sovereign", "iso2", "sov_iso2", "pol_type")}]
    attach_zone_labels(sibs)
    want = int(zone.get("mrgid") or 0)
    hit = next((s for s in sibs if int(s.get("mrgid") or 0) == want), None)
    if hit:
        for key in ("label", "qualifier", "qualifier_key", "disambiguated"):
            zone[key] = hit.get(key)
    return zone


PUBLISHED_RUN = "published"


def _is_published(run_id: str | None) -> bool:
    return not run_id or run_id == PUBLISHED_RUN


async def _find_run_mrgid(coll, run_id: str, mrgid: int) -> list[dict]:
    if coll is None:
        return []
    try:
        return await coll.find({"run_id": run_id, "mrgid": int(mrgid)}).to_list(8000)
    except Exception:
        return []


async def build_zone_fiche(db, mrgid: int, run_id: str | None = None) -> dict | None:
    """Charge Atlas en lecture seule et assemble la fiche.

    ``run_id=None`` / ``published`` : ports v1 + toutes les URLs de runs comme
    sources auxiliaires. Un ``run_id`` précis : ports et sources de CE run.
    """
    mid = int(mrgid)
    zone = await db.eez_zones.find_one({"mrgid": mid}, {"geometry": 0})
    seeds = await _find_mrgid(getattr(db, "poe_seed_ports", None), mid)
    if _is_published(run_id):
        if not zone:
            return None
        ports = await db.poe_ports.find({"mrgid": mid}).to_list(2000)
        # Graines pour les URLs BU ; zones de run seulement pour l'URL TD.
        # On ne charge pas poe_run_ports (tous les mondiaux) — trop lourd.
        run_ports = []
        run_zones = await _find_mrgid(getattr(db, "poe_run_zones", None), mid)
    else:
        ports = await _find_run_mrgid(getattr(db, "poe_run_ports", None), run_id, mid)
        run_zones = await _find_run_mrgid(getattr(db, "poe_run_zones", None), run_id, mid)
        run_ports = ports
        if not zone:
            zone = run_zones[0] if run_zones else None
        elif run_zones:
            rz = run_zones[0]
            zone = {
                **zone,
                "sources": rz.get("sources") if rz.get("sources") is not None else zone.get("sources"),
                "sources_td": rz.get("sources_td") if rz.get("sources_td") is not None else zone.get("sources_td"),
                "confidence_avg": rz.get("confidence_avg", zone.get("confidence_avg")),
                "status": rz.get("status") or zone.get("status"),
                "poe_count": rz.get("poe_count", zone.get("poe_count")),
            }
        if not zone:
            return None
    zone = await _label_zone(db, zone)
    return assemble_zone_fiche(
        zone, ports, seeds=seeds, run_ports=run_ports, run_zones=run_zones)
