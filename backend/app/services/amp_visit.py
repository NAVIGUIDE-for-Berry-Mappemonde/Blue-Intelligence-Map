"""Découverte des URL de visite AMP — cascade Capitaineries / PoE.

1. Refresh attributs ProtectedSeas (ArcGIS, sans géométrie) — extras gratuits.
2. Heuristique extras / labels Website.
3. TinyFish Fetch sur ``manager_url`` nettoyé.
4. TinyFish Search (``site:`` puis web ouvert).
5. Juge Muse (NVIDIA), filet OpenRouter : choisit parmi les hits, n'invente pas.

``visit_url`` n'est jamais la homepage gestionnaire.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Awaitable, Callable
from app.core.extract import serp_filter
from app.core.tinyfish import AMP_VISIT_PURPOSE, FETCH_URL_CAP, tf_api_key, tf_fetch, tf_search
from app.db import get_settings
from app.services import amp as amp_svc

JudgeFn = Callable[[dict, list[dict]], Awaitable[str | None]]
AttrsFetchFn = Callable[[list[str]], Awaitable[dict[str, dict]]]

VISIT_JUDGE_SYSTEM = (
    "Tu juges des URL de visite d'aire marine protégée. "
    "Réponds uniquement en JSON strict : "
    '{"url": "https://example.com/visite", "accept": true, "reason": ""} '
    "url doit être l'une des candidates, ou null. "
    "accept=true seulement si la page donne des procédures de visite, d'entrée, "
    "de permis, de mouillage ou de plaisance POUR LE SITE NOMMÉ. "
    "accept=false pour une homepage institutionnelle, un blog mouillage générique "
    "d'un pays, un article académique, un charter, une page tourisme sans règles, "
    "un autre parc ou un autre pays. N'invente aucune URL."
)
JUDGE_CANDIDATE_CAP = 8

VISIT_HINT_RE = amp_svc.VISIT_HINT_RE
BAD_URL_RE = re.compile(
    r"facebook\.|twitter\.|instagram\.|tiktok\.|linkedin\.|"
    r"tripadvisor\.|booking\.|airbnb\.|youtube\.|"
    r"researchgate\.|atraques\.|yachtmate\.|noonsite\.|"
    r"safetyanchoralarm\.|leportvauban\.|"
    r"/contact|/about|/news|/presse|/donate|/privacy|/legal|"
    r"/login|/cart|/shop",
    re.I,
)
FETCH_BATCH = FETCH_URL_CAP

FetchManyFn = Callable[[list[str]], Awaitable[dict[str, dict]]]
SearchFn = Callable[..., Awaitable[list[dict]]]


def manager_host(url: str | None) -> str | None:
    return amp_svc.url_host(url)


def score_visit_candidate(
    url: str | None,
    manager_url: str | None,
    *,
    title: str = "",
    snippet: str = "",
    curated: bool = False,
    name: str = "",
    require_name: bool = False,
) -> int:
    """Score > 0 = candidat plausible. 0 = rejeter (homepage, pub, hors sujet)."""
    if BAD_URL_RE.search(url or ""):
        return 0
    return amp_svc.rank_visit_candidate(
        url, manager_url, curated=curated, title=title, snippet=snippet,
        name=name, require_name=require_name)


def pick_visit_from_urls(
    manager_url: str | None,
    urls: list[str],
    *,
    titles: dict[str, str] | None = None,
    name: str = "",
    require_name: bool = False,
) -> str | None:
    titles = titles or {}
    best_url, best_score = None, 0
    for raw in urls:
        sc = score_visit_candidate(
            raw, manager_url, title=titles.get(raw, ""),
            name=name, require_name=require_name)
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
    """Requête ouverte : la page visite n'est pas toujours sur l'hôte gestionnaire."""
    name = (doc.get("name") or "").strip()
    country = (doc.get("country") or "").strip()
    q = f'"{name}" {country} visit permit anchoring mooring plaisance réglementation'.strip()
    return q, manager_host(doc.get("manager_url"))


def visit_judge_prompt(doc: dict, candidates: list[dict]) -> str:
    lines = []
    for i, cand in enumerate(candidates[:JUDGE_CANDIDATE_CAP], 1):
        title = (cand.get("title") or "").strip()
        lines.append(f"{i}. {cand.get('url')} | {title}")
    return (
        f"Site : {(doc.get('name') or '').strip()}\n"
        f"Pays : {(doc.get('country') or '').strip()}\n"
        f"URL gestionnaire (interdite comme visit_url) : {doc.get('manager_url')}\n"
        f"Candidats :\n" + "\n".join(lines)
    )


def parse_visit_judge(
    data: dict | None,
    candidates: list[dict],
    manager_url: str | None,
) -> str | None:
    """Retient une URL déjà proposée. Refuse manager et URL hors liste."""
    if not isinstance(data, dict) or data.get("accept") is not True:
        return None
    raw = str(data.get("url") or "").strip()
    if not raw:
        return None
    allowed: dict[str, str] = {}
    for cand in candidates:
        url = cand.get("url") if isinstance(cand, dict) else cand
        key = amp_svc.normalize_url(url)
        if key:
            allowed[key] = str(url).strip()
    chosen = allowed.get(amp_svc.normalize_url(raw) or "")
    if not chosen or amp_svc.urls_equivalent(chosen, manager_url):
        return None
    return chosen


async def llm_judge_visit(
    doc: dict,
    candidates: list[dict],
    *,
    settings: dict | None = None,
    log=None,
) -> str | None:
    """Muse d'abord (comme le juge PoE), OpenRouter si NVIDIA absent ou en échec."""
    if not candidates:
        return None
    from app.core import nvidia
    from app.core.llm import _call_openrouter, get_llm_key, parse_json_flexible

    prompt = visit_judge_prompt(doc, candidates)
    parsed = None
    engine = None
    if nvidia.nvidia_enabled(settings):
        try:
            parsed = await nvidia.complete_json_nvidia(
                VISIT_JUDGE_SYSTEM, prompt, settings, max_tokens=400, log=log)
            engine = nvidia.engine_label()
        except Exception as exc:
            if log:
                log(f"NVIDIA juge AMP: {type(exc).__name__}: {str(exc)[:80]}")
            parsed = None
    if parsed is None:
        key = get_llm_key(settings)
        if key:
            try:
                raw = await _call_openrouter(
                    prompt, VISIT_JUDGE_SYSTEM, key, json_mode=True, max_tokens=400)
                parsed = parse_json_flexible(raw)
                engine = "openrouter"
            except Exception as exc:
                if log:
                    log(f"OpenRouter juge AMP: {type(exc).__name__}: {str(exc)[:80]}")
                parsed = None
    chosen = parse_visit_judge(parsed, candidates, doc.get("manager_url"))
    if chosen:
        doc["visit_url_judge"] = engine
    return chosen


def search_candidates(
    doc: dict,
    hits: list[dict],
    *,
    require_name: bool = True,
) -> list[dict]:
    """Préfiltre SERP : score > 0, jamais la homepage gestionnaire."""
    out: list[dict] = []
    seen: set[str] = set()
    manager = doc.get("manager_url")
    name = doc.get("name") or ""
    for hit in hits:
        url = hit.get("url") if isinstance(hit, dict) else None
        if not url or amp_svc.urls_equivalent(url, manager):
            continue
        key = amp_svc.normalize_url(url)
        if not key or key in seen:
            continue
        title = (hit.get("title") or "") if isinstance(hit, dict) else ""
        if score_visit_candidate(
            url, manager, title=title, name=name, require_name=require_name,
        ) <= 0:
            continue
        seen.add(key)
        out.append({"url": url, "title": title})
        if len(out) >= JUDGE_CANDIDATE_CAP:
            break
    return out


def search_queries(doc: dict) -> list[tuple[str, str | None]]:
    """site:hôte d'abord (bonus), puis recherche ouverte si besoin."""
    name = (doc.get("name") or "").strip()
    country = (doc.get("country") or "").strip()
    host = manager_host(doc.get("manager_url"))
    open_q, _ = search_query(doc)
    out: list[tuple[str, str | None]] = []
    if host:
        scoped = (
            f"site:{host} (visite OR visit OR plaisance OR mouillage OR permit "
            f"OR réglementation OR anchoring) \"{name}\""
        ).strip()
        out.append((scoped, host))
    out.append((open_q, None))
    return out


def _needs_visit(doc: dict) -> bool:
    if (doc.get("visit_url_source") or "") == "manual" and doc.get("visit_url"):
        return False
    if doc.get("visit_url") and not amp_svc.urls_equivalent(
            doc.get("visit_url"), doc.get("manager_url")):
        return False
    return True


async def _write_visit(db, doc: dict) -> None:
    from app.services.isolated_runs import current_run_id, write_item
    rid = current_run_id()
    fields = {
        "visit_url": doc.get("visit_url"),
        "visit_url_status": doc.get("visit_url_status"),
        "visit_url_source": doc.get("visit_url_source"),
        "visit_url_judge": doc.get("visit_url_judge"),
        "enriched_at": doc.get("enriched_at"),
        "manager_url": doc.get("manager_url"),
        "ps_website_raw": doc.get("ps_website_raw"),
        "other_helpful_links": doc.get("other_helpful_links"),
    }
    if rid:
        payload = {**doc, **fields}
        await write_item(
            db, "amp", rid, payload,
            source_id=doc.get("site_id") or doc.get("_id"),
        )
        return
    await db.amp_sites.update_one({"_id": doc["_id"]}, {"$set": fields})


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


async def _pick_from_search(
    doc: dict,
    hits: list[dict],
    *,
    judge: JudgeFn | None,
) -> str | None:
    cands = search_candidates(doc, hits, require_name=True)
    if judge:
        return await judge(doc, cands)
    titles = {c["url"]: c.get("title") or "" for c in cands}
    return pick_visit_from_urls(
        doc.get("manager_url"),
        [c["url"] for c in cands],
        titles=titles,
        name=doc.get("name") or "",
        require_name=True,
    )


async def discover_visit_urls(
    db,
    *,
    state,
    limit: int = 200,
    skip_search: bool = False,
    fetch_many_fn: FetchManyFn | None = None,
    search_fn: SearchFn | None = None,
    tf_key: str | None = None,
    refresh_attrs: bool = True,
    attrs_fetch_fn: AttrsFetchFn | None = None,
    use_llm_judge: bool = True,
    judge_fn: JudgeFn | None = None,
    run_id: str | None = None,
) -> dict:
    """Refresh PS → extras → Fetch → Search → juge Muse / OpenRouter."""
    from app.services.isolated_runs import bind_run, reset_run

    token = bind_run(run_id) if run_id else None
    state.running = True
    state.started_at = time.time()
    state.finished_at = None
    state.error = None
    state.logs = []
    state.summary = None
    state.progress = 0
    state.cancel = False
    state.run_id = run_id

    docs = await pending_sites(db, limit)
    state.total = len(docs)
    counters = {
        "selected": len(docs),
        "attrs_refreshed": 0,
        "from_links": 0,
        "from_fetch": 0,
        "from_search": 0,
        "rejected_same_as_manager": 0,
        "unchanged": 0,
        "errors": 0,
        "no_tinyfish_key": False,
        "judge_engine": None,
    }
    state.log(f"AMP visite : {len(docs)} site(s) sans URL de visite")

    remaining: list[dict] = []
    try:
        if refresh_attrs and docs:
            refresh_docs = list(docs)
            seen_ids = {d.get("_id") for d in refresh_docs}
            try:
                dirty = await db.amp_sites.find(
                    {"manager_url": {"$regex": r"\|"}}).to_list(2000)
            except Exception:
                dirty = []
            for extra in dirty:
                if extra.get("_id") not in seen_ids:
                    refresh_docs.append(extra)
                    seen_ids.add(extra.get("_id"))
            counters["attrs_refreshed"] = await amp_svc.refresh_protectedseas_attrs(
                db, refresh_docs, fetch_fn=attrs_fetch_fn, log=state.log)

        settings = {}
        if use_llm_judge or tf_key is None:
            try:
                settings = await get_settings()
            except Exception:
                settings = {}
        judge = None if not use_llm_judge else (
            judge_fn or (lambda doc, cands: llm_judge_visit(
                doc, cands, settings=settings, log=state.log)))

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
                if after != before or doc.get("ps_website_raw"):
                    await _write_visit(db, doc)
            state.progress += 1

        key = (tf_key if tf_key is not None else tf_api_key(settings)).strip()
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
            by_manager: dict[str, list[dict]] = defaultdict(list)
            for doc in remaining:
                url = doc.get("manager_url") or ""
                if url:
                    by_manager[url].append(doc)
                else:
                    after_fetch.append(doc)
            unique_urls = list(by_manager)
            state.log(
                f"TinyFish Fetch : {len(unique_urls)} URL gestionnaire(s) "
                f"pour {len(remaining)} site(s)")
            for i in range(0, len(unique_urls), FETCH_BATCH):
                if getattr(state, "cancel", False):
                    state.log("Stop demandé")
                    break
                batch_urls = unique_urls[i:i + FETCH_BATCH]
                try:
                    recs = await fetch_many(batch_urls)
                except Exception as exc:
                    state.log(f"Lot Fetch : {type(exc).__name__}: {str(exc)[:80]}")
                    recs = {}
                for url in batch_urls:
                    rec = recs.get(url) or {}
                    links = urls_from_fetch_record(rec)
                    for doc in by_manager[url]:
                        picked = pick_visit_from_urls(
                            doc.get("manager_url"), links,
                            name=doc.get("name") or "")
                        verdict = await _commit_discovered(
                            db, doc, picked, "tinyfish_fetch")
                        if verdict == "found":
                            counters["from_fetch"] += 1
                            state.log(f"✓ {doc.get('name')} ← tinyfish_fetch")
                        else:
                            if verdict == "rejected":
                                counters["rejected_same_as_manager"] += 1
                            after_fetch.append(doc)

            if not skip_search:
                state.log(f"TinyFish Search + juge : {len(after_fetch)} site(s)")
                for doc in after_fetch:
                    if getattr(state, "cancel", False):
                        state.log("Stop demandé")
                        break
                    if not _needs_visit(doc):
                        continue
                    picked = None
                    try:
                        for query, host in search_queries(doc):
                            hits = await search(query, include_domains=host)
                            picked = await _pick_from_search(doc, hits, judge=judge)
                            if picked:
                                if doc.get("visit_url_judge"):
                                    counters["judge_engine"] = doc.get("visit_url_judge")
                                break
                    except Exception as exc:
                        counters["errors"] += 1
                        state.log(f"✗ Search {doc.get('name')}: {type(exc).__name__}")
                        counters["unchanged"] += 1
                        continue
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
        if token is not None:
            reset_run(token)
