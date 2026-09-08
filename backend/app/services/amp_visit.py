"""Découverte des URL de visite AMP — même cascade que les autres modes.

1. Liens extra ProtectedSeas (gratuit, déjà en cache).
2. TinyFish Fetch sur ``manager_url`` (liens internes /visite, /plaisance…).
3. TinyFish Search si Fetch ne trouve rien.

``visit_url`` n'est jamais la homepage gestionnaire. On n'invente pas d'URL :
on ne retient qu'un lien déjà présent sur la page ou dans la SERP.
"""
from __future__ import annotations

import re
import time
from typing import Awaitable, Callable
from urllib.parse import urlparse

from app.core.extract import serp_filter
from app.core.tinyfish import AMP_VISIT_PURPOSE, FETCH_URL_CAP, tf_api_key, tf_fetch, tf_search
from app.db import get_settings
from app.services import amp as amp_svc

VISIT_HINT_RE = re.compile(
    r"visite|visit|plaisance|mouillage|anchor|mooring|permit|permis|"
    r"autorisation|reglement|réglement|reglementation|entry|entree|entrée|"
    r"entrer|formalit|pleasure.?craft|yacht|recreational|clearance|"
    r"access|acceso|acceso|fondeo|amarr|navegac",
    re.I,
)
BAD_URL_RE = re.compile(
    r"facebook\.|twitter\.|instagram\.|tiktok\.|linkedin\.|"
    r"tripadvisor\.|booking\.|airbnb\.|youtube\.|"
    r"/contact|/about|/news|/presse|/donate|/privacy|/legal|"
    r"/login|/cart|/shop",
    re.I,
)
FETCH_BATCH = FETCH_URL_CAP

FetchManyFn = Callable[[list[str]], Awaitable[dict[str, dict]]]
SearchFn = Callable[..., Awaitable[list[dict]]]


def manager_host(url: str | None) -> str | None:
    host = (urlparse(url or "").hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def score_visit_candidate(
    url: str | None,
    manager_url: str | None,
    *,
    title: str = "",
    snippet: str = "",
) -> int:
    """Score > 0 = candidat plausible. 0 = rejeter (homepage, pub, hors sujet)."""
    if not amp_svc.normalize_url(url):
        return 0
    if amp_svc.urls_equivalent(url, manager_url):
        return 0
    if BAD_URL_RE.search(url or ""):
        return 0
    blob = f"{url} {title} {snippet}"
    score = 0
    if VISIT_HINT_RE.search(urlparse(url or "").path or ""):
        score += 4
    if VISIT_HINT_RE.search(blob):
        score += 2
    if score == 0:
        return 0
    mh = manager_host(manager_url)
    uh = manager_host(url)
    if mh and uh and mh == uh:
        score += 2
    return score


def pick_visit_from_urls(
    manager_url: str | None,
    urls: list[str],
    *,
    titles: dict[str, str] | None = None,
) -> str | None:
    titles = titles or {}
    best_url, best_score = None, 0
    for raw in urls:
        sc = score_visit_candidate(raw, manager_url, title=titles.get(raw, ""))
        if sc > best_score:
            best_url, best_score = raw, sc
    if not best_url:
        return None
    chosen, status = amp_svc.pick_visit_url(manager_url, discovered=best_url)
    return chosen if status == "found" else None


def urls_from_fetch_record(rec: dict | None) -> list[str]:
    if not rec:
        return []
    out: list[str] = []
    for link in rec.get("links") or []:
        if isinstance(link, str):
            out.append(link)
        elif isinstance(link, dict):
            href = link.get("url") or link.get("href") or ""
            if href:
                out.append(href)
    out.extend(amp_svc.extract_urls(rec.get("text") or ""))
    return out


def search_query(doc: dict) -> tuple[str, str | None]:
    name = (doc.get("name") or "").strip()
    country = (doc.get("country") or "").strip()
    q = f'"{name}" {country} visit permit anchoring mooring plaisance réglementation'.strip()
    return q, manager_host(doc.get("manager_url"))


def _needs_visit(doc: dict) -> bool:
    if (doc.get("visit_url_source") or "") == "manual" and doc.get("visit_url"):
        return False
    if doc.get("visit_url") and not amp_svc.urls_equivalent(
            doc.get("visit_url"), doc.get("manager_url")):
        return False
    return True


async def _write_visit(db, doc: dict) -> None:
    await db.amp_sites.update_one(
        {"_id": doc["_id"]},
        {"$set": {
            "visit_url": doc.get("visit_url"),
            "visit_url_status": doc.get("visit_url_status"),
            "visit_url_source": doc.get("visit_url_source"),
            "enriched_at": doc.get("enriched_at"),
        }},
    )


async def _commit_discovered(db, doc: dict, url: str | None, source: str) -> str:
    if not url:
        return "unchanged"
    amp_svc.apply_visit_choice(doc, discovered=url, source=source)
    after = doc.get("visit_url")
    if after and not amp_svc.urls_equivalent(after, doc.get("manager_url")):
        await _write_visit(db, doc)
        return "found"
    if doc.get("visit_url_status") == "rejected_same_as_manager":
        await _write_visit(db, doc)
        return "rejected"
    return "unchanged"


async def pending_sites(db, limit: int) -> list[dict]:
    q = {
        "$or": [
            {"visit_url": {"$in": [None, ""]}},
            {"visit_url_status": {"$in": ["none", "not_found", None]}},
        ],
    }
    docs = await db.amp_sites.find(q).to_list(int(limit))
    return [d for d in docs if _needs_visit(d)][:int(limit)]


async def default_fetch_many(urls: list[str], *, key: str, log=None) -> dict[str, dict]:
    return await tf_fetch(urls, key, links=True, purpose=AMP_VISIT_PURPOSE, log=log)


async def default_search(query: str, *, key: str, include_domains=None, log=None) -> list[dict]:
    hits = await tf_search(
        query, key, include_domains=include_domains,
        purpose=AMP_VISIT_PURPOSE, log=log)
    return serp_filter(hits)


async def discover_visit_urls(
    db,
    *,
    state,
    limit: int = 200,
    skip_search: bool = False,
    fetch_many_fn: FetchManyFn | None = None,
    search_fn: SearchFn | None = None,
    tf_key: str | None = None,
) -> dict:
    """Job de fond : heuristique liens extra, puis Fetch, puis Search."""
    state.running = True
    state.started_at = time.time()
    state.finished_at = None
    state.error = None
    state.logs = []
    state.summary = None
    state.progress = 0
    state.cancel = False

    docs = await pending_sites(db, limit)
    state.total = len(docs)
    counters = {
        "selected": len(docs),
        "from_links": 0,
        "from_fetch": 0,
        "from_search": 0,
        "rejected_same_as_manager": 0,
        "unchanged": 0,
        "errors": 0,
        "no_tinyfish_key": False,
    }
    state.log(f"AMP visite : {len(docs)} site(s) sans URL de visite")

    remaining: list[dict] = []
    try:
        for doc in docs:
            if getattr(state, "cancel", False):
                state.log("Stop demandé")
                break
            before = doc.get("visit_url")
            amp_svc.apply_visit_choice(doc, source="other_helpful_links")
            after = doc.get("visit_url")
            if after and not amp_svc.urls_equivalent(after, doc.get("manager_url")):
                await _write_visit(db, doc)
                counters["from_links"] += 1
                state.log(f"✓ {doc.get('name')} ← other_helpful_links")
            else:
                if doc.get("visit_url_status") == "rejected_same_as_manager":
                    counters["rejected_same_as_manager"] += 1
                remaining.append(doc)
                if after != before:
                    await _write_visit(db, doc)
            state.progress += 1

        key = (tf_key if tf_key is not None else tf_api_key(await get_settings())).strip()
        if not key:
            counters["no_tinyfish_key"] = True
            counters["unchanged"] += len(remaining)
            state.log("Pas de clé TinyFish — Fetch / Search sautés (comme Marinas sans clé)")
        else:
            fetch_many = fetch_many_fn or (
                lambda urls: default_fetch_many(urls, key=key, log=state.log))
            search = search_fn or (
                lambda q, include_domains=None: default_search(
                    q, key=key, include_domains=include_domains, log=state.log))

            after_fetch: list[dict] = []
            for i in range(0, len(remaining), FETCH_BATCH):
                if getattr(state, "cancel", False):
                    state.log("Stop demandé")
                    break
                chunk = remaining[i:i + FETCH_BATCH]
                urls = [d.get("manager_url") for d in chunk if d.get("manager_url")]
                try:
                    recs = await fetch_many(urls) if urls else {}
                except Exception as exc:
                    state.log(f"Lot Fetch : {type(exc).__name__}: {str(exc)[:80]}")
                    recs = {}
                for doc in chunk:
                    rec = recs.get(doc.get("manager_url") or "") or {}
                    picked = pick_visit_from_urls(
                        doc.get("manager_url"), urls_from_fetch_record(rec))
                    verdict = await _commit_discovered(
                        db, doc, picked, "tinyfish_fetch")
                    if verdict == "found":
                        counters["from_fetch"] += 1
                        state.log(f"✓ {doc.get('name')} ← tinyfish_fetch")
                    elif verdict == "rejected":
                        counters["rejected_same_as_manager"] += 1
                        after_fetch.append(doc)
                    else:
                        after_fetch.append(doc)

            if not skip_search:
                for doc in after_fetch:
                    if getattr(state, "cancel", False):
                        state.log("Stop demandé")
                        break
                    if not _needs_visit(doc):
                        continue
                    query, host = search_query(doc)
                    try:
                        hits = await search(query, include_domains=host)
                    except Exception as exc:
                        counters["errors"] += 1
                        state.log(f"✗ Search {doc.get('name')}: {type(exc).__name__}")
                        counters["unchanged"] += 1
                        continue
                    titles = {h.get("url"): h.get("title") or "" for h in hits if h.get("url")}
                    picked = pick_visit_from_urls(
                        doc.get("manager_url"),
                        [h.get("url") for h in hits if h.get("url")],
                        titles=titles,
                    )
                    verdict = await _commit_discovered(
                        db, doc, picked, "tinyfish_search")
                    if verdict == "found":
                        counters["from_search"] += 1
                        state.log(f"✓ {doc.get('name')} ← tinyfish_search")
                    elif verdict == "rejected":
                        counters["rejected_same_as_manager"] += 1
                    else:
                        counters["unchanged"] += 1
            else:
                counters["unchanged"] += len(after_fetch)

        summary = {
            **counters,
            "found": counters["from_links"] + counters["from_fetch"] + counters["from_search"],
            "skip_search": skip_search,
        }
        state.summary = summary
        state.log(f"AMP visite terminé: {summary}")
        return summary
    except Exception as exc:
        state.error = f"{type(exc).__name__}: {exc}"
        state.log(f"FATAL: {state.error}")
        raise
    finally:
        state.finished_at = time.time()
        state.running = False
