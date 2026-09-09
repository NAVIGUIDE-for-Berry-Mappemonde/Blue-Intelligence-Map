"""Adaptateur NVIDIA NIM hosted (OpenAI-compatible).

Complétions JSON — jamais la recherche web (:online reste OpenRouter).

Le catalogue Build (https://build.nvidia.com/models, ~143 fiches) mélange
ASR, bio, CFD, image, OCR et LLM. GET /v1/models est un index OpenAI périmé
(ids 404 : yi-large, dbrx, granite…). IDs chat : docs.api.nvidia.com/nim/
reference/llm-apis + URL canonique /{publisher}/{title}.

Beaucoup de fiches restent en ligne alors que le hosted trial répond 410 Gone
(EOL, successeur daté : deepseek-v4-flash → flash-0731). D'autres (Muse,
Laguna, Gemma 4) sont live mais « Structured Output: Not supported » :
json_object les fait pendre — on omet response_format.

Chaînes de fallback (échec HTTP / timeout / JSON vide → suivant) :

  judge   Pro → Muse → gpt-oss-20b → Flash
  extract Pro → Muse → gpt-oss-20b → Kimi
  legal   Kimi → Pro → Muse
  json    Pro → Muse → gpt-oss-20b   # gatekeeper, projet, géocode, AMP
  page    Pro → Muse → gpt-oss-20b   # marina / capitainerie (texte de page)
  text    Muse → Pro → gpt-oss-20b   # ask_text, pas de json_object

Après la chaîne NIM : OpenRouter (complétion), puis Claude **en dernier**.
La recherche web (`:online`) reste OpenRouter — NIM n'a pas de plugin web.

Paramètres JSON — contrat hosted = fiche infer (docs.api.nvidia.com/nim/…-infer),
pas le playground ni la carte locale (temp/top_k hors schéma hosted) :

  Pro    effort none (défaut infer) ; kwargs {thinking:false} (prototype Build)
  Flash  effort none (défaut infer = **high**) ; kwargs thinking=false
  Muse   pas de json_object ; 0.95 / 1.0 ; effort low (défaut high)
  gpt-oss effort low (défaut medium ; enum sans none) ; 0.6 / 0.7
  Kimi   temp 1.0 ; pas de top_p (non exposé) ; effort low (défaut max)
  Laguna 1 / 0.95 ; pas de thinking/effort sur l'API infer


Clé : NVIDIA_API_KEY (env) ou settings["nvidia_api_key"] (UI).
Provider : LLM_PROVIDER=nvidia|openrouter|auto (auto = NVIDIA si clé présente).
"""
from __future__ import annotations

import asyncio
import json
import os
import re

import httpx

NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
FLASH_MODEL = "deepseek-ai/deepseek-v4-flash-0731"
PRO_MODEL = "deepseek-ai/deepseek-v4-pro-0813"
PRIMARY_MODEL = PRO_MODEL
SECONDARY_MODEL = "meta/muse-glimmer-30b"
LEGAL_MODEL = "moonshotai/kimi-k3"
GPT_OSS_MODEL = "openai/gpt-oss-20b"

# Fiches Build : Capabilities → Structured Output: Not supported.
_NO_JSON_OBJECT = (
    "muse-glimmer",
    "laguna",
    "gemma-4",
    "diffusiongemma",
)

# IDs docs / aliases EOL → successeur hosted encore servi.
_ALIASES = {
    "deepseek-ai/deepseek-v4-flash": FLASH_MODEL,
    "deepseek-ai/deepseek-v4-pro": PRO_MODEL,
    "poolside/laguna-xs-2-1": "poolside/laguna-xs-2.1",
}

# Rôles → ordre mesuré (canari PoE 2026-09-08, sans json_object sur Muse).
# Pro 4/4 ~9 s ; Muse 4/4 ~19 s ; gpt-oss 4/4 ~43 s ; Flash 4/4 mais lent
# sous charge ; Kimi pour les décrets ; Laguna 503 capacité ; Gemma hang.
CHAINS = {
    "judge": (PRO_MODEL, SECONDARY_MODEL, GPT_OSS_MODEL, FLASH_MODEL),
    "extract": (PRO_MODEL, SECONDARY_MODEL, GPT_OSS_MODEL, LEGAL_MODEL),
    "legal": (LEGAL_MODEL, PRO_MODEL, SECONDARY_MODEL),
    "json": (PRO_MODEL, SECONDARY_MODEL, GPT_OSS_MODEL),
    "page": (PRO_MODEL, SECONDARY_MODEL, GPT_OSS_MODEL),
    "text": (SECONDARY_MODEL, PRO_MODEL, GPT_OSS_MODEL),
}

_THINKING_RE = re.compile(r"^\s*here's a thinking process", re.I)
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)
_LEGAL_RE = re.compile(
    r"\b("
    r"d[ée]cret|arr[êe]t[ée]s?|gazette|journal\s+officiel|"
    r"puertos?\s+habilitados?|boleti[nń]\s+oficial|"
    r"points?\s+de\s+passage\s+frontaliers?|"
    r"designated\s+ports?\s+of\s+entry|"
    r"official\s+list\s+of\s+ports?\s+of\s+entry|"
    r"capitan[ií]as?\s+mar[ií]timas?|"
    r"loi\s+n[°ºo]|boe\.es|douane\.gouv"
    r")\b",
    re.I,
)


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def get_nvidia_key(settings: dict | None = None) -> str:
    s = settings or {}
    return (s.get("nvidia_api_key") or _env("NVIDIA_API_KEY")).strip()


def llm_provider(settings: dict | None = None) -> str:
    s = settings or {}
    raw = str(s.get("llm_provider") or _env("LLM_PROVIDER") or "auto").strip().lower()
    if raw in ("nvidia", "openrouter"):
        return raw
    return "nvidia" if get_nvidia_key(s) else "openrouter"


def nvidia_enabled(settings: dict | None = None) -> bool:
    s = settings or {}
    return llm_provider(s) == "nvidia" and bool(get_nvidia_key(s))


def _alias(model: str) -> str:
    """Corrige les slugs docs / EOL. Muse et Laguna restent appelables."""
    raw = (model or "").strip()
    return _ALIASES.get(raw, raw)


def _usable_nim(model: str) -> str:
    return _alias(model or "")


def supports_json_object(model: str | None) -> bool:
    blob = (model or "").lower()
    return not any(token in blob for token in _NO_JSON_OBJECT)


def primary_model() -> str:
    return _usable_nim(_env("NVIDIA_MODEL") or PRIMARY_MODEL)


def secondary_model() -> str:
    return _usable_nim(_env("NVIDIA_MODEL_SECONDARY") or SECONDARY_MODEL)


def legal_model() -> str:
    return _usable_nim(_env("NVIDIA_MODEL_LEGAL") or LEGAL_MODEL)


def _dedupe(models: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in models:
        used = _usable_nim(raw)
        if not used or used in seen:
            continue
        seen.add(used)
        out.append(used)
    return tuple(out)


def models_for(role: str, preferred: str | None = None) -> tuple[str, ...]:
    """Chaîne ordonnée (judge, extract, legal, json, page, text)."""
    key = role if role in CHAINS else "json"
    defaults = list(CHAINS[key])
    extra = _env(f"NVIDIA_MODEL_CHAIN_{key.upper()}")
    if extra:
        defaults = [p.strip() for p in extra.split(",") if p.strip()] or defaults
    head: list[str] = []
    if preferred:
        head.append(preferred)
    if key == "legal":
        head.append(legal_model())
    elif key != "text":
        # text : CHAINS commence par Muse (pas de json_object).
        head.append(primary_model())
        if key in ("judge", "extract"):
            head.append(secondary_model())
    return _dedupe([*head, *defaults])


def engine_label(model: str | None = None) -> str:
    """Étiquette persistée (judge_engine / extraction_engine)."""
    m = (model or primary_model()).lower()
    if "deepseek" in m:
        return "nvidia-deepseek"
    if "muse" in m:
        return "nvidia-muse"
    if "llama-3.2" in m:
        return "nvidia-llama"
    if "kimi" in m:
        return "nvidia-kimi"
    if "laguna" in m:
        return "nvidia-laguna"
    if "gpt-oss" in m:
        return "nvidia-gpt-oss"
    if "gemma" in m:
        return "nvidia-gemma"
    if "minimax" in m:
        return "nvidia-minimax"
    if "nemotron" in m or "lightning" in m:
        return "nvidia-nemotron"
    return "nvidia"


def muse_generation_extras(model: str | None = None) -> dict:
    """Paramètres NIM documentés (fiches infer) pour JSON PoE."""
    return generation_extras(model)


def sampling_params(model: str | None = None) -> dict:
    """Échantillonnage des fiches NVIDIA infer, pas le greedy générique."""
    m = (model or primary_model()).lower()
    if "muse" in m:
        # infer : greedy dégrade ; couple recommandé 0.95 / 1.0.
        # (carte locale : 1.0 / 0.95 / top_k 64 — top_k absent du schéma hosted)
        return {"temperature": 0.95, "top_p": 1.0}
    if "kimi-k3" in m:
        # kimi-k3-infer : « Recommended for Kimi-K3: 1.0 » ; top_p non exposé.
        return {"temperature": 1.0}
    if "gpt-oss" in m:
        # openai-gpt-oss-20b-infer : défauts 0.6 / 0.7.
        return {"temperature": 0.6, "top_p": 0.7}
    if "laguna" in m:
        # poolside-laguna-xs-2-1-infer : défauts 1 / 0.95.
        return {"temperature": 1.0, "top_p": 0.95}
    # DeepSeek V4 infer : défaut 1 / 0.95. JSON PoE : temperature 0 seule
    # (la fiche déconseille de toucher temperature et top_p ensemble).
    return {"temperature": 0}


def generation_extras(model: str | None = None, role: str = "json") -> dict:
    """reasoning_effort / chat_template_kwargs selon la fiche infer et l'usage."""
    m = (model or primary_model()).lower()
    # legal : Kimi thinking always on ; défaut infer = max. JSON PoE / page :
    # low pour ne pas manger max_tokens (trial 429 si max).
    if "muse" in m:
        return {
            "reasoning_effort": "low",
            "chat_template_kwargs": {"reasoning_strength": "low"},
        }
    if "deepseek-v4-flash" in m:
        return {
            "reasoning_effort": "none",
            "chat_template_kwargs": {
                "thinking": False,
                "reasoning_effort": "none",
            },
        }
    if "deepseek-v4" in m:
        return {
            "reasoning_effort": "none",
            "chat_template_kwargs": {"thinking": False},
        }
    if "gpt-oss" in m:
        return {"reasoning_effort": "low"}
    if "kimi-k3" in m:
        effort = "high" if role == "legal" else "low"
        return {"reasoning_effort": effort}
    return {}


def looks_like_legal_text(text: str | None) -> bool:
    """True si l'extrait ressemble à un décret / gazette (Kimi, pas le juge courant)."""
    blob = (text or "").strip()
    if len(blob) < 80:
        return False
    return bool(_LEGAL_RE.search(blob))


def second_extract_choice(context: str | None) -> tuple[str, str] | None:
    """Second lecteur : Kimi sur décret ; sinon le suivant de la chaîne extract."""
    prim = primary_model()
    if looks_like_legal_text(context):
        chain = models_for("legal")
    else:
        chain = models_for("extract")
    for model in chain:
        if model != prim:
            return model, engine_label(model)
    return None


def parse_json_strict(txt: str | None):
    """JSON uniquement. Refuse le chain-of-thought (exemple du prompt inclus)."""
    if not isinstance(txt, str) or not txt.strip():
        return None
    s = _FENCE_RE.sub("", txt.strip()).strip()
    if not s or _THINKING_RE.search(s):
        return None
    if not s.lstrip()[:1] in "{[":
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def _extract_json_object(txt: str | None):
    """Premier objet JSON équilibré (filet pour reasoning_content)."""
    if not isinstance(txt, str):
        return None
    start = txt.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i, ch in enumerate(txt[start:]):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(txt[start:start + i + 1])
                except Exception:
                    return None
                return obj if isinstance(obj, dict) else None
    return None


def _message_text(msg: dict | None) -> str:
    msg = msg or {}
    content = msg.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get("type") in ("text", "output_text"):
                parts.append(p.get("text") or "")
            elif isinstance(p, str):
                parts.append(p)
        return "".join(parts).strip()
    return ""


def _json_from_message(msg: dict | None):
    msg = msg or {}
    raw = _message_text(msg)
    data = parse_json_strict(raw)
    if isinstance(data, dict):
        return data
    reason = msg.get("reasoning_content")
    data = parse_json_strict(reason if isinstance(reason, str) else None)
    if isinstance(data, dict):
        return data
    return _extract_json_object(reason if isinstance(reason, str) else None)


def _retry_wait(response: httpx.Response, fallback: float) -> float:
    raw = (response.headers.get("Retry-After") or "").strip()
    if raw.isdigit():
        return min(90.0, max(fallback, float(raw)))
    try:
        return min(90.0, max(fallback, float(raw)))
    except (TypeError, ValueError):
        return fallback


def chat_payload(model: str, system: str, user: str, max_tokens: int,
                 *, json_object: bool | None = None, role: str = "json") -> dict:
    """Corps chat/completions. json_object=None → selon la fiche Build."""
    used = _usable_nim(model)
    use_json = supports_json_object(used) if json_object is None else json_object
    body = {
        "model": used,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "stream": False,
        **sampling_params(used),
        **generation_extras(used, role=role),
    }
    if use_json:
        body["response_format"] = {"type": "json_object"}
    return body


async def _complete_one(key: str, payload: dict, *,
                        max_tokens: int, log=None) -> dict:
    """Un modèle. 410/404 lèvent tout de suite ; 400 json_object → retry sans format."""
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    delays = (5.0, 12.0, 25.0)
    last_err = "nvidia exhausted retries"
    timeout = httpx.Timeout(120.0, connect=20.0)
    used = dict(payload)
    for delay in (*delays, None):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(NVIDIA_URL, headers=headers, json=used)
        except httpx.TimeoutException as e:
            # Pas 3×120 s : le modèle suivant de la chaîne doit partir
            # (Gemma 4 pend même sans json_object).
            raise RuntimeError(f"nvidia timeout: {type(e).__name__}")
        if r.status_code == 400 and used.get("response_format"):
            used = {k: v for k, v in used.items() if k != "response_format"}
            last_err = f"nvidia HTTP 400: {(r.text or '')[:160]}"
            if log:
                log(f"nvidia {used['model']}: json_object rejeté, retry sans format")
            continue
        if r.status_code in (429, 500, 502, 503) and delay is not None:
            wait = _retry_wait(r, delay)
            if log:
                log(f"nvidia {used['model']}: HTTP {r.status_code}, retry in {wait:.0f}s")
            await asyncio.sleep(wait)
            last_err = f"nvidia HTTP {r.status_code}"
            continue
        if r.status_code >= 400:
            raise RuntimeError(
                f"nvidia HTTP {r.status_code}: {(r.text or '')[:160]}")
        body = r.json()
        choices = body.get("choices") or []
        msg = (choices[0].get("message") or {}) if choices else {}
        data = _json_from_message(msg)
        if isinstance(data, dict):
            return data
        last_err = "nvidia: no JSON in output"
        if delay is None:
            break
        used["max_tokens"] = min(int(used.get("max_tokens") or max_tokens) * 2, 2500)
        if log:
            log(f"nvidia {used['model']}: no strict JSON, retry tokens={used['max_tokens']}")
        await asyncio.sleep(2.0)
        continue
    raise RuntimeError(last_err)


async def complete_json_nvidia_tracked(
        system: str, prompt: str,
        settings: dict | None = None, *,
        model: str | None = None,
        role: str = "json",
        fallback: bool = True,
        max_tokens: int = 800,
        log=None) -> tuple[dict, str]:
    """Comme complete_json_nvidia, plus l'id réellement servi."""
    key = get_nvidia_key(settings)
    if not key:
        raise RuntimeError("NVIDIA_API_KEY missing")
    chain = models_for(role, preferred=model) if fallback else (
        (_usable_nim(model or primary_model()),)
    )
    last_err = "nvidia exhausted chain"
    for used in chain:
        payload = chat_payload(used, system, prompt, max_tokens, role=role)
        try:
            data = await _complete_one(key, payload, max_tokens=max_tokens, log=log)
            return data, used
        except RuntimeError as e:
            last_err = str(e)
            more = fallback and used != chain[-1]
            if log:
                nxt = " → suivant" if more else ""
                log(f"nvidia {used}: {last_err[:120]}{nxt}")
            if not more:
                break
            continue
    raise RuntimeError(last_err)


async def complete_json_nvidia(system: str, prompt: str,
                               settings: dict | None = None, *,
                               model: str | None = None,
                               role: str = "json",
                               fallback: bool = True,
                               max_tokens: int = 800,
                               log=None) -> dict:
    """Complétion JSON. fallback=True : chaîne du rôle si le modèle échoue."""
    data, _used = await complete_json_nvidia_tracked(
        system, prompt, settings, model=model, role=role,
        fallback=fallback, max_tokens=max_tokens, log=log)
    return data


async def complete_text_nvidia(system: str, prompt: str,
                               settings: dict | None = None, *,
                               model: str | None = None,
                               role: str = "text",
                               fallback: bool = True,
                               max_tokens: int = 800,
                               log=None) -> str:
    """Complétion texte (pas de json_object). Chaîne `text` par défaut."""
    key = get_nvidia_key(settings)
    if not key:
        raise RuntimeError("NVIDIA_API_KEY missing")
    chain = models_for(role, preferred=model) if fallback else (
        (_usable_nim(model or secondary_model()),)
    )
    last_err = "nvidia exhausted chain"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    timeout = httpx.Timeout(120.0, connect=20.0)
    for used in chain:
        payload = chat_payload(
            used, system, prompt, max_tokens, json_object=False, role=role)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(NVIDIA_URL, headers=headers, json=payload)
        except httpx.TimeoutException as e:
            last_err = f"nvidia timeout: {type(e).__name__}"
            if log:
                log(f"nvidia {used}: {last_err}")
            if not fallback or used == chain[-1]:
                break
            continue
        if r.status_code >= 400:
            last_err = f"nvidia HTTP {r.status_code}: {(r.text or '')[:160]}"
            if log:
                log(f"nvidia {used}: {last_err[:120]}")
            if not fallback or used == chain[-1]:
                break
            continue
        msg = ((r.json().get("choices") or [{}])[0].get("message") or {})
        text = _message_text(msg).strip()
        if text:
            return text
        last_err = "nvidia: empty text"
        if not fallback or used == chain[-1]:
            break
    raise RuntimeError(last_err)


async def extract_ports_nvidia(context: str, zone: dict,
                               settings: dict | None = None, log=None,
                               model: str | None = None,
                               engine: str | None = None,
                               fallback: bool | None = None) -> list[dict]:
    from app.core.llm import POE_EXTRACT_PROMPT, coerce_ports

    # Le lecteur principal reste la chaîne extract (Flash…). Kimi n'est
    # second lecteur que via second_extract_choice (décret / gazette).
    role = "extract"
    do_fb = True if fallback is None and model is None else bool(fallback)
    prompt = POE_EXTRACT_PROMPT.format(
        name=zone.get("name") or zone.get("geoname"),
        sovereign=zone.get("sovereign") or "",
        context=(context or "")[:20000],
    )
    data, used = await complete_json_nvidia_tracked(
        "Tu réponds uniquement en JSON strict.", prompt, settings,
        model=model, role=role, fallback=do_fb, max_tokens=2500, log=log)
    tag = engine or engine_label(used)
    ports = coerce_ports(data, context=context)
    for p in ports:
        p["extraction_engine"] = tag
    if log:
        log(f"LLM {tag}: {len(ports)} port(s) extraits")
    return ports
