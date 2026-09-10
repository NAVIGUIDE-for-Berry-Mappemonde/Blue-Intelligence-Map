"""
NAVIGUIDE — Cascade LLM : NVIDIA NIM → OpenRouter → Claude (Anthropic).

Aligné sur l'adaptateur Blue Intelligence (backend/app/core/nvidia.py et
backend/app/core/llm.py) : mêmes endpoints, mêmes variables d'environnement,
même ordre de cascade. Version *texte* (briefings, chat, conseils de route) —
pas de mode JSON strict ici.

Ordre de cascade — un fournisseur sans clé est simplement sauté :
  1. NVIDIA NIM   https://integrate.api.nvidia.com/v1   (NVIDIA_API_KEY)
     chaîne interne : deepseek-v4-pro → gpt-oss-20b → muse-glimmer-30b
  2. OpenRouter   https://openrouter.ai/api/v1          (OPENROUTER_API_KEY)
  3. Claude       SDK anthropic                         (ANTHROPIC_API_KEY)

Surcharges env : NVIDIA_MODEL (tête de chaîne NIM), OPENROUTER_MODEL,
ANTHROPIC_MODEL.

API publique :
  complete(prompt, system="", messages=None, max_tokens=1024)
      → (texte, provider) — synchrone, provider ∈ {nvidia, openrouter,
        claude, none}. Ne lève jamais : ("", "none") si tout échoue.
  stream(prompt, system="", max_tokens=1024)
      → AsyncIterator[str] — jetons SSE. Bascule au fournisseur/modèle
        suivant tant qu'aucun jeton n'a été émis ; s'arrête si le flux
        se rompt après le premier jeton (comportement SSE historique).
  has_any_llm() → bool

Import — ce fichier vit à la racine naviguide/, partagé par les deux racines
de service (naviguide-api/ et naviguide_workspace/) :
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from llm_cascade import complete, stream
"""

from __future__ import annotations

import json
import logging
import os
from typing import AsyncIterator, Dict, List, Optional, Tuple

import httpx

log = logging.getLogger("naviguide.llm_cascade")

NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Chaîne NIM par défaut. Déviation délibérée de l'ordre Blue Intelligence
# (deepseek-v4-pro en tête) : NAVIGUIDE est interactif (chat, SSE) et le
# hosted trial de deepseek-v4-pro part régulièrement en queue (timeouts),
# alors que gpt-oss-20b répond en quelques secondes à qualité équivalente
# sur ces textes courts. deepseek-v4-pro reste en 2ᵉ position.
NVIDIA_CHAIN = (
    "openai/gpt-oss-20b",
    "deepseek-ai/deepseek-v4-pro-0813",
    "meta/muse-glimmer-30b",
)
OPENROUTER_DEFAULT = "openai/gpt-4o-mini"
ANTHROPIC_DEFAULT = "claude-opus-4-5"

# Timeouts courts (usage interactif) : un modèle en queue bascule vite au
# suivant. En SSE, read = délai max avant le premier jeton / entre chunks.
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_STREAM_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def has_any_llm() -> bool:
    """True si au moins un fournisseur de la cascade a une clé configurée."""
    return bool(
        _env("NVIDIA_API_KEY")
        or _env("OPENROUTER_API_KEY")
        or _env("ANTHROPIC_API_KEY")
    )


def _nvidia_models() -> Tuple[str, ...]:
    head = _env("NVIDIA_MODEL")
    seen, out = set(), []
    for m in (head, *NVIDIA_CHAIN):
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return tuple(out)


def _openrouter_model() -> str:
    return _env("OPENROUTER_MODEL") or OPENROUTER_DEFAULT


def _anthropic_model() -> str:
    return _env("ANTHROPIC_MODEL") or ANTHROPIC_DEFAULT


def _nim_extras(model: str) -> Dict:
    """Paramètres des fiches infer NIM (repris de Blue Intelligence) :
    raisonnement coupé pour que max_tokens serve à la réponse, pas au thinking."""
    m = model.lower()
    if "deepseek-v4-flash" in m:
        return {
            "reasoning_effort": "none",
            "chat_template_kwargs": {"thinking": False, "reasoning_effort": "none"},
        }
    if "deepseek-v4" in m:
        return {
            "reasoning_effort": "none",
            "chat_template_kwargs": {"thinking": False},
        }
    if "gpt-oss" in m:
        return {"reasoning_effort": "low", "temperature": 0.6, "top_p": 0.7}
    if "muse" in m:
        return {
            "reasoning_effort": "low",
            "chat_template_kwargs": {"reasoning_strength": "low"},
            "temperature": 0.95,
            "top_p": 1.0,
        }
    return {}


def _openrouter_headers(key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": "https://www.naviguide.fr",
        "X-Title": "NAVIGUIDE",
    }


def _message_text(body: Dict) -> str:
    """Texte de choices[0].message.content (str ou liste de parts)."""
    choices = body.get("choices") or []
    msg = (choices[0].get("message") or {}) if choices else {}
    content = msg.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get("type") in ("text", "output_text"):
                parts.append(p.get("text") or "")
            elif isinstance(p, str):
                parts.append(p)
        return "".join(parts).strip()
    return ""


def _user_messages(prompt: str, messages: Optional[List[Dict]]) -> List[Dict]:
    msgs = list(messages or [])
    if prompt:
        msgs.append({"role": "user", "content": prompt})
    return msgs


def _with_system(system: str, msgs: List[Dict]) -> List[Dict]:
    return ([{"role": "system", "content": system}] if system else []) + msgs


# ──────────────────────────────────────────────────────────────────────────────
# Complétions synchrones (LangGraph nodes, endpoints via threadpool)
# ──────────────────────────────────────────────────────────────────────────────

def _nvidia_complete(oai_msgs: List[Dict], max_tokens: int) -> str:
    key = _env("NVIDIA_API_KEY")
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    last = "nvidia: empty chain"
    with httpx.Client(timeout=_TIMEOUT) as client:
        for model in _nvidia_models():
            payload = {
                "model": model,
                "messages": oai_msgs,
                "max_tokens": max_tokens,
                "stream": False,
                **_nim_extras(model),
            }
            try:
                r = client.post(NVIDIA_URL, headers=headers, json=payload)
            except httpx.HTTPError as e:
                last = f"nvidia {model}: {type(e).__name__}"
                log.warning(last)
                continue
            if r.status_code >= 400:
                last = f"nvidia {model}: HTTP {r.status_code}: {(r.text or '')[:120]}"
                log.warning(last)
                continue
            text = _message_text(r.json())
            if text:
                log.info(f"llm_cascade: nvidia {model} ok ({len(text)} chars)")
                return text
            last = f"nvidia {model}: empty output"
            log.warning(last)
    raise RuntimeError(last)


def _openrouter_complete(oai_msgs: List[Dict], max_tokens: int) -> str:
    key = _env("OPENROUTER_API_KEY")
    model = _openrouter_model()
    payload = {"model": model, "messages": oai_msgs, "max_tokens": max_tokens}
    with httpx.Client(timeout=_TIMEOUT) as client:
        r = client.post(OPENROUTER_URL, headers=_openrouter_headers(key), json=payload)
    if r.status_code >= 400:
        raise RuntimeError(f"openrouter {model}: HTTP {r.status_code}: {(r.text or '')[:120]}")
    text = _message_text(r.json())
    if not text:
        raise RuntimeError(f"openrouter {model}: empty output")
    log.info(f"llm_cascade: openrouter {model} ok ({len(text)} chars)")
    return text


def _claude_complete(user_msgs: List[Dict], system: str, max_tokens: int) -> str:
    from anthropic import Anthropic

    client = Anthropic(api_key=_env("ANTHROPIC_API_KEY"))
    kwargs = {
        "model": _anthropic_model(),
        "max_tokens": max_tokens,
        "messages": user_msgs,
    }
    if system:
        kwargs["system"] = system
    message = client.messages.create(**kwargs)
    text = (message.content[0].text or "").strip()
    if not text:
        raise RuntimeError("claude: empty output")
    log.info(f"llm_cascade: claude {kwargs['model']} ok ({len(text)} chars)")
    return text


def complete(
    prompt: str = "",
    system: str = "",
    messages: Optional[List[Dict]] = None,
    max_tokens: int = 1024,
) -> Tuple[str, str]:
    """Complétion texte via la cascade NIM → OpenRouter → Claude.

    Args:
        prompt   — dernier message utilisateur (optionnel si `messages` fourni)
        system   — prompt système (optionnel)
        messages — historique [{role, content}] au format OpenAI (optionnel)

    Returns:
        (texte, provider) — provider ∈ {"nvidia", "openrouter", "claude"}.
        ("", "none") si aucun fournisseur n'est disponible ou si tout échoue.
    """
    user_msgs = _user_messages(prompt, messages)
    if not user_msgs:
        return "", "none"
    oai_msgs = _with_system(system, user_msgs)

    if _env("NVIDIA_API_KEY"):
        try:
            return _nvidia_complete(oai_msgs, max_tokens), "nvidia"
        except Exception as e:
            log.warning(f"llm_cascade: nvidia épuisé ({e}) → openrouter")
    if _env("OPENROUTER_API_KEY"):
        try:
            return _openrouter_complete(oai_msgs, max_tokens), "openrouter"
        except Exception as e:
            log.warning(f"llm_cascade: openrouter échec ({e}) → claude")
    if _env("ANTHROPIC_API_KEY"):
        try:
            return _claude_complete(user_msgs, system, max_tokens), "claude"
        except Exception as e:
            log.warning(f"llm_cascade: claude échec ({e}) — cascade épuisée")
    return "", "none"


# ──────────────────────────────────────────────────────────────────────────────
# Streaming asynchrone (endpoints SSE token-par-token)
# ──────────────────────────────────────────────────────────────────────────────

async def _openai_sse(url: str, headers: Dict[str, str], payload: Dict) -> AsyncIterator[str]:
    """Flux SSE chat/completions OpenAI-compatible → jetons de texte."""
    async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as r:
            if r.status_code >= 400:
                await r.aread()
                raise RuntimeError(f"HTTP {r.status_code}: {(r.text or '')[:120]}")
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    delta = (json.loads(data).get("choices") or [{}])[0].get("delta") or {}
                except Exception:
                    continue
                token = delta.get("content") or ""
                if token:
                    yield token


async def stream(
    prompt: str,
    system: str = "",
    max_tokens: int = 1024,
) -> AsyncIterator[str]:
    """Flux de jetons via la cascade NIM → OpenRouter → Claude.

    Tant qu'aucun jeton n'a été émis, un échec passe au modèle/fournisseur
    suivant. Une rupture après le premier jeton arrête le flux (l'appelant
    gère déjà ce cas via son fallback « aucun contenu »).
    """
    oai_msgs = _with_system(system, [{"role": "user", "content": prompt}])

    candidates = []
    if _env("NVIDIA_API_KEY"):
        key = _env("NVIDIA_API_KEY")
        headers = {"Authorization": f"Bearer {key}", "Accept": "text/event-stream"}
        for model in _nvidia_models():
            payload = {
                "model": model,
                "messages": oai_msgs,
                "max_tokens": max_tokens,
                "stream": True,
                **_nim_extras(model),
            }
            candidates.append(("nvidia", model, NVIDIA_URL, headers, payload))
    if _env("OPENROUTER_API_KEY"):
        model = _openrouter_model()
        payload = {"model": model, "messages": oai_msgs, "max_tokens": max_tokens, "stream": True}
        candidates.append(
            ("openrouter", model, OPENROUTER_URL, _openrouter_headers(_env("OPENROUTER_API_KEY")), payload)
        )

    for provider, model, url, headers, payload in candidates:
        emitted = False
        try:
            async for token in _openai_sse(url, headers, payload):
                if not emitted:
                    log.info(f"llm_cascade: stream via {provider} {model}")
                emitted = True
                yield token
        except Exception as e:
            if emitted:
                log.warning(f"llm_cascade: flux {provider} {model} rompu ({e})")
                return
            log.warning(f"llm_cascade: stream {provider} {model}: {e} → suivant")
            continue
        if emitted:
            return

    if _env("ANTHROPIC_API_KEY"):
        try:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=_env("ANTHROPIC_API_KEY"))
            kwargs = {
                "model": _anthropic_model(),
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                kwargs["system"] = system
            log.info(f"llm_cascade: stream via claude {kwargs['model']}")
            async with client.messages.stream(**kwargs) as s:
                async for token in s.text_stream:
                    yield token
        except Exception as e:
            log.warning(f"llm_cascade: stream claude échec ({e}) — cascade épuisée")
            return
