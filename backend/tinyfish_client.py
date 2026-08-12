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


def discovery_goal(org_name: str) -> str:
    return (
        f"You are a maritime OSINT discovery agent for Blue Intelligence, exploring the website of '{org_name}'. "
        "Navigate menus, project/program/campaign listings, and pagination as needed. "
        "Collect pages that each describe ONE individual marine, ocean, coastal, reef, mangrove, seagrass, "
        "fisheries or marine-protected-area conservation project or program. "
        "Exclude news, events, jobs, donation pages, generic category pages, and external links. "
        "Return every qualifying page as projects with canonical URL and visible page title. "
        "Do not invent values. If none qualify, return an empty projects array."
    )


def extract_goal(url: str) -> str:
    return (
        "Open this marine conservation project page and extract: the official project title, "
        "a description of its ecological impact (max 250 characters), the most specific geographic "
        "location name, and GPS latitude/longitude if visible on the page or in an embedded map. "
        "Do not invent coordinates."
    )


def _headers(key: str) -> dict:
    return {"X-API-Key": key, "Content-Type": "application/json"}


async def tf_run_async(url: str, goal: str, schema: dict, key: str) -> dict:
    payload = {"url": url, "goal": goal, "output_schema": schema, "browser_profile": "lite"}
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
