"""Choix keep/drop du réviseur Formalités.

Collection `review_choices` : ce que le réviseur coche sur la fiche polygone.
N'écrit jamais `poe_ports` / `eez_zones`. Les URLs sont stockées en listes
(pas en clés Mongo — un `.` dans l'URL casserait un sous-document).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.poe_pipeline import zone_to_item

CHOICE_KINDS = ("eez",)
TARGETS = ("td", "port", "bu")
ACTIONS = ("keep", "drop", "clear")

GOLD_INCOMPLETE = (
    "gold incomplete: keep at least one official list "
    "(or UNCLOS none / zero ports) and decide every PoE"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sid(value) -> str:
    return "" if value is None else str(value)


def choice_key(kind: str, entity_id: str) -> str:
    return f"{kind}:{_sid(entity_id)}"


def empty_choices() -> dict:
    return {"td": {}, "ports": {}, "bu": {}}


def public_choices(doc: dict | None) -> dict:
    """Maps pour l'UI : td[url], ports[port_id], bu[port_id][url] → keep|drop."""
    if not doc:
        return empty_choices()
    td: dict[str, str] = {}
    for row in doc.get("td") or []:
        url, act = row.get("url"), row.get("action")
        if url and act in ("keep", "drop"):
            td[str(url)] = act
    ports: dict[str, str] = {}
    for row in doc.get("ports") or []:
        pid, act = row.get("port_id"), row.get("action")
        if pid and act in ("keep", "drop"):
            ports[str(pid)] = act
    bu: dict[str, dict[str, str]] = {}
    for row in doc.get("bu") or []:
        pid, url, act = row.get("port_id"), row.get("url"), row.get("action")
        if pid and url and act in ("keep", "drop"):
            bu.setdefault(str(pid), {})[str(url)] = act
    return {"td": td, "ports": ports, "bu": bu}


def _pack(public: dict) -> dict:
    td = [{"url": u, "action": a} for u, a in (public.get("td") or {}).items()
          if a in ("keep", "drop")]
    ports = [{"port_id": pid, "action": a}
             for pid, a in (public.get("ports") or {}).items()
             if a in ("keep", "drop")]
    bu = []
    for pid, urls in (public.get("bu") or {}).items():
        for url, act in (urls or {}).items():
            if act in ("keep", "drop"):
                bu.append({"port_id": pid, "url": url, "action": act})
    return {"td": td, "ports": ports, "bu": bu}


def gold_ready(fiche: dict | None, choices: dict | None) -> bool:
    """Au moins une TD gardée (sauf UNCLOS / zéro port sans liste) et chaque PoE tranché."""
    fiche = fiche or {}
    ch = choices or empty_choices()
    td_urls = [r.get("url") for r in (fiche.get("sources_td") or []) if r.get("url")]
    n_keep = sum(1 for u in td_urls if (ch.get("td") or {}).get(u) == "keep")
    unclos = fiche.get("unclos") if isinstance(fiche.get("unclos"), dict) else {}
    kind = str(fiche.get("kind") or "")
    ports = fiche.get("ports") or []
    if td_urls:
        td_ok = n_keep >= 1
    else:
        td_ok = kind == "none" or bool(unclos.get("code")) or not ports
    pm = ch.get("ports") or {}
    ports_ok = all(
        pm.get(_sid(p.get("port_id") or p.get("id"))) in ("keep", "drop")
        for p in ports
    )
    return bool(td_ok and ports_ok)


def finalize_choices(fiche: dict, choices: dict) -> dict:
    """Au Gold : TD et BU non cochées → drop. Les PoE doivent déjà être tranchés."""
    out = {
        "td": dict((choices or {}).get("td") or {}),
        "ports": dict((choices or {}).get("ports") or {}),
        "bu": {pid: dict(m) for pid, m in ((choices or {}).get("bu") or {}).items()},
    }
    for rec in fiche.get("sources_td") or []:
        url = rec.get("url")
        if url and url not in out["td"]:
            out["td"][url] = "drop"
    for p in fiche.get("ports") or []:
        pid = _sid(p.get("port_id") or p.get("id"))
        if not pid:
            continue
        bmap = out["bu"].setdefault(pid, {})
        for rec in p.get("urls_bu") or []:
            url = rec.get("url")
            if url and url not in bmap:
                bmap[url] = "drop"
    return out


def build_gold_snapshot(fiche: dict, choices: dict, comment: str = "") -> dict:
    td_map = (choices or {}).get("td") or {}
    kept_td = [rec for rec in (fiche.get("sources_td") or [])
               if rec.get("url") and td_map.get(rec["url"]) == "keep"]
    url_td = kept_td[0] if kept_td else None
    port_map = (choices or {}).get("ports") or {}
    bu_all = (choices or {}).get("bu") or {}
    kept_ports: list[dict] = []
    for p in fiche.get("ports") or []:
        pid = _sid(p.get("port_id") or p.get("id"))
        if port_map.get(pid) != "keep":
            continue
        bmap = bu_all.get(pid) or {}
        kept_bu = [rec for rec in (p.get("urls_bu") or [])
                    if rec.get("url") and bmap.get(rec["url"]) == "keep"]
        best = kept_bu[0] if kept_bu else None
        kept_ports.append({
            "id": pid,
            "port_id": pid,
            "name": p.get("name"),
            "city": p.get("city"),
            "lat": p.get("lat"),
            "lon": p.get("lon"),
            "confidence": p.get("confidence"),
            "spatial_kind": p.get("spatial_kind"),
            "validated": bool(p.get("validated")),
            "url_bu": best,
            "urls_bu": kept_bu,
            "source_urls": [rec["url"] for rec in kept_bu if rec.get("url")],
        })
    return {
        "mrgid": fiche.get("mrgid"),
        "sources_td": kept_td,
        "url_td": url_td,
        "ports": kept_ports,
        "comment": comment or "",
        "golded_at": now_iso(),
        "kind": fiche.get("kind"),
        "label": fiche.get("label"),
        "zone_name": fiche.get("name") or fiche.get("label"),
        "iso2": fiche.get("iso2"),
    }


def snapshot_to_fiche(zone: dict, snapshot: dict) -> dict:
    """Fiche carte / popup à partir du snapshot Gold (plus la v1)."""
    item = zone_to_item(zone)
    sources_td = list(snapshot.get("sources_td") or [])
    url_td = snapshot.get("url_td")
    ports = list(snapshot.get("ports") or [])
    bu_seen: dict[str, dict] = {}
    for p in ports:
        for rec in p.get("urls_bu") or []:
            if rec.get("url"):
                bu_seen[rec["url"]] = rec
        bu = p.get("url_bu")
        if isinstance(bu, dict) and bu.get("url"):
            bu_seen.setdefault(bu["url"], bu)
    item["url_td"] = url_td
    item["sources_td"] = sources_td
    item["sources_bu"] = list(bu_seen.values())
    item["sources_td_total"] = len(sources_td)
    item["sources_bu_total"] = len(bu_seen)
    item["urls"] = ([url_td] if url_td else []) + [
        rec for rec in bu_seen.values()
        if not url_td or rec.get("url") != (url_td.get("url") if isinstance(url_td, dict) else None)
    ]
    item["kind"] = snapshot.get("kind") or (
        "none" if not sources_td and not ports else "general_list")
    item["ports"] = ports
    item["poe_count"] = len(ports)
    item["wrote_poe_ports"] = False
    item["crawled"] = False
    item["fiche_scope"] = "gold"
    item["gold_published"] = True
    item["golded_at"] = snapshot.get("golded_at")
    return item


def snapshot_port_docs(mrgid: int, snapshot: dict) -> list[dict]:
    """Docs style poe_ports pour le GeoJSON carte — ids stables `gold:{mrgid}:{port_id}`."""
    docs: list[dict] = []
    iso2 = snapshot.get("iso2")
    zone_name = snapshot.get("zone_name") or snapshot.get("label")
    for p in snapshot.get("ports") or []:
        pid = _sid(p.get("port_id") or p.get("id"))
        bu = p.get("url_bu")
        docs.append({
            "_id": f"gold:{mrgid}:{pid}",
            "name": p.get("name"),
            "city": p.get("city"),
            "lat": p.get("lat"),
            "lon": p.get("lon"),
            "mrgid": int(mrgid),
            "zone_name": zone_name,
            "country_iso2": iso2,
            "confidence": p.get("confidence"),
            "validated": bool(p.get("validated")),
            "spatial_kind": p.get("spatial_kind"),
            "url_bu": bu,
            "source_urls": list(p.get("source_urls") or []),
        })
    return docs


async def get_choices(db, kind: str, entity_id: str) -> dict:
    try:
        doc = await db.review_choices.find_one({"_id": choice_key(kind, entity_id)})
    except Exception:
        doc = None
    return public_choices(doc)


async def save_choices_doc(db, kind: str, entity_id: str, public: dict) -> dict:
    eid = _sid(entity_id)
    cid = choice_key(kind, eid)
    packed = _pack(public)
    doc = {
        "_id": cid,
        "kind": kind,
        "entity_id": eid,
        "td": packed["td"],
        "ports": packed["ports"],
        "bu": packed["bu"],
        "updated_at": now_iso(),
    }
    await db.review_choices.update_one({"_id": cid}, {"$set": doc}, upsert=True)
    return public_choices(doc)


async def save_choice(db, kind: str, entity_id: str, target: str, action: str,
                      *, url: str | None = None, port_id: str | None = None) -> dict:
    if kind not in CHOICE_KINDS:
        raise ValueError("choice is only for eez")
    if target not in TARGETS:
        raise ValueError("target must be td|port|bu")
    if action not in ACTIONS:
        raise ValueError("action must be keep|drop|clear")
    eid = _sid(entity_id)
    if not eid:
        raise ValueError("id required")
    current = await get_choices(db, kind, eid)
    if target == "td":
        href = (url or "").strip()
        if not href:
            raise ValueError("url required")
        if action == "clear":
            current["td"].pop(href, None)
        else:
            current["td"][href] = action
    elif target == "port":
        pid = _sid(port_id)
        if not pid:
            raise ValueError("port_id required")
        if action == "clear":
            current["ports"].pop(pid, None)
        else:
            current["ports"][pid] = action
    else:
        pid = _sid(port_id)
        href = (url or "").strip()
        if not pid or not href:
            raise ValueError("port_id and url required")
        bucket = current["bu"].setdefault(pid, {})
        if action == "clear":
            bucket.pop(href, None)
            if not bucket:
                current["bu"].pop(pid, None)
        else:
            bucket[href] = action
    public = await save_choices_doc(db, kind, eid, current)
    return {
        "kind": kind,
        "id": eid,
        "choices": public,
        "wrote_poe_ports": False,
        "wrote_projects": False,
        "wrote_marinas": False,
    }


async def ensure_choice_indexes(db) -> None:
    try:
        await db.review_choices.create_index("kind")
        await db.review_choices.create_index("entity_id")
    except Exception:
        pass
