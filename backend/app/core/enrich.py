"""Ordre d'enrichissement marina / capitainerie : une chaîne, deux schémas.

Porte d'entrée : ``run_page_enrich``. Même question partout (« extraire des
champs d'une fiche déjà nommée, sans inventer »). Les schémas restent
propres à chaque mode : une marina a des places visiteurs et un tirant
d'eau, une capitainerie n'a besoin que du téléphone et du VHF.

  1. Tags déjà là (OSM / SHOM / NOAA).
  2. Chercher le web seulement s'il manque une URL.
  3. Lire la page (``read_url``).
  4. Extraire par règle simple ce qui est trivial (numéro, canal).
  5. NVIDIA puis OpenRouter seulement s'il reste un trou, sur le texte déjà lu.
  6. Agent TinyFish seulement si l'URL est officielle — jamais un hit moteur.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Sequence

from app.core.extract import serp_drop_reason

LogFn = Callable[[str], None]
DiscoverFn = Callable[..., Awaitable[list[str]]]
FetchFn = Callable[..., Awaitable[list[dict]]]
NvidiaFn = Callable[..., Awaitable[Optional[dict]]]
OpenRouterFn = Callable[..., Awaitable[Optional[dict]]]
AgentFn = Callable[..., Awaitable[Optional[dict]]]


def url_ok(url: str) -> bool:
    """Même couperet SERP que le top-down / AMP / recherche nommée."""
    return serp_drop_reason(url) is None


def field_present(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (list, tuple, set, dict, str)) and not value:
        return False
    return True


def has_holes(working: dict, hole_fields: Sequence[str]) -> bool:
    return any(not field_present(working.get(k)) for k in hole_fields)


def fill_empty(base: dict, incoming: dict | None, fields: Sequence[str]) -> dict:
    """Remplit seulement les champs vides. Jamais d'écrasement."""
    out = dict(base)
    if not incoming:
        return out
    for k in fields:
        if field_present(out.get(k)):
            continue
        if field_present(incoming.get(k)):
            out[k] = incoming[k]
    return out


def pages_blob(pages: list[dict], limit: int = 8000) -> str:
    chunks = []
    for page in pages or []:
        url = page.get("url") or ""
        title = page.get("title") or ""
        text = page.get("text") or ""
        if not text:
            continue
        chunks.append(f"URL {url}\nTitle: {title}\n{text}")
    return "\n\n".join(chunks)[:limit]


def apply_incoming(
    working: dict,
    incoming: dict | None,
    fields: Sequence[str],
    merge: Callable[[dict, dict | None], dict],
) -> tuple[dict, bool]:
    """Fusionne un payload ; True si au moins un champ vide a été rempli."""
    if not incoming or not isinstance(incoming, dict):
        return working, False
    payload = {k: v for k, v in incoming.items() if k != "_engine"}
    if not any(field_present(v) for v in payload.values()):
        return working, False
    merged = merge(working, payload)
    after = dict(working)
    filled = False
    for k in fields:
        if k not in merged:
            continue
        new = merged[k]
        if field_present(new) and not field_present(working.get(k)):
            filled = True
        after[k] = new
    return after, filled


async def collect_page_urls(
    official: str | None,
    *,
    extra: Sequence[str | None] | None = None,
    search: Callable[[], Awaitable[Sequence[str]]] | None = None,
    max_urls: int = 8,
    url_ok_fn: Callable[[str], bool] | None = None,
) -> list[str]:
    """URL officielle d'abord. ``search`` seulement s'il n'en reste aucune."""
    ok = url_ok_fn or url_ok
    urls: list[str] = []
    seen: set[str] = set()

    def _add(raw: str | None) -> None:
        u = (raw or "").strip()
        if not u or u in seen or not ok(u):
            return
        seen.add(u)
        urls.append(u)

    _add(official)
    for u in extra or ():
        _add(u)
    if urls:
        return urls[:max_urls]
    if search:
        for u in await search():
            _add(u)
            if len(urls) >= max_urls:
                break
    return urls[:max_urls]


async def fetch_pages(
    urls: list[str],
    *,
    purpose: str = "",
    tinyfish_key: Optional[str] = None,
    min_chars: int = 80,
    logger: Optional[LogFn] = None,
    prefer_fetch: Optional[bool] = None,
) -> list[dict]:
    """Fetch d'abord si clé ; cascade (PDF / JS / HTML) dès que le texte manque."""
    from app.core.extract import read_urls
    if not urls:
        return []
    use_fetch = bool(tinyfish_key) if prefer_fetch is None else prefer_fetch
    pages_by = await read_urls(
        urls,
        min_chars=min_chars,
        prefer_fetch=use_fetch,
        fetch_purpose=purpose,
        fetch_key=tinyfish_key or "",
        log=logger,
    )
    pages: list[dict] = []
    for url in urls:
        rec = pages_by.get(url) or {}
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
                logger(f"[fetch] {rec.get('level')} {len(text)} chars from {url[:80]}")
    return pages


def enrich_result(
    working: dict,
    fields: Sequence[str],
    source: str,
    now: str,
    tf_attempted: bool,
) -> dict:
    payload = {k: working.get(k) for k in fields}
    filled = any(field_present(payload.get(k)) for k in fields)
    return {
        **payload,
        "enriched": bool(filled),
        "enrichment_source": source if filled else None,
        "enriched_at": now if filled else None,
        "_tinyfish_attempted": tf_attempted,
    }


@dataclass
class PageEnrichSpec:
    """Crochets propres à un mode. L'ordre des étapes est fixe."""
    fields: tuple[str, ...]
    hole_fields: tuple[str, ...]
    from_tags: Callable[[dict], dict]
    official_url: Callable[[dict], str | None]
    allow_web: Callable[[dict], bool]
    discover_urls: DiscoverFn
    fetch_pages: FetchFn
    from_pages: Callable[[list[dict]], dict]
    nvidia: NvidiaFn
    openrouter: OpenRouterFn
    agent: AgentFn
    merge: Callable[[dict, dict | None], dict] | None = None
    url_ok: Callable[[str], bool] | None = None


async def run_page_enrich(
    doc: dict,
    spec: PageEnrichSpec,
    *,
    tinyfish_key: Optional[str] = None,
    openrouter_key: Optional[str] = None,
    min_credit_usd: float = 0.5,
    logger: Optional[LogFn] = None,
    skip_tinyfish: bool = False,
    settings: Optional[dict] = None,
) -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    log = logger or (lambda m: None)
    merge = spec.merge or (
        lambda working, incoming: fill_empty(working, incoming, spec.fields)
    )
    ok_url = spec.url_ok or url_ok

    tagged = spec.from_tags(doc) or {}
    working = dict(doc)
    working.update({k: tagged[k] for k in spec.fields if k in tagged})
    source = "tags"
    tf_attempted = False

    if not has_holes(working, spec.hole_fields):
        log("already complete from tags — skip website")
        return enrich_result(working, spec.fields, source, now, False)

    if not spec.allow_web(working):
        log("no official site, no name, no GPS — skip web lookup")
        return enrich_result(working, spec.fields, source, now, False)

    log("=== attempt 1: page / regex ===")
    urls = await spec.discover_urls(
        working, tinyfish_key=tinyfish_key, logger=logger)
    pages = (
        await spec.fetch_pages(urls, tinyfish_key=tinyfish_key, logger=logger)
        if urls else []
    )
    regex = spec.from_pages(pages) or {}
    working, filled = apply_incoming(working, regex, spec.fields, merge)
    if filled:
        source = "fetch"
        log(f"[regex] filled={[k for k in spec.fields if field_present(regex.get(k))]}")
    if not has_holes(working, spec.hole_fields):
        return enrich_result(working, spec.fields, source, now, False)

    context = pages_blob(pages)
    if context:
        log("=== attempt 2: NVIDIA NIM (page) ===")
        nv = await spec.nvidia(working, context, settings, logger)
        engine = "nvidia"
        if isinstance(nv, dict):
            engine = nv.get("_engine") or "nvidia"
        working, filled = apply_incoming(working, nv, spec.fields, merge)
        if filled:
            source = engine
        if not has_holes(working, spec.hole_fields):
            return enrich_result(working, spec.fields, source, now, False)

        if openrouter_key:
            log("=== attempt 3: OpenRouter ===")
            incoming = await spec.openrouter(
                working, openrouter_key, min_credit_usd=min_credit_usd,
                logger=logger, context=context,
            )
            working, filled = apply_incoming(working, incoming, spec.fields, merge)
            if filled:
                source = "openrouter"
            if not has_holes(working, spec.hole_fields):
                return enrich_result(working, spec.fields, source, now, False)
    else:
        log("no page text — skip NIM / OpenRouter")

    official = spec.official_url(working)
    if tinyfish_key and not skip_tinyfish and official and ok_url(official):
        log("=== attempt 4: TinyFish agent (official site) ===")
        tf_attempted = True
        incoming = await spec.agent(working, tinyfish_key, logger)
        working, filled = apply_incoming(working, incoming, spec.fields, merge)
        if filled:
            source = "tinyfish"

    return enrich_result(working, spec.fields, source, now, tf_attempted)
