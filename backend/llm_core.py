"""
llm_core.py — Adaptateur LLM OpenRouter obligatoire.

Toutes les opérations LLM passent par l'API OpenRouter. Aucun fallback local,
Gemini ou Emergent n'est utilisé : une clé OpenRouter manquante ou un appel
échoué remonte explicitement une erreur.
"""
import asyncio
import json
import os
import re
import uuid
from urllib.parse import urlparse

import httpx

OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
JSON_SYSTEM = ("You are the Blue Intelligence maritime OSINT engine. "
               "Reply ONLY with a single valid JSON object, no prose, no markdown fences.")

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


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def get_llm_key(settings: dict | None = None) -> str:
    s = settings or {}
    return (s.get("openrouter_api_key") or _env("OPENROUTER_API_KEY")).strip()


def has_llm(settings: dict | None = None) -> bool:
    return bool(get_llm_key(settings))


def available_engines(settings: dict | None = None) -> list[str]:
    """Expose OpenRouter only when its required key is configured."""
    return ["openrouter"] if get_llm_key(settings) else []


# ---------------------------------------------------------------------------
# Parsing JSON robuste (fusion ai.py + poe.py)
# ---------------------------------------------------------------------------
def parse_json_flexible(txt: str):
    txt = re.sub(r"^```(json)?|```$", "", (txt or "").strip(), flags=re.M).strip()
    try:
        return json.loads(txt)
    except Exception:
        pass
    m = re.search(r"\{.*\}", txt, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    m = re.search(r"\[.*\]", txt, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------
async def _call_gemini_rest(prompt: str, system: str, key: str, json_mode: bool = True,
                            max_tokens: int = 2048, retries: int = 2) -> str:
    body = {
        "contents": [{"parts": [{"text": f"{system}\n\n{prompt}"}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    for attempt in range(retries):
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_REST_MODEL}:generateContent?key={key}",
                json=body,
            )
            if r.status_code in (429, 500, 503) and attempt < retries - 1:
                await asyncio.sleep(10 * (attempt + 1))
                continue
            r.raise_for_status()
            d = r.json()
        return "".join(p.get("text", "")
                       for p in ((d.get("candidates") or [{}])[0].get("content") or {}).get("parts", []))
    raise RuntimeError("gemini rest exhausted retries")


async def _call_openrouter(prompt: str, system: str, key: str, model: str = OPENROUTER_MODEL,
                           json_mode: bool = True, max_tokens: int = 2000) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(OPENROUTER_API_URL,
                              headers={"Authorization": f"Bearer {key}"}, json=payload)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


async def _dispatch(engine: str, prompt: str, system: str, settings: dict | None,
                    json_mode: bool, max_tokens: int) -> str:
    if engine != "openrouter":
        raise ValueError(f"unsupported LLM engine: {engine}")
    key = get_llm_key(settings)
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    return await _call_openrouter(prompt, system, key, json_mode=json_mode, max_tokens=max_tokens)


# ---------------------------------------------------------------------------
# API publique — cascade avec fallback automatique
# ---------------------------------------------------------------------------
async def ask_json(prompt: str, system: str = JSON_SYSTEM, settings: dict | None = None,
                   prefer: str | None = None, max_tokens: int = 2000, log=None) -> tuple[dict, str]:
    """Retourne (dict, engine utilisé) via OpenRouter uniquement."""
    order = available_engines(settings)
    if not order:
        raise RuntimeError("OPENROUTER_API_KEY is required; no local LLM fallback is available")
    if prefer and prefer in order:
        order.remove(prefer)
        order.insert(0, prefer)
    errors = []
    for engine in order:
        try:
            raw = await _dispatch(engine, prompt, system, settings, True, max_tokens)
            data = parse_json_flexible(raw)
            if isinstance(data, dict):
                return data, engine
            errors.append(f"{engine}: no JSON in output")
        except Exception as e:
            errors.append(f"{engine}: {type(e).__name__}: {str(e)[:100]}")
            if log:
                log(f"llm_core: {engine} en échec ({type(e).__name__}) — fallback suivant")
    raise RuntimeError("All LLM backends failed: " + " | ".join(errors[:3]))


async def ask_text(prompt: str, system: str = "You are a helpful assistant.",
                   settings: dict | None = None, prefer: str | None = None,
                   max_tokens: int = 2000) -> tuple[str, str]:
    order = available_engines(settings)
    if not order:
        raise RuntimeError("OPENROUTER_API_KEY is required; no local LLM fallback is available")
    if prefer and prefer in order:
        order.remove(prefer)
        order.insert(0, prefer)
    errors = []
    for engine in order:
        try:
            return await _dispatch(engine, prompt, system, settings, False, max_tokens), engine
        except Exception as e:
            errors.append(f"{engine}: {type(e).__name__}")
    raise RuntimeError("All LLM backends failed: " + " | ".join(errors[:3]))


# ---------------------------------------------------------------------------
# Gatekeeper marin (fusion ai.py) + pré-filtre ML local (weak supervision)
# ---------------------------------------------------------------------------
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
    # 1. Classifieur local (bootstrappé sur les projets existants) : si très
    # confiant, décision sans appel LLM (économie de crédits).
    try:
        from ml_core import predict_relevance
        ml = predict_relevance(f"{title} {text[:2500]}")
    except Exception:
        ml = None
    if ml is not None:
        if ml["score"] >= 0.85:
            return {"accepted": True, "score": round(ml["score"], 3),
                    "reason": "ML gatekeeper: high-confidence marine (local model, no LLM call)",
                    "engine": "ML Gatekeeper (local)"}
        if ml["score"] <= 0.12:
            return {"accepted": False, "score": round(ml["score"], 3),
                    "reason": "ML gatekeeper: high-confidence non-marine (local model, no LLM call)",
                    "engine": "ML Gatekeeper (local)"}
    # 2. LLM (cascade) ou heuristique
    if not available_engines(settings):
        raise RuntimeError("OPENROUTER_API_KEY is required for gatekeeper checks")
    prompt = f"""Gatekeeper Protocol: decide if this project is a MARINE/OCEAN/COASTAL conservation, restoration or protection project.
REJECT purely terrestrial (mountains, inland forests) or freshwater (lakes, rivers) projects, UNLESS it is an estuary with direct coastal impact.
Project title: {title}
Page content (truncated):
{text[:3000]}

Return JSON: {{"marine": true/false, "score": 0.0-1.0, "reason": "<short reason>"}}"""
    try:
        prefer = settings.get("extraction_engine")
        prefer = {"gpt": "emergent", "claude": "emergent"}.get(prefer, prefer)
        out, engine = await ask_json(prompt, settings=settings,
                                     prefer=prefer if prefer in ("gemini", "emergent", "openrouter") else None)
        score = float(out.get("score", 0))
        return {"accepted": bool(out.get("marine")) and score >= float(settings.get("min_marine_score", 0.5)),
                "score": round(score, 3), "reason": str(out.get("reason", ""))[:300],
                "engine": f"{engine.title()} Gatekeeper"}
    except Exception as e:
        raise RuntimeError(f"OpenRouter gatekeeper failed: {e}") from e


# ---------------------------------------------------------------------------
# Extraction stricte des Ports d'Entrée (fusion poe.py)
# ---------------------------------------------------------------------------
POE_EXTRACT_PROMPT = """Tu extrais les PORTS D'ENTRÉE OFFICIELS (ports de clearance douanière) pour les navires de PLAISANCE étrangers dans : {name} ({sovereign}).

Réponds UNIQUEMENT avec un JSON strict de la forme:
{{"ports": [{{"name": "...", "city": "... ou null", "note": "précision courte ou null"}}]}}

Règles absolues:
- Uniquement les ports d'entrée / de clearance OFFICIELS pour la plaisance mentionnés dans les extraits.
- Ne JAMAIS inventer. Si les extraits ne désignent aucun port d'entrée: {{"ports": []}}.
- "name" = nom du port/marina/quai tel qu'écrit. "note" en français, max 120 caractères.

EXTRAITS DES SOURCES OFFICIELLES:
{context}"""


def coerce_ports(data) -> list[dict]:
    ports = data.get("ports") if isinstance(data, dict) else None
    out = []
    for p in ports or []:
        if isinstance(p, dict) and (p.get("name") or "").strip():
            out.append({
                "name": str(p["name"]).strip()[:120],
                "city": (str(p["city"]).strip()[:80] if p.get("city") else None),
                "note": (str(p["note"]).strip()[:200] if p.get("note") else None),
            })
    return out[:150]  # plafond de sécurité élevé — pas de cap par pays (grands États maritimes)


async def extract_ports(context: str, zone: dict, settings: dict | None = None, log=None) -> list[dict]:
    prompt = POE_EXTRACT_PROMPT.format(
        name=zone.get("name") or zone.get("geoname"),
        sovereign=zone.get("sovereign") or "",
        context=context[:20000],
    )
    data, engine = await ask_json(prompt, system="Tu réponds uniquement en JSON strict.",
                                  settings=settings, max_tokens=2500, log=log)
    ports = coerce_ports(data)
    if log:
        log(f"LLM {engine}: {len(ports)} port(s) extraits")
    return ports


# ---------------------------------------------------------------------------
# Géocodage intelligent par LLM (ex ai.gemini_geocode)
# ---------------------------------------------------------------------------
async def llm_geocode(location: str, title: str, settings: dict):
    if not available_engines(settings):
        return None
    prompt = f"""You are a maritime geocoding expert. Give the best-estimate GPS coordinates for this marine conservation project site.
Project: {title}
Location description: {location or 'unknown'}

Rules: prefer the actual project site (reef, bay, MPA, coastal zone) over any city or HQ. If the location is a coastal region, return a point in the adjacent waters.
Return JSON: {{"latitude": <decimal>, "longitude": <decimal>, "confidence": <0.0-1.0>}}. If you truly cannot estimate, use confidence 0."""
    try:
        out, _ = await ask_json(prompt, settings=settings, max_tokens=300)
        lat, lon = float(out.get("latitude")), float(out.get("longitude"))
        if float(out.get("confidence", 0)) >= 0.4 and -90 <= lat <= 90 and -180 <= lon <= 180 and not (lat == 0 and lon == 0):
            return lat, lon
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Recherche groundée : Gemini google_search (si clé) sinon OpenRouter :online
# ---------------------------------------------------------------------------
def _fallback_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


async def grounded_search(prompt: str, log=None, domain_fn=None) -> tuple[list[dict], str | None]:
    """Retourne (candidats [{url, domain}], synthèse texte)."""
    log = log or (lambda m: None)
    dom = domain_fn or _fallback_domain
    or_key = _env("OPENROUTER_API_KEY")
    if not or_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for grounded search")
    return await _grounded_openrouter(prompt, or_key, log, dom)


async def _grounded_gemini(prompt: str, key: str, log, dom) -> tuple[list[dict], str | None]:
    body = {"contents": [{"parts": [{"text": prompt}]}], "tools": [{"google_search": {}}]}
    d = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_REST_MODEL}:generateContent?key={key}",
                    json=body,
                )
                if r.status_code in (429, 500, 503) and attempt < 2:
                    log(f"Gemini grounding: HTTP {r.status_code} — retry dans {10 * (attempt + 1)}s")
                    await asyncio.sleep(10 * (attempt + 1))
                    continue
                r.raise_for_status()
                d = r.json()
                break
        except Exception as e:
            if attempt < 2:
                log(f"Gemini grounding: {type(e).__name__} — retry")
                await asyncio.sleep(8)
                continue
            log(f"Gemini grounding: échec ({type(e).__name__}: {e})")
            return [], None
    if d is None:
        return [], None
    cand = (d.get("candidates") or [{}])[0]
    synthesis = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
    chunks = (cand.get("groundingMetadata") or {}).get("groundingChunks") or []
    raw = []
    for c in chunks:
        w = c.get("web") or {}
        if w.get("uri"):
            raw.append({"redirect": w["uri"], "title": (w.get("title") or "").strip().lower()})
    log(f"Gemini grounding: {len(raw)} sources candidates, synthèse {len(synthesis)} chars")

    async def _resolve(item):
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                async with client.stream("GET", item["redirect"]) as r:
                    return {"url": str(r.url), "domain": dom(str(r.url))}
        except Exception:
            t = item["title"]
            if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", t or ""):
                return {"url": f"https://{t}/", "domain": t}
            return None

    resolved = await asyncio.gather(*(_resolve(x) for x in raw[:10]))
    seen, out = set(), []
    for x in resolved:
        if x and x["domain"] and x["domain"] not in seen:
            seen.add(x["domain"])
            out.append(x)
    return out, synthesis


async def _grounded_openrouter(prompt: str, key: str, log, dom) -> tuple[list[dict], str | None]:
    """OpenRouter web search (suffixe :online) — citations dans message.annotations."""
    payload = {
        "model": f"{OPENROUTER_MODEL}:online",
        "messages": [{"role": "user", "content": prompt + "\n\nCite the official source URLs you used."}],
        "temperature": 0,
        "max_tokens": 1800,
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post("https://openrouter.ai/api/v1/chat/completions",
                                  headers={"Authorization": f"Bearer {key}"}, json=payload)
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
    except Exception as e:
        log(f"OpenRouter :online: échec ({type(e).__name__}: {str(e)[:80]})")
        return [], None
    synthesis = msg.get("content") or ""
    urls = []
    for a in msg.get("annotations") or []:
        cit = a.get("url_citation") or {}
        u = cit.get("url") or a.get("url")
        if u and u.startswith("http"):
            urls.append(u)
    # URLs citées inline dans la synthèse en complément
    urls += re.findall(r"https?://[^\s\)\]\"']+", synthesis)
    seen, out = set(), []
    for u in urls:
        u = u.rstrip(".,;")
        d = dom(u)
        if d and d not in seen:
            seen.add(d)
            out.append({"url": u, "domain": d})
    log(f"OpenRouter :online: {len(out)} sources candidates, synthèse {len(synthesis)} chars")
    return out[:10], synthesis or None
