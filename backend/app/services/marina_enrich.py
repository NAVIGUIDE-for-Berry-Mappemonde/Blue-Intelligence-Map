"""
Marina enrichment.

Chain (cost-ordered):
    1. NVIDIA NIM page chain (Pro → gpt-oss → Muse) on marina website text
    2. OpenRouter (same contract if NIM is off or empty)
    3. TinyFish   (agent mission on the official OSM website tag — last paid resort)
    4. Fallback   (whatever the OSM tags already say — never fabricated)

Claude n'est pas appelé ici (contrat claude.py : pas les marinas).

Credit guards:
    - OpenRouter: GET /v1/key before spending. Respect OPENROUTER_MIN_CREDITS
      (default 0.5 USD remaining if a spend limit is set on the key). If limit is null,
      the key is unmetered so we pass through.
    - TinyFish exposes no quota API — auth/quota HTTP errors fall through the chain.

NEVER fabricates values. Every field is null when unknown.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Callable, Optional
from urllib.parse import unquote

import httpx
from bs4 import BeautifulSoup
from readability import Document


# TinyFish's schema validator is strict: no union types, no "description" on properties,
# and no "nullable" flag either. Fields are all required-optional and we treat empty/zero
# values as nulls in _normalise_enrichment().
MARINA_ENRICH_SCHEMA = {
    "type": "object",
    "properties": {
        "canal_vhf": {"type": "string"},
        "places_visiteurs": {"type": "integer"},
        "tirant_eau_max_metres": {"type": "number"},
        "score_protection_meteo": {"type": "integer"},
        "services_disponibles": {"type": "array", "items": {"type": "string"}},
        "telephone_capitainerie": {"type": "string"},
        "resume_avis": {"type": "string"},
    },
}

ENRICH_FIELDS = (
    "canal_vhf",
    "places_visiteurs",
    "tirant_eau_max_metres",
    "score_protection_meteo",
    "services_disponibles",
    "telephone_capitainerie",
    "resume_avis",
)

DDG_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def marina_enrich_goal(marina: dict) -> str:
    return (
        f"Find and open the official website or authoritative reference page for the marina "
        f"'{marina['name']}' located at latitude {marina['lat']:.4f}, longitude {marina['lon']:.4f}. "
        f"If you land on a directory or aggregator, drill in to the marina's own page. "
        f"From that page extract these fields:\n"
        f"- canal_vhf: the VHF radio channel (e.g. '9' or '9/16')\n"
        f"- places_visiteurs: number of visitor berths (integer)\n"
        f"- tirant_eau_max_metres: maximum draft in meters (number)\n"
        f"- score_protection_meteo: weather protection on a 1-5 scale (integer, 1=exposed, 5=fully sheltered)\n"
        f"- services_disponibles: short French labels (e.g. 'eau','électricité','carburant',"
        f"'douches','wifi','capitainerie','grue','carénage','restaurant')\n"
        f"- telephone_capitainerie: harbour master phone (string, keep as printed)\n"
        f"- resume_avis: two-sentence review summary in French, max 200 characters.\n\n"
        f"Return null for any field not present on the page. Never invent values. "
        f"Do not just repeat OSM tag content — extract from the marina's own site."
    )


# ------------------------------------------------------------------
# Credit guard
# ------------------------------------------------------------------
async def openrouter_check_credit(
    client: httpx.AsyncClient,
    key: str,
    min_usd: float = 0.5,
    logger: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Return True if the OpenRouter key has enough remaining credit (or is unmetered).
    Silent False on any HTTP or parsing error.
    """
    try:
        r = await client.get(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
        )
        if r.status_code != 200:
            if logger:
                logger(f"[credit-guard] OpenRouter GET /v1/key → HTTP {r.status_code}, treating as no credit")
            return False
        data = (r.json().get("data") or {})
        limit = data.get("limit")
        usage = float(data.get("usage") or 0)
        if limit is None:
            if logger:
                logger(f"[credit-guard] OpenRouter limit=null (unmetered), usage=${usage:.6f} — PASS")
            return True
        remaining = float(limit) - usage
        ok = remaining >= min_usd
        if logger:
            logger(
                f"[credit-guard] OpenRouter limit=${limit}, used=${usage:.4f}, "
                f"remaining=${remaining:.4f}, min=${min_usd} → {'PASS' if ok else 'BLOCK'}"
            )
        return ok
    except Exception as e:
        if logger:
            logger(f"[credit-guard] OpenRouter error: {type(e).__name__}: {str(e)[:120]}")
        return False


# ------------------------------------------------------------------
# DuckDuckGo HTML search (no API key required)
# ------------------------------------------------------------------
async def duckduckgo_html_search(
    query: str,
    client: httpx.AsyncClient,
    max_results: int = 3,
) -> list[dict]:
    """Return a list of {url, title} — best-effort, silent on failure."""
    try:
        r = await client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "kl": "wt-wt"},
            headers={"User-Agent": DDG_UA},
            timeout=20,
            follow_redirects=True,
        )
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        hits = []
        for a in soup.select("a.result__a")[: max_results * 2]:
            href = a.get("href", "")
            title = a.get_text(" ", strip=True)
            if "/l/?" in href or "duckduckgo.com/l/" in href:
                m = re.search(r"uddg=([^&]+)", href)
                if m:
                    href = unquote(m.group(1))
            if href.startswith("http") and title:
                hits.append({"url": href, "title": title})
            if len(hits) >= max_results:
                break
        return hits
    except Exception:
        return []


async def fetch_readable(url: str, client: httpx.AsyncClient, timeout: int = 20) -> tuple[str, str]:
    r = await client.get(
        url,
        headers={"User-Agent": DDG_UA},
        timeout=timeout,
        follow_redirects=True,
    )
    r.raise_for_status()
    doc = Document(r.text)
    title = (doc.short_title() or "").strip()
    summary_html = doc.summary()
    soup = BeautifulSoup(summary_html, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    return title, text[:6000]


# ------------------------------------------------------------------
# TinyFish path
# ------------------------------------------------------------------
async def enrich_via_tinyfish(
    marina: dict,
    key: str,
    logger: Optional[Callable[[str], None]] = None,
    total_budget_s: float = 210.0,
) -> Optional[dict]:
    """
    Use TinyFish run-async + poll (rather than run-sync) so we can bound the wait budget precisely.
    """
    from app.core.tinyfish import tf_get_run, tf_run_async

    tags = marina.get("tags") or {}
    url_hint = tags.get("website") or tags.get("contact:website") or tags.get("url")
    if not url_hint:
        try:
            async with httpx.AsyncClient() as c:
                hits = await duckduckgo_html_search(f"{marina['name']} marina port", c, max_results=3)
                url_hint = hits[0]["url"] if hits else None
                if url_hint and logger:
                    logger(f"[tinyfish] DDG picked {url_hint}")
        except Exception as e:
            if logger:
                logger(f"[tinyfish] DDG lookup failed: {e}")
    if not url_hint:
        if logger:
            logger("[tinyfish] no URL hint — skipping")
        return None
    goal = marina_enrich_goal(marina)
    try:
        if logger:
            logger(f"[tinyfish] run-async on {url_hint} (server cap 120s)")
        started = await tf_run_async(url_hint, goal, MARINA_ENRICH_SCHEMA, key, max_duration_s=120)
    except Exception as e:
        # Body/message often carries what TinyFish rejected
        detail = ""
        if hasattr(e, "response") and e.response is not None:  # httpx.HTTPStatusError
            try:
                detail = e.response.text[:200]
            except Exception:
                pass
        if logger:
            logger(f"[tinyfish] run-async error: {type(e).__name__}: {str(e)[:120]} {detail}")
        return None
    run_id = started.get("run_id") or started.get("id")
    if not run_id:
        if logger:
            logger(f"[tinyfish] no run_id in response: {str(started)[:150]}")
        return None
    if logger:
        logger(f"[tinyfish] run_id={run_id}, polling every 4s")

    deadline = asyncio.get_event_loop().time() + total_budget_s
    last_status = None
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(4)
        try:
            info = await tf_get_run(run_id, key)
        except Exception as e:
            if logger:
                logger(f"[tinyfish] poll error: {type(e).__name__}: {str(e)[:80]}")
            continue
        status = info.get("status")
        if status != last_status and logger:
            logger(f"[tinyfish] status={status}")
            last_status = status
        if status in ("COMPLETED", "SUCCESS", "SUCCEEDED"):
            payload: Any = info.get("result") or info.get("output") or info
            for pk in ("result", "output", "extraction", "data"):
                if isinstance(payload, dict) and pk in payload and isinstance(payload[pk], dict):
                    payload = payload[pk]
            if isinstance(payload, dict) and any(payload.get(k) is not None for k in ENRICH_FIELDS):
                filled = [k for k in ENRICH_FIELDS if payload.get(k) not in (None, "", 0, 0.0, [])]
                if logger:
                    logger(f"[tinyfish] returned useful payload: filled={filled}")
                return _normalise_enrichment(payload)
            if logger:
                logger("[tinyfish] returned empty/unusable payload")
            return None
        if status in ("FAILED", "ERROR", "CANCELLED", "CANCELED"):
            if logger:
                err = str(info.get("error") or info.get("message"))[:150]
                logger(f"[tinyfish] {status}: {err}")
            return None
    if logger:
        logger(f"[tinyfish] TIMEOUT after {total_budget_s:.0f}s (last status={last_status})")
    return None


# ------------------------------------------------------------------
# OpenRouter path
# ------------------------------------------------------------------
async def enrich_via_openrouter(
    marina: dict,
    or_key: str,
    model: str | None = None,
    min_credit_usd: float = 0.5,
    logger: Optional[Callable[[str], None]] = None,
) -> Optional[dict]:
    from app.core.llm import openrouter_model
    model = model or openrouter_model()
    if not or_key:
        return None
    async with httpx.AsyncClient() as client:
        if not await openrouter_check_credit(client, or_key, min_usd=min_credit_usd, logger=logger):
            return None
        tags = marina.get("tags") or {}
        url = tags.get("website") or tags.get("contact:website") or tags.get("url")
        if not url:
            hits = await duckduckgo_html_search(f"marina {marina['name']} port", client)
            url = hits[0]["url"] if hits else None
            if url and logger:
                logger(f"[openrouter] DDG picked {url}")
        page_title = ""
        text = ""
        if url:
            try:
                page_title, text = await fetch_readable(url, client)
                if logger:
                    logger(f"[openrouter] readability got {len(text)} chars from {url}")
            except Exception as e:
                if logger:
                    logger(f"[openrouter] readability failed: {type(e).__name__}: {str(e)[:80]}")
        # If we still have no text, we can still ask the model to reason from OSM tags alone,
        # but honesty rule: only fill fields the model can support from the tag content.
        tags_str = json.dumps(
            {k: v for k, v in tags.items() if isinstance(v, str)},
            ensure_ascii=False,
        )
        prompt = (
            "You are extracting factual marina information. Return STRICT JSON matching this schema:\n"
            "{\"canal_vhf\": string|null, \"places_visiteurs\": integer|null, "
            "\"tirant_eau_max_metres\": number|null, \"score_protection_meteo\": integer|null (1-5), "
            "\"services_disponibles\": string[]|null, \"telephone_capitainerie\": string|null, "
            "\"resume_avis\": string|null}\n\n"
            f"Marina: {marina['name']}\n"
            f"Coordinates: {marina['lat']}, {marina['lon']}\n"
            f"OSM tags: {tags_str}\n\n"
            f"Website source ({url or 'n/a'}) title: {page_title}\n"
            "Website source content:\n"
            f"{text}\n\n"
            "RULES:\n"
            "- Set a field to null if not present in the source text or tags. NEVER fabricate.\n"
            "- services_disponibles must be short French labels: eau, électricité, carburant, "
            "douches, wifi, capitainerie, grue, carénage, restaurant, pumpout, déchets.\n"
            "- resume_avis in French, max 200 characters, only if the source text supports it.\n"
            "- score_protection_meteo: only if the source text discusses shelter/weather — else null.\n"
            "Return only the JSON object. No markdown. No commentary."
        )
        try:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {or_key}",
                    "HTTP-Referer": "https://blue-intelligence.local",
                    "X-Title": "BlueIntelligence Marina Enrichment",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": 600,
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
            )
            if r.status_code != 200:
                if logger:
                    logger(f"[openrouter] chat/completions HTTP {r.status_code}: {r.text[:120]}")
                return None
            body = r.json()
            content = body["choices"][0]["message"]["content"]
            data = json.loads(content)
            usage = body.get("usage") or {}
            if logger:
                logger(
                    f"[openrouter] OK model={model} "
                    f"in={usage.get('prompt_tokens')} out={usage.get('completion_tokens')} "
                    f"cost≈${(usage.get('total_cost') or usage.get('cost') or 0):.6f}"
                )
            return _normalise_enrichment(data)
        except Exception as e:
            if logger:
                logger(f"[openrouter] error: {type(e).__name__}: {str(e)[:150]}")
            return None


# ------------------------------------------------------------------
# OSM-tag fallback
# ------------------------------------------------------------------
def enrich_from_osm_tags(marina: dict) -> dict:
    """Zero-cost fallback: what OSM already knows. Never fabricates."""
    t = marina.get("tags") or {}

    def _to_int(v):
        try:
            m = re.search(r"-?\d+", str(v))
            return int(m.group()) if m else None
        except Exception:
            return None

    def _to_float(v):
        try:
            m = re.search(r"[-+]?\d*\.?\d+", str(v))
            return float(m.group()) if m else None
        except Exception:
            return None

    services = []
    for tag, label in [
        ("shower", "douches"),
        ("toilets", "toilettes"),
        ("drinking_water", "eau"),
        ("electricity", "électricité"),
        ("fuel", "carburant"),
        ("pumpout", "pumpout"),
        ("waste_disposal", "déchets"),
        ("wifi", "wifi"),
        ("internet_access", "wifi"),
        ("shop", "commerce"),
        ("restaurant", "restaurant"),
    ]:
        val = t.get(tag)
        if val and str(val).lower() not in ("no", "false", "0"):
            services.append(label)

    return {
        "canal_vhf": t.get("vhf_channel") or t.get("vhf"),
        "places_visiteurs": _to_int(
            t.get("capacity") or t.get("capacity:persons") or t.get("seamark:harbour:capacity")
        ),
        "tirant_eau_max_metres": _to_float(
            t.get("max_depth") or t.get("depth") or t.get("seamark:harbour:draught")
        ),
        "score_protection_meteo": None,
        "services_disponibles": services or None,
        "telephone_capitainerie": t.get("phone") or t.get("contact:phone"),
        "resume_avis": None,
    }


# ------------------------------------------------------------------
# Normaliser
# ------------------------------------------------------------------
def _normalise_enrichment(payload: dict) -> dict:
    """Coerce types + trim strings; keep nulls. Empty strings and zeros are treated as nulls
    (schemas that can't express null often use these placeholders — e.g. TinyFish)."""
    out: dict[str, Any] = {}
    for k in ENRICH_FIELDS:
        v = payload.get(k) if isinstance(payload, dict) else None
        if v in ("", "null", "None", 0, 0.0):
            v = None
        if k == "canal_vhf" and v is not None:
            v = str(v).strip()[:20] or None
        elif k == "places_visiteurs" and v is not None:
            try:
                v = int(float(v))
                if v <= 0:
                    v = None
            except Exception:
                v = None
        elif k == "tirant_eau_max_metres" and v is not None:
            try:
                v = float(v)
                if v <= 0:
                    v = None
            except Exception:
                v = None
        elif k == "score_protection_meteo" and v is not None:
            try:
                v = int(v)
                if v < 1 or v > 5:
                    v = None
            except Exception:
                v = None
        elif k == "services_disponibles":
            if isinstance(v, list):
                v = [str(x).strip()[:40] for x in v if x and str(x).strip()]
                v = v or None
            elif isinstance(v, str):
                v = [x.strip() for x in re.split(r"[,;/]", v) if x.strip()] or None
            else:
                v = None
        elif k in ("telephone_capitainerie", "resume_avis") and v is not None:
            v = str(v).strip()
            if k == "resume_avis":
                v = v[:220]
            v = v or None
        out[k] = v
    return out


async def enrich_via_nvidia(
    marina: dict,
    settings: dict | None,
    logger: Optional[Callable[[str], None]] = None,
) -> Optional[dict]:
    """Chaîne `page` : Pro → gpt-oss → Muse (même contrat JSON qu'OpenRouter)."""
    from app.core import nvidia
    if not nvidia.nvidia_enabled(settings):
        return None
    tags = marina.get("tags") or {}
    url = tags.get("website") or tags.get("contact:website") or tags.get("url")
    page_title = ""
    text = ""
    async with httpx.AsyncClient() as client:
        if not url:
            hits = await duckduckgo_html_search(f"marina {marina['name']} port", client)
            url = hits[0]["url"] if hits else None
            if url and logger:
                logger(f"[nvidia] DDG picked {url}")
        if url:
            try:
                page_title, text = await fetch_readable(url, client)
                if logger:
                    logger(f"[nvidia] readability got {len(text)} chars from {url}")
            except Exception as e:
                if logger:
                    logger(f"[nvidia] readability failed: {type(e).__name__}: {str(e)[:80]}")
    if not text:
        return None
    tags_str = json.dumps(
        {k: v for k, v in tags.items() if isinstance(v, str)},
        ensure_ascii=False,
    )
    prompt = (
        "You are extracting factual marina information. Return STRICT JSON matching this schema:\n"
        "{\"canal_vhf\": string|null, \"places_visiteurs\": integer|null, "
        "\"tirant_eau_max_metres\": number|null, \"score_protection_meteo\": integer|null (1-5), "
        "\"services_disponibles\": string[]|null, \"telephone_capitainerie\": string|null, "
        "\"resume_avis\": string|null}\n\n"
        f"Marina: {marina['name']}\n"
        f"Coordinates: {marina['lat']}, {marina['lon']}\n"
        f"OSM tags: {tags_str}\n\n"
        f"Website source ({url or 'n/a'}) title: {page_title}\n"
        "Website source content:\n"
        f"{text}\n\n"
        "RULES:\n"
        "- Set a field to null if not present in the source text or tags. NEVER fabricate.\n"
        "- services_disponibles must be short French labels: eau, électricité, carburant, "
        "douches, wifi, capitainerie, grue, carénage, restaurant, pumpout, déchets.\n"
        "- resume_avis in French, max 200 characters, only if the source text supports it.\n"
        "- score_protection_meteo: only if the source text discusses shelter/weather — else null.\n"
        "Return only the JSON object. No markdown. No commentary."
    )
    try:
        data = await nvidia.complete_json_nvidia(
            "Tu réponds uniquement en JSON strict.", prompt, settings,
            role="page", max_tokens=600, log=logger)
        cleaned = _normalise_enrichment(data if isinstance(data, dict) else {})
        if any(cleaned.get(k) is not None for k in ENRICH_FIELDS):
            if logger:
                logger(f"[nvidia] filled={[k for k, v in cleaned.items() if v is not None]}")
            return cleaned
        if logger:
            logger("[nvidia] empty payload")
        return None
    except Exception as e:
        if logger:
            logger(f"[nvidia] {type(e).__name__}: {str(e)[:120]}")
        return None


# ------------------------------------------------------------------
# Orchestrator
# ------------------------------------------------------------------
async def enrich_marina(
    marina: dict,
    tinyfish_key: Optional[str] = None,
    openrouter_key: Optional[str] = None,
    min_credit_usd: float = 0.5,
    logger: Optional[Callable[[str], None]] = None,
    skip_tinyfish: bool = False,
    settings: Optional[dict] = None,
) -> dict:
    """
    Cost-ordered chain:
        NVIDIA NIM → OpenRouter → TinyFish (site OSM) → OSM-tag fallback.
    """
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if logger:
        logger("=== attempt 1: NVIDIA NIM ===")
    nv_data = await enrich_via_nvidia(marina, settings, logger=logger)
    if nv_data and any(nv_data.get(k) is not None for k in ENRICH_FIELDS):
        return {**nv_data, "enriched": True, "enrichment_source": "nvidia",
                "enriched_at": now, "_tinyfish_attempted": False}
    if openrouter_key:
        if logger:
            logger("=== attempt 2: OpenRouter ===")
        or_data = await enrich_via_openrouter(
            marina, openrouter_key, min_credit_usd=min_credit_usd, logger=logger
        )
        if or_data and any(or_data.get(k) is not None for k in ENRICH_FIELDS):
            return {**or_data, "enriched": True, "enrichment_source": "openrouter",
                    "enriched_at": now, "_tinyfish_attempted": False}
    elif logger:
        logger("OpenRouter: no key configured — skipping")
    # 2. TinyFish — DERNIER recours : uniquement si un site officiel est connu (tag OSM),
    #    jamais sur un résultat DuckDuckGo (agrégateurs = runs longs et chers).
    tags = marina.get("tags") or {}
    has_official_site = bool(tags.get("website") or tags.get("contact:website") or tags.get("url"))
    tf_attempted = False
    if tinyfish_key and not skip_tinyfish and has_official_site:
        if logger:
            logger("=== attempt 3: TinyFish (last resort — official site only) ===")
        tf_attempted = True
        tf_data = await enrich_via_tinyfish(marina, tinyfish_key, logger=logger, total_budget_s=150.0)
        if tf_data and any(tf_data.get(k) is not None for k in ENRICH_FIELDS):
            return {**tf_data, "enriched": True, "enrichment_source": "tinyfish", "enriched_at": now, "_tinyfish_attempted": True}
    elif logger:
        if skip_tinyfish:
            logger("TinyFish: skipped (économie de crédits / échec précédent)")
        elif not has_official_site:
            logger("TinyFish: skipped (pas de site officiel dans les tags OSM)")
        else:
            logger("TinyFish: no key configured — skipping")
    # 3. Fallback
    if logger:
        logger("=== attempt 4: OSM-tag fallback ===")
    fb = enrich_from_osm_tags(marina)
    has_any = any(v not in (None, [], "") for v in fb.values())
    return {**fb, "enriched": has_any, "enrichment_source": "fallback", "enriched_at": now, "_tinyfish_attempted": tf_attempted}


def is_stale(marina: dict, max_age_days: int = 365) -> bool:
    ea = marina.get("enriched_at")
    if not ea:
        return False
    try:
        t = time.strptime(ea, "%Y-%m-%dT%H:%M:%SZ")
        return (time.time() - time.mktime(t)) > max_age_days * 86400
    except (ValueError, TypeError):
        return False
