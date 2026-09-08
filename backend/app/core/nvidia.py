"""Adaptateur NVIDIA NIM hosted (OpenAI-compatible).

Complétions JSON uniquement — jamais la recherche web (:online reste
OpenRouter). Modèles par défaut, mesurés sur le juge / extracteur PoE :

  - Muse     meta/muse-glimmer-30b      lecteur principal (juge + extract)
  - Kimi     moonshotai/kimi-k3         textes juridiques (décret, gazette)
  - Laguna   poolside/laguna-xs-2.1     hors service (ne plus appeler)

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
PRIMARY_MODEL = "meta/muse-glimmer-30b"
SECONDARY_MODEL = "meta/muse-glimmer-30b"
LEGAL_MODEL = "moonshotai/kimi-k3"

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


def _usable_nim(model: str) -> str:
    """Laguna répond 503 : ne jamais l'appeler, même via NVIDIA_MODEL."""
    if "laguna" in (model or "").lower():
        return PRIMARY_MODEL
    return model


def primary_model() -> str:
    return _usable_nim(_env("NVIDIA_MODEL") or PRIMARY_MODEL)


def secondary_model() -> str:
    return _usable_nim(_env("NVIDIA_MODEL_SECONDARY") or SECONDARY_MODEL)


def legal_model() -> str:
    return _env("NVIDIA_MODEL_LEGAL") or LEGAL_MODEL


def engine_label(model: str | None = None) -> str:
    """Étiquette persistée (judge_engine / extraction_engine)."""
    m = (model or primary_model()).lower()
    if "muse" in m:
        return "nvidia-muse"
    if "kimi" in m:
        return "nvidia-kimi"
    if "laguna" in m:
        return "nvidia-laguna"
    return "nvidia"


def looks_like_legal_text(text: str | None) -> bool:
    """True si l'extrait ressemble à un décret / gazette (Kimi, pas le juge courant)."""
    blob = (text or "").strip()
    if len(blob) < 80:
        return False
    return bool(_LEGAL_RE.search(blob))


def second_extract_choice(context: str | None) -> tuple[str, str] | None:
    """Second lecteur : Kimi sur décret ; sinon Muse seulement s'il n'est pas déjà le principal."""
    if looks_like_legal_text(context):
        return legal_model(), "nvidia-kimi"
    sec = secondary_model()
    if sec == primary_model():
        return None
    return sec, engine_label(sec)


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


def _retry_wait(response: httpx.Response, fallback: float) -> float:
    raw = (response.headers.get("Retry-After") or "").strip()
    if raw.isdigit():
        return min(60.0, max(1.0, float(raw)))
    try:
        return min(60.0, max(1.0, float(raw)))
    except (TypeError, ValueError):
        return fallback


async def complete_json_nvidia(system: str, prompt: str,
                               settings: dict | None = None, *,
                               model: str | None = None,
                               max_tokens: int = 800,
                               log=None) -> dict:
    """Complétion JSON strict. Backoff exponentiel sur 429 / 5xx."""
    key = get_nvidia_key(settings)
    if not key:
        raise RuntimeError("NVIDIA_API_KEY missing")
    payload = {
        "model": model or primary_model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    delays = (2.0, 4.0, 8.0, 16.0)
    last_err = "nvidia exhausted retries"
    for attempt, delay in enumerate((*delays, None)):
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(NVIDIA_URL, headers=headers, json=payload)
        if r.status_code in (429, 500, 502, 503) and delay is not None:
            wait = _retry_wait(r, delay)
            if log:
                log(f"nvidia {payload['model']}: HTTP {r.status_code}, retry in {wait:.0f}s")
            await asyncio.sleep(wait)
            last_err = f"nvidia HTTP {r.status_code}"
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"nvidia HTTP {r.status_code}: {(r.text or '')[:160]}")
        body = r.json()
        choices = body.get("choices") or []
        raw = _message_text((choices[0].get("message") or {}) if choices else {})
        data = parse_json_strict(raw)
        if isinstance(data, dict):
            return data
        if log:
            log("nvidia: no strict JSON in output")
        raise RuntimeError("nvidia: no JSON in output")
    raise RuntimeError(last_err)


async def extract_ports_nvidia(context: str, zone: dict,
                               settings: dict | None = None, log=None,
                               model: str | None = None,
                               engine: str | None = None) -> list[dict]:
    from app.core.llm import POE_EXTRACT_PROMPT, coerce_ports

    used = model or primary_model()
    tag = engine or engine_label(used)
    prompt = POE_EXTRACT_PROMPT.format(
        name=zone.get("name") or zone.get("geoname"),
        sovereign=zone.get("sovereign") or "",
        context=(context or "")[:20000],
    )
    data = await complete_json_nvidia(
        "Tu réponds uniquement en JSON strict.", prompt, settings,
        model=used, max_tokens=2500, log=log)
    ports = coerce_ports(data, context=context)
    for p in ports:
        p["extraction_engine"] = tag
    if log:
        log(f"LLM {tag}: {len(ports)} port(s) extraits")
    return ports
