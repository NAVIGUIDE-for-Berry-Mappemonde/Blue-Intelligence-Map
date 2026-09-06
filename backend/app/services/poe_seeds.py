"""
poe_seeds — Union bottom-up des Port d'Entrée déjà connus.

Ne crawl pas. Ne touche pas poe_ports. Les sources sont des graines :

  - carte v1 (poe_ports)
  - runs versionnés (poe_run_ports) — mondiaux ou canaris
  - listing communautaire (noms, souvent sans coordonnées)
  - tags OSM déjà posés sur v1 (osm_confidence)

VLIZ (mrgid) reste la clé d'appartenance. Le listing n'est plus un juge
après-coup : c'est une graine. Le crawl SERP / Claude ne devrait viser
que le résidu (listing sans match extrait, ou graine sans coordonnées).

Verdicts de vérification (pas une extraction) :

  confirmed  — listing ∩ (v1|run) + coordonnées : déjà un PoE recoupé
  probable   — OSM ≥ 0.5 ou ≥ 2 runs extraits, ou listing ∩ extrait sans point
  unverified — une seule source extraite (souvent v1 seule) : à juger
  name_only  — listing sans point : file de géocode, pas de SERP mondial
"""
from __future__ import annotations

from collections import Counter

import re

from app.core.dedup import (
    find_duplicate_in_list, merge_docs, normalize_name, text_similarity,
)
from app.services.listing_control import compare_to_listing, load_run_ports
from app.services.listing_ref import project_listing
from app.services.poe_bestof import is_legal_fragment
from app.services.poe_pipeline import now_iso

_PAREN = re.compile(r"\s*\([^)]*\)\s*")
_PREFIX = (
    "porto de ", "port of ", "port de ", "pkk porti i ", "puerto de ", "haven ",
    "port autonome de ",
)


def _alias_name(name: str) -> str:
    n = _PAREN.sub(" ", (name or "").strip()).strip()
    low = n.lower()
    for p in _PREFIX:
        if low.startswith(p):
            return n[len(p):].strip() or n
    return n


def _match_seed(seed: dict, pool: list[dict]) -> dict | None:
    """Dédup : fuzzy habituel + alias « Port of / (…) » (Fort Bay ≈ Fort Bay (Fort Baai))."""
    hit = find_duplicate_in_list(seed, pool, title_key="name")
    if hit:
        return hit
    a = _alias_name(seed.get("name") or "")
    if not a:
        return None
    for other in pool:
        b = _alias_name(other.get("name") or "")
        if not b:
            continue
        if find_duplicate_in_list({"name": a}, [{"name": b}], title_key="name"):
            return other
        if text_similarity(a, b) >= 0.90:
            return other
        if seed.get("mrgid") is not None and seed.get("mrgid") == other.get("mrgid"):
            if text_similarity(a, b) >= 0.82:
                return other
    return None

# Runs mondiaux déjà en base Atlas (285 ZEE). Le canari 12 ZEE n'en fait pas partie.
DEFAULT_MONDIAL_RUN_IDS = (
    "20260905-201122-91f6da",   # bestof3-complete
    "20260905-084036-fe1e08",   # bestof3-v2
    "20260905-084036-5ecfa7",   # bestof3-tinyfish
    "20260904-073236-8748b2",   # tinyfish-vs-v1-full
    "20260829-003645-d7ab2e",   # v2-full-from-scratch-2
)


def _slim(port: dict, source: str) -> dict:
    mid = port.get("mrgid")
    try:
        mid = int(mid) if mid is not None else None
    except (TypeError, ValueError):
        mid = None
    name = (port.get("name") or "").strip()
    urls = list(port.get("source_urls") or [])
    return {
        "name": name,
        "mrgid": mid,
        "zone_name": port.get("zone_name"),
        "country_iso2": port.get("country_iso2"),
        "lat": port.get("lat"),
        "lon": port.get("lon"),
        "validated": bool(port.get("validated")),
        "osm_confidence": port.get("osm_confidence"),
        "osm_tags": list(port.get("osm_tags") or []),
        "source_urls": urls,
        "extraction_engine": port.get("extraction_engine"),
        "confidence": port.get("confidence"),
        "dedup_key": port.get("dedup_key") or (
            f"{mid}:{normalize_name(name)}" if mid is not None and name else None
        ),
        "seed_sources": [source],
        "has_coords": port.get("lat") is not None and port.get("lon") is not None,
    }


def _merge_seed(existing: dict, incoming: dict) -> None:
    """Enrichit existing. Union des sources ; les coords vides se remplissent."""
    srcs = list(existing.get("seed_sources") or [])
    for s in incoming.get("seed_sources") or []:
        if s not in srcs:
            srcs.append(s)
    existing["seed_sources"] = srcs
    existing.update(merge_docs(existing, incoming))
    urls = list(existing.get("source_urls") or [])
    for u in incoming.get("source_urls") or []:
        if u and u not in urls:
            urls.append(u)
    existing["source_urls"] = urls
    a = existing.get("osm_confidence")
    b = incoming.get("osm_confidence")
    if b is not None and (a is None or float(b) > float(a)):
        existing["osm_confidence"] = b
        if incoming.get("osm_tags"):
            existing["osm_tags"] = list(incoming["osm_tags"])
    existing["has_coords"] = (
        existing.get("lat") is not None and existing.get("lon") is not None
    )
    existing["validated"] = bool(existing.get("validated") or incoming.get("validated"))
    if existing.get("mrgid") is None and incoming.get("mrgid") is not None:
        existing["mrgid"] = incoming["mrgid"]
        existing["zone_name"] = existing.get("zone_name") or incoming.get("zone_name")


def union_extracted(batches: list[tuple[str, list[dict]]],
                    drop_legal: bool = True) -> list[dict]:
    """Déduplique v1 + runs. `batches` = [(source, ports), ...].

    L'appariement se fait par ZEE (mrgid) : un scan mondial O(n²) timeout
    au-delà de quelques milliers de ports.
    """
    out: list[dict] = []
    by_zone: dict[int | None, list[dict]] = {}
    by_key: dict[str, dict] = {}
    for source, ports in batches:
        for raw in ports:
            if not (raw.get("name") or "").strip():
                continue
            if drop_legal and is_legal_fragment(raw):
                continue
            seed = _slim(raw, source)
            key = seed.get("dedup_key")
            if key and key in by_key:
                _merge_seed(by_key[key], seed)
                continue
            pool = by_zone.setdefault(seed.get("mrgid"), [])
            hit = _match_seed(seed, pool)
            if hit is None:
                out.append(seed)
                pool.append(seed)
                if key:
                    by_key[key] = seed
            else:
                _merge_seed(hit, seed)
                if key:
                    by_key[key] = hit
    return out


def listing_name_seeds(listing_ports: list[dict]) -> list[dict]:
    """Graines nom-seul (rôle poe). Pas de lat/lon."""
    seeds = []
    for lp in listing_ports:
        if lp.get("role") != "poe":
            continue
        name = (lp.get("name") or "").strip()
        if not name:
            continue
        mid = lp.get("mrgid")
        try:
            mid = int(mid) if mid is not None else None
        except (TypeError, ValueError):
            mid = None
        seeds.append({
            "name": name,
            "mrgid": mid,
            "mrgids": list(lp.get("mrgids") or ([mid] if mid is not None else [])),
            "zone_name": lp.get("zone_name"),
            "country_iso2": lp.get("country_iso2"),
            "slug": lp.get("slug"),
            "lat": None,
            "lon": None,
            "validated": False,
            "osm_confidence": None,
            "osm_tags": [],
            "source_urls": [],
            "extraction_engine": "listing",
            "dedup_key": lp.get("dedup_key") or (
                f"{mid}:{normalize_name(name)}" if mid is not None else None
            ),
            "seed_sources": ["listing"],
            "has_coords": False,
        })
    return seeds


def attach_listing_seeds(extracted: list[dict], listing_ports: list[dict]) -> dict:
    """Ajoute les noms listing sans match. Les matches annotent la graine extraite."""
    listing_seeds = listing_name_seeds(listing_ports)
    by_zone: dict[int | None, list[dict]] = {}
    for p in extracted:
        by_zone.setdefault(p.get("mrgid"), []).append(p)
    attached = 0
    novel = []
    for ls in listing_seeds:
        pool = []
        for mid in ls.get("mrgids") or ([ls["mrgid"]] if ls.get("mrgid") is not None else []):
            pool.extend(by_zone.get(mid) or [])
        if not pool:
            novel.append(ls)
            continue
        hit = _match_seed(ls, pool)
        if hit is not None:
            _merge_seed(hit, ls)
            hit["listing_name"] = ls["name"]
            attached += 1
        else:
            novel.append(ls)
    seeds = extracted + novel
    return {
        "extracted": extracted,
        "seeds": seeds,
        "listing_attached": attached,
        "listing_novel": novel,
    }


def _source_counts(ports: list[dict]) -> dict[str, int]:
    c: Counter[str] = Counter()
    for p in ports:
        for s in p.get("seed_sources") or []:
            c[s] += 1
    return dict(c)


VERDICTS = ("confirmed", "probable", "unverified", "name_only")


def _has_extracted_source(seed: dict) -> bool:
    return any(
        s == "v1" or str(s).startswith("run:")
        for s in (seed.get("seed_sources") or [])
    )


def _extracted_source_count(seed: dict) -> int:
    return sum(
        1 for s in (seed.get("seed_sources") or [])
        if s == "v1" or str(s).startswith("run:")
    )


def verdict_for_seed(seed: dict) -> str:
    """Classe une graine : est-ce déjà un PoE recoupé, ou un nom à vérifier ?"""
    srcs = set(seed.get("seed_sources") or [])
    has_listing = "listing" in srcs
    has_extracted = _has_extracted_source(seed)
    has_coords = bool(seed.get("has_coords") or (
        seed.get("lat") is not None and seed.get("lon") is not None))
    try:
        osm = float(seed["osm_confidence"]) if seed.get("osm_confidence") is not None else None
    except (TypeError, ValueError):
        osm = None
    osm_hi = osm is not None and osm >= 0.5
    multi = _extracted_source_count(seed) >= 2

    if has_listing and has_extracted and has_coords:
        return "confirmed"
    if has_listing and has_extracted:
        return "probable"
    if has_listing and not has_extracted:
        return "name_only"
    if has_extracted and has_coords and (osm_hi or multi):
        return "probable"
    if has_extracted and has_coords:
        return "unverified"
    if has_listing:
        return "name_only"
    return "unverified"


def annotate_verdicts(seeds: list[dict]) -> dict[str, int]:
    """Pose verify_verdict sur chaque graine. Retourne les comptes."""
    buckets = {v: 0 for v in VERDICTS}
    for seed in seeds:
        verdict = verdict_for_seed(seed)
        seed["verify_verdict"] = verdict
        buckets[verdict] += 1
    return buckets


def build_seed_report(extracted: list[dict], listing_ports: list[dict],
                      include_listing_seeds: bool = True) -> dict:
    """Couverture listing de l'union extraite, plus file résiduelle."""
    packed = attach_listing_seeds(list(extracted), listing_ports)
    extracted = packed["extracted"]
    seeds = packed["seeds"] if include_listing_seeds else extracted
    by_verdict = annotate_verdicts(seeds)
    cmp = compare_to_listing(
        extracted, listing_ports, restrict_to_run_zones=False)
    residual = []
    for row in (cmp.get("review") or {}).get("listing_only") or []:
        listing = row.get("listing") or {}
        residual.append({
            "mrgid": row.get("mrgid"),
            "zone_name": row.get("zone_name"),
            "name": listing.get("name"),
            "slug": listing.get("slug"),
            "action": "geocode_then_osm",
        })
    geocoded = sum(1 for p in extracted if p.get("has_coords"))
    osm_hi = sum(1 for p in extracted if (p.get("osm_confidence") or 0) >= 0.5)
    summary = {
        **cmp["summary"],
        "extracted_ports": len(extracted),
        "extracted_geocoded": geocoded,
        "extracted_osm_high": osm_hi,
        "listing_names_attached": packed["listing_attached"],
        "listing_names_novel": len(packed["listing_novel"]),
        "seed_ports": len(seeds),
        "residual": len(residual),
        "by_source": _source_counts(extracted),
        "by_verdict": by_verdict,
    }
    return {
        "summary": summary,
        "listing": cmp,
        "residual": residual,
        "extracted": extracted,
        "seeds": seeds,
        "built_at": now_iso(),
    }


async def persist_verify_run(db, report: dict, *, label: str = "seed-verify") -> dict:
    """Écrit l'union classée dans un run versionné. Ne touche pas poe_ports."""
    from app.services.poe_runs import ensure_run_indexes, new_run_id
    from app.services.run_fingerprint import build_code_fingerprint, merge_run_params

    await ensure_run_indexes(db)
    run_id = new_run_id()
    now = now_iso()
    seeds = list(report.get("seeds") or [])
    docs: list[dict] = []
    by_zone: dict[int, list[dict]] = {}
    for seed in seeds:
        mid = seed.get("mrgid")
        try:
            mid_i = int(mid) if mid is not None else None
        except (TypeError, ValueError):
            mid_i = None
        doc = {
            "run_id": run_id,
            "name": seed.get("name"),
            "mrgid": mid_i,
            "zone_name": seed.get("zone_name"),
            "country_iso2": seed.get("country_iso2"),
            "lat": seed.get("lat"),
            "lon": seed.get("lon"),
            "validated": bool(seed.get("validated")),
            "osm_confidence": seed.get("osm_confidence"),
            "osm_tags": list(seed.get("osm_tags") or []),
            "source_urls": list(seed.get("source_urls") or []),
            "extraction_engine": "seed",
            "seed_sources": list(seed.get("seed_sources") or []),
            "verify_verdict": seed.get("verify_verdict") or verdict_for_seed(seed),
            "confidence": seed.get("confidence"),
            "listing_name": seed.get("listing_name"),
            "extracted_at": now,
            "dedup_key": seed.get("dedup_key"),
        }
        docs.append(doc)
        if mid_i is not None:
            by_zone.setdefault(mid_i, []).append(doc)
    if docs:
        await db.poe_run_ports.insert_many(docs)
    zone_docs = []
    for mid, ports in by_zone.items():
        confirmed = sum(1 for p in ports if p.get("verify_verdict") == "confirmed")
        zone_docs.append({
            "run_id": run_id,
            "mrgid": mid,
            "name": ports[0].get("zone_name"),
            "status": "ia" if ports else "erreur",
            "poe_count": len(ports),
            "verify_confirmed": confirmed,
            "generated_at": now,
        })
    if zone_docs:
        await db.poe_run_zones.insert_many(zone_docs)
    fingerprint = build_code_fingerprint({}, zone_timeout_s=0)
    params = merge_run_params({
        "label": label,
        "variant": "verify",
        "crawled": False,
        "force": False,
        "use_seeds": True,
    }, fingerprint)
    summary = dict(report.get("summary") or {})
    summary["run_id"] = run_id
    await db.poe_runs.insert_one({
        "_id": run_id,
        "label": label,
        "params": params,
        "state": "done",
        "created_at": now,
        "started_at": now,
        "finished_at": now,
        "zones_total": len(zone_docs),
        "zones_done": len(zone_docs),
        "ports_total": len(docs),
        "by_status": {"ia": len(zone_docs)},
        "summary": summary,
        "error": None,
    })
    return {
        "run_id": run_id,
        "ports": len(docs),
        "zones": len(zone_docs),
        "wrote_poe_ports": False,
        "crawled": False,
        "by_verdict": summary.get("by_verdict"),
    }


async def collect_seed_report(db, run_ids: list[str] | None = None,
                              include_v1: bool = True,
                              include_listing: bool = True,
                              use_default_mondials: bool = False) -> dict:
    """Charge Atlas, unionne, classe. Retourne le rapport interne (avec seeds)."""
    ids = list(run_ids or [])
    if use_default_mondials and not ids:
        ids = list(DEFAULT_MONDIAL_RUN_IDS)
    batches: list[tuple[str, list[dict]]] = []
    loaded = []
    missing = []
    if include_v1:
        ports, meta = await load_run_ports(db, "v1")
        batches.append(("v1", ports))
        loaded.append(meta)
    for rid in ids:
        try:
            ports, meta = await load_run_ports(db, rid)
        except KeyError:
            missing.append(rid)
            continue
        batches.append((f"run:{rid}", ports))
        loaded.append(meta)
    extracted = union_extracted(batches)
    proj = project_listing()
    listing_ports = proj["ports"] if include_listing else []
    report = build_seed_report(extracted, listing_ports)
    report["listing_ref_id"] = proj["listing_ref_id"]
    report["listing_stats"] = proj["stats"]
    report["sources"] = loaded
    report["missing_run_ids"] = missing
    return report


def public_seed_view(report: dict, *, mode: str = "seed-union") -> dict:
    """Réponse API : pas les seeds (trop gros), seulement les comptes."""
    return {
        "mode": mode,
        "crawled": False,
        "wrote_poe_ports": False,
        "listing_ref_id": report.get("listing_ref_id"),
        "listing_stats": report.get("listing_stats"),
        "sources": report.get("sources") or [],
        "missing_run_ids": report.get("missing_run_ids") or [],
        "summary": report.get("summary"),
        "residual_preview": (report.get("residual") or [])[:80],
        "residual_total": len(report.get("residual") or []),
        "built_at": report.get("built_at"),
    }


async def build_seed_union(db, run_ids: list[str] | None = None,
                           include_v1: bool = True,
                           include_listing: bool = True,
                           use_default_mondials: bool = False) -> dict:
    """Charge Atlas, unionne, compare au listing. Lecture seule."""
    report = await collect_seed_report(
        db, run_ids, include_v1=include_v1, include_listing=include_listing,
        use_default_mondials=use_default_mondials)
    return public_seed_view(report)
