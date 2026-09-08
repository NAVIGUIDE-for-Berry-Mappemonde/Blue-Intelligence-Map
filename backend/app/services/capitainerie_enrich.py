"""Enrichissement capitainerie : tags d'abord, puis site officiel.

Champs : telephone, canal_vhf. Jamais inventés. Un champ déjà rempli
par OSM/SHOM n'est pas écrasé.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

import httpx

from app.services.capitainerie_world import contact_from_tags, fill_contact
from app.services.marina_enrich import (
    duckduckgo_html_search,
    fetch_readable,
    openrouter_check_credit,
)
from app.services.marina_world import official_website

ENRICH_FIELDS = ("telephone", "canal_vhf")

CONTACT_SCHEMA = {
    "type": "object",
    "properties": {
        "telephone": {"type": "string"},
        "canal_vhf": {"type": "string"},
    },
}


def contact_enrich_goal(doc: dict) -> str:
    name = doc.get("name") or "harbour master's office"
    return (
        f"Find the official harbour master / capitainerie page for '{name}' "
        f"at {doc.get('lat'):.4f},{doc.get('lon'):.4f}. "
        f"Extract only: telephone (harbour master phone as printed) and "
        f"canal_vhf (VHF channel, e.g. '9' or '9/16'). "
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


GENERIC_OFFICE_NAMES = frozenset({
    "capitainerie",
    "harbour office",
    "harbour office (unnamed)",
    "harbour master's office",
    "harbour master",
    "harbourmaster",
})


def _has_distinct_name(doc: dict) -> bool:
    name = str(doc.get("name") or "").strip().lower()
    return bool(name) and name not in GENERIC_OFFICE_NAMES


def allow_web_lookup(doc: dict) -> bool:
    """Site officiel, ou un nom distinct. Pas de DDG sur « Capitainerie » générique."""
    if official_website(doc):
        return True
    if (doc.get("tags") or {}).get("website"):
        return True
    return _has_distinct_name(doc)


def rank_enrich_candidates(docs: list[dict]) -> list[dict]:
    """Site officiel d'abord, puis nom distinct — pas les libellés génériques SHOM."""
    def key(d: dict):
        site = 1 if official_website(d) else 0
        named = 1 if _has_distinct_name(d) else 0
        return (-site, -named, str(d.get("name") or "").lower())
    return sorted(docs, key=key)


async def enrich_via_openrouter(
    doc: dict,
    or_key: str,
    min_credit_usd: float = 0.5,
    logger: Optional[Callable[[str], None]] = None,
) -> Optional[dict]:
    from app.core.llm import openrouter_model
    if not or_key:
        return None
    async with httpx.AsyncClient() as client:
        if not await openrouter_check_credit(client, or_key, min_usd=min_credit_usd, logger=logger):
            return None
        url = official_website(doc) or (doc.get("tags") or {}).get("website")
        if not url:
            name = str(doc.get("name") or "").strip()
            if not name:
                if logger:
                    logger("[openrouter] no website and no name — skip DDG")
                return None
            q = f"{name} harbour master capitainerie VHF telephone"
            hits = await duckduckgo_html_search(q, client)
            url = hits[0]["url"] if hits else None
            if url and logger:
                logger(f"[openrouter] DDG picked {url}")
        page_title = ""
        text = ""
        if url:
            try:
                page_title, text = await fetch_readable(url, client)
                if logger:
                    logger(f"[openrouter] readability {len(text)} chars from {url}")
            except Exception as e:
                if logger:
                    logger(f"[openrouter] readability failed: {type(e).__name__}: {str(e)[:80]}")
        tags = doc.get("tags") or {}
        tags_str = json.dumps(
            {k: v for k, v in tags.items() if isinstance(v, str)},
            ensure_ascii=False,
        )
        prompt = (
            "Extract harbour master / capitainerie contact. Return STRICT JSON:\n"
            "{\"telephone\": string|null, \"canal_vhf\": string|null}\n\n"
            f"Name: {doc.get('name')}\n"
            f"Coordinates: {doc.get('lat')}, {doc.get('lon')}\n"
            f"OSM/SHOM tags: {tags_str}\n\n"
            f"Website ({url or 'n/a'}) title: {page_title}\n"
            f"{text}\n\n"
            "RULES: null if not in the source. NEVER fabricate. "
            "canal_vhf like '9' or '9/16'. telephone as printed. JSON only."
        )
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
                    "messages": [{"role": "user", "content": prompt}],
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
            from app.core.llm import parse_json_flexible
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
            logger("[tinyfish] no official website — skipping")
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


async def enrich_capitainerie(
    doc: dict,
    tinyfish_key: Optional[str] = None,
    openrouter_key: Optional[str] = None,
    min_credit_usd: float = 0.5,
    logger: Optional[Callable[[str], None]] = None,
    skip_tinyfish: bool = False,
) -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    from_tags = merge_contact_payload(doc, None)
    working = dict(doc)
    working.update(from_tags)

    if not needs_website_enrich(working):
        if logger:
            logger("contact already complete from tags — skip website")
        return {
            **from_tags,
            "enriched": True,
            "enrichment_source": "tags",
            "enriched_at": now,
            "_tinyfish_attempted": False,
        }

    if not allow_web_lookup(working):
        if logger:
            logger("no official site and no name — skip web lookup")
        filled = any(from_tags.get(k) for k in ENRICH_FIELDS)
        return {
            **from_tags,
            "enriched": bool(filled),
            "enrichment_source": "tags" if filled else None,
            "enriched_at": now if filled else None,
            "_tinyfish_attempted": False,
        }

    incoming = None
    source = "tags"
    tf_attempted = False

    if openrouter_key:
        if logger:
            logger("=== attempt 1: OpenRouter ===")
        incoming = await enrich_via_openrouter(
            working, openrouter_key, min_credit_usd=min_credit_usd, logger=logger,
        )
        if incoming and any(incoming.values()):
            source = "openrouter"

    has_site = bool(official_website(working))
    if not incoming and tinyfish_key and not skip_tinyfish and has_site:
        if logger:
            logger("=== attempt 2: TinyFish (official site) ===")
        tf_attempted = True
        incoming = await enrich_via_tinyfish(working, tinyfish_key, logger=logger)
        if incoming and any(incoming.values()):
            source = "tinyfish"

    merged = merge_contact_payload(working, incoming)
    filled = any(merged.get(k) for k in ENRICH_FIELDS)
    return {
        **merged,
        "enriched": bool(filled),
        "enrichment_source": source if filled else None,
        "enriched_at": now if filled else None,
        "_tinyfish_attempted": tf_attempted,
    }
