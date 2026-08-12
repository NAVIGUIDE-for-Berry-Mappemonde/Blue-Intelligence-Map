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
    return (settings.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def has_llm(settings: dict) -> bool:
    return bool(get_llm_key(settings))


async def _claude_json(prompt: str, model: str, key: str) -> dict:
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(
        api_key=key,
        session_id=str(uuid.uuid4()),
        system_message="You are the Blue Intelligence maritime OSINT engine. Reply ONLY with a single valid JSON object, no prose, no markdown fences.",
    ).with_model("anthropic", model)
    resp = await chat.send_message(UserMessage(text=prompt))
    text = resp if isinstance(resp, str) else str(resp)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in model output")
    return json.loads(m.group(0))


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
        out = await _claude_json(prompt, settings.get("gatekeeper_model", "claude-haiku-4-5-20251001"), key)
        score = float(out.get("score", 0))
        return {"accepted": bool(out.get("marine")) and score >= float(settings.get("min_marine_score", 0.5)),
                "score": round(score, 3), "reason": str(out.get("reason", ""))[:300],
                "engine": "Claude Gatekeeper"}
    except Exception as e:
        res = heuristic_gatekeeper(f"{title} {text}", settings)
        res["reason"] = f"claude failed ({str(e)[:80]}), {res['reason']}"
        return res


def heuristic_extract(title: str, text: str, meta_desc: str, settings: dict) -> dict:
    desc = (meta_desc or text[:400]).strip().replace("\n", " ")
    desc = re.sub(r"\s+", " ", desc)[:250]
    gk = heuristic_gatekeeper(f"{title} {text}", settings)
    return {"title": title[:200], "description": desc, "location": None,
            "latitude": None, "longitude": None, "s_ocean": gk["score"],
            "engine": "Heuristic Extractor"}


async def extract_project(title: str, text: str, meta_desc: str, url: str, funder: str, settings: dict) -> dict:
    key = get_llm_key(settings)
    if not key:
        return heuristic_extract(title, text, meta_desc, settings)
    prompt = f"""Extract structured data from this marine conservation project page.
URL: {url}
Funder: {funder}
Page title: {title}
Content (truncated):
{text[:5000]}

Return JSON:
{{"title": "<official project name>",
 "description": "<ecological impact synthesis, WHAT and WHY, max 250 chars, do not repeat title>",
 "location": "<most specific geographic place name, e.g. 'Banc d'Arguin, Mauritania', or null if global>",
 "latitude": <decimal or null>,
 "longitude": <decimal or null>,
 "s_ocean": <0.0-1.0 relevance score: technicality + source reliability + oceanic localization>}}"""
    try:
        out = await _claude_json(prompt, settings.get("extract_model", "claude-sonnet-4-6"), key)
        return {
            "title": str(out.get("title") or title)[:200],
            "description": str(out.get("description") or "")[:250],
            "location": out.get("location"),
            "latitude": out.get("latitude"),
            "longitude": out.get("longitude"),
            "s_ocean": round(float(out.get("s_ocean") or 0.5), 3),
            "engine": "Claude Extractor",
        }
    except Exception:
        return heuristic_extract(title, text, meta_desc, settings)
