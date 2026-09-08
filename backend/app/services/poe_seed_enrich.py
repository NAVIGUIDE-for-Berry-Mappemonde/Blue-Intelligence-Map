"""
poe_seed_enrich — Géocode les name_only, juge les autres graines.

Search paginé (quota PAYG), Fetch de tous les hits whitelistés (cap 10),
juge Laguna → Muse (listing / inconclusive) si NVIDIA, sinon
Haiku → Sonnet → OpenRouter.
Agent TinyFish seulement si Fetch renvoie bot_blocked (1 / graine, lite puis
stealth, 2 concurrents, cap crédits).

N'écrit jamais dans poe_ports : seulement poe_run_ports / poe_seed_ports.
Reprise : saute les ports déjà géocodés / déjà jugés.
Double lecture : parseur catalogue → sources_bu + remember_seed_urls ;
juge oui/non seulement le résidu (nom absent de la liste).
"""
from __future__ import annotations

import asyncio
import os
from collections import Counter, defaultdict
from functools import lru_cache

from shapely.geometry import shape
from shapely.prepared import prep

from app.core.extract import (
    catalog_is_sufficient, extract_structured_ports, geocode_query_name,
    is_geocodeable_name,
)
from app.core.geo import (
    INLAND_FAR_SCORE_KM,
    classify_poe_point, geocode_port_dual, inland_exception_flags,
    select_geocode_candidate,
)
from app.services.poe_gps_registry import accepted_by_key
from app.core.llm import ask_json
from app.core.tinyfish import (
    FETCH_URL_CAP, SEARCH_PAGE_CAP, tf_api_key, tf_fetch, tf_poe_agent,
    tf_search_pages,
)
from app.services.poe_pipeline import (
    build_whitelist, load_exceptions, now_iso, remember_seed_urls,
    search_polygon_name, url_allowed, urls_with_catalog,
)
from app.services.poe_seeds import (
    SEARCH_EXCLUDE_DOMAINS, listing_is_poe, seed_search_query,
    url_is_excluded_search, verdict_for_seed, _match_seed,
)

JUDGE_SYSTEM = (
    "Tu es un juge Ports d'Entrée pour la plaisance. Réponds uniquement en JSON strict : "
    '{"is_poe": true, "confidence": 0, "reason": "", "official_name": null, '
    '"kind": "pleasure"} '
    'kind = pleasure | mixed | cargo | other | unknown. '
    "is_poe=true seulement si une source officielle désigne CE lieu comme "
    "port d'entrée / clearance / puerto habilitado / designated port "
    "POUR la plaisance (yacht, recreational, pleasure craft) OU mixte "
    "(commerce ET plaisance explicites). "
    "false si cargo-only, terminal conteneur, industriel, aéroport, ville, autre pays. "
    "Une marina n'est PAS false automatique : si clearance officielle à CETTE marina, "
    "is_poe=true et kind=pleasure. "
    "null si extraits insuffisants, ou port désigné sans trafic lisible "
    "(plaisance vs cargo). "
    "Juge uniquement le lieu nommé. Ne liste aucun autre port. "
    "Ignore listing communautaire et forums."
)

_KIND_CANON = {
    "pleasure": "pleasure",
    "yacht": "pleasure",
    "yachts": "pleasure",
    "recreational": "pleasure",
    "pleasure_craft": "pleasure",
    "pleasurecraft": "pleasure",
    "plaisance": "pleasure",
    "mixed": "mixed",
    "mixte": "mixed",
    "both": "mixed",
    "cargo": "cargo",
    "commercial": "cargo",
    "freight": "cargo",
    "industrial": "cargo",
    "commerce": "cargo",
    "container": "cargo",
    "cargo_only": "cargo",
    "other": "other",
    "unknown": "unknown",
}


def normalize_judge_kind(raw) -> str:
    """Canonise kind LLM → pleasure | mixed | cargo | other | unknown."""
    if raw is None:
        return "unknown"
    key = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    return _KIND_CANON.get(key, "unknown")


DEFAULT_VERIFY_RUN = "20260906-071347-6a9509"
VERIFY_ORDER = ("name_only", "unverified", "probable")
DEFAULT_ENRICH_LIMIT = 200
WHITELIST_DOMAIN_CAP = 15
CATALOG_FETCH_CHARS = 20000


def parse_judge(data: dict | None) -> dict:
    data = data if isinstance(data, dict) else {}
    flag = data.get("is_poe")
    kind = normalize_judge_kind(data.get("kind"))
    if flag is True:
        status = "accepted"
    elif flag is False:
        status = "rejected"
    else:
        status = "inconclusive"
    # Filet déterministe : cargo-only n'est jamais un PoE plaisance.
    if kind == "cargo" and status == "accepted":
        status = "rejected"
    try:
        conf = int(data.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0
    return {
        "judge_status": status,
        "judge_confidence": max(0, min(100, conf)),
        "judge_reason": str(data.get("reason") or "")[:240],
        "official_name": data.get("official_name"),
        "judge_kind": kind,
    }


def apply_judge_verdict(seed: dict, judge: dict) -> str:
    """Met à jour verify_verdict après un jugement. Ne touche pas confirmed."""
    current = seed.get("verify_verdict") or verdict_for_seed(seed)
    if current == "confirmed":
        return "confirmed"
    status = judge.get("judge_status")
    has_listing = listing_is_poe(seed)
    has_coords = bool(seed.get("has_coords") or (
        seed.get("lat") is not None and seed.get("lon") is not None))
    if status == "catalog":
        # Faisceau D : nommé par la liste. Pas un oui plaisance (P vient après).
        if current == "name_only" and has_coords:
            return "unverified"
        return current
    if status == "accepted" and has_listing and has_coords:
        return "confirmed"
    if status == "accepted":
        return "probable"
    if status == "rejected" and current == "name_only":
        return "name_only"
    if status == "rejected":
        return "unverified"
    if current == "name_only" and has_coords:
        return "unverified"
    return current


def should_escalate_sonnet(judge: dict | None, doc: dict) -> bool:
    """Sonnet si Haiku inconclusive, ou si la graine vient du listing."""
    status = (judge or {}).get("judge_status")
    if status == "inconclusive" or not judge:
        return True
    return "listing" in set(doc.get("seed_sources") or [])


def select_fetch_urls(hits: list[dict], whitelist: list[str],
                      cap: int = FETCH_URL_CAP) -> list[str]:
    """Tous les hits whitelistés, dans l'ordre Search, cap souple (~10)."""
    out, seen = [], set()
    for h in hits or []:
        u = (h.get("url") or "").strip()
        if not u.startswith("http") or u in seen:
            continue
        if url_is_excluded_search(u):
            continue
        if whitelist and not url_allowed(u, whitelist):
            continue
        if not whitelist:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= cap:
            break
    return out


def _legacy_geocode_cands(dual: dict) -> list[dict]:
    cands = []
    for source in ("nominatim", "geonames"):
        xy = (dual or {}).get(source)
        if not xy:
            continue
        meta = (dual or {}).get(f"{source}_meta") or {}
        cands.append({
            "source": source, "lat": float(xy[0]), "lon": float(xy[1]),
            "label": "",
            "osm_class": meta.get("osm_class") or "",
            "osm_type": meta.get("osm_type") or "",
            "geonames_fcode": meta.get("geonames_fcode") or "",
        })
    return cands


def pick_geocode(dual: dict, port: dict, zone: dict, geom, prepared) -> dict:
    """Score les homonymes (ZEE, parenthèses, listing), puis filtre spatial."""
    dual = dual or {}
    pick = dual.get("pick") or {}
    raw_cands = list(dual.get("candidates") or []) or _legacy_geocode_cands(dual)
    sel = pick if pick.get("status") else None
    if raw_cands and (sel is None or not sel.get("ranked")):
        sel = select_geocode_candidate(raw_cands, port, zone, geom, prepared)
    if sel and sel.get("status") == "ambiguous":
        ranked = sel.get("ranked") or []
        alts = ranked[:2]
        return {
            "lat": None, "lon": None, "geocode_source": None,
            "validated": False, "spatial_kind": "ambiguous",
            "geocode_status": "ambiguous",
            "geocode_arbitration": "ambiguous",
            "geocode_agree": dual.get("agree"),
            "has_coords": False,
            "geocode_alt": [
                {"lat": c.get("lat"), "lon": c.get("lon"),
                 "source": c.get("source"), "score": c.get("score"),
                 "label": (c.get("label") or "")[:160]}
                for c in alts
            ],
        }
    chosen_scored = (sel or {}).get("chosen") if sel else None
    cands = []
    if chosen_scored and chosen_scored.get("lat") is not None:
        sources = [chosen_scored]
        for source in ("nominatim", "geonames"):
            xy = dual.get(source)
            if not xy:
                continue
            if (abs(float(xy[0]) - float(chosen_scored["lat"])) < 1e-4
                    and abs(float(xy[1]) - float(chosen_scored["lon"])) < 1e-4):
                continue
            sources.append({"source": source, "lat": xy[0], "lon": xy[1]})
        # Un seul point à valider : le gagnant du score. Les autres restent
        # dispo si le gagnant est rejeté spatialement.
        ordered = [chosen_scored] + [
            c for c in raw_cands
            if not (abs(float(c["lat"]) - float(chosen_scored["lat"])) < 1e-4
                    and abs(float(c["lon"]) - float(chosen_scored["lon"])) < 1e-4)
        ]
    else:
        ordered = raw_cands
    for item in ordered:
        source = item.get("source") or "nominatim"
        meta = dual.get(f"{source}_meta") or {
            "osm_class": item.get("osm_class") or "",
            "osm_type": item.get("osm_type") or "",
            "geonames_fcode": item.get("geonames_fcode") or "",
        }
        inland = inland_exception_flags(port, zone, meta, official_list=True)
        lat, lon = float(item["lat"]), float(item["lon"])
        row = {"source": source, "lat": lat, "lon": lon,
               "validated": False, "dist_km": None, "kind": "unknown"}
        if geom is not None:
            row.update(classify_poe_point(lat, lon, geom, prepared, inland=inland))
        else:
            row["validated"] = True
            row["kind"] = "unknown"
        cands.append(row)
    if not cands:
        return {"lat": None, "lon": None, "geocode_source": None,
                "validated": False, "spatial_kind": "miss",
                "geocode_agree": dual.get("agree")}
    if dual.get("agree"):
        chosen, arb = cands[0], "agree"
    elif len(cands) == 1:
        chosen, arb = cands[0], "single"
    else:
        valid = [c for c in cands if c.get("validated")]
        chosen, arb = (valid[0] if valid else cands[0]), "eez"
    if not chosen.get("validated") and chosen.get("kind") not in (None, "unknown"):
        other = next((c for c in cands if c is not chosen and c.get("validated")), None)
        if other:
            chosen, arb = other, "spatial_switch"
        else:
            dist = chosen.get("dist_km")
            # Accords Nominatim/GeoNames juste hors sliver 2,2 km (Cassis, Geelong).
            if ((dual or {}).get("agree") and dist is not None
                    and float(dist) <= 4.0):
                return {
                    "lat": chosen["lat"], "lon": chosen["lon"],
                    "geocode_source": chosen["source"],
                    "validated": True, "spatial_kind": chosen.get("kind"),
                    "distance_km": dist,
                    "geocode_agree": True,
                    "geocode_arbitration": "agree_near_eez",
                    "has_coords": True,
                }
            return {
                "lat": None, "lon": None, "geocode_source": None,
                "validated": False, "spatial_kind": chosen.get("kind"),
                "distance_km": dist,
                "geocode_agree": (dual or {}).get("agree"),
                "geocode_arbitration": "spatial_rejected",
                "geocode_rejected_lat": chosen["lat"],
                "geocode_rejected_lon": chosen["lon"],
                "geocode_rejected_source": chosen["source"],
                "has_coords": False,
            }
    return {
        "lat": chosen["lat"], "lon": chosen["lon"],
        "geocode_source": chosen["source"],
        "validated": bool(chosen.get("validated")),
        "spatial_kind": chosen.get("kind"),
        "distance_km": chosen.get("dist_km"),
        "geocode_agree": (dual or {}).get("agree"),
        "geocode_agreement_km": (dual or {}).get("agreement_km"),
        "geocode_arbitration": arb,
        "has_coords": True,
    }


GPS_AUDIT_KEEP = {"ok", "corrected", "dismissed"}
INLAND_FAR_KINDS = {"inland_river", "inland", "other_water"}


def _needs_geocode(doc: dict) -> bool:
    """name_only sans GPS, ou inland_far / ambiguous. Pas les confirmed ok."""
    verdict = doc.get("verify_verdict") or ""
    audit = doc.get("gps_audit_status") or ""
    if verdict == "confirmed" and audit in GPS_AUDIT_KEEP:
        return False
    if (doc.get("geocode_status") or doc.get("geocode_arbitration")) == "ambiguous":
        return True
    kind = doc.get("spatial_kind") or doc.get("spatial_class") or ""
    dist = doc.get("dist_km_to_eez_poly")
    if dist is None:
        dist = doc.get("distance_km")
    try:
        dist_f = float(dist) if dist is not None else None
    except (TypeError, ValueError):
        dist_f = None
    if kind in INLAND_FAR_KINDS and dist_f is not None and dist_f > INLAND_FAR_SCORE_KM:
        return True
    if audit == "flagged":
        reasons = doc.get("gps_audit_reasons") or []
        if any(r in reasons for r in (
                "inland_far", "listing_group_outlier",
                "homonym_paren_mismatch", "nominatim_inland_listing_only")):
            return True
    if doc.get("geocoded_at"):
        return False
    if doc.get("lat") is not None and doc.get("lon") is not None:
        return False
    return verdict == "name_only"


def _needs_judge(doc: dict, verdicts: tuple[str, ...]) -> bool:
    if doc.get("judge_status"):
        return False
    return (doc.get("verify_verdict") or "") in verdicts


async def _zone_cache(db, mrgids: set[int]) -> dict[int, dict]:
    if not mrgids:
        return {}
    docs = await db.eez_zones.find(
        {"mrgid": {"$in": list(mrgids)}},
        {"mrgid": 1, "name": 1, "geoname": 1, "iso2": 1, "sov_iso2": 1,
         "sovereign": 1, "geometry": 1, "sources_bu": 1, "catalog_bu": 1},
    ).to_list(500)
    out = {}
    for z in docs:
        mid = z.get("mrgid")
        if mid is None:
            continue
        geom = prepared = None
        try:
            if z.get("geometry"):
                geom = shape(z["geometry"])
                prepared = prep(geom)
        except Exception:
            geom = prepared = None
        rec = {**z, "_geom": geom, "_prep": prepared}
        rec["_bu_catalog"] = catalog_cache_from_zone(rec)
        out[int(mid)] = rec
    return out


@lru_cache(maxsize=1)
def _listing_group_by_key() -> dict[str, str]:
    from app.services.listing_ref import project_listing
    out: dict[str, str] = {}
    try:
        for p in project_listing().get("ports") or []:
            k = p.get("dedup_key")
            g = p.get("group")
            if k and g:
                out[str(k)] = str(g)
    except Exception:
        return out
    return out


def attach_geocode_context(ports: list[dict]) -> None:
    """listing_group + pairs côtiers (filtre, jamais un GPS à copier)."""
    groups = _listing_group_by_key()
    for p in ports:
        if not p.get("listing_group"):
            g = groups.get(str(p.get("dedup_key") or ""))
            if g:
                p["listing_group"] = g
    peers_by: dict[tuple, list] = defaultdict(list)
    for p in ports:
        try:
            lat, lon = p.get("lat"), p.get("lon")
            if lat is None or lon is None:
                continue
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            continue
        kind = p.get("spatial_kind") or p.get("spatial_class") or ""
        audit = p.get("gps_audit_status") or ""
        inland = kind in INLAND_FAR_KINDS
        if inland and audit not in GPS_AUDIT_KEEP:
            continue
        grp = p.get("listing_group")
        if not grp or p.get("mrgid") is None:
            continue
        try:
            mid = int(p["mrgid"])
        except (TypeError, ValueError):
            continue
        peers_by[(mid, grp)].append(
            {"lat": lat, "lon": lon, "name": p.get("name")})
    for p in ports:
        grp = p.get("listing_group")
        if not grp or p.get("mrgid") is None:
            continue
        try:
            mid = int(p["mrgid"])
        except (TypeError, ValueError):
            continue
        others = [
            x for x in peers_by.get((mid, grp), [])
            if x.get("name") != p.get("name")
        ]
        p["geocode_peers"] = others[:24]


def _registry_geocode(doc: dict, zone: dict, log) -> dict | None:
    """GPS déjà tranché (registre git) : pas Nominatim, pas Claude."""
    hit = accepted_by_key(str(doc.get("dedup_key") or ""))
    if not hit:
        return None
    lat, lon = float(hit["lat"]), float(hit["lon"])
    src = hit.get("geocode_source") or "manual_audit"
    out = {
        "lat": lat, "lon": lon, "has_coords": True,
        "geocode_source": src,
        "geocode_arbitration": "gps_registry",
        "geocoded_at": now_iso(),
        "geocode_query": geocode_query_name(doc.get("name") or ""),
    }
    geom = zone.get("_geom") if zone else None
    prepared = zone.get("_prep") if zone else None
    if geom is not None:
        inland = inland_exception_flags(doc, zone or {}, {}, official_list=True)
        cls = classify_poe_point(lat, lon, geom, prepared, inland=inland)
        out["spatial_kind"] = cls.get("kind")
        out["validated"] = bool(cls.get("validated"))
        out["distance_km"] = cls.get("dist_km")
    if hit.get("action") == "keep":
        out["geocode_kept_previous"] = True
        log(f"géocode registre keep: {hit.get('dedup_key')}")
    else:
        log(f"géocode registre: {hit.get('dedup_key')}")
    return out


async def geocode_one(doc: dict, zone: dict, log) -> dict:
    raw = doc.get("name") or ""
    name = geocode_query_name(raw)
    if name != raw:
        log(f"géocode alias: {raw} → {name}")
    registered = _registry_geocode(doc, zone, log)
    if registered is not None:
        return registered
    if not is_geocodeable_name(name) and not is_geocodeable_name(raw):
        log(f"géocode sauté (non toponyme): {raw}")
        return {"geocoded_at": now_iso(), "spatial_kind": "not_geocodeable",
                "geocode_query": name}
    if not doc.get("listing_group"):
        g = _listing_group_by_key().get(str(doc.get("dedup_key") or ""))
        if g:
            doc["listing_group"] = g
    port = {
        "name": name,
        "city": doc.get("city"),
        "listing_role": "poe" if "listing" in (doc.get("seed_sources") or []) else None,
        "listing_name": doc.get("listing_name") or raw,
        "listing_group": doc.get("listing_group"),
        "geocode_peers": list(doc.get("geocode_peers") or []),
        "dedup_key": doc.get("dedup_key"),
    }
    dual = await geocode_port_dual(port, zone, log)
    picked = pick_geocode(dual, port, zone, zone.get("_geom"), zone.get("_prep"))
    picked["geocoded_at"] = now_iso()
    picked["geocode_query"] = name
    if (not picked.get("has_coords") and doc.get("lat") is not None
            and doc.get("lon") is not None):
        # Ne jamais écraser un GPS existant par un miss / ambiguous.
        picked.pop("lat", None)
        picked.pop("lon", None)
        picked["has_coords"] = True
        picked["geocode_kept_previous"] = True
    return picked


def _judge_prompt(doc: dict, zone: dict, context: str) -> str:
    """Nom + zone + extraits. Pas de jetons listing/OSM/WPI (ça biaiserait)."""
    name = (doc.get("name") or "").strip()
    return (
        f"Candidat : {name}\n"
        f"Zone VLIZ : {search_polygon_name(zone) or zone.get('name') or zone.get('geoname')} "
        f"(mrgid={zone.get('mrgid')}, {zone.get('iso2') or ''})\n"
        f"Juge uniquement CE lieu à partir des extraits. "
        f"Ne liste aucun autre port.\n\n"
        f"EXTRAITS:\n{(context or '')[:8000]}"
    )


async def _judge_llm(doc: dict, zone: dict, context: str, settings: dict, log) -> dict:
    from app.core import claude, nvidia
    prompt = _judge_prompt(doc, zone, context)
    result = None

    async def _nvidia(model: str, engine: str) -> dict | None:
        try:
            parsed = await nvidia.complete_json_nvidia(
                JUDGE_SYSTEM, prompt, settings, model=model, max_tokens=400, log=log)
            out = parse_judge(parsed)
            out["judge_engine"] = engine
            return out
        except Exception as e:
            log(f"NVIDIA {engine}: {type(e).__name__}: {str(e)[:80]}")
            return None

    async def _claude(model: str, engine: str) -> dict | None:
        if not (claude.claude_enabled(settings) and claude.budget_allows_call(settings)):
            return None
        try:
            parsed = await claude.complete_json_claude(
                JUDGE_SYSTEM, prompt, settings, model=model, max_tokens=300, log=log)
            out = parse_judge(parsed)
            out["judge_engine"] = engine
            return out
        except Exception as e:
            log(f"Claude {engine}: {type(e).__name__}: {str(e)[:80]}")
            return None

    if nvidia.nvidia_enabled(settings):
        result = await _nvidia(nvidia.primary_model(), "nvidia-laguna")
        if should_escalate_sonnet(result, doc):
            muse = await _nvidia(nvidia.secondary_model(), "nvidia-muse")
            if muse:
                result = muse
        if result is not None:
            return result

    result = await _claude(claude.CLAUDE_HAIKU_MODEL, "claude-haiku")
    if should_escalate_sonnet(result, doc):
        sonnet = await _claude(claude.CLAUDE_SONNET_MODEL, "claude-sonnet")
        if sonnet:
            result = sonnet
    if result is None or result.get("judge_status") == "inconclusive":
        try:
            data = await ask_json(prompt, system=JUDGE_SYSTEM, settings=settings,
                                  max_tokens=300, log=log)
            out = parse_judge(data)
            out["judge_engine"] = "openrouter"
            if result is None or out.get("judge_status") != "inconclusive":
                result = out
        except Exception as e:
            log(f"OpenRouter juge: {type(e).__name__}: {str(e)[:80]}")
            if result is None:
                result = parse_judge({"is_poe": None, "reason": "llm_error"})
    return result


def drop_excluded_hits(hits: list[dict]) -> list[dict]:
    return [h for h in (hits or []) if not url_is_excluded_search(h.get("url") or "")]


async def _search_hits(doc: dict, zone: dict, whitelist: list[str], key: str, log) -> list[dict]:
    iso = (zone.get("iso2") or "").lower() or None
    query = (doc.get("search_query") or "").strip() or seed_search_query({
        **doc,
        "zone_name": doc.get("zone_name") or zone.get("name") or zone.get("geoname"),
    })

    def enough(hs):
        kept = drop_excluded_hits(hs)
        return sum(1 for h in kept if url_allowed(h.get("url") or "", whitelist)) >= FETCH_URL_CAP

    domains = whitelist[:WHITELIST_DOMAIN_CAP] or None
    hits = await tf_search_pages(
        query, key, location=iso, language="en",
        include_domains=domains, exclude_domains=SEARCH_EXCLUDE_DOMAINS,
        max_pages=SEARCH_PAGE_CAP, stop_when=enough, log=log)
    official_n = sum(
        1 for h in drop_excluded_hits(hits)
        if url_allowed(h.get("url") or "", whitelist))
    if official_n == 0:
        extra = await tf_search_pages(
            query, key, location=iso, language="en",
            exclude_domains=SEARCH_EXCLUDE_DOMAINS,
            max_pages=SEARCH_PAGE_CAP, stop_when=enough, log=log)
        seen = {h.get("url") for h in hits}
        for h in extra:
            if h.get("url") not in seen:
                hits.append(h)
    return drop_excluded_hits(hits)


def harvest_bu_catalog(fetched: dict, urls: list[str]) -> dict:
    """Parseur catalogue sur les pages d'État déjà fetchées. 0 crawl."""
    blocks = []
    for u in urls or []:
        rec = (fetched or {}).get(u) or {}
        if rec.get("blocked") or rec.get("error"):
            continue
        text = rec.get("text") or ""
        if not str(text).strip():
            continue
        blocks.append(f"[SOURCE: {u}]\n{text[:CATALOG_FETCH_CHARS].rstrip()}\n")
    raw = "\n\n".join(blocks)
    ports = extract_structured_ports(raw)
    sufficient = catalog_is_sufficient(ports, raw)
    productive = urls_with_catalog(blocks) if blocks else []
    if sufficient and not productive:
        productive = [
            u for u in (urls or [])
            if ((fetched or {}).get(u) or {}).get("text")
        ]
    return {
        "ports": ports,
        "urls": productive,
        "sufficient": sufficient,
        "raw": raw,
    }


def seed_on_catalog(doc: dict, ports: list[dict] | None) -> dict | None:
    """True si le nom de la graine est déjà sur la liste officielle (dedup)."""
    if not ports:
        return None
    return _match_seed(
        {"name": doc.get("name"), "mrgid": doc.get("mrgid")},
        list(ports),
    )


def merge_catalog_cache(cache: dict, harvest: dict) -> dict:
    """Fusionne une moisson dans le cache ZEE (même lot, 0 re-fetch)."""
    if not harvest or not harvest.get("sufficient"):
        return cache
    cache["sufficient"] = True
    seen = {(p.get("name") or "").casefold() for p in (cache.get("ports") or [])}
    ports = list(cache.get("ports") or [])
    for p in harvest.get("ports") or []:
        key = (p.get("name") or "").casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        ports.append({
            "name": p.get("name"), "lat": p.get("lat"), "lon": p.get("lon"),
            "city": p.get("city"), "note": p.get("note"),
            "extraction_engine": p.get("extraction_engine") or "catalog",
        })
    cache["ports"] = ports
    cache["urls"] = list(dict.fromkeys(
        [*(cache.get("urls") or []), *(harvest.get("urls") or [])]))
    return cache


def catalog_cache_from_zone(zone: dict | None) -> dict:
    zone = zone or {}
    urls = []
    for u in zone.get("sources_bu") or []:
        if isinstance(u, str) and u.startswith("http"):
            urls.append(u)
        elif isinstance(u, dict) and str(u.get("url") or "").startswith("http"):
            urls.append(u["url"])
    ports = list(zone.get("catalog_bu") or [])
    if urls and ports:
        return {"ports": ports, "urls": urls, "sufficient": True}
    return {"ports": ports, "urls": urls, "sufficient": bool(ports and urls)}


def _attach_bu(out: dict, harvest: dict | None, *, named: bool = False,
               official=None) -> dict:
    if harvest:
        if harvest.get("urls"):
            out["sources_bu"] = harvest["urls"]
        if harvest.get("ports") is not None:
            out["catalog_bu_n"] = len(harvest["ports"])
    out["catalog_named"] = bool(named)
    if official:
        out["official_name"] = official
    return out


def catalog_named_verdict(doc: dict, hit: dict, harvest: dict) -> dict:
    """Nom déjà sur la liste : pas de juge oui/non (faisceau D)."""
    out = {
        "judge_status": "catalog",
        "judge_engine": "catalog-bu",
        "judge_kind": "unknown",
        "judge_confidence": 100,
        "judge_reason": (
            "Nom présent sur la liste officielle (faisceau D). "
            "Juge oui/non sauté — plaisance (P) plus tard."
        )[:240],
        "judge_at": now_iso(),
    }
    return _attach_bu(out, harvest, named=True, official=(hit or {}).get("name"))


async def persist_bu_catalog(db, zone: dict, cache: dict) -> None:
    """Écrit sources_bu + catalog_bu sur la fiche ZEE. Pas poe_ports."""
    if db is None or not zone or zone.get("mrgid") is None:
        return
    if not cache.get("sufficient") or not (cache.get("urls") or cache.get("ports")):
        return
    try:
        await db.eez_zones.update_one(
            {"mrgid": int(zone["mrgid"])},
            {"$addToSet": {"sources_bu": {"$each": list(cache.get("urls") or [])}},
             "$set": {
                 "catalog_bu": list(cache.get("ports") or []),
                 "catalog_bu_at": now_iso(),
             }},
        )
    except Exception:
        return


async def judge_one(doc: dict, zone: dict, settings: dict, log,
                    use_agent: bool = True, db=None, catalog_cache: dict | None = None,
                    persist_memory: bool = True) -> dict:
    name = doc.get("name") or ""
    cache = catalog_cache if catalog_cache is not None else catalog_cache_from_zone(zone)
    cached_hit = seed_on_catalog(doc, cache.get("ports")) if cache.get("sufficient") else None
    if cached_hit:
        log(f"catalogue BU: {name} déjà sur la liste — juge sauté")
        out = catalog_named_verdict(doc, cached_hit, cache)
        out["judge_sources"] = list(cache.get("urls") or [])
        out["judge_agent"] = False
        return out

    exc = load_exceptions()
    whitelist = build_whitelist(zone.get("iso2"), zone.get("sov_iso2"), exc)
    key = tf_api_key(settings) or (os.environ.get("TINYFISH_API_KEY") or "")
    hits = await _search_hits(doc, zone, whitelist, key, log) if key else []
    urls = select_fetch_urls(hits, whitelist, FETCH_URL_CAP)
    texts = []
    blocked_official = []
    fetched = {}
    if key and urls:
        fetched = await tf_fetch(urls, key, log=log)
        for u in urls:
            rec = fetched.get(u) or {}
            if rec.get("blocked") or rec.get("error") == "bot_blocked":
                blocked_official.append(u)
                continue
            if rec.get("error"):
                continue
            chunk = (rec.get("text") or "")[:4000]
            if chunk:
                texts.append(f"URL {u}\n{chunk}")
    agent_used = False
    if use_agent and key and blocked_official:
        agent_used = True
        zname = zone.get("name") or zone.get("geoname") or ""
        agent = await tf_poe_agent(
            blocked_official[0], name, zname, key,
            iso2=zone.get("iso2"), log=log)
        if agent and not agent.get("_agent_error"):
            texts.append(
                "AGENT TinyFish "
                f"{agent.get('_agent_profile') or ''}\n"
                f"{agent}"
            )
            if not any((fetched.get(u) or {}).get("text") for u in urls):
                judged = parse_judge(agent)
                if judged.get("judge_status") != "inconclusive":
                    judged["judge_engine"] = "tinyfish-agent"
                    judged["judge_sources"] = urls
                    judged["judge_agent_url"] = blocked_official[0]
                    judged["judge_at"] = now_iso()
                    return judged
    harvest = harvest_bu_catalog(fetched, urls)
    if harvest["sufficient"]:
        merge_catalog_cache(cache, harvest)
        zone["sources_bu"] = list(cache.get("urls") or [])
        zone["catalog_bu"] = list(cache.get("ports") or [])
        remembered = remember_seed_urls(
            zone, harvest["urls"], persist=persist_memory)
        if remembered:
            log(f"sources_bu mémorisées ({zone.get('iso2')}): {remembered}")
        log(f"catalogue BU: {len(harvest['ports'])} port(s) · "
            f"{len(harvest['urls'])} url(s)")
        await persist_bu_catalog(db, zone, cache)
        hit = seed_on_catalog(doc, harvest["ports"])
        if hit:
            log(f"catalogue BU: {name} sur la liste — juge sauté")
            out = catalog_named_verdict(doc, hit, harvest)
            out["judge_sources"] = urls
            out["judge_agent"] = agent_used
            if blocked_official:
                out["judge_agent_url"] = blocked_official[0]
            return out
        log(f"catalogue BU: {name} hors liste — juge du résidu")
    if not texts:
        snippets = [
            f"{h.get('title') or ''} — {h.get('snippet') or ''}"
            for h in hits if url_allowed(h.get("url") or "", whitelist)
        ] or [
            f"{h.get('title') or ''} — {h.get('snippet') or ''}" for h in hits[:FETCH_URL_CAP]
        ]
        texts = [s for s in snippets if s.strip(" —")]
    context = "\n\n".join(texts).strip()
    if not context:
        out = parse_judge({"is_poe": None, "reason": "aucune source"})
        out["judge_engine"] = None
        out["judge_sources"] = urls
        out["judge_agent"] = agent_used
        out["judge_at"] = now_iso()
        return _attach_bu(out, harvest if harvest.get("sufficient") else None)
    judged = await _judge_llm(doc, zone, context, settings, log)
    judged["judge_sources"] = urls
    judged["judge_agent"] = agent_used
    if blocked_official:
        judged["judge_agent_url"] = blocked_official[0]
    judged["judge_at"] = now_iso()
    if harvest.get("sufficient"):
        _attach_bu(judged, harvest, named=False)
    return judged


async def execute_enrich(db, state, *, run_id: str = "",
                         source: str = "run",
                         do_geocode: bool = True, do_verify: bool = True,
                         verdicts: list[str] | None = None,
                         limit: int = 0, concurrency: int = 2,
                         use_agent: bool = True,
                         persist_memory: bool = True) -> dict:
    """Géocode puis juge. Reprise. Pas de poe_ports.

    source=seeds lit/écrit poe_seed_ports. source=run utilise poe_run_ports.
    """
    from app.db import get_settings

    wanted = tuple(v for v in (verdicts or list(VERIFY_ORDER)) if v in VERIFY_ORDER)
    settings = {}
    try:
        settings = await get_settings()
    except Exception:
        pass
    from_seeds = source == "seeds"
    if from_seeds:
        coll = db.poe_seed_ports
        ports = await coll.find({}).to_list(20000)
        if not ports:
            raise ValueError("poe_seed_ports vide — lancer POST /api/poe/seeds/build")
        task_id = "seed-enrich"
    else:
        coll = db.poe_run_ports
        q = {"run_id": run_id}
        ports = await coll.find(q).to_list(20000)
        if not ports:
            raise ValueError(f"run {run_id} sans ports — lancer POST /api/poe/seeds/verify")
        task_id = run_id
    attach_geocode_context(ports)
    geo_todo = [p for p in ports if do_geocode and _needs_geocode(p)]
    judge_pool = [p for p in ports if do_verify and _needs_judge(p, wanted)]
    if limit and limit > 0:
        geo_todo = geo_todo[:limit]
        if geo_todo:
            # Lot name_only : on juge ce qu'on géocode, pas un 2e lot unverified.
            judge_pool = []
        else:
            judge_pool = judge_pool[:limit]
    else:
        # Run complet : géocoder d'abord, ne pas juger deux fois la même graine.
        judge_pool = [p for p in judge_pool if not _needs_geocode(p)]
    mrgids = {int(p["mrgid"]) for p in geo_todo + judge_pool if p.get("mrgid") is not None}
    zones = await _zone_cache(db, mrgids)
    state.total = len(geo_todo) + len(judge_pool)
    state.progress = 0
    log = state.log
    log(f"enrich {task_id}: géocode {len(geo_todo)} · juge {len(judge_pool)} "
        f"(concurrency={concurrency} agent={use_agent} source={'seeds' if from_seeds else 'run'})")
    counts = Counter()
    just_geocoded = []
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _geo_one(doc):
        async with sem:
            if state.cancel:
                return
            zone = zones.get(int(doc["mrgid"])) if doc.get("mrgid") is not None else None
            if not zone:
                log(f"pas de ZEE pour {doc.get('name')} mrgid={doc.get('mrgid')}")
                counts["geo_no_zone"] += 1
                return
            try:
                upd = await geocode_one(doc, zone, lambda m: log(f"[{doc.get('name')}] {m}"))
            except Exception as e:
                counts["geo_error"] += 1
                log(f"géocode FAIL {doc.get('name')}: {type(e).__name__}: {e}")
                return
            if upd.get("has_coords"):
                counts["geo_ok"] += 1
                doc.update(upd)
                if doc.get("verify_verdict") == "name_only":
                    doc["verify_verdict"] = "unverified"
                    upd["verify_verdict"] = "unverified"
                just_geocoded.append(doc)
            else:
                counts["geo_miss"] += 1
            await coll.update_one(
                {"_id": doc["_id"]}, {"$set": upd})
            state.progress += 1

    async def _judge_one(doc):
        async with sem:
            if state.cancel:
                return
            zone = zones.get(int(doc["mrgid"])) if doc.get("mrgid") is not None else None
            if not zone:
                counts["judge_no_zone"] += 1
                return
            try:
                cache = zone.setdefault("_bu_catalog", catalog_cache_from_zone(zone))
                judged = await judge_one(
                    doc, zone, settings, lambda m: log(f"[{doc.get('name')}] {m}"),
                    use_agent=use_agent, db=db, catalog_cache=cache,
                    persist_memory=persist_memory)
            except Exception as e:
                counts["judge_error"] += 1
                log(f"juge FAIL {doc.get('name')}: {type(e).__name__}: {e}")
                return
            doc.update(judged)
            if judged.get("has_coords") or doc.get("lat") is not None:
                doc["has_coords"] = True
            new_v = apply_judge_verdict(doc, judged)
            judged["verify_verdict"] = new_v
            counts[f"judge_{judged.get('judge_status')}"] += 1
            await coll.update_one(
                {"_id": doc["_id"]}, {"$set": judged})
            state.progress += 1

    if geo_todo:
        await asyncio.gather(*[_geo_one(p) for p in geo_todo])
        if do_verify:
            extra_mrgids = {
                int(p["mrgid"]) for p in just_geocoded if p.get("mrgid") is not None
            } - set(zones)
            if extra_mrgids:
                zones.update(await _zone_cache(db, extra_mrgids))
            for p in just_geocoded:
                if not p.get("judge_status"):
                    judge_pool.append(p)
            state.total = len(geo_todo) + len(judge_pool)

    if judge_pool and not state.cancel:
        await asyncio.gather(*[_judge_one(p) for p in judge_pool])

    summary = {
        "run_id": task_id,
        "source": "seeds" if from_seeds else "run",
        "geocode_todo": len(geo_todo),
        "judge_todo": len(judge_pool),
        "counts": dict(counts),
        "cancelled": bool(state.cancel),
        "wrote_poe_ports": False,
        "use_agent": use_agent,
        "finished_at": now_iso(),
    }
    await db.poe_runs.update_one(
        {"_id": task_id},
        {"$set": {"enrich": summary, "enriched_at": now_iso()}},
        upsert=from_seeds)
    state.summary = summary
    log(f"enrich terminé: {summary['counts']}")
    return summary
