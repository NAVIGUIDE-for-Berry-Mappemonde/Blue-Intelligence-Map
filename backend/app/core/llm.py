"""
llm_core.py — Adaptateur LLM.

Complétions JSON : NVIDIA (chaîne du rôle) → OpenRouter → Claude en dernier.
grounded_search reste OpenRouter (:online) — NIM n'a pas de recherche web.

  - ask_json / ask_text        : complétions (JSON strict ou texte libre)
  - gatekeeper_check           : filtre marin (pré-filtre ML local puis LLM)
  - extract_project            : extraction structurée d'un projet marin
  - extract_ports              : extraction stricte des Ports d'Entrée
  - llm_geocode                : géocodage intelligent
  - grounded_search            : recherche web groundée (suffixe :online)

Clés : NVIDIA_API_KEY / OPENROUTER_API_KEY (env) ou settings UI.
"""
import asyncio
import json
import os
import re
from urllib.parse import urlparse

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"
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


def openrouter_model() -> str:
    return _env("OPENROUTER_MODEL") or DEFAULT_MODEL


def get_llm_key(settings: dict | None = None) -> str:
    """Clé OpenRouter : settings (UI) prioritaire, sinon variable d'environnement."""
    s = settings or {}
    return (s.get("openrouter_api_key") or _env("OPENROUTER_API_KEY")).strip()


def has_llm(settings: dict | None = None) -> bool:
    from app.core.nvidia import nvidia_enabled
    from app.core import claude
    if nvidia_enabled(settings) or bool(get_llm_key(settings)):
        return True
    return claude.claude_enabled(settings) and claude.budget_allows_call(settings)


# ---------------------------------------------------------------------------
# Parsing JSON robuste
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
# Backend unique : OpenRouter
# ---------------------------------------------------------------------------
async def _call_openrouter(prompt: str, system: str, key: str, model: str | None = None,
                           json_mode: bool = True, max_tokens: int = 2000,
                           retries: int = 2) -> str:
    payload = {
        "model": model or openrouter_model(),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": "https://blueintelligence.online",
        "X-Title": "Blue Intelligence",
    }
    for attempt in range(retries):
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(OPENROUTER_URL, headers=headers, json=payload)
            if r.status_code in (429, 500, 502, 503) and attempt < retries - 1:
                await asyncio.sleep(8 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    raise RuntimeError("openrouter exhausted retries")


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------
def _public_engine(engine: str, kind: str) -> str:
    """Libellé persisté (gatekeeper / extracteur projet)."""
    if (engine or "").startswith("nvidia"):
        return f"NVIDIA {kind}"
    if (engine or "").startswith("claude"):
        return f"Claude {kind}"
    return f"OpenRouter {kind}"


async def ask_json_tracked(prompt: str, system: str = JSON_SYSTEM,
                           settings: dict | None = None,
                           max_tokens: int = 2000, log=None,
                           role: str = "json") -> tuple[dict, str]:
    """JSON strict : NVIDIA (chaîne du rôle) → OpenRouter → Claude en dernier.

    Retourne (objet, engine) — engine = nvidia-* | openrouter | claude.
    """
    from app.core import claude, nvidia
    last: Exception | None = None
    if nvidia.nvidia_enabled(settings):
        try:
            data, used = await nvidia.complete_json_nvidia_tracked(
                system, prompt, settings, max_tokens=max_tokens, log=log,
                role=role)
            return data, nvidia.engine_label(used)
        except Exception as e:
            last = e
            if log:
                log(f"nvidia JSON épuisé: {str(e)[:120]}")
    key = get_llm_key(settings)
    if key:
        try:
            data = await _json_openrouter(prompt, system, settings, max_tokens)
            return data, "openrouter"
        except Exception as e:
            last = e
            if log:
                log(f"openrouter JSON: {str(e)[:120]}")
    if claude.claude_enabled(settings) and claude.budget_allows_call(settings):
        try:
            data = await claude.complete_json_claude(
                system, prompt, settings,
                max_tokens=min(int(max_tokens), 800), log=log)
            return data, "claude"
        except Exception as e:
            last = e
            if log:
                log(f"claude JSON (dernier): {str(e)[:120]}")
    if last:
        raise last
    raise RuntimeError("no LLM backend")


async def ask_json(prompt: str, system: str = JSON_SYSTEM, settings: dict | None = None,
                   max_tokens: int = 2000, log=None, role: str = "json") -> dict:
    """JSON strict : NVIDIA → OpenRouter → Claude en dernier."""
    data, _engine = await ask_json_tracked(
        prompt, system, settings, max_tokens=max_tokens, log=log, role=role)
    return data


async def ask_text(prompt: str, system: str = "You are a helpful assistant.",
                   settings: dict | None = None, max_tokens: int = 2000) -> str:
    """Texte : NVIDIA (chaîne text) puis OpenRouter. Pas de Claude (adaptateur JSON)."""
    from app.core import nvidia
    if nvidia.nvidia_enabled(settings):
        try:
            return await nvidia.complete_text_nvidia(
                system, prompt, settings, max_tokens=max_tokens)
        except Exception:
            pass
    key = get_llm_key(settings)
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY missing")
    return await _call_openrouter(prompt, system, key, json_mode=False, max_tokens=max_tokens)


# ---------------------------------------------------------------------------
# Gatekeeper marin + pré-filtre ML local (weak supervision)
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
        from app.core.ml import predict_relevance
        ml = predict_relevance(f"{title} {text[:2500]}")
    except Exception:
        ml = None
    if ml is not None:
        accept_at = float(settings.get("gatekeeper_accept", 0.85))
        reject_at = float(settings.get("gatekeeper_reject", 0.12))
        if ml["score"] >= accept_at:
            return {"accepted": True, "score": round(ml["score"], 3),
                    "reason": "ML gatekeeper: high-confidence marine (local model, no LLM call)",
                    "engine": "ML Gatekeeper (local)"}
        if ml["score"] <= reject_at:
            return {"accepted": False, "score": round(ml["score"], 3),
                    "reason": "ML gatekeeper: high-confidence non-marine (local model, no LLM call)",
                    "engine": "ML Gatekeeper (local)"}
    # 2. LLM (NIM → OpenRouter → Claude) ou heuristique
    if not has_llm(settings):
        return heuristic_gatekeeper(f"{title} {text}", settings)
    prompt = f"""Gatekeeper Protocol: decide if this project is a MARINE/OCEAN/COASTAL conservation, restoration or protection project.
REJECT purely terrestrial (mountains, inland forests) or freshwater (lakes, rivers) projects, UNLESS it is an estuary with direct coastal impact.
Project title: {title}
Page content (truncated):
{text[:3000]}

Return JSON: {{"marine": true/false, "score": 0.0-1.0, "reason": "<short reason>"}}"""
    try:
        out, engine = await ask_json_tracked(prompt, settings=settings)
        score = float(out.get("score", 0))
        return {"accepted": bool(out.get("marine")) and score >= float(settings.get("min_marine_score", 0.5)),
                "score": round(score, 3), "reason": str(out.get("reason", ""))[:300],
                "engine": _public_engine(engine, "Gatekeeper")}
    except Exception as e:
        res = heuristic_gatekeeper(f"{title} {text}", settings)
        res["reason"] = f"llm failed ({str(e)[:80]}), {res['reason']}"
        return res


# ---------------------------------------------------------------------------
# Extraction structurée d'un projet marin (ex ai.extract_project)
# ---------------------------------------------------------------------------
def heuristic_extract(title: str, text: str, meta_desc: str, settings: dict) -> dict:
    desc = (meta_desc or text[:400]).strip().replace("\n", " ")
    desc = re.sub(r"\s+", " ", desc)[:250]
    gk = heuristic_gatekeeper(f"{title} {text}", settings)
    return {"title": title[:200], "description": desc, "location": None,
            "latitude": None, "longitude": None, "s_ocean": gk["score"],
            "engine": "Heuristic Extractor"}


async def extract_project(title: str, text: str, meta_desc: str, url: str, funder: str,
                          settings: dict, ext_links=None) -> dict:
    if not has_llm(settings):
        return heuristic_extract(title, text, meta_desc, settings)
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
        out, engine = await ask_json_tracked(prompt, settings=settings)
        return {
            "title": str(out.get("title") or title)[:200],
            "description": str(out.get("description") or "")[:250],
            "location": out.get("location"),
            "latitude": out.get("latitude"),
            "longitude": out.get("longitude"),
            "s_ocean": round(float(out.get("s_ocean") or 0.5), 3),
            "category": str(out.get("category") or "Other"),
            "partners": [p for p in (out.get("partners") or []) if isinstance(p, dict) and p.get("name")][:3],
            "engine": _public_engine(engine, "Extractor"),
        }
    except Exception:
        return heuristic_extract(title, text, meta_desc, settings)


# ---------------------------------------------------------------------------
# Extraction stricte des Ports d'Entrée
# ---------------------------------------------------------------------------
POE_EXTRACT_PROMPT = """Tu extrais les ports officiellement désignés pour l'entrée des navires étrangers dans : {name} ({sovereign}).

Réponds UNIQUEMENT avec un JSON strict de la forme:
{{"ports": [{{"name": "...", "city": "... ou null", "note": "... ou null", "lat": <decimal ou null>, "lon": <decimal ou null>, "geocodeable": true}}]}}

Règles absolues:
- Prendre tout port / terminal / harbour que la source officielle désigne comme point d'entrée :
  ports d'entrée, clearance, puertos habilitados (décret), ports of entry,
  « port of / port de / puerto de X », capitanías de puerto, delegaciones,
  designated ports, gazette, décret, liste de ports de plaisance, places of first arrival.
  Un règlement scanné (OCR) reste une source : extraire les noms malgré les fautes OCR.
  Un tableau SCT « N° Nom État Puerto/Terminal date lat lon » (sans le mot Latitud)
  est un catalogue : ne garder QUE les ports tagués turística / Turística.
  Annexe I Mayotte : uniquement les sites « Frontières maritimes » (pas l'aéroport).
  Royaume-Uni : si une liste de ports de plaisance est publiée, tous sont Ports of Entry.
  Sint Maarten : la phrase « Some examples include » de Customs.aspx est une liste
  de PoE (marinas + Greatbay harbor + Cruise Terminal) — ignorer aéroport et poste.
  Égypte : titres « X Marina: » de la page SIS yacht-tourism — ne pas inventer
  Alexandria / Port Said / Sharm s'ils ne figurent pas en titre.
  Albanie : « Porti detar X » de la kartelë akcizë / anijet e peshkimit
  (Durrës, Shëngjin, Vlorë, Sarandë) — pas Lezhë (dega doganore seulement).
  Tableaux MPI « | Nom | / Approved vessels » = places of first arrival.
  La mention « plaisance » n'est PAS exigée si l'État publie une liste officielle.
- Ne JAMAIS inventer un nom absent des extraits. Si aucun port n'est nommé : {{"ports": []}}.
- Ignorer les aéroports (sauf s'ils sont le seul point d'entrée maritime nommé — ne pas les extraire).
- "name" = nom du port tel qu'écrit. "note" en français, max 120 caractères.
- "lat"/"lon" : recopier UNIQUEMENT un nombre présent dans l'extrait. Sinon null.
  Ne jamais estimer un GPS de mémoire.
- "geocodeable": false si le nom n'est pas un toponyme (phrase, verbe, fragment).

EXTRAITS DES SOURCES OFFICIELLES:
{context}"""


_COORD_TOKEN_RE = re.compile(r"[+-]?\d+\.\d+|[+-]\d{2,}")


def _parse_coord(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _number_in_text(value: float, text: str) -> bool:
    """Le nombre (ou un arrondi cohérent) figure dans l'extrait source."""
    if not text:
        return False
    raw = f"{value:.10f}".rstrip("0").rstrip(".")
    if raw and raw in text:
        return True
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    for m in _COORD_TOKEN_RE.finditer(text):
        try:
            n = float(m.group(0))
        except ValueError:
            continue
        if decimals >= 2:
            if abs(round(n, decimals) - round(value, decimals)) <= 10 ** (-decimals):
                return True
        elif decimals == 1:
            if abs(n - value) <= 0.05:
                return True
        elif abs(n - value) < 1e-6:
            return True
    return False


def coords_appear_in_text(lat: float, lon: float, text: str) -> bool:
    """True seulement si lat et lon sont recopiés depuis l'extrait (pas inventés)."""
    return _number_in_text(lat, text) and _number_in_text(lon, text)


def _as_bool_or_none(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
    return None


def coerce_ports(data, context: str | None = None) -> list[dict]:
    ports = data.get("ports") if isinstance(data, dict) else None
    out = []
    for p in ports or []:
        if not (isinstance(p, dict) and (p.get("name") or "").strip()):
            continue
        row = {
            "name": str(p["name"]).strip()[:120],
            "city": (str(p["city"]).strip()[:80] if p.get("city") else None),
            "note": (str(p["note"]).strip()[:200] if p.get("note") else None),
        }
        geo_flag = _as_bool_or_none(p.get("geocodeable"))
        if geo_flag is not None:
            row["geocodeable"] = geo_flag
        lat = _parse_coord(p.get("lat") if p.get("lat") is not None else p.get("latitude"))
        lon = _parse_coord(p.get("lon") if p.get("lon") is not None else p.get("longitude"))
        if lat is not None and lon is not None:
            if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
                lat = lon = None
            elif context is not None and not coords_appear_in_text(lat, lon, context):
                lat = lon = None
        if lat is not None and lon is not None:
            row["lat"] = lat
            row["lon"] = lon
        out.append(row)
    return out[:150]  # plafond de sécurité élevé — pas de cap par pays (grands États maritimes)


async def _json_openrouter(prompt: str, system: str, settings: dict | None,
                           max_tokens: int) -> dict:
    key = get_llm_key(settings)
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY missing")
    raw = await _call_openrouter(
        prompt, system, key, json_mode=True, max_tokens=max_tokens)
    data = parse_json_flexible(raw)
    if isinstance(data, dict):
        return data
    raise RuntimeError("openrouter: no JSON in output")


async def extract_ports_openrouter(context: str, zone: dict,
                                   settings: dict | None = None, log=None) -> list[dict]:
    """Lecteur OpenRouter seul (pas de reboucle NIM)."""
    from app.services.poe_zone_label import search_polygon_name
    prompt = POE_EXTRACT_PROMPT.format(
        name=search_polygon_name(zone) or (zone.get("name") or zone.get("geoname") or ""),
        sovereign=zone.get("sovereign") or "",
        context=context[:20000],
    )
    data = await _json_openrouter(
        prompt, "Tu réponds uniquement en JSON strict.", settings, 2500)
    ports = coerce_ports(data, context=context)
    for p in ports:
        p["extraction_engine"] = "openrouter"
    if log:
        log(f"LLM OpenRouter: {len(ports)} port(s) extraits")
    return ports


async def extract_ports(context: str, zone: dict, settings: dict | None = None, log=None) -> list[dict]:
    """Lecteur principal. Le second lecteur (gpt-oss / Kimi) est
    orchestré dans poe_pipeline.extract_ports_llm."""
    s = settings
    if s is None:
        try:
            from app.db import get_settings
            s = await get_settings()
        except Exception:
            s = {}
    from app.core.nvidia import extract_ports_nvidia, nvidia_enabled
    from app.core import claude
    if nvidia_enabled(s):
        try:
            return await extract_ports_nvidia(context, zone, settings=s, log=log)
        except Exception as e:
            if log:
                log(f"NVIDIA extract épuisé: {type(e).__name__}: {str(e)[:100]}")
    try:
        return await extract_ports_openrouter(context, zone, settings=s, log=log)
    except Exception as e:
        if log:
            log(f"OpenRouter extract: {type(e).__name__}: {str(e)[:100]}")
    if claude.claude_enabled(s) and claude.budget_allows_call(s):
        return await claude.extract_ports_claude(context, zone, settings=s, log=log)
    raise RuntimeError("extract_ports: no backend")


# ---------------------------------------------------------------------------
# Géocodage intelligent par LLM
# ---------------------------------------------------------------------------
async def llm_geocode(location: str, title: str, settings: dict):
    if not has_llm(settings):
        return None
    prompt = f"""You are a maritime geocoding expert. Give the best-estimate GPS coordinates for this marine conservation project site.
Project: {title}
Location description: {location or 'unknown'}

Rules: prefer the actual project site (reef, bay, MPA, coastal zone) over any city or HQ. If the location is a coastal region, return a point in the adjacent waters.
Return JSON: {{"latitude": <decimal>, "longitude": <decimal>, "confidence": <0.0-1.0>}}. If you truly cannot estimate, use confidence 0."""
    try:
        out = await ask_json(prompt, settings=settings, max_tokens=300)
        lat, lon = float(out.get("latitude")), float(out.get("longitude"))
        if float(out.get("confidence", 0)) >= 0.4 and -90 <= lat <= 90 and -180 <= lon <= 180 and not (lat == 0 and lon == 0):
            return lat, lon
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Recherche groundée : OpenRouter web search (suffixe :online)
# ---------------------------------------------------------------------------
def _fallback_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


async def grounded_search(prompt: str, log=None, domain_fn=None) -> tuple[list[dict], str | None]:
    """Retourne (candidats [{url, domain}], synthèse texte) via OpenRouter :online."""
    log = log or (lambda m: None)
    dom = domain_fn or _fallback_domain
    key = _env("OPENROUTER_API_KEY")
    if not key:
        log("grounded_search: OPENROUTER_API_KEY absente")
        return [], None
    payload = {
        "model": f"{openrouter_model()}:online",
        "messages": [{"role": "user", "content": prompt + "\n\nCite the official source URLs you used."}],
        "temperature": 0,
        "max_tokens": 1800,
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(OPENROUTER_URL,
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


# ---------------------------------------------------------------------------
# Départage Nominatim vs GeoNames (un appel JSON par zone)
# ---------------------------------------------------------------------------
_TIEBREAK_SYSTEM = (
    "Tu départages un géocodage double. Réponds UNIQUEMENT avec un JSON "
    '{"picks": [{"name": "...", "choice": "nominatim|geonames|none"}]}. '
    "Ne propose aucune autre coordonnée. none = les deux points sont faux "
    "ou hors sujet pour ce port dans cette zone."
)


def _tiebreak_user(zone: dict, items: list[dict]) -> str:
    name = zone.get("name") or zone.get("geoname") or ""
    sovereign = zone.get("sovereign") or ""
    lines = [
        f"Zone : {name} ({sovereign}).",
        "Nominatim et GeoNames divergent. Choisis pour chaque port "
        "nominatim, geonames ou none. N'invente aucune coordonnée.",
        "",
    ]
    for i, it in enumerate(items, 1):
        nom = it.get("nominatim") or [None, None]
        geo = it.get("geonames") or [None, None]
        lines.append(
            f"{i}. {it.get('name')}\n"
            f"   nominatim: {nom[0]}, {nom[1]}\n"
            f"   geonames: {geo[0]}, {geo[1]}"
        )
    return "\n".join(lines)


async def arbitrate_geocode(zone: dict, items: list[dict],
                            settings: dict | None = None,
                            log=None) -> dict:
    """NVIDIA → OpenRouter → Claude. Dict vide = repli EEZ côté pipeline."""
    from app.core import claude, nvidia
    if not items:
        return {}
    prompt = _tiebreak_user(zone, items)
    if nvidia.nvidia_enabled(settings):
        try:
            data = await nvidia.complete_json_nvidia(
                _TIEBREAK_SYSTEM, prompt, settings, role="json",
                max_tokens=400, log=log)
            picks = claude._parse_tiebreak(data, items)
            if picks:
                if log:
                    log(f"NVIDIA tiebreak: {len(items)} port(s)")
                return picks
        except Exception as e:
            if log:
                log(f"NVIDIA tiebreak: {type(e).__name__}: {str(e)[:80]}")
    if get_llm_key(settings):
        try:
            data = await _json_openrouter(
                prompt, _TIEBREAK_SYSTEM, settings, 400)
            picks = claude._parse_tiebreak(data, items)
            if picks:
                if log:
                    log(f"OpenRouter tiebreak: {len(items)} port(s)")
                return picks
        except Exception as e:
            if log:
                log(f"OpenRouter tiebreak: {type(e).__name__}: {str(e)[:80]}")
    return await claude.arbitrate_geocode_claude(
        zone, items, settings=settings, log=log)
