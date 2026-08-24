import json
import os
import re
import uuid

MARINE_KW = [
    "ocean", "marine", "sea", "coral", "reef", "mangrove", "seagrass", "coastal",
    "fishery", "fisheries", "fishing", "mpa", "marine protected", "kelp", "whale",
    "shark", "turtle", "estuary", "pelagic", "aquaculture", "blue carbon", "coast",
    "seabird", "dolphin", "tide", "tidal", "island", "gulf", "bay", "archipelago", "atoll",
]
LAND_KW = [
    "mountain", "rainforest", "savanna", "desert", "grassland", "freshwater lake",
    "river basin", "alpine", "prairie", "inland forest", "terrestrial",
]


def get_llm_key(settings: dict) -> str:
    # Priority: user-provided Gemini key in Settings > GEMINI_API_KEY env > EMERGENT_LLM_KEY universal env.
    # emergentintegrations LlmChat routes to Gemini when .with_model("gemini", ...) is used,
    # so the Emergent universal key works transparently as a fallback.
    return (
        settings.get("gemini_api_key")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("EMERGENT_LLM_KEY")
        or ""
    ).strip()


def has_llm(settings: dict) -> bool:
    return bool(get_llm_key(settings))


async def _llm_json(prompt: str, model: str, key: str, engine: str = "gemini") -> dict:
    """
    Unified JSON call. Routes through emergentintegrations for gemini/gpt/claude
    (all three via the universal EMERGENT_LLM_KEY) — Phase 5.
    Falls back to a bare httpx POST to OpenRouter when engine == "openrouter".
    """
    if engine == "openrouter":
        import httpx
        or_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
        if not or_key:
            raise ValueError("OPENROUTER_API_KEY missing")
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {or_key}"},
                json={
                    "model": "openai/gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "max_tokens": 900,
                },
            )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError("no JSON in openrouter output")
        return json.loads(m.group(0))
    # ---- gemini / gpt / claude via emergentintegrations ---------------------
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    # Emergent library expects (provider, model_id). We map "gpt"/"claude"
    # to sensible defaults; the caller can still override `model`.
    provider = engine if engine in ("gemini", "openai", "anthropic") else {
        "gpt": "openai",
        "claude": "anthropic",
    }.get(engine, "gemini")
    default_models = {
        "gemini":    "gemini-2.5-flash",
        "openai":    "gpt-4o-mini",
        "anthropic": "claude-3-5-sonnet-20241022",
    }
    chosen_model = model if provider == "gemini" else default_models.get(provider, model)
    chat = LlmChat(
        api_key=key,
        session_id=str(uuid.uuid4()),
        system_message="You are the Blue Intelligence maritime OSINT engine. Reply ONLY with a single valid JSON object, no prose, no markdown fences.",
    ).with_model(provider, chosen_model)
    resp = await chat.send_message(UserMessage(text=prompt))
    text = resp if isinstance(resp, str) else str(resp)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in model output")
    return json.loads(m.group(0))


# Backward-compat alias
async def _gemini_json(prompt: str, model: str, key: str) -> dict:
    return await _llm_json(prompt, model, key, engine="gemini")


def heuristic_gatekeeper(text: str, settings: dict) -> dict:
    low = text.lower()
    marine = sum(low.count(k) for k in MARINE_KW)
    land = sum(low.count(k) for k in LAND_KW)
    score = marine / (marine + land * 1.5 + 1e-9) if marine else 0.0
    score = round(min(1.0, score), 3)
    accepted = marine >= 3 and score >= float(settings.get("min_marine_score", 0.5))
    return {"accepted": accepted, "score": score,
            "reason": f"heuristic: {marine} marine / {land} terrestrial keyword hits",
            "engine": "Heuristic Gatekeeper"}


async def gatekeeper_check(title: str, text: str, settings: dict) -> dict:
    key = get_llm_key(settings)
    if not key:
        return heuristic_gatekeeper(f"{title} {text}", settings)
    prompt = f"""Gatekeeper Protocol: decide if this project is a MARINE/OCEAN/COASTAL conservation, restoration or protection project.
REJECT purely terrestrial (mountains, inland forests) or freshwater (lakes, rivers) projects, UNLESS it is an estuary with direct coastal impact.
Project title: {title}
Page content (truncated):
{text[:3000]}

Return JSON: {{"marine": true/false, "score": 0.0-1.0, "reason": "<short reason>"}}"""
    try:
        engine = settings.get("extraction_engine", "gemini")
        out = await _llm_json(prompt, settings.get("gatekeeper_model", "gemini-3-flash-preview"), key, engine=engine)
        score = float(out.get("score", 0))
        return {"accepted": bool(out.get("marine")) and score >= float(settings.get("min_marine_score", 0.5)),
                "score": round(score, 3), "reason": str(out.get("reason", ""))[:300],
                "engine": f"{engine.title()} Gatekeeper"}
    except Exception as e:
        res = heuristic_gatekeeper(f"{title} {text}", settings)
        res["reason"] = f"llm failed ({str(e)[:80]}), {res['reason']}"
        return res


def heuristic_extract(title: str, text: str, meta_desc: str, settings: dict) -> dict:
    desc = (meta_desc or text[:400]).strip().replace("\n", " ")
    desc = re.sub(r"\s+", " ", desc)[:250]
    gk = heuristic_gatekeeper(f"{title} {text}", settings)
    return {"title": title[:200], "description": desc, "location": None,
            "latitude": None, "longitude": None, "s_ocean": gk["score"],
            "engine": "Heuristic Extractor"}


async def gemini_geocode(location: str, title: str, settings: dict):
    """Smart geocoding: Gemini estimates precise coastal/marine coordinates."""
    key = get_llm_key(settings)
    if not key:
        return None
    prompt = f"""You are a maritime geocoding expert. Give the best-estimate GPS coordinates for this marine conservation project site.
Project: {title}
Location description: {location or 'unknown'}

Rules: prefer the actual project site (reef, bay, MPA, coastal zone) over any city or HQ. If the location is a coastal region, return a point in the adjacent waters.
Return JSON: {{"latitude": <decimal>, "longitude": <decimal>, "confidence": <0.0-1.0>}}. If you truly cannot estimate, use confidence 0."""
    try:
        out = await _gemini_json(prompt, settings.get("gatekeeper_model", "gemini-3-flash-preview"), key)
        lat, lon = float(out.get("latitude")), float(out.get("longitude"))
        if float(out.get("confidence", 0)) >= 0.4 and -90 <= lat <= 90 and -180 <= lon <= 180 and not (lat == 0 and lon == 0):
            return lat, lon
    except Exception:
        pass
    return None


async def extract_project(title: str, text: str, meta_desc: str, url: str, funder: str, settings: dict, ext_links=None) -> dict:
    key = get_llm_key(settings)
    if not key:
        return heuristic_extract(title, text, meta_desc, settings)
    links_block = ""
    if ext_links:
        links_block = "\nExternal organization links found on the page:\n" + "\n".join(f"- {l['name']}: {l['url']}" for l in ext_links[:15])
    prompt = f"""Extract structured data from this marine conservation project page.
URL: {url}
Funder: {funder}
Page title: {title}
Content (truncated):
{text[:5000]}{links_block}

Return JSON:
{{"title": "<official project name>",
 "description": "<ecological impact synthesis, WHAT and WHY, max 250 chars, do not repeat title>",
 "location": "<most specific geographic place name, e.g. 'Banc d'Arguin, Mauritania', or null if global>",
 "latitude": <decimal or null>,
 "longitude": <decimal or null>,
 "s_ocean": <0.0-1.0 relevance score: technicality + source reliability + oceanic localization>,
 "category": "<exactly one of: MPA, Conservation, Research, Fisheries, Policy & Advocacy, Pollution, Coastal & Habitat, Education, Other>",
 "partners": [<up to 3 partner/grantee MARINE conservation organizations explicitly mentioned, each {{"name": "...", "url": "<their website from the links list, or null>"}}. Empty array if none>]}}"""
    try:
        engine = settings.get("extraction_engine", "gemini")
        out = await _llm_json(prompt, settings.get("extract_model", "gemini-3.1-pro-preview"), key, engine=engine)
        return {
            "title": str(out.get("title") or title)[:200],
            "description": str(out.get("description") or "")[:250],
            "location": out.get("location"),
            "latitude": out.get("latitude"),
            "longitude": out.get("longitude"),
            "s_ocean": round(float(out.get("s_ocean") or 0.5), 3),
            "category": str(out.get("category") or "Other"),
            "partners": [p for p in (out.get("partners") or []) if isinstance(p, dict) and p.get("name")][:3],
            "engine": f"{engine.title()} Extractor",
        }
    except Exception:
        return heuristic_extract(title, text, meta_desc, settings)
