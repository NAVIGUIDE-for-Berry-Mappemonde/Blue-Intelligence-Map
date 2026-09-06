"""
poe_seed_enrich — Géocode les name_only, juge les autres graines.

Search paginé (quota PAYG), Fetch de tous les hits whitelistés (cap 10),
juge Haiku → Sonnet (listing / inconclusive) → OpenRouter.
Agent TinyFish seulement si Fetch renvoie bot_blocked (1 / graine, lite puis
stealth, 2 concurrents, cap crédits).

N'écrit jamais dans poe_ports : seulement poe_run_ports.
Reprise : saute les ports déjà géocodés / déjà jugés.
"""
from __future__ import annotations

import asyncio
import os
from collections import Counter

from shapely.geometry import shape
from shapely.prepared import prep

from app.core.extract import geocode_query_name, is_geocodeable_name
from app.core.geo import (
    classify_poe_point, geocode_port_dual, inland_exception_flags,
)
from app.core.llm import ask_json
from app.core.tinyfish import (
    FETCH_URL_CAP, SEARCH_PAGE_CAP, tf_api_key, tf_fetch, tf_poe_agent,
    tf_search_pages,
)
from app.services.poe_pipeline import (
    build_whitelist, load_exceptions, now_iso, url_allowed,
)
from app.services.poe_seeds import verdict_for_seed

JUDGE_SYSTEM = (
    "Tu es un juge Ports d'Entrée. Réponds uniquement en JSON strict : "
    '{"is_poe": true, "confidence": 0, "reason": "", "official_name": null} '
    "is_poe=true seulement si une source officielle désigne CE lieu comme "
    "port d'entrée / clearance / puerto habilitado / designated port. "
    "false si les sources parlent d'autre chose (marina, ville, autre pays). "
    "null si les extraits ne permettent pas de décider."
)

DEFAULT_VERIFY_RUN = "20260906-071347-6a9509"
VERIFY_ORDER = ("name_only", "unverified", "probable")
DEFAULT_ENRICH_LIMIT = 200
WHITELIST_DOMAIN_CAP = 15


def parse_judge(data: dict | None) -> dict:
    data = data if isinstance(data, dict) else {}
    flag = data.get("is_poe")
    if flag is True:
        status = "accepted"
    elif flag is False:
        status = "rejected"
    else:
        status = "inconclusive"
    try:
        conf = int(data.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0
    return {
        "judge_status": status,
        "judge_confidence": max(0, min(100, conf)),
        "judge_reason": str(data.get("reason") or "")[:240],
        "official_name": data.get("official_name"),
    }


def apply_judge_verdict(seed: dict, judge: dict) -> str:
    """Met à jour verify_verdict après un jugement. Ne touche pas confirmed."""
    current = seed.get("verify_verdict") or verdict_for_seed(seed)
    if current == "confirmed":
        return "confirmed"
    status = judge.get("judge_status")
    srcs = set(seed.get("seed_sources") or [])
    has_listing = "listing" in srcs
    has_coords = bool(seed.get("has_coords") or (
        seed.get("lat") is not None and seed.get("lon") is not None))
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
        if whitelist and not url_allowed(u, whitelist):
            continue
        if not whitelist:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= cap:
            break
    return out


def pick_geocode(dual: dict, port: dict, zone: dict, geom, prepared) -> dict:
    """Choisit Nominatim/GeoNames puis applique le filtre spatial VLIZ."""
    cands = []
    for source in ("nominatim", "geonames"):
        xy = (dual or {}).get(source)
        if not xy:
            continue
        meta = (dual or {}).get(f"{source}_meta") or {}
        inland = inland_exception_flags(port, zone, meta, official_list=True)
        lat, lon = float(xy[0]), float(xy[1])
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
                "geocode_agree": (dual or {}).get("agree")}
    if (dual or {}).get("agree"):
        chosen = next((c for c in cands if c["source"] == "nominatim"), cands[0])
        arb = "agree"
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
            return {"lat": None, "lon": None, "geocode_source": None,
                    "validated": False, "spatial_kind": chosen.get("kind"),
                    "distance_km": chosen.get("dist_km"),
                    "geocode_agree": (dual or {}).get("agree"),
                    "geocode_arbitration": "spatial_rejected"}
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


def _needs_geocode(doc: dict) -> bool:
    if doc.get("geocoded_at"):
        return False
    if doc.get("lat") is not None and doc.get("lon") is not None:
        return False
    return (doc.get("verify_verdict") or "") == "name_only"


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
         "sovereign": 1, "geometry": 1},
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
        out[int(mid)] = {**z, "_geom": geom, "_prep": prepared}
    return out


async def geocode_one(doc: dict, zone: dict, log) -> dict:
    raw = doc.get("name") or ""
    name = geocode_query_name(raw)
    if name != raw:
        log(f"géocode alias: {raw} → {name}")
    if not is_geocodeable_name(name) and not is_geocodeable_name(raw):
        log(f"géocode sauté (non toponyme): {raw}")
        return {"geocoded_at": now_iso(), "spatial_kind": "not_geocodeable",
                "geocode_query": name}
    port = {"name": name, "city": doc.get("city"),
            "listing_role": "poe" if "listing" in (doc.get("seed_sources") or []) else None}
    dual = await geocode_port_dual(port, zone, log)
    picked = pick_geocode(dual, port, zone, zone.get("_geom"), zone.get("_prep"))
    picked["geocoded_at"] = now_iso()
    picked["geocode_query"] = name
    return picked


def _judge_prompt(doc: dict, zone: dict, context: str) -> str:
    return (
        f"Candidat : {doc.get('name')}\n"
        f"Zone VLIZ : {zone.get('name') or zone.get('geoname')} "
        f"({zone.get('iso2') or ''})\n"
        f"Sources graines : {', '.join(doc.get('seed_sources') or [])}\n\n"
        f"EXTRAITS:\n{(context or '')[:8000]}"
    )


async def _judge_llm(doc: dict, zone: dict, context: str, settings: dict, log) -> dict:
    from app.core import claude
    prompt = _judge_prompt(doc, zone, context)
    result = None

    async def _claude(model: str, engine: str) -> dict | None:
        if not (claude.claude_enabled(settings) and claude.budget_allows_call(settings)):
            return None
        try:
            parsed = await claude.complete_json_claude(
                JUDGE_SYSTEM, prompt, settings, model=model, max_tokens=250, log=log)
            out = parse_judge(parsed)
            out["judge_engine"] = engine
            return out
        except Exception as e:
            log(f"Claude {engine}: {type(e).__name__}: {str(e)[:80]}")
            return None

    result = await _claude(claude.CLAUDE_HAIKU_MODEL, "claude-haiku")
    if should_escalate_sonnet(result, doc):
        sonnet = await _claude(claude.CLAUDE_SONNET_MODEL, "claude-sonnet")
        if sonnet:
            result = sonnet
    if result is None or result.get("judge_status") == "inconclusive":
        try:
            data = await ask_json(prompt, system=JUDGE_SYSTEM, settings=settings,
                                  max_tokens=250, log=log)
            out = parse_judge(data)
            out["judge_engine"] = "openrouter"
            if result is None or out.get("judge_status") != "inconclusive":
                result = out
        except Exception as e:
            log(f"OpenRouter juge: {type(e).__name__}: {str(e)[:80]}")
            if result is None:
                result = parse_judge({"is_poe": None, "reason": "llm_error"})
    return result


async def _search_hits(name: str, zone: dict, whitelist: list[str], key: str, log) -> list[dict]:
    iso = (zone.get("iso2") or "").lower() or None
    query = (
        f'{name} official port of entry OR clearance OR "puerto habilitado" '
        f'{zone.get("name") or ""}'
    )

    def enough(hs):
        return sum(1 for h in hs if url_allowed(h.get("url") or "", whitelist)) >= FETCH_URL_CAP

    domains = whitelist[:WHITELIST_DOMAIN_CAP] or None
    hits = await tf_search_pages(
        query, key, location=iso, language="en",
        include_domains=domains, max_pages=SEARCH_PAGE_CAP,
        stop_when=enough, log=log)
    official_n = sum(1 for h in hits if url_allowed(h.get("url") or "", whitelist))
    if official_n == 0:
        extra = await tf_search_pages(
            query, key, location=iso, language="en",
            max_pages=SEARCH_PAGE_CAP, stop_when=enough, log=log)
        seen = {h.get("url") for h in hits}
        for h in extra:
            if h.get("url") not in seen:
                hits.append(h)
    return hits


async def judge_one(doc: dict, zone: dict, settings: dict, log,
                    use_agent: bool = True) -> dict:
    name = doc.get("name") or ""
    exc = load_exceptions()
    whitelist = build_whitelist(zone.get("iso2"), zone.get("sov_iso2"), exc)
    key = tf_api_key(settings) or (os.environ.get("TINYFISH_API_KEY") or "")
    hits = await _search_hits(name, zone, whitelist, key, log) if key else []
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
        return out
    judged = await _judge_llm(doc, zone, context, settings, log)
    judged["judge_sources"] = urls
    judged["judge_agent"] = agent_used
    if blocked_official:
        judged["judge_agent_url"] = blocked_official[0]
    judged["judge_at"] = now_iso()
    return judged


async def execute_enrich(db, state, *, run_id: str,
                         do_geocode: bool = True, do_verify: bool = True,
                         verdicts: list[str] | None = None,
                         limit: int = 0, concurrency: int = 2,
                         use_agent: bool = True) -> dict:
    """Géocode puis juge. Reprise sur le même run_id. Pas de poe_ports."""
    from app.db import get_settings

    wanted = tuple(v for v in (verdicts or list(VERIFY_ORDER)) if v in VERIFY_ORDER)
    settings = {}
    try:
        settings = await get_settings()
    except Exception:
        pass
    q = {"run_id": run_id}
    ports = await db.poe_run_ports.find(q).to_list(20000)
    if not ports:
        raise ValueError(f"run {run_id} sans ports — lancer POST /api/poe/seeds/verify")
    geo_todo = [p for p in ports if do_geocode and _needs_geocode(p)]
    judge_pool = [p for p in ports if do_verify and _needs_judge(p, wanted)]
    if limit and limit > 0:
        geo_todo = geo_todo[:limit]
        if geo_todo:
            # Lot name_only : on juge ce qu'on géocode, pas un 2e lot unverified.
            judge_pool = []
        else:
            judge_pool = judge_pool[:limit]
    mrgids = {int(p["mrgid"]) for p in geo_todo + judge_pool if p.get("mrgid") is not None}
    zones = await _zone_cache(db, mrgids)
    state.total = len(geo_todo) + len(judge_pool)
    state.progress = 0
    log = state.log
    log(f"enrich {run_id}: géocode {len(geo_todo)} · juge {len(judge_pool)} "
        f"(concurrency={concurrency} agent={use_agent})")
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
            await db.poe_run_ports.update_one(
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
                judged = await judge_one(
                    doc, zone, settings, lambda m: log(f"[{doc.get('name')}] {m}"),
                    use_agent=use_agent)
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
            await db.poe_run_ports.update_one(
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
        "run_id": run_id,
        "geocode_todo": len(geo_todo),
        "judge_todo": len(judge_pool),
        "counts": dict(counts),
        "cancelled": bool(state.cancel),
        "wrote_poe_ports": False,
        "use_agent": use_agent,
        "finished_at": now_iso(),
    }
    await db.poe_runs.update_one(
        {"_id": run_id},
        {"$set": {"enrich": summary, "enriched_at": now_iso()}})
    state.summary = summary
    log(f"enrich terminé: {summary['counts']}")
    return summary
