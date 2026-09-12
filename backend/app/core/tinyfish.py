import asyncio
import json
import os
import time
from urllib.parse import urlparse

import httpx

BASE = "https://agent.tinyfish.ai/v1"
SEARCH_URL = "https://api.search.tinyfish.ai"
FETCH_URL = "https://api.fetch.tinyfish.ai"

POE_PURPOSE = (
    "Official designated ports of entry / puertos habilitados / ports désignés "
    "for foreign pleasure craft or mixed (commercial AND pleasure), not cargo-only; "
    "also seaports, yacht marinas, porti detar or maritime checkpoints listed in an "
    "excise authorization, gazette, yacht-tourism page, sPCR or fishing-fuel kartelë. "
    "Prefer government domains. Ignore airports."
)

AMP_VISIT_PURPOSE = (
    "Skipper-facing visit / entry / anchoring / mooring / permit page for a "
    "named marine protected area. Prefer a path such as /visite, /plaisance, "
    "/permits or /reglementation — never the organization homepage alone."
)

PROJECTS_DISCOVERY_PURPOSE = (
    "Individual marine, ocean or coastal conservation project pages "
    "(project, campaign, initiative, programme). Ignore news, donations and events."
)

# Une retry 429 ; monkeypatchable dans les tests.
SEARCH_RETRY_SLEEP_S = 2.0
FETCH_LEVEL = "N3-mirror-tinyfish"

# Quotas publics PAYG (docs.tinyfish.ai) — Search 30 req/min, Fetch 150 URL/min.
# Starter = 60 / 300 ; on aligne le bucket sur le plan le plus bas.
SEARCH_RPM = 30
FETCH_RPM = 150
AGENT_CONCURRENCY = 2
AGENT_CREDIT_CAP = 40          # max_steps = crédits, pas la file
FETCH_URL_CAP = 10             # max URLs / requête Fetch
SEARCH_PAGE_CAP = 3            # ~10 hits/page → jusqu'à 30 URLs / graine
SEARCH_PAGE_MAX = 10           # plafond API TinyFish

POE_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_poe": {"type": ["boolean", "null"]},
        "confidence": {"type": "integer"},
        "reason": {"type": "string"},
        "official_name": {"type": ["string", "null"]},
        "kind": {
            "type": "string",
            "enum": ["pleasure", "mixed", "cargo", "other", "unknown"],
        },
    },
    "required": ["is_poe", "confidence", "reason"],
}

DISCOVERY_SCHEMA = {
    "type": "object",
    "properties": {
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"url": {"type": "string"}, "title": {"type": "string"}},
                "required": ["url", "title"],
            },
        }
    },
    "required": ["projects"],
}

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "location": {"type": "string"},
        "latitude": {"type": "number"},
        "longitude": {"type": "number"},
    },
    "required": ["title", "description"],
}


def discovery_goal(org_name: str, known_urls=None) -> str:
    base = (
        f"You are a maritime OSINT discovery agent for Blue Intelligence, exploring the website of '{org_name}'. "
        "Navigate menus, project/program/campaign listings, and pagination as needed. "
        "Collect pages that each describe ONE individual marine, ocean, coastal, reef, mangrove, seagrass, "
        "fisheries or marine-protected-area conservation project or program. "
        "Exclude news, events, jobs, donation pages, generic category pages, and external links. "
        "Return every qualifying page as projects with canonical URL and visible page title. "
        "Do not invent values. If none qualify, return an empty projects array."
    )
    if known_urls:
        sample = "\n".join(f"- {u}" for u in known_urls[:40])
        base += (
            f"\n\nINCREMENTAL MODE: we already know the following {len(known_urls)} project URLs from a previous scan. "
            f"Return ONLY project pages that are NOT in this list (new or recently added projects):\n{sample}"
        )
    return base


def extract_goal(url: str) -> str:
    return (
        "Open this marine conservation project page and extract: the official project title, "
        "a description of its ecological impact (max 250 characters), the most specific geographic "
        "location name, and GPS latitude/longitude if visible on the page or in an embedded map. "
        "Do not invent coordinates."
    )


def _headers(key: str) -> dict:
    return {"X-API-Key": key, "Content-Type": "application/json"}


async def tf_run_async(url: str, goal: str, schema: dict, key: str, max_duration_s: int | None = None) -> dict:
    payload = {"url": url, "goal": goal, "output_schema": schema, "browser_profile": "lite"}
    if max_duration_s:
        payload["agent_config"] = {"max_duration_seconds": int(max_duration_s)}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{BASE}/automation/run-async", headers=_headers(key), json=payload)
        r.raise_for_status()
        return r.json()


async def tf_get_run(run_id: str, key: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{BASE}/runs/{run_id}", headers=_headers(key))
        r.raise_for_status()
        return r.json()


async def tf_run_sync(url: str, goal: str, schema: dict, key: str, timeout: int = 360) -> dict:
    payload = {"url": url, "goal": goal, "output_schema": schema, "browser_profile": "lite",
               "agent_config": {"max_duration_seconds": 300}}
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(f"{BASE}/automation/run", headers=_headers(key), json=payload)
        r.raise_for_status()
        return r.json()


async def tf_run_sse(url: str, goal: str, schema: dict, key: str, on_event=None,
                     timeout: int = 420, browser_profile: str = "lite",
                     agent_config: dict | None = None) -> dict:
    """Stream a TinyFish run via SSE; returns final result dict, raises on failure."""
    payload = {
        "url": url, "goal": goal, "output_schema": schema,
        "browser_profile": browser_profile or "lite",
    }
    if agent_config:
        payload["agent_config"] = agent_config
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=30)) as client:
        async with client.stream("POST", f"{BASE}/automation/run-sse", headers=_headers(key), json=payload) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data:
                    continue
                try:
                    ev = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if on_event:
                    await on_event(ev)
                et = ev.get("type")
                if et == "COMPLETE":
                    if ev.get("status") != "COMPLETED":
                        raise ValueError(f"run {ev.get('status')}: {str(ev.get('error'))[:120]}")
                    return ev.get("result") or {}
                if et in ("ERROR", "FAILED"):
                    raise ValueError(str(ev.get("message") or ev)[:150])
    raise TimeoutError("SSE stream ended without COMPLETE event")



def find_live_url(body: dict):
    for k in ("streaming_url", "live_url", "live_view_url", "session_url", "replay_url"):
        v = body.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
    data = body.get("data") or {}
    if isinstance(data, dict):
        for k in ("streaming_url", "live_url"):
            v = data.get(k)
            if isinstance(v, str) and v.startswith("http"):
                return v
    return None


# ---------------------------------------------------------------------------
# Search / Fetch (gratuits) — client httpx, no-op sans clé
# ---------------------------------------------------------------------------
class _TokenBucket:
    """Quota in-process (Search PAYG 30 req/min, Fetch PAYG 150 URL/min)."""

    def __init__(self, rate_per_min: float):
        self.rate = rate_per_min / 60.0
        self.cap = float(rate_per_min)
        self.tokens = float(rate_per_min)
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, n: int = 1):
        n = max(1, int(n))
        async with self._lock:
            now = time.monotonic()
            self.tokens = min(self.cap, self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            if self.tokens < n:
                wait = (n - self.tokens) / self.rate
                await asyncio.sleep(wait)
                self.tokens = 0.0
                self.updated = time.monotonic()
            else:
                self.tokens -= n


_search_bucket = _TokenBucket(SEARCH_RPM)
_fetch_bucket = _TokenBucket(FETCH_RPM)
_agent_sem = asyncio.Semaphore(AGENT_CONCURRENCY)


def reset_rate_limits():
    """Réinitialise les buckets et le sémaphore Agent (tests)."""
    global _search_bucket, _fetch_bucket, _agent_sem
    _search_bucket = _TokenBucket(SEARCH_RPM)
    _fetch_bucket = _TokenBucket(FETCH_RPM)
    _agent_sem = asyncio.Semaphore(AGENT_CONCURRENCY)


def tf_api_key(settings=None) -> str:
    """Même résolution que Swarm._tf_key : settings persistés puis env."""
    if settings:
        k = (settings.get("tinyfish_api_key") or "").strip()
        if k:
            return k
    return (os.environ.get("TINYFISH_API_KEY") or "").strip()


def _tf_domain(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _join_domains(domains) -> str:
    if not domains:
        return ""
    if isinstance(domains, (list, tuple, set)):
        return ",".join(str(d).strip() for d in domains if d)
    return str(domains).strip()


def _search_params(query: str, location=None, language=None,
                   include_domains=None, exclude_domains=None,
                   purpose=None, page: int = 0) -> dict:
    params = {"query": query}
    if location:
        params["location"] = str(location).upper()
    if language:
        params["language"] = str(language)
    included = _join_domains(include_domains)
    if included:
        params["include_domains"] = included
    excluded = _join_domains(exclude_domains)
    if excluded:
        params["exclude_domains"] = excluded
    if purpose:
        params["purpose"] = purpose
    page = max(0, min(SEARCH_PAGE_MAX, int(page or 0)))
    if page:
        params["page"] = page
    return params


def _map_search_hits(payload: dict) -> list[dict]:
    out = []
    for r in payload.get("results") or []:
        u = (r.get("url") or "").strip()
        if not u.startswith("http"):
            continue
        out.append({
            "url": u,
            "domain": _tf_domain(u),
            "title": r.get("title") or "",
            "snippet": r.get("snippet") or "",
            "engine": "tinyfish",
        })
    return out


async def tf_search(query: str, key: str, *, location: str | None = None,
                    language: str | None = None, include_domains=None,
                    exclude_domains=None, purpose: str | None = POE_PURPOSE,
                    page: int = 0, log=None) -> list[dict]:
    """GET Search API. 401/402/429/timeout → [] (jamais d'exception)."""
    log = log or (lambda m: None)
    if not (key or "").strip() or not (query or "").strip():
        return []
    params = _search_params(
        query, location, language, include_domains, exclude_domains,
        purpose, page)
    await _search_bucket.acquire()
    last_status = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(SEARCH_URL, headers=_headers(key), params=params)
            last_status = r.status_code
            if r.status_code == 429 and attempt == 0:
                log("TinyFish Search: 429 — retry")
                await asyncio.sleep(SEARCH_RETRY_SLEEP_S)
                continue
            if r.status_code in (401, 402, 403, 404, 429, 500, 503):
                log(f"TinyFish Search: HTTP {r.status_code} — ignoré")
                return []
            r.raise_for_status()
            return _map_search_hits(r.json() if r.content else {})
        except Exception as e:
            log(f"TinyFish Search: échec ({type(e).__name__}: {str(e)[:80]})")
            if last_status == 429 and attempt == 0:
                await asyncio.sleep(SEARCH_RETRY_SLEEP_S)
                continue
            return []
    return []


def _fetch_record(url: str, *, text="", title="", blocked=False, links=None,
                  error=None, final_url=None) -> dict:
    if isinstance(text, dict):
        text = json.dumps(text, ensure_ascii=False)
    return {
        "text": text or "",
        "title": title or "",
        "blocked": bool(blocked),
        "links": list(links or []),
        "level": FETCH_LEVEL,
        "error": error,
        "final_url": final_url,
    }


def _map_fetch_payload(payload: dict, requested: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for item in payload.get("results") or []:
        u = (item.get("url") or "").strip()
        if not u:
            continue
        links = item.get("links") or []
        rec = _fetch_record(
            u, text=item.get("text") or "", title=item.get("title") or "",
            links=links, final_url=item.get("final_url"))
        out[u] = rec
        final = item.get("final_url")
        if final and final not in out:
            out[final] = rec
    for err in payload.get("errors") or []:
        u = (err.get("url") or "").strip()
        if not u:
            continue
        code = err.get("error") or "error"
        out[u] = _fetch_record(u, blocked=(code == "bot_blocked"), error=code)
    for u in requested:
        out.setdefault(u, _fetch_record(u, error="missing"))
    return out


async def tf_fetch(urls: list[str], key: str, *, ttl: int = 0, links: bool = True,
                   purpose: str | None = POE_PURPOSE, log=None) -> dict[str, dict]:
    """POST Fetch API (lots de 10). bot_blocked → blocked=True, texte vide."""
    log = log or (lambda m: None)
    if not (key or "").strip():
        return {}
    clean = [u for u in (urls or []) if isinstance(u, str) and u.startswith("http")]
    if not clean:
        return {}
    out: dict[str, dict] = {}
    for i in range(0, len(clean), 10):
        batch = clean[i:i + 10]
        await _fetch_bucket.acquire(len(batch))
        body = {
            "urls": batch,
            "format": "markdown",
            "ttl": int(ttl),
            "links": bool(links),
        }
        if purpose:
            body["purpose"] = purpose
        try:
            async with httpx.AsyncClient(timeout=150) as client:
                r = await client.post(FETCH_URL, headers=_headers(key), json=body)
            if r.status_code in (401, 402, 403, 429, 500):
                log(f"TinyFish Fetch: HTTP {r.status_code} — ignoré")
                for u in batch:
                    out.setdefault(u, _fetch_record(u, error=f"http_{r.status_code}"))
                continue
            r.raise_for_status()
            mapped = _map_fetch_payload(r.json() if r.content else {}, batch)
            out.update(mapped)
        except Exception as e:
            log(f"TinyFish Fetch: échec ({type(e).__name__}: {str(e)[:80]})")
            for u in batch:
                out.setdefault(u, _fetch_record(u, error=type(e).__name__))
    return out


async def tf_search_pages(query: str, key: str, *, location: str | None = None,
                          language: str | None = None, include_domains=None,
                          exclude_domains=None, purpose: str | None = POE_PURPOSE,
                          max_pages: int = SEARCH_PAGE_CAP,
                          stop_when=None, log=None) -> list[dict]:
    """Enchaîne les pages Search (0..max_pages-1) jusqu'à stop_when(hits)."""
    log = log or (lambda m: None)
    pages = max(1, min(SEARCH_PAGE_MAX + 1, int(max_pages or 1)))
    hits, seen = [], set()
    for page in range(pages):
        batch = await tf_search(
            query, key, location=location, language=language,
            include_domains=include_domains, exclude_domains=exclude_domains,
            purpose=purpose, page=page, log=log)
        if not batch:
            break
        added = 0
        for h in batch:
            u = (h.get("url") or "").strip()
            if not u or u in seen:
                continue
            seen.add(u)
            hits.append(h)
            added += 1
        if added == 0:
            break
        if stop_when and stop_when(hits):
            break
    return hits


def poe_agent_goal(name: str, zone_name: str, iso2: str | None = None) -> str:
    cc = f" ({iso2})" if iso2 else ""
    return (
        f"Open this official page. Decide if « {name} » in {zone_name}{cc} "
        "is a designated port of entry / puerto habilitado / port d'entrée "
        "for foreign pleasure craft (yachts, recreational) OR mixed "
        "(commercial AND pleasure). Do not invent names. is_poe=true only if "
        "THIS page designates THIS place for pleasure or mixed traffic. "
        "false if cargo-only, container terminal, industrial, airport, city, "
        "or another country. A marina is not automatically false: official "
        "clearance at THIS marina is is_poe=true, kind=pleasure. "
        "Set kind to pleasure, mixed, cargo, other, or unknown. "
        "null if you cannot decide or the page names a designated port "
        "without readable traffic type."
    )


async def tf_poe_agent(url: str, name: str, zone_name: str, key: str, *,
                       iso2: str | None = None, log=None,
                       credit_cap: int = AGENT_CREDIT_CAP) -> dict:
    """Un Agent par graine : lite puis stealth. 2 concurrents, max_steps=crédits."""
    log = log or (lambda m: None)
    if not (key or "").strip() or not (url or "").startswith("http"):
        return {}
    goal = poe_agent_goal(name, zone_name, iso2)
    cap = max(1, min(500, int(credit_cap or AGENT_CREDIT_CAP)))
    cfg = {"max_steps": cap, "max_duration_seconds": 180}
    last_err = None
    async with _agent_sem:
        for profile in ("lite", "stealth"):
            try:
                log(f"TinyFish Agent {profile} cap={cap} {url[:80]}")
                result = await tf_run_sse(
                    url, goal, POE_JUDGE_SCHEMA, key,
                    browser_profile=profile, agent_config=cfg, timeout=240)
                if isinstance(result, dict) and result:
                    out = dict(result)
                    out["_agent_profile"] = profile
                    return out
                last_err = "empty result"
            except Exception as e:
                last_err = e
                log(f"TinyFish Agent {profile}: {type(e).__name__}: {str(e)[:80]}")
    return {"_agent_error": str(last_err or "empty")}
