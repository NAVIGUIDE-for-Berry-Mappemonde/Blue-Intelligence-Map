"""
project_review — File opérateur, Gold et promotion manuelle (CDC v2, phase D).

Le swarm n'écrit jamais `projects`. Seules les actions manuelles ici
(accepter un site, promouvoir un run) touchent la carte live.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from app.config import DATA_DIR
from app.core.dedup import is_duplicate, merge_docs
from app.core.project_geo import site_publishable, valid_coords

GOLD_FILE = DATA_DIR / "project_gold.json"

SOURCES = (
    "v1_snapped",
    "v1_fallback",
    "run_unlocated",
    "run_hq",
    "run_diff",
)
STATUSES = ("pending", "accepted", "rejected")

_FALLBACK_MARKERS = ("fallback", "ocean_fallback", "ocean-region-fallback")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_snapped(doc: dict | None) -> bool:
    if not doc:
        return False
    return bool(doc.get("snapped") or doc.get("snapped_coastal"))


def is_fallback_geo(doc: dict | None) -> bool:
    if not doc:
        return False
    src = str(doc.get("geo_source") or "").strip().lower().replace(" ", "_")
    if not src:
        return False
    return any(m.replace("-", "_") in src for m in _FALLBACK_MARKERS)


def gold_eligible_v1(doc: dict | None) -> bool:
    """v1 publiable dans le Gold : pas snapped, pas fallback océan."""
    if not doc:
        return False
    return not is_snapped(doc) and not is_fallback_geo(doc)


def review_id(source: str, url: str = "", extra: str = "") -> str:
    raw = f"{source}|{url}|{extra}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


async def ensure_review_indexes(db):
    try:
        await db.project_review.create_index("status")
        await db.project_review.create_index("source")
        await db.project_review.create_index("run_id")
        await db.project_review.create_index([("status", 1), ("source", 1)])
        await db.project_review.create_index("url")
    except Exception:
        pass


def merge_site_lists(existing, incoming) -> list[dict]:
    out = [dict(s) for s in (existing or []) if isinstance(s, dict)]
    for s in incoming or []:
        if not isinstance(s, dict):
            continue
        cand = {
            "title": s.get("name") or s.get("location"),
            "lat": s.get("lat"),
            "lon": s.get("lon"),
        }
        if any(
            is_duplicate(
                cand,
                {"title": t.get("name") or t.get("location"),
                 "lat": t.get("lat"), "lon": t.get("lon")},
            )
            for t in out
        ):
            continue
        out.append(s)
    return out


def union_funders(*groups) -> list[str]:
    seen, out = set(), []
    for g in groups:
        for f in g or []:
            name = (f if isinstance(f, str) else str(f or "")).strip()
            if name and name not in seen:
                seen.add(name)
                out.append(name)
    return out


def _hq_hint(doc: dict) -> bool:
    kind = str(doc.get("geo_kind") or doc.get("reason") or "").lower()
    if "hq" in kind:
        return True
    for s in doc.get("sites") or []:
        if not isinstance(s, dict):
            continue
        blob = " ".join(str(s.get(k) or "") for k in ("verdict", "geo_kind", "reason"))
        if "hq" in blob.lower():
            return True
        judge = s.get("judge") or {}
        if "hq" in str(judge.get("kind") or judge.get("reason") or "").lower():
            return True
    return False


def _item_from_v1(p: dict, source: str) -> dict:
    url = p.get("url") or ""
    return {
        "_id": review_id(source, url, str(p.get("_id") or "")),
        "source": source,
        "status": "pending",
        "project_id": p.get("_id"),
        "run_id": None,
        "url": url,
        "title": p.get("title"),
        "description": p.get("description"),
        "location": p.get("location"),
        "funders": p.get("funders") or ([p.get("funder")] if p.get("funder") else []),
        "lat": p.get("lat"),
        "lon": p.get("lon"),
        "sites": p.get("sites") or [],
        "snapped": is_snapped(p),
        "geo_source": p.get("geo_source"),
        "reason": "snapped" if source == "v1_snapped" else "fallback",
        "created_at": now_iso(),
    }


def _item_from_run(d: dict, source: str, reason: str) -> dict:
    url = d.get("url") or ""
    return {
        "_id": review_id(source, url, d.get("run_id") or ""),
        "source": source,
        "status": "pending",
        "project_id": None,
        "run_id": d.get("run_id"),
        "run_project_id": d.get("_id"),
        "url": url,
        "title": d.get("title"),
        "description": d.get("description"),
        "location": d.get("location"),
        "funders": d.get("funders") or ([d.get("funder")] if d.get("funder") else []),
        "lat": d.get("lat"),
        "lon": d.get("lon"),
        "sites": d.get("sites") or [],
        "verdict": d.get("verdict"),
        "geo_source": d.get("geo_source"),
        "geo_kind": d.get("geo_kind"),
        "reason": reason,
        "created_at": now_iso(),
    }


async def _latest_run_ids(db, limit: int = 20) -> list[str]:
    docs = await db.project_runs.find({}).sort("created_at", -1).to_list(limit)
    return [d["_id"] for d in docs if d.get("_id")]


async def collect_candidates(db, run_id: str | None = None) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()

    def _push(item: dict):
        rid = item["_id"]
        if rid in seen:
            return
        seen.add(rid)
        items.append(item)

    v1_docs = await db.projects.find({}, {
        "url": 1, "title": 1, "description": 1, "location": 1,
        "funders": 1, "funder": 1, "lat": 1, "lon": 1, "sites": 1,
        "snapped": 1, "snapped_coastal": 1, "geo_source": 1,
    }).to_list(50000)
    v1_urls = {p.get("url") for p in v1_docs if p.get("url")}
    for p in v1_docs:
        if is_snapped(p):
            _push(_item_from_v1(p, "v1_snapped"))
        elif is_fallback_geo(p):
            _push(_item_from_v1(p, "v1_fallback"))

    run_ids = [run_id] if run_id else await _latest_run_ids(db)
    for rid in run_ids:
        docs = await db.project_run_projects.find({"run_id": rid}).to_list(20000)
        for d in docs:
            verdict = d.get("verdict")
            if verdict == "unlocated" or verdict == "rejected":
                src = "run_hq" if _hq_hint(d) else "run_unlocated"
                _push(_item_from_run(d, src, d.get("reason") or verdict or src))
            elif verdict == "site" and d.get("url") and d.get("url") not in v1_urls:
                _push(_item_from_run(d, "run_diff", "added"))
    return items


async def rebuild_queue(db, run_id: str | None = None) -> dict:
    """Reconstruit les pending. Ne touche pas aux acceptés / rejetés."""
    await ensure_review_indexes(db)
    candidates = await collect_candidates(db, run_id=run_id)
    existing = await db.project_review.find({}).to_list(50000)
    by_id = {d["_id"]: d for d in existing}
    keep = {c["_id"] for c in candidates}
    created = updated = preserved = removed = 0

    for item in candidates:
        prev = by_id.get(item["_id"])
        if prev and prev.get("status") in ("accepted", "rejected"):
            preserved += 1
            continue
        payload = dict(item)
        if prev:
            payload["status"] = prev.get("status") or "pending"
            if prev.get("edited_lat") is not None:
                payload["edited_lat"] = prev.get("edited_lat")
                payload["edited_lon"] = prev.get("edited_lon")
            if prev.get("edited_site_name"):
                payload["edited_site_name"] = prev.get("edited_site_name")
            await db.project_review.update_one({"_id": item["_id"]}, {"$set": payload})
            updated += 1
        else:
            await db.project_review.update_one(
                {"_id": item["_id"]},
                {"$setOnInsert": payload},
                upsert=True,
            )
            created += 1

    for prev in existing:
        if prev["_id"] in keep:
            continue
        if prev.get("status") in ("accepted", "rejected"):
            preserved += 1
            continue
        if prev.get("status") == "pending":
            await db.project_review.delete_one({"_id": prev["_id"]})
            removed += 1

    stats = await review_stats(db)
    return {
        "created": created,
        "updated": updated,
        "preserved": preserved,
        "removed_stale_pending": removed,
        "candidates": len(candidates),
        **stats,
    }


def public_item(d: dict) -> dict:
    return {
        "id": d.get("_id"),
        "source": d.get("source"),
        "status": d.get("status"),
        "project_id": d.get("project_id"),
        "run_id": d.get("run_id"),
        "url": d.get("url"),
        "title": d.get("title"),
        "description": d.get("description"),
        "location": d.get("location"),
        "funders": d.get("funders") or [],
        "lat": d["edited_lat"] if d.get("edited_lat") is not None else d.get("lat"),
        "lon": d["edited_lon"] if d.get("edited_lon") is not None else d.get("lon"),
        "orig_lat": d.get("lat"),
        "orig_lon": d.get("lon"),
        "edited_lat": d.get("edited_lat"),
        "edited_lon": d.get("edited_lon"),
        "edited_site_name": d.get("edited_site_name"),
        "sites": d.get("sites") or [],
        "reason": d.get("reason"),
        "geo_source": d.get("geo_source"),
        "geo_kind": d.get("geo_kind"),
        "verdict": d.get("verdict"),
        "note": d.get("note"),
        "reviewed_at": d.get("reviewed_at"),
        "wrote_projects": d.get("wrote_projects", False),
    }


async def list_review(db, *, status: str | None = None, source: str | None = None,
                      run_id: str | None = None, limit: int = 200) -> dict:
    q: dict = {}
    if status:
        q["status"] = status
    if source:
        q["source"] = source
    if run_id:
        q["run_id"] = run_id
    total = await db.project_review.count_documents(q)
    docs = await db.project_review.find(q).to_list(min(int(limit or 200), 2000))
    return {"total": total, "count": len(docs), "items": [public_item(d) for d in docs]}


async def review_stats(db) -> dict:
    docs = await db.project_review.find({}).to_list(50000)
    by_status = {s: 0 for s in STATUSES}
    by_source = {s: 0 for s in SOURCES}
    pending_by_source = {s: 0 for s in SOURCES}
    for d in docs:
        st = d.get("status") or "pending"
        src = d.get("source") or ""
        if st in by_status:
            by_status[st] += 1
        if src in by_source:
            by_source[src] += 1
        if st == "pending" and src in pending_by_source:
            pending_by_source[src] += 1
    return {
        "total": len(docs),
        "by_status": by_status,
        "by_source": by_source,
        "pending_by_source": pending_by_source,
    }


async def get_item(db, item_id: str) -> dict:
    doc = await db.project_review.find_one({"_id": item_id})
    if not doc:
        raise KeyError(item_id)
    return doc


async def edit_item(db, item_id: str, *, lat=None, lon=None,
                    site_name: str | None = None, note: str | None = None) -> dict:
    doc = await get_item(db, item_id)
    if doc.get("status") != "pending":
        raise ValueError("seul un item pending peut être édité")
    updates: dict = {"updated_at": now_iso()}
    if lat is not None and lon is not None:
        if not valid_coords(lat, lon):
            raise ValueError("coordonnées invalides")
        updates["edited_lat"] = float(lat)
        updates["edited_lon"] = float(lon)
    if site_name is not None:
        updates["edited_site_name"] = str(site_name).strip()[:200]
    if note is not None:
        updates["note"] = str(note)[:500]
    await db.project_review.update_one({"_id": item_id}, {"$set": updates})
    return public_item(await get_item(db, item_id))


def _effective_coords(doc: dict, lat=None, lon=None):
    if lat is not None and lon is not None:
        return lat, lon
    if doc.get("edited_lat") is not None and doc.get("edited_lon") is not None:
        return doc["edited_lat"], doc["edited_lon"]
    return doc.get("lat"), doc.get("lon")


def _site_payload(doc: dict, lat, lon, site_name: str | None) -> list[dict]:
    name = (
        site_name
        or doc.get("edited_site_name")
        or doc.get("location")
        or doc.get("title")
    )
    incoming = [{
        "name": name,
        "location": doc.get("location") or name,
        "lat": float(lat),
        "lon": float(lon),
        "verdict": "site_ok",
        "geo_source": "review",
        "evidence": "operator review",
    }]
    return merge_site_lists(doc.get("sites"), incoming)


async def apply_site_to_projects(db, *, url: str, title: str, description: str = "",
                                 location: str | None = None, lat=None, lon=None,
                                 funders: list | None = None, sites: list | None = None,
                                 overwrite_dirty: bool = False,
                                 extra: dict | None = None) -> dict:
    """Upsert carte live par URL. Fusion additive ; overwrite GPS si v1 dirty."""
    if not url:
        raise ValueError("url required")
    incoming = {
        "title": title,
        "description": description,
        "location": location,
        "lat": lat,
        "lon": lon,
        "funders": list(funders or []),
        "sites": list(sites or []),
        "geo_source": "review",
        "snapped": False,
        "updated_at": now_iso(),
        **(extra or {}),
    }
    existing = await db.projects.find_one({"url": url})
    if not existing:
        rid = str(uuid.uuid4())
        doc = {
            "_id": rid,
            "title": (title or url)[:200],
            "url": url,
            "description": (description or "")[:500],
            "location": location,
            "lat": lat,
            "lon": lon,
            "funders": union_funders(funders),
            "funder": (funders or [None])[0],
            "sites": list(sites or []),
            "s_ocean": extra.get("s_ocean", 0.7) if extra else 0.7,
            "snapped": False,
            "geo_source": "review",
            "engine": "operator-review",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.projects.insert_one(doc)
        return {"action": "inserted", "id": rid}

    updates = merge_docs(existing, incoming)
    updates["funders"] = union_funders(existing.get("funders"), funders)
    updates["sites"] = merge_site_lists(existing.get("sites"), sites)
    dirty = is_snapped(existing) or is_fallback_geo(existing)
    if (overwrite_dirty or dirty) and valid_coords(lat, lon):
        updates["lat"] = float(lat)
        updates["lon"] = float(lon)
        updates["snapped"] = False
        updates["geo_source"] = "review"
        if location:
            updates["location"] = location
        if title and not existing.get("title"):
            updates["title"] = title
    updates["updated_at"] = now_iso()
    await db.projects.update_one({"_id": existing["_id"]}, {"$set": updates})
    return {"action": "merged", "id": str(existing["_id"])}


async def accept_item(db, item_id: str, *, lat=None, lon=None,
                      site_name: str | None = None, note: str = "",
                      write_projects: bool = True, force: bool = False,
                      settings: dict | None = None) -> dict:
    doc = await get_item(db, item_id)
    if doc.get("status") == "rejected":
        raise ValueError("item déjà rejeté")
    elat, elon = _effective_coords(doc, lat, lon)
    if not valid_coords(elat, elon):
        raise ValueError("GPS requis pour accepter un site (éditer lat/lon)")
    ok, kind = site_publishable(elat, elon, settings)
    if not ok and not force:
        raise ValueError(f"point non publiable ({kind}) — éditer le GPS ou force=true")
    sites = _site_payload(doc, elat, elon, site_name)
    wrote = None
    if write_projects:
        wrote = await apply_site_to_projects(
            db,
            url=doc.get("url") or f"review:{item_id}",
            title=doc.get("title") or site_name or "Reviewed site",
            description=doc.get("description") or "",
            location=site_name or doc.get("edited_site_name") or doc.get("location"),
            lat=float(elat),
            lon=float(elon),
            funders=doc.get("funders"),
            sites=sites,
            overwrite_dirty=True,
        )
    await db.project_review.update_one({"_id": item_id}, {"$set": {
        "status": "accepted",
        "edited_lat": float(elat),
        "edited_lon": float(elon),
        "edited_site_name": (site_name or doc.get("edited_site_name")
                             or doc.get("location") or doc.get("title")),
        "note": note or doc.get("note"),
        "reviewed_at": now_iso(),
        "wrote_projects": bool(write_projects),
        "publish_kind": kind,
        "gold": True,
    }})
    return {
        "item": public_item(await get_item(db, item_id)),
        "wrote_projects": bool(write_projects),
        "projects": wrote,
        "publish_kind": kind,
    }


async def reject_item(db, item_id: str, *, note: str = "") -> dict:
    doc = await get_item(db, item_id)
    if doc.get("status") == "accepted":
        raise ValueError("item déjà accepté")
    await db.project_review.update_one({"_id": item_id}, {"$set": {
        "status": "rejected",
        "note": note or doc.get("note"),
        "reviewed_at": now_iso(),
        "wrote_projects": False,
        "gold": False,
    }})
    return {"item": public_item(await get_item(db, item_id)), "wrote_projects": False}


async def promote_run(db, run_id: str, *, settings: dict | None = None,
                      force: bool = False) -> dict:
    """Écrit les sites `verdict=site` du run dans `projects`. Action manuelle."""
    run = await db.project_runs.find_one({"_id": run_id})
    if not run:
        raise KeyError(run_id)
    docs = await db.project_run_projects.find(
        {"run_id": run_id, "verdict": "site"},
    ).to_list(20000)
    inserted = merged = skipped = 0
    errors = []
    for d in docs:
        lat, lon = d.get("lat"), d.get("lon")
        sites = [s for s in (d.get("sites") or []) if isinstance(s, dict)
                 and valid_coords(s.get("lat"), s.get("lon"))]
        if not sites and valid_coords(lat, lon):
            sites = [{
                "name": d.get("location") or d.get("title"),
                "location": d.get("location"),
                "lat": lat, "lon": lon,
                "verdict": "site_ok",
                "geo_source": "run_promote",
            }]
        if not sites:
            skipped += 1
            continue
        first = sites[0]
        ok, kind = site_publishable(first.get("lat"), first.get("lon"), settings)
        if not ok and not force:
            skipped += 1
            errors.append({"url": d.get("url"), "reason": kind})
            continue
        try:
            out = await apply_site_to_projects(
                db,
                url=d.get("url"),
                title=d.get("title") or d.get("url"),
                description=d.get("description") or "",
                location=d.get("location"),
                lat=first.get("lat"),
                lon=first.get("lon"),
                funders=d.get("funders") or ([d.get("funder")] if d.get("funder") else []),
                sites=sites,
                overwrite_dirty=True,
                extra={
                    "s_ocean": d.get("s_ocean", 0.7),
                    "category": d.get("category"),
                    "category_group": d.get("category_group"),
                    "image": d.get("image"),
                    "engine": "run-promote",
                    "promoted_run_id": run_id,
                },
            )
        except ValueError as e:
            skipped += 1
            errors.append({"url": d.get("url"), "reason": str(e)})
            continue
        if out["action"] == "inserted":
            inserted += 1
        else:
            merged += 1

    summary = {
        "run_id": run_id,
        "wrote_projects": True,
        "site_rows": len(docs),
        "inserted": inserted,
        "merged": merged,
        "skipped": skipped,
        "errors": errors[:30],
        "promoted_at": now_iso(),
    }
    await db.project_runs.update_one({"_id": run_id}, {"$set": {
        "wrote_projects": True,
        "promoted_at": summary["promoted_at"],
        "promote_summary": summary,
    }})
    return summary


def slim_gold(p: dict) -> dict:
    names = []
    for s in p.get("sites") or []:
        if isinstance(s, dict) and s.get("name"):
            names.append(s["name"])
    return {
        "id": p.get("_id") or p.get("id"),
        "title": p.get("title"),
        "description": p.get("description"),
        "location": p.get("location"),
        "site_name": p.get("site_name") or (names[0] if names else None),
        "sites": names,
        "url": p.get("url"),
        "lat": p.get("lat"),
        "lon": p.get("lon"),
        "funders": p.get("funders") or [],
    }


def gold_text(p: dict) -> str:
    bits = [p.get("title"), p.get("description"), p.get("location"), p.get("site_name")]
    bits.extend(p.get("sites") or [])
    return " ".join(str(b) for b in bits if b).strip()


async def collect_gold_items(db) -> list[dict]:
    """v1 moins snapped moins fallback, plus les acceptés revue absents de ce filtre."""
    items: list[dict] = []
    seen_urls: set[str] = set()
    docs = await db.projects.find({}, {
        "title": 1, "description": 1, "location": 1, "site_name": 1,
        "url": 1, "lat": 1, "lon": 1, "funders": 1, "sites": 1,
        "snapped": 1, "snapped_coastal": 1, "geo_source": 1,
    }).to_list(50000)
    for p in docs:
        if not gold_eligible_v1(p):
            continue
        slim = slim_gold(p)
        items.append(slim)
        if slim.get("url"):
            seen_urls.add(slim["url"])
    for r in await db.project_review.find({"status": "accepted"}).to_list(20000):
        url = r.get("url")
        if url and url in seen_urls:
            continue
        slim = slim_gold({
            "_id": r.get("_id"),
            "title": r.get("title"),
            "description": r.get("description"),
            "location": r.get("edited_site_name") or r.get("location"),
            "url": url,
            "lat": r.get("edited_lat", r.get("lat")),
            "lon": r.get("edited_lon", r.get("lon")),
            "funders": r.get("funders"),
            "sites": r.get("sites"),
        })
        items.append(slim)
        if url:
            seen_urls.add(url)
    return items


async def gold_stats(db) -> dict:
    """Aperçu rapide : pas de slim_gold / pas de relecture complète des fiches."""
    projects = await db.projects.find(
        {}, {"snapped": 1, "snapped_coastal": 1, "geo_source": 1, "url": 1},
    ).to_list(50000)
    snapped = fallback = gold_n = 0
    clean_urls: set[str] = set()
    for p in projects:
        if is_snapped(p):
            snapped += 1
        elif is_fallback_geo(p):
            fallback += 1
        else:
            gold_n += 1
            if p.get("url"):
                clean_urls.add(p["url"])
    extra_accepted = 0
    for r in await db.project_review.find(
        {"status": "accepted"}, {"url": 1},
    ).to_list(20000):
        url = r.get("url")
        if url and url not in clean_urls:
            extra_accepted += 1
            gold_n += 1
    accepted = await db.project_review.count_documents({"status": "accepted"})
    rejected = await db.project_review.count_documents({"status": "rejected"})
    return {
        "projects_total": len(projects),
        "excluded_snapped": snapped,
        "excluded_fallback": fallback,
        "gold_count": gold_n,
        "review_accepted": accepted,
        "review_rejected": rejected,
        "review_accepted_extra": extra_accepted,
        "file_exists": GOLD_FILE.exists(),
        "file_path": str(GOLD_FILE),
    }


async def export_gold(db, path=None) -> dict:
    DATA_DIR.mkdir(exist_ok=True)
    dest = path or GOLD_FILE
    items = await collect_gold_items(db)
    payload = {
        "exported_at": now_iso(),
        "source": "v1 minus snapped minus fallback plus review accepted",
        "count": len(items),
        "items": items,
    }
    dest.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    stats = await gold_stats(db)
    stats["exported"] = len(items)
    stats["file_path"] = str(dest)
    stats["file_exists"] = dest.exists()
    return stats


def load_gold_file(path=None) -> list[dict]:
    dest = path or GOLD_FILE
    if not dest.exists():
        return []
    try:
        data = json.loads(dest.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = data.get("items") if isinstance(data, dict) else data
    return [i for i in (items or []) if isinstance(i, dict)]


async def gold_positive_texts(db, max_docs: int = 8000) -> list[str]:
    """Positifs gatekeeper = même définition que l'export Gold (collecte live)."""
    items = await collect_gold_items(db)
    texts = []
    for p in items[:max_docs]:
        txt = gold_text(p)
        if len(txt) > 20:
            texts.append(txt)
    return texts


async def rejected_negative_texts(db, max_docs: int = 2000) -> list[str]:
    texts = []
    for r in await db.project_review.find({"status": "rejected"}).to_list(max_docs):
        reason = str(r.get("reason") or r.get("source") or "")
        extra = " headquarters inland terrestrial office" if "hq" in reason.lower() or r.get("source") == "run_hq" else ""
        txt = gold_text(r) + " " + reason + extra
        if len(txt.strip()) > 15:
            texts.append(txt.strip())
    return texts
