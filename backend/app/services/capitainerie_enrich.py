"""Enrichissement capitainerie : tags, Search/Fetch, regex, Muse, OpenRouter.

Chaîne (coût croissant) :
  1. tags OSM/SHOM/NOAA
  2. TinyFish Search (nom distinct ou « capitainerie » + GPS)
  3. TinyFish Fetch (ou readability) + parsing regex — stop si tél et VHF
  4. NVIDIA Muse sur le texte de page
  5. OpenRouter sur le même texte
  6. Agent TinyFish (site officiel uniquement, dernier recours)

Jamais inventé. Un champ déjà rempli n'est pas écrasé.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import httpx

from app.services.capitainerie_world import (
    GENERIC_OFFICE_NAMES,
    contact_from_tags,
    contact_from_text,
    fill_contact,
)
from app.services.marina_enrich import (
    duckduckgo_html_search,
    fetch_readable,
    openrouter_check_credit,
)
from app.services.marina_world import official_website

ENRICH_FIELDS = ("telephone", "canal_vhf")
MAX_FETCH_URLS = 8

CONTACT_SCHEMA = {
    "type": "object",
    "properties": {
        "telephone": {"type": "string"},
        "canal_vhf": {"type": "string"},
    },
}

CAPITAINERIE_PURPOSE = (
    "Official harbour master / capitainerie office contact page "
    "(telephone and VHF channel). Prefer government and port-authority domains. "
    "Ignore restaurants, hotels, Instagram, Tripadvisor."
)

CONTACT_SYSTEM = (
    "You extract harbour-master contact from the given source text. "
    "Reply ONLY with a single JSON object. Never invent a phone number or VHF channel."
)

SEARCH_EXCLUDE_SNIPS = (
    "facebook.", "instagram.", "twitter.", "x.com/", "tiktok.",
    "tripadvisor.", "booking.com", "airbnb.", "pinterest.",
)


def contact_enrich_goal(doc: dict) -> str:
    name = doc.get("name") or "harbour master's office"
    return (
        f"Find the official harbour master / capitainerie page for '{name}' "
        f"at {doc.get('lat'):.4f},{doc.get('lon'):.4f}. "
        f"Extract only: telephone (harbour master phone as printed) and "
        f"canal_vhf (VHF channel, e.g. '9' or '9/16' or '9/68'). "
        f"Return null if a field is not on the official page. Never invent values."
    )


def _normalise_contact(payload: dict | None) -> dict:
    out = {"telephone": None, "canal_vhf": None}
    if not isinstance(payload, dict):
        return out
    from app.services.capitainerie_world import _clean_phone, _clean_vhf
    tel = payload.get("telephone") or payload.get("telephone_capitainerie") or payload.get("phone")
    vhf = payload.get("canal_vhf") or payload.get("vhf") or payload.get("vhf_channel")
    out["telephone"] = _clean_phone(tel)
    out["canal_vhf"] = _clean_vhf(vhf)
    return out


def merge_contact_payload(doc: dict, incoming: dict | None) -> dict:
    """Tags / site : ne remplit que les vides."""
    base = {
        "telephone": doc.get("telephone"),
        "canal_vhf": doc.get("canal_vhf"),
    }
    tags_phone, tags_vhf = contact_from_tags(doc.get("tags") or {})
    fill_contact(base, tags_phone, tags_vhf)
    cleaned = _normalise_contact(incoming)
    fill_contact(base, cleaned.get("telephone"), cleaned.get("canal_vhf"))
    return base


def needs_website_enrich(doc: dict) -> bool:
    phone, vhf = doc.get("telephone"), doc.get("canal_vhf")
    if not phone or not vhf:
        t_phone, t_vhf = contact_from_tags(doc.get("tags") or {})
        phone = phone or t_phone
        vhf = vhf or t_vhf
    return not (phone and vhf)


def _has_distinct_name(doc: dict) -> bool:
    name = str(doc.get("name") or "").strip().lower()
    return bool(name) and name not in GENERIC_OFFICE_NAMES


def _has_coords(doc: dict) -> bool:
    try:
        lat, lon = float(doc["lat"]), float(doc["lon"])
    except (TypeError, ValueError, KeyError):
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def allow_web_lookup(doc: dict) -> bool:
    """Site officiel, nom distinct, ou GPS (libellé générique « Capitainerie » + coords)."""
    if official_website(doc):
        return True
    if (doc.get("tags") or {}).get("website"):
        return True
    if _has_distinct_name(doc):
        return True
    return _has_coords(doc)


def rank_enrich_candidates(docs: list[dict]) -> list[dict]:
    """Site officiel d'abord, puis nom distinct, puis générique avec GPS."""
    def key(d: dict):
        site = 1 if official_website(d) else 0
        named = 1 if _has_distinct_name(d) else 0
        gps = 1 if _has_coords(d) else 0
        return (-site, -named, -gps, str(d.get("name") or "").lower())
    return sorted(docs, key=key)


def _coords_fragment(doc: dict) -> str:
    try:
        return f"{float(doc['lat']):.4f},{float(doc['lon']):.4f}"
    except (TypeError, ValueError, KeyError):
        return ""


def contact_search_query(doc: dict) -> str:
    """Requête Search : nom distinct, sinon « capitainerie » + GPS."""
    name = str(doc.get("name") or "").strip()
    coords = _coords_fragment(doc)
    if name and name.lower() not in GENERIC_OFFICE_NAMES:
        bits = [f'"{name}"', "harbour master", "capitainerie"]
        if coords:
            bits.append(coords)
        bits.extend(["VHF", "telephone"])
        return " ".join(bits)
    bits = ["capitainerie", "harbour master"]
    if coords:
        bits.append(coords)
    bits.extend(["VHF", "telephone"])
    return " ".join(bits)


def _url_ok(url: str) -> bool:
    u = (url or "").strip().lower()
    if not u.startswith("http"):
        return False
    return not any(snip in u for snip in SEARCH_EXCLUDE_SNIPS)


def _url_rank(url: str, official: str | None) -> tuple:
    u = (url or "").lower()
    official_hit = 0
    if official:
        off = official.rstrip("/").lower()
        official_hit = 1 if off in u.rstrip("/") or u.rstrip("/") in off else 0
    host = ""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""
    gov = 1 if any(
        token in host or token in u
        for token in (
            ".gouv.", ".gov", ".gc.ca", "port", "harbour", "harbor",
            "marina", "capitainerie", "harbourmaster",
        )
    ) else 0
    return (-official_hit, -gov)


def _pages_blob(pages: list[dict], limit: int = 8000) -> str:
    chunks = []
    for page in pages:
        url = page.get("url") or ""
        title = page.get("title") or ""
        text = page.get("text") or ""
        if not text:
            continue
        chunks.append(f"URL {url}\nTitle: {title}\n{text}")
    return "\n\n".join(chunks)[:limit]


def _contact_prompt(doc: dict, context: str) -> str:
    tags = doc.get("tags") or {}
    tags_str = json.dumps(
        {k: v for k, v in tags.items() if isinstance(v, str)},
        ensure_ascii=False,
    )
    return (
        "Extract harbour master / capitainerie contact. Return STRICT JSON:\n"
        "{\"telephone\": string|null, \"canal_vhf\": string|null}\n\n"
        f"Name: {doc.get('name')}\n"
        f"Coordinates: {doc.get('lat')}, {doc.get('lon')}\n"
        f"OSM/SHOM/NOAA tags: {tags_str}\n\n"
        f"SOURCE:\n{context}\n\n"
        "RULES: null if not in the source. NEVER fabricate. "
        "canal_vhf like '9' or '9/16' or '9/68'. telephone as printed. JSON only."
    )


def _apply_incoming(working: dict, incoming: dict | None, source: str) -> tuple[dict, str]:
    if not incoming or not any(incoming.values()):
        return working, source
    merged = merge_contact_payload(working, incoming)
    working = dict(working)
    working.update(merged)
    return working, source


async def discover_contact_urls(
    doc: dict,
    tinyfish_key: Optional[str] = None,
    logger: Optional[Callable[[str], None]] = None,
) -> list[str]:
    """URL officielle d'abord, puis TinyFish Search (DDG si pas de clé)."""
    urls: list[str] = []
    seen: set[str] = set()

    def _add(url: str | None):
        u = (url or "").strip()
        if not _url_ok(u) or u in seen:
            return
        seen.add(u)
        urls.append(u)

    _add(official_website(doc))
    _add((doc.get("tags") or {}).get("website"))
    query = contact_search_query(doc)
    hits: list[dict] = []
    if tinyfish_key:
        from app.core.tinyfish import tf_search
        try:
            hits = await tf_search(
                query, tinyfish_key, purpose=CAPITAINERIE_PURPOSE, log=logger,
            )
            if logger:
                logger(f"[search] TinyFish {len(hits)} hit(s) for {query[:80]}")
        except Exception as e:
            if logger:
                logger(f"[search] TinyFish {type(e).__name__}: {str(e)[:80]}")
            hits = []
    if not hits:
        try:
            async with httpx.AsyncClient() as client:
                hits = await duckduckgo_html_search(query, client, max_results=5)
            if logger and hits:
                logger(f"[search] DDG {len(hits)} hit(s)")
        except Exception as e:
            if logger:
                logger(f"[search] DDG {type(e).__name__}: {str(e)[:80]}")
            hits = []
    official = official_website(doc)
    ranked = sorted(
        [h for h in hits if _url_ok((h or {}).get("url") or "")],
        key=lambda h: _url_rank(h.get("url") or "", official),
    )
    for hit in ranked:
        _add(hit.get("url"))
        if len(urls) >= MAX_FETCH_URLS:
            break
    return urls[:MAX_FETCH_URLS]


async def fetch_contact_pages(
    urls: list[str],
    tinyfish_key: Optional[str] = None,
    logger: Optional[Callable[[str], None]] = None,
) -> list[dict]:
    """TinyFish Fetch prioritaire ; readability si pages vides / bloquées."""
    pages: list[dict] = []
    if tinyfish_key and urls:
        from app.core.tinyfish import tf_fetch
        recs = await tf_fetch(urls, tinyfish_key, purpose=CAPITAINERIE_PURPOSE, log=logger)
        for url in urls:
            rec = recs.get(url) or next(
                (v for k, v in recs.items() if k.rstrip("/") == url.rstrip("/")),
                {},
            )
            if rec.get("blocked"):
                if logger:
                    logger(f"[fetch] blocked {url[:80]}")
                continue
            text = (rec.get("text") or "").strip()
            if text:
                pages.append({
                    "url": rec.get("final_url") or url,
                    "title": rec.get("title") or "",
                    "text": text,
                })
        if logger:
            logger(f"[fetch] TinyFish {len(pages)} page(s) utilisable(s)")
    if pages:
        return pages
    async with httpx.AsyncClient() as client:
        for url in urls[:3]:
            try:
                title, text = await fetch_readable(url, client)
                if text:
                    pages.append({"url": url, "title": title, "text": text})
                    if logger:
                        logger(f"[fetch] readability {len(text)} chars from {url[:80]}")
            except Exception as e:
                if logger:
                    logger(f"[fetch] readability {type(e).__name__}: {str(e)[:80]}")
    return pages


def contact_from_pages(pages: list[dict]) -> dict:
    phone = vhf = None
    for page in pages:
        p, v = contact_from_text(page.get("text") or "")
        phone = phone or p
        vhf = vhf or v
        if phone and vhf:
            break
    return {"telephone": phone, "canal_vhf": vhf}


async def enrich_via_nvidia_muse(
    doc: dict,
    context: str,
    settings: dict | None,
    logger: Optional[Callable[[str], None]] = None,
) -> Optional[dict]:
    from app.core import nvidia
    if not context or not nvidia.nvidia_enabled(settings):
        return None
    try:
        if logger:
            logger("[muse] NVIDIA Muse on page text")
        data = await nvidia.complete_json_nvidia(
            CONTACT_SYSTEM, _contact_prompt(doc, context), settings,
            model=nvidia.secondary_model(), role="page",
            max_tokens=200, log=logger,
        )
        cleaned = _normalise_contact(data if isinstance(data, dict) else {})
        if any(cleaned.values()):
            if logger:
                logger(f"[muse] filled={[k for k, v in cleaned.items() if v]}")
            return cleaned
        if logger:
            logger("[muse] empty payload")
        return None
    except Exception as e:
        if logger:
            logger(f"[muse] {type(e).__name__}: {str(e)[:120]}")
        return None


async def enrich_via_openrouter(
    doc: dict,
    or_key: str,
    min_credit_usd: float = 0.5,
    logger: Optional[Callable[[str], None]] = None,
    context: str = "",
) -> Optional[dict]:
    from app.core.llm import openrouter_model, parse_json_flexible
    if not or_key or not context:
        return None
    async with httpx.AsyncClient() as client:
        if not await openrouter_check_credit(client, or_key, min_usd=min_credit_usd, logger=logger):
            return None
        prompt = _contact_prompt(doc, context)
        try:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {or_key}",
                    "HTTP-Referer": "https://blue-intelligence.local",
                    "X-Title": "BlueIntelligence Capitainerie Enrichment",
                },
                json={
                    "model": openrouter_model(),
                    "messages": [
                        {"role": "system", "content": CONTACT_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0,
                    "max_tokens": 200,
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
            )
            if r.status_code != 200:
                if logger:
                    logger(f"[openrouter] HTTP {r.status_code}: {r.text[:120]}")
                return None
            content = (((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "")
            payload = parse_json_flexible(content)
            cleaned = _normalise_contact(payload if isinstance(payload, dict) else {})
            if any(cleaned.values()):
                if logger:
                    logger(f"[openrouter] filled={[k for k, v in cleaned.items() if v]}")
                return cleaned
            if logger:
                logger("[openrouter] empty payload")
            return None
        except Exception as e:
            if logger:
                logger(f"[openrouter] {type(e).__name__}: {str(e)[:120]}")
            return None


async def enrich_via_tinyfish(
    doc: dict,
    key: str,
    logger: Optional[Callable[[str], None]] = None,
    total_budget_s: float = 180.0,
) -> Optional[dict]:
    import asyncio
    from app.core.tinyfish import tf_get_run, tf_run_async

    url_hint = official_website(doc)
    if not url_hint:
        if logger:
            logger("[tinyfish] no official website — skipping agent")
        return None
    goal = contact_enrich_goal(doc)
    try:
        if logger:
            logger(f"[tinyfish] run-async on {url_hint}")
        started = await tf_run_async(url_hint, goal, CONTACT_SCHEMA, key, max_duration_s=120)
    except Exception as e:
        if logger:
            logger(f"[tinyfish] run-async error: {type(e).__name__}: {str(e)[:120]}")
        return None
    run_id = started.get("run_id") or started.get("id")
    if not run_id:
        return None
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
            cleaned = _normalise_contact(payload if isinstance(payload, dict) else {})
            if any(cleaned.values()):
                return cleaned
            if logger:
                logger("[tinyfish] empty payload")
            return None
        if status in ("FAILED", "ERROR", "CANCELLED", "CANCELED"):
            if logger:
                logger(f"[tinyfish] {status}")
            return None
    if logger:
        logger(f"[tinyfish] TIMEOUT after {total_budget_s:.0f}s")
    return None


def _result(working: dict, source: str, now: str, tf_attempted: bool) -> dict:
    merged = {
        "telephone": working.get("telephone"),
        "canal_vhf": working.get("canal_vhf"),
    }
    filled = any(merged.get(k) for k in ENRICH_FIELDS)
    return {
        **merged,
        "enriched": bool(filled),
        "enrichment_source": source if filled else None,
        "enriched_at": now if filled else None,
        "_tinyfish_attempted": tf_attempted,
    }


async def enrich_capitainerie(
    doc: dict,
    tinyfish_key: Optional[str] = None,
    openrouter_key: Optional[str] = None,
    min_credit_usd: float = 0.5,
    logger: Optional[Callable[[str], None]] = None,
    skip_tinyfish: bool = False,
    settings: Optional[dict] = None,
) -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    from_tags = merge_contact_payload(doc, None)
    working = dict(doc)
    working.update(from_tags)
    source = "tags"
    tf_attempted = False

    if not needs_website_enrich(working):
        if logger:
            logger("contact already complete from tags — skip website")
        return _result(working, "tags", now, False)

    if not allow_web_lookup(working):
        if logger:
            logger("no official site, no name, no GPS — skip web lookup")
        filled = any(from_tags.get(k) for k in ENRICH_FIELDS)
        return {
            **from_tags,
            "enriched": bool(filled),
            "enrichment_source": "tags" if filled else None,
            "enriched_at": now if filled else None,
            "_tinyfish_attempted": False,
        }

    if logger:
        logger("=== attempt 1: TinyFish Search + Fetch / regex ===")
    urls = await discover_contact_urls(working, tinyfish_key=tinyfish_key, logger=logger)
    pages = await fetch_contact_pages(urls, tinyfish_key=tinyfish_key, logger=logger) if urls else []
    regex = contact_from_pages(pages)
    working, src = _apply_incoming(working, regex, "fetch")
    if any(regex.values()):
        source = src
        if logger:
            logger(f"[regex] filled={[k for k, v in regex.items() if v]}")
    if not needs_website_enrich(working):
        return _result(working, source, now, False)

    context = _pages_blob(pages)
    if context:
        if logger:
            logger("=== attempt 2: NVIDIA Muse ===")
        muse = await enrich_via_nvidia_muse(working, context, settings, logger=logger)
        working, src = _apply_incoming(working, muse, "nvidia-muse")
        if muse and any(muse.values()):
            source = src
        if not needs_website_enrich(working):
            return _result(working, source, now, False)

        if openrouter_key:
            if logger:
                logger("=== attempt 3: OpenRouter ===")
            incoming = await enrich_via_openrouter(
                working, openrouter_key, min_credit_usd=min_credit_usd,
                logger=logger, context=context,
            )
            working, src = _apply_incoming(working, incoming, "openrouter")
            if incoming and any(incoming.values()):
                source = src
            if not needs_website_enrich(working):
                return _result(working, source, now, False)
    elif logger:
        logger("no page text — skip Muse / OpenRouter")

    has_site = bool(official_website(working))
    if tinyfish_key and not skip_tinyfish and has_site:
        if logger:
            logger("=== attempt 4: TinyFish agent (official site) ===")
        tf_attempted = True
        incoming = await enrich_via_tinyfish(working, tinyfish_key, logger=logger)
        working, src = _apply_incoming(working, incoming, "tinyfish")
        if incoming and any(incoming.values()):
            source = src

    return _result(working, source, now, tf_attempted)
