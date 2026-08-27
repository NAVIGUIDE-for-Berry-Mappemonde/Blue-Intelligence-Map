"""
ai.py — Wrapper de rétrocompatibilité au-dessus de llm_core (Core mutualisé).
Les pipelines et server.py continuent d'importer ai.py ; toute la logique LLM
(cascade Gemini/Emergent/OpenRouter, Gatekeeper, extraction JSON) vit dans llm_core.
"""
import re

from llm_core import (
    MARINE_KW, LAND_KW,  # noqa: F401 (rétrocompat)
    ask_json,
    available_engines,
    gatekeeper_check,  # noqa: F401 — ré-export direct
    get_llm_key,  # noqa: F401
    has_llm,  # noqa: F401
    heuristic_gatekeeper,  # noqa: F401
    llm_geocode,
)


async def _llm_json(prompt: str, model: str, key: str, engine: str = "gemini") -> dict:
    """Rétrocompat : toutes les requêtes sont désormais routées vers OpenRouter."""
    data, _ = await ask_json(prompt, settings={"openrouter_api_key": key}, prefer="openrouter")
    return data


async def _gemini_json(prompt: str, model: str, key: str) -> dict:
    data, _ = await ask_json(prompt, settings={"openrouter_api_key": key}, prefer="openrouter")
    return data


async def gemini_geocode(location: str, title: str, settings: dict):
    """Rétrocompat : géocodage intelligent LLM (llm_core.llm_geocode)."""
    return await llm_geocode(location, title, settings)


def heuristic_extract(title: str, text: str, meta_desc: str, settings: dict) -> dict:
    desc = (meta_desc or text[:400]).strip().replace("\n", " ")
    desc = re.sub(r"\s+", " ", desc)[:250]
    gk = heuristic_gatekeeper(f"{title} {text}", settings)
    return {"title": title[:200], "description": desc, "location": None,
            "latitude": None, "longitude": None, "s_ocean": gk["score"],
            "engine": "Heuristic Extractor"}


async def extract_project(title: str, text: str, meta_desc: str, url: str, funder: str,
                          settings: dict, ext_links=None) -> dict:
    if not available_engines(settings):
        raise RuntimeError("OPENROUTER_API_KEY is required for project extraction")
    links_block = ""
    if ext_links:
        links_block = "\nExternal organization links found on the page:\n" + \
            "\n".join(f"- {l['name']}: {l['url']}" for l in ext_links[:15])
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
        prefer = settings.get("extraction_engine")
        prefer = {"gpt": "emergent", "claude": "emergent"}.get(prefer, prefer)
        out, engine = await ask_json(prompt, settings=settings,
                                     prefer=prefer if prefer in ("gemini", "emergent", "openrouter") else None)
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
    except Exception as exc:
        raise RuntimeError(f"OpenRouter project extraction failed: {exc}") from exc
