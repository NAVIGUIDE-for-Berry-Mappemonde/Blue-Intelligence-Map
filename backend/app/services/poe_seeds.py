"""
poe_seeds — Inventaire bottom-up des ports candidats déjà connus.

Ne crawl pas. Ne touche pas poe_ports. Les sources sont des graines
(union dédupliquée, pas un croisement exclusif) :

  - carte v1 (poe_ports)
  - runs versionnés (poe_run_ports) — mondiaux ou canaris
  - OSM cache (osm_port_seeds) + priors fichier (harbour/marina ≤ 800 m
    d'une douane / border_control)
  - listing communautaire (rôle poe | other, souvent sans coordonnées)

Une identité (mrgid + nom) porte toutes les observations. On n'aplatit
pas listing / OSM / runs en un seul is_poe. VLIZ (mrgid) = clé de zone,
pas un moteur de crawl.

Collection persistée : poe_seed_ports (reconstruite).
La graine dit à TinyFish *quoi* chercher (`search_query`). Noonsite est
exclu des recherches : le listing est déjà dans la base. Claude juge les
extraits officiels (nom + zone), pas les jetons listing/OSM/runs.

Verdicts de vérification (pas une extraction) :

  confirmed  — listing:poe ∩ (v1|run|osm) + coordonnées : déjà recoupé
  probable   — OSM ≥ 0.5 ou ≥ 2 sources extraites, ou listing:poe ∩ extrait sans point
  unverified — une seule source extraite (souvent v1 seule) : à juger
  name_only  — listing:poe sans point : file de géocode, pas de SERP mondial
"""
from __future__ import annotations

import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from app.config import DATA_DIR
from app.core.dedup import (
    find_duplicate_in_list, merge_docs, normalize_name, text_similarity,
)
from app.core.geo import haversine_km
from app.services.listing_control import compare_to_listing, load_run_ports
from app.services.listing_ref import listing_ports_for_mrgid, project_listing
from app.services.poe_bestof import is_legal_fragment
from app.services.poe_pipeline import now_iso

SEED_COLLECTION = "poe_seed_ports"
OSM_PRIORS_FILE = DATA_DIR / "osm_port_priors.json"
# Déjà extrait dans le listing — ne pas le redemander à TinyFish.
SEARCH_EXCLUDE_DOMAINS = ("noonsite.com",)

SEED_LEGEND = (
    "Ligne graine (prior, pas une preuve officielle). "
    "Jeton absent = inconnu, jamais faux. "
    "Grammaire : NOM [| lat,lon] [| jeton · jeton]. "
    "listing:poe = Noonsite classe ce lieu PoE ; "
    "listing:other = autre port Noonsite ; "
    "osm:customs = douane OSM ≤ 800 m ; "
    "osm:border = barrier=border_control ≤ 800 m ; "
    "osm:poe=yes|no = tag port_of_entry ; "
    "osm:marina / osm:port = infra OSM ; "
    "runs:N = vu dans N extraits (v1 inclus) ; "
    "verdict:* = confirmed|probable|unverified|name_only. "
    "Juge uniquement CE lieu. Ne liste aucun autre port."
)

OSM_PROXIMITY_KM = 0.8

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


def _source_kind(origin: str) -> str:
    if origin == "listing":
        return "listing"
    if origin == "osm":
        return "osm"
    return "run"


def _observation(origin: str, port: dict) -> dict:
    return {
        "source": _source_kind(origin),
        "origin": origin,
        "name": port.get("name"),
        "lat": port.get("lat"),
        "lon": port.get("lon"),
        "source_urls": list(port.get("source_urls") or [])[:8],
        "osm_id": port.get("osm_id"),
        "listing_role": port.get("listing_role") or port.get("role"),
        "osm_customs": bool(port.get("osm_customs")),
        "osm_border": bool(port.get("osm_border") or port.get("osm_border_control")),
        "osm_port_of_entry": port.get("osm_port_of_entry"),
        "extraction_engine": port.get("extraction_engine"),
    }


def _slim(port: dict, source: str) -> dict:
    mid = port.get("mrgid")
    try:
        mid = int(mid) if mid is not None else None
    except (TypeError, ValueError):
        mid = None
    name = (port.get("name") or "").strip()
    urls = list(port.get("source_urls") or [])
    role = port.get("listing_role") or port.get("role")
    seed = {
        "name": name,
        "mrgid": mid,
        "zone_name": port.get("zone_name"),
        "country_iso2": port.get("country_iso2"),
        "lat": port.get("lat"),
        "lon": port.get("lon"),
        "validated": bool(port.get("validated")),
        "osm_confidence": port.get("osm_confidence"),
        "osm_tags": list(port.get("osm_tags") or []),
        "osm_id": port.get("osm_id"),
        "osm_ids": list(port.get("osm_ids") or (
            [port["osm_id"]] if port.get("osm_id") else [])),
        "source_urls": urls,
        "extraction_engine": port.get("extraction_engine"),
        "confidence": port.get("confidence"),
        "dedup_key": port.get("dedup_key") or (
            f"{mid}:{normalize_name(name)}" if mid is not None and name else None
        ),
        "seed_sources": [source],
        "has_coords": port.get("lat") is not None and port.get("lon") is not None,
        "listing_role": role,
        "osm_customs": bool(port.get("osm_customs")),
        "osm_border": bool(port.get("osm_border") or port.get("osm_border_control")),
        "osm_port_of_entry": port.get("osm_port_of_entry"),
        "osm_kinds": list(port.get("osm_kinds") or []),
    }
    seed["observations"] = list(port.get("observations") or [_observation(source, seed)])
    return seed


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
    ids = list(existing.get("osm_ids") or [])
    for oid in incoming.get("osm_ids") or []:
        if oid and oid not in ids:
            ids.append(oid)
    if incoming.get("osm_id") and incoming["osm_id"] not in ids:
        ids.append(incoming["osm_id"])
    existing["osm_ids"] = ids
    if not existing.get("osm_id") and incoming.get("osm_id"):
        existing["osm_id"] = incoming["osm_id"]
    existing["has_coords"] = (
        existing.get("lat") is not None and existing.get("lon") is not None
    )
    existing["validated"] = bool(existing.get("validated") or incoming.get("validated"))
    if existing.get("mrgid") is None and incoming.get("mrgid") is not None:
        existing["mrgid"] = incoming["mrgid"]
        existing["zone_name"] = existing.get("zone_name") or incoming.get("zone_name")
    in_role = incoming.get("listing_role")
    if existing.get("listing_role") == "poe" or in_role == "poe":
        existing["listing_role"] = "poe"
    elif in_role and not existing.get("listing_role"):
        existing["listing_role"] = in_role
    existing["osm_customs"] = bool(
        existing.get("osm_customs") or incoming.get("osm_customs"))
    existing["osm_border"] = bool(
        existing.get("osm_border") or incoming.get("osm_border")
        or incoming.get("osm_border_control"))
    poe_in, poe_ex = incoming.get("osm_port_of_entry"), existing.get("osm_port_of_entry")
    if poe_in == "yes" or poe_ex == "yes":
        existing["osm_port_of_entry"] = "yes"
    elif poe_in and not poe_ex:
        existing["osm_port_of_entry"] = poe_in
    kinds = list(existing.get("osm_kinds") or [])
    for kind in incoming.get("osm_kinds") or []:
        if kind not in kinds:
            kinds.append(kind)
    existing["osm_kinds"] = kinds
    obs = list(existing.get("observations") or [])
    seen = {(o.get("origin"), o.get("name"), o.get("osm_id")) for o in obs}
    incoming_obs = incoming.get("observations") or [
        _observation((incoming.get("seed_sources") or ["?"])[0], incoming)]
    for o in incoming_obs:
        key = (o.get("origin"), o.get("name"), o.get("osm_id"))
        if key not in seen:
            seen.add(key)
            obs.append(o)
    existing["observations"] = obs[:24]


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
            "osm_id": None,
            "osm_ids": [],
            "source_urls": [],
            "extraction_engine": "listing",
            "dedup_key": lp.get("dedup_key") or (
                f"{mid}:{normalize_name(name)}" if mid is not None else None
            ),
            "seed_sources": ["listing"],
            "has_coords": False,
            "listing_role": "poe",
            "osm_customs": False,
            "osm_border": False,
            "osm_port_of_entry": None,
            "osm_kinds": [],
            "observations": [_observation("listing", {
                "name": name, "listing_role": "poe",
                "extraction_engine": "listing",
            })],
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


def attach_listing_other(seeds: list[dict], listing_ports: list[dict]) -> int:
    """Attache le rôle listing:other sur une identité déjà connue. Pas de graine novel."""
    by_zone: dict[int | None, list[dict]] = {}
    for p in seeds:
        by_zone.setdefault(p.get("mrgid"), []).append(p)
    attached = 0
    for lp in listing_ports:
        if lp.get("role") != "other":
            continue
        name = (lp.get("name") or "").strip()
        if not name:
            continue
        mid = lp.get("mrgid")
        try:
            mid = int(mid) if mid is not None else None
        except (TypeError, ValueError):
            mid = None
        incoming = {
            "name": name,
            "mrgid": mid,
            "seed_sources": ["listing"],
            "listing_role": "other",
            "has_coords": False,
            "observations": [_observation("listing", {
                "name": name, "listing_role": "other",
                "extraction_engine": "listing",
            })],
        }
        pool: list[dict] = []
        for zid in lp.get("mrgids") or ([mid] if mid is not None else []):
            pool.extend(by_zone.get(zid) or [])
        hit = _match_seed(incoming, pool) if pool else None
        if hit is None:
            continue
        _merge_seed(hit, incoming)
        attached += 1
    return attached


def _nearest_seed(seed: dict, pool: list[dict], max_km: float) -> dict | None:
    if seed.get("lat") is None or seed.get("lon") is None:
        return None
    best, best_d = None, max_km
    for other in pool:
        if other.get("lat") is None or other.get("lon") is None:
            continue
        try:
            dist = haversine_km(
                float(seed["lat"]), float(seed["lon"]),
                float(other["lat"]), float(other["lon"]))
        except (TypeError, ValueError):
            continue
        if dist < best_d:
            best, best_d = other, dist
    return best


def attach_osm_seeds(extracted: list[dict], osm_docs: list[dict]) -> dict:
    """Union OSM : fusion nom / proximité, création des havres nommés orphelins."""
    from app.services.osm_seeds import cache_doc_to_seed, is_seed_candidate

    by_zone: dict[int | None, list[dict]] = {}
    for p in extracted:
        by_zone.setdefault(p.get("mrgid"), []).append(p)

    merged_name = merged_near = created = 0
    skipped_unnamed = skipped_no_eez = skipped_bad = skipped_not_candidate = 0
    for raw in osm_docs:
        if not raw.get("in_eez") or raw.get("mrgid") is None:
            skipped_no_eez += 1
            continue
        tags = {str(k): str(v) for k, v in (raw.get("tags") or {}).items()}
        if tags and not is_seed_candidate(tags):
            skipped_not_candidate += 1
            continue
        seed = cache_doc_to_seed(raw)
        if seed is None:
            skipped_bad += 1
            continue
        pool = by_zone.setdefault(seed.get("mrgid"), [])
        hit = _match_seed(seed, pool) if seed.get("name") else None
        if hit is not None:
            _merge_seed(hit, seed)
            merged_name += 1
            continue
        near = _nearest_seed(seed, pool, OSM_PROXIMITY_KM)
        if near is not None:
            _merge_seed(near, seed)
            merged_near += 1
            continue
        if not seed.get("name"):
            skipped_unnamed += 1
            continue
        extracted.append(seed)
        pool.append(seed)
        created += 1
    return {
        "osm_candidates_in_eez": len(osm_docs),
        "osm_merged_by_name": merged_name,
        "osm_merged_by_proximity": merged_near,
        "osm_created": created,
        "osm_skipped_unnamed_in_eez": skipped_unnamed,
        "osm_skipped_outside_eez": skipped_no_eez,
        "osm_skipped_not_candidate": skipped_not_candidate,
        "osm_skipped_bad": skipped_bad,
    }


@lru_cache(maxsize=1)
def load_osm_priors(path: str | None = None) -> dict:
    p = Path(path) if path else OSM_PRIORS_FILE
    if not p.is_file():
        return {"n": 0, "ports": []}
    return json.loads(p.read_text(encoding="utf-8"))


def osm_priors_as_seeds(osm: dict | None = None) -> list[dict]:
    """Havres / marinas déjà recoupés avec une douane ou un poste frontière."""
    doc = osm if osm is not None else load_osm_priors()
    out: list[dict] = []
    for raw in doc.get("ports") or []:
        name = (raw.get("name") or "").strip()
        if not name:
            continue
        zones = raw.get("eez") or []
        in_eez = [z for z in zones if z.get("relation") == "in_eez"]
        use = in_eez or [z for z in zones if z.get("relation")]
        customs = bool(raw.get("customs"))
        border = bool(raw.get("border_control"))
        poe = raw.get("port_of_entry")
        kinds = list(raw.get("kinds") or [])
        conf = 0.4
        if customs:
            conf = 0.55
        if customs and border:
            conf = 0.65
        if poe == "yes":
            conf = max(conf, 0.7)
        tags: list[str] = []
        if customs:
            tags.append("customs@800m")
        if border:
            tags.append("border_control@800m")
        if poe:
            tags.append(f"port_of_entry={poe}")
        for zone in use:
            try:
                mid = int(zone.get("mrgid"))
            except (TypeError, ValueError):
                continue
            seed = {
                "name": name,
                "mrgid": mid,
                "zone_name": zone.get("name"),
                "country_iso2": zone.get("iso2"),
                "lat": raw.get("lat"),
                "lon": raw.get("lon"),
                "validated": zone.get("relation") == "in_eez",
                "osm_confidence": conf,
                "osm_tags": list(tags),
                "osm_id": raw.get("id"),
                "osm_ids": [raw["id"]] if raw.get("id") else [],
                "source_urls": (
                    [f"https://www.openstreetmap.org/{raw['id']}"]
                    if raw.get("id") else []),
                "extraction_engine": "osm_prior",
                "confidence": conf,
                "dedup_key": f"{mid}:{normalize_name(name)}",
                "seed_sources": ["osm"],
                "has_coords": raw.get("lat") is not None and raw.get("lon") is not None,
                "listing_role": None,
                "osm_customs": customs,
                "osm_border": border,
                "osm_port_of_entry": poe,
                "osm_kinds": kinds,
            }
            seed["observations"] = [_observation("osm", seed)]
            out.append(seed)
    return out


def attach_converted_osm(extracted: list[dict], osm_seeds: list[dict]) -> dict:
    """Fusionne des graines OSM déjà converties (priors ou cache)."""
    by_zone: dict[int | None, list[dict]] = {}
    for p in extracted:
        by_zone.setdefault(p.get("mrgid"), []).append(p)
    merged_name = merged_near = created = 0
    for seed in osm_seeds:
        if seed.get("mrgid") is None:
            continue
        pool = by_zone.setdefault(seed.get("mrgid"), [])
        hit = _match_seed(seed, pool) if seed.get("name") else None
        if hit is not None:
            _merge_seed(hit, seed)
            merged_name += 1
            continue
        near = _nearest_seed(seed, pool, OSM_PROXIMITY_KM)
        if near is not None:
            _merge_seed(near, seed)
            merged_near += 1
            continue
        if not seed.get("name"):
            continue
        extracted.append(seed)
        pool.append(seed)
        created += 1
    return {
        "osm_priors": len(osm_seeds),
        "osm_merged_by_name": merged_name,
        "osm_merged_by_proximity": merged_near,
        "osm_created": created,
    }


def attach_osm_priors(extracted: list[dict], osm: dict | None = None) -> dict:
    return attach_converted_osm(extracted, osm_priors_as_seeds(osm))


def listing_is_poe(seed: dict) -> bool:
    role = seed.get("listing_role")
    if role == "other":
        return False
    if role == "poe":
        return True
    return "listing" in set(seed.get("seed_sources") or [])


def _tag_blob(seed: dict) -> str:
    return " ".join(str(t).lower() for t in (seed.get("osm_tags") or []))


def seed_tokens(seed: dict) -> list[str]:
    tokens: list[str] = []
    role = seed.get("listing_role")
    srcs = set(seed.get("seed_sources") or [])
    if role == "other":
        tokens.append("listing:other")
    elif role == "poe" or "listing" in srcs:
        tokens.append("listing:poe")
    blob = _tag_blob(seed)
    if seed.get("osm_customs") or "customs" in blob:
        tokens.append("osm:customs")
    if seed.get("osm_border") or "border_control" in blob:
        tokens.append("osm:border")
    poe = seed.get("osm_port_of_entry")
    if poe not in ("yes", "no"):
        if "port_of_entry=yes" in blob:
            poe = "yes"
        elif "port_of_entry=no" in blob:
            poe = "no"
    if poe == "yes":
        tokens.append("osm:poe=yes")
    elif poe == "no":
        tokens.append("osm:poe=no")
    kinds = {str(k) for k in (seed.get("osm_kinds") or [])}
    if "marina" in kinds or "marina" in blob:
        tokens.append("osm:marina")
    if "port" in kinds or "industrial=port" in blob or "harbour" in blob:
        tokens.append("osm:port")
    n_runs = sum(
        1 for s in srcs if s == "v1" or str(s).startswith("run:"))
    if n_runs:
        tokens.append(f"runs:{n_runs}")
    verdict = seed.get("verify_verdict")
    if verdict:
        tokens.append(f"verdict:{verdict}")
    return tokens


def format_seed_line(seed: dict) -> str:
    """Résumé humain de l'inventaire — pas envoyé à Claude."""
    name = (seed.get("name") or "").strip() or "unknown"
    parts = [name]
    if seed.get("lat") is not None and seed.get("lon") is not None:
        try:
            parts.append(f"{float(seed['lat']):.3f},{float(seed['lon']):.3f}")
        except (TypeError, ValueError):
            pass
    tokens = seed_tokens(seed)
    if tokens:
        parts.append(" · ".join(tokens))
    return " | ".join(parts)


def seed_search_query(seed: dict) -> str:
    """Requête TinyFish pour CETTE graine. Pas de nom Noonsite, pas de jetons."""
    name = (seed.get("name") or seed.get("listing_name") or "").strip()
    zone = (seed.get("zone_name") or "").strip()
    if not name:
        return ""
    q = f'{name} official port of entry OR clearance OR "puerto habilitado"'
    if zone:
        q = f"{q} {zone}"
    return q


def url_is_excluded_search(url: str, banned=SEARCH_EXCLUDE_DOMAINS) -> bool:
    """True si l'URL est noonsite (ou autre domaine déjà extrait)."""
    from app.core.tinyfish import _tf_domain
    host = _tf_domain(url or "")
    if not host:
        return False
    return any(host == b or host.endswith("." + b) for b in banned)


def match_named_seed(seeds: list[dict], mrgid: int, name: str) -> dict | None:
    cand = {"name": (name or "").strip(), "mrgid": int(mrgid)}
    pool = [s for s in seeds if s.get("mrgid") == int(mrgid)]
    return _match_seed(cand, pool)


def seed_from_files(mrgid: int, name: str, *,
                    listing_ports: list[dict] | None = None,
                    priors_doc: dict | None = None) -> dict | None:
    """Lookup hors Mongo : listing + priors OSM pour une ZEE."""
    mid = int(mrgid)
    listing = listing_ports if listing_ports is not None else listing_ports_for_mrgid(
        project_listing()["ports"], mid)
    extracted: list[dict] = []
    attach_converted_osm(extracted, [
        s for s in osm_priors_as_seeds(priors_doc) if s.get("mrgid") == mid])
    report = build_seed_report(extracted, listing)
    return match_named_seed(report["seeds"], mid, name)


def build_seeds_offline(*, extracted: list[dict] | None = None,
                        listing_ports: list[dict] | None = None,
                        priors_doc: dict | None = None,
                        include_priors: bool = True) -> dict:
    """Assemble l'inventaire sans Mongo (listing + OSM priors + extraits fournis)."""
    ports = list(extracted or [])
    prior_stats: dict = {}
    if include_priors:
        prior_stats = attach_osm_priors(ports, priors_doc)
    if listing_ports is None:
        listing_ports = project_listing()["ports"]
    report = build_seed_report(ports, listing_ports)
    report["osm_priors"] = prior_stats
    return report


def _source_counts(ports: list[dict]) -> dict[str, int]:
    c: Counter[str] = Counter()
    for p in ports:
        for s in p.get("seed_sources") or []:
            c[s] += 1
    return dict(c)


VERDICTS = ("confirmed", "probable", "unverified", "name_only")


def _is_extracted_source(source: str) -> bool:
    return source == "v1" or source == "osm" or str(source).startswith("run:")


def _has_extracted_source(seed: dict) -> bool:
    return any(_is_extracted_source(s) for s in (seed.get("seed_sources") or []))


def _extracted_source_count(seed: dict) -> int:
    return sum(1 for s in (seed.get("seed_sources") or []) if _is_extracted_source(s))


def verdict_for_seed(seed: dict) -> str:
    """Classe une graine : est-ce déjà un PoE recoupé, ou un nom à vérifier ?"""
    has_listing = listing_is_poe(seed)
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
    listing_other = attach_listing_other(seeds, listing_ports)
    by_verdict = annotate_verdicts(seeds)
    for seed in seeds:
        seed["seed_line"] = format_seed_line(seed)
        seed["search_query"] = seed_search_query(seed)
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
        "listing_other_attached": listing_other,
        "seed_ports": len(seeds),
        "residual": len(residual),
        "by_source": _source_counts(extracted),
        "by_source_seeds": _source_counts(seeds),
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
            "osm_id": seed.get("osm_id"),
            "osm_ids": list(seed.get("osm_ids") or []),
            "source_urls": list(seed.get("source_urls") or []),
            "extraction_engine": "seed",
            "seed_sources": list(seed.get("seed_sources") or []),
            "verify_verdict": seed.get("verify_verdict") or verdict_for_seed(seed),
            "confidence": seed.get("confidence"),
            "listing_name": seed.get("listing_name"),
            "listing_role": seed.get("listing_role"),
            "osm_customs": bool(seed.get("osm_customs")),
            "osm_border": bool(seed.get("osm_border")),
            "osm_port_of_entry": seed.get("osm_port_of_entry"),
            "osm_kinds": list(seed.get("osm_kinds") or []),
            "observations": list(seed.get("observations") or []),
            "seed_line": seed.get("seed_line") or format_seed_line(seed),
            "search_query": seed.get("search_query") or seed_search_query(seed),
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


async def ensure_seed_indexes(db) -> None:
    try:
        await db.poe_seed_ports.create_index("dedup_key", unique=True, sparse=True)
        await db.poe_seed_ports.create_index("mrgid")
        await db.poe_seed_ports.create_index("verify_verdict")
        await db.poe_seed_ports.create_index([("mrgid", 1), ("name", 1)])
    except Exception:
        pass


def seed_db_doc(seed: dict, built_at: str) -> dict:
    line = seed.get("seed_line") or format_seed_line(seed)
    query = seed.get("search_query") or seed_search_query(seed)
    return {
        "dedup_key": seed.get("dedup_key"),
        "name": seed.get("name"),
        "mrgid": seed.get("mrgid"),
        "zone_name": seed.get("zone_name"),
        "country_iso2": seed.get("country_iso2"),
        "lat": seed.get("lat"),
        "lon": seed.get("lon"),
        "has_coords": bool(seed.get("has_coords") or (
            seed.get("lat") is not None and seed.get("lon") is not None)),
        "validated": bool(seed.get("validated")),
        "seed_sources": list(seed.get("seed_sources") or []),
        "listing_role": seed.get("listing_role"),
        "listing_name": seed.get("listing_name"),
        "osm_confidence": seed.get("osm_confidence"),
        "osm_tags": list(seed.get("osm_tags") or []),
        "osm_id": seed.get("osm_id"),
        "osm_ids": list(seed.get("osm_ids") or []),
        "osm_customs": bool(seed.get("osm_customs")),
        "osm_border": bool(seed.get("osm_border")),
        "osm_port_of_entry": seed.get("osm_port_of_entry"),
        "osm_kinds": list(seed.get("osm_kinds") or []),
        "source_urls": list(seed.get("source_urls") or []),
        "observations": list(seed.get("observations") or []),
        "verify_verdict": seed.get("verify_verdict") or verdict_for_seed(seed),
        "search_query": query,
        "search_exclude_domains": list(SEARCH_EXCLUDE_DOMAINS),
        "seed_line": line,
        "confidence": seed.get("confidence"),
        "extraction_engine": "seed",
        "built_at": built_at,
    }


async def persist_seed_database(db, report: dict) -> dict:
    """Remplace poe_seed_ports. Ne touche pas poe_ports / poe_run_ports."""
    await ensure_seed_indexes(db)
    built = report.get("built_at") or now_iso()
    by_key: dict[str, dict] = {}
    no_key: list[dict] = []
    for seed in report.get("seeds") or []:
        doc = seed_db_doc(seed, built)
        key = doc.get("dedup_key")
        if key:
            by_key[key] = doc
        else:
            no_key.append(doc)
    docs = list(by_key.values()) + no_key
    for i, doc in enumerate(docs):
        doc["_id"] = doc.get("dedup_key") or f"seed:{i}"
    await db.poe_seed_ports.delete_many({})
    if docs:
        await db.poe_seed_ports.insert_many(docs)
    return {
        "collection": SEED_COLLECTION,
        "ports": len(docs),
        "by_verdict": dict(Counter(d["verify_verdict"] for d in docs)),
        "wrote_poe_ports": False,
        "crawled": False,
        "built_at": built,
    }


async def collect_seed_report(db, run_ids: list[str] | None = None,
                              include_v1: bool = True,
                              include_listing: bool = True,
                              include_osm: bool = True,
                              use_default_mondials: bool = False) -> dict:
    """Charge Atlas, unionne, classe. Retourne le rapport interne (avec seeds)."""
    from app.services.osm_seeds import cache_stats, load_cached_osm

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
    osm_info: dict = {"included": include_osm}
    if include_osm:
        osm_info.update(await cache_stats(db))
        osm_docs = await load_cached_osm(db, in_eez_only=True)
        osm_info.update(attach_osm_seeds(extracted, osm_docs))
        prior_stats = attach_osm_priors(extracted)
        osm_info["priors"] = prior_stats
        loaded.append({
            "run_id": "osm", "label": "osm", "variant": "osm",
            "state": "cache", "ports": osm_info.get("cached_named_in_eez") or 0,
        })
        loaded.append({
            "run_id": "osm_priors", "label": "osm_priors", "variant": "osm",
            "state": "file", "ports": prior_stats.get("osm_priors") or 0,
        })
    proj = project_listing()
    listing_ports = proj["ports"] if include_listing else []
    report = build_seed_report(extracted, listing_ports)
    report["listing_ref_id"] = proj["listing_ref_id"]
    report["listing_stats"] = proj["stats"]
    report["sources"] = loaded
    report["missing_run_ids"] = missing
    report["osm"] = osm_info
    summary = report.get("summary") or {}
    summary["osm"] = {k: osm_info.get(k) for k in (
        "included", "cached_total", "cached_named_in_eez",
        "osm_merged_by_name", "osm_merged_by_proximity", "osm_created",
        "refreshed_at", "priors",
    )}
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
        "osm": report.get("osm") or {},
        "summary": report.get("summary"),
        "residual_preview": (report.get("residual") or [])[:80],
        "residual_total": len(report.get("residual") or []),
        "built_at": report.get("built_at"),
    }


async def build_seed_union(db, run_ids: list[str] | None = None,
                           include_v1: bool = True,
                           include_listing: bool = True,
                           include_osm: bool = True,
                           use_default_mondials: bool = False) -> dict:
    """Charge Atlas, unionne, compare au listing. Lecture seule."""
    report = await collect_seed_report(
        db, run_ids, include_v1=include_v1, include_listing=include_listing,
        include_osm=include_osm, use_default_mondials=use_default_mondials)
    return public_seed_view(report)
