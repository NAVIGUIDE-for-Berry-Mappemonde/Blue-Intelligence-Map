import json

import httpx

BASE = "https://agent.tinyfish.ai/v1"

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


async def tf_run_sse(url: str, goal: str, schema: dict, key: str, on_event=None, timeout: int = 420) -> dict:
    """Stream a TinyFish run via SSE; returns final result dict, raises on failure."""
    payload = {"url": url, "goal": goal, "output_schema": schema, "browser_profile": "lite"}
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
