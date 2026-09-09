"""Oui ou non : un branchement LLM, trois prompts.

Porte d'entrée : ``ask_yes_no``. Même question technique partout
(« j'accepte ou je refuse, éventuellement cette URL parmi les
candidates, voici pourquoi »). Les textes de prompt et les rôles
NVIDIA restent propres à chaque mode. On n'écrit pas un juge
« projet ou port ou aire protégée ». Une URL hors liste n'est
jamais retenue.

Chaîne d'appel (un seul endroit à corriger) :

  1. NVIDIA NIM (chaîne du ``role``)
  2. OpenRouter
  3. Claude (Haiku, puis Sonnet seulement si le caller le demande)

Le hop listing / inconclusive du bottom-up n'est pas un second métier :
c'est le même câble, avec ``hop_if`` pour essayer le modèle NIM suivant
ou Sonnet. Les questions « projet marin ? », « port plaisance ? »,
« quelle URL de visite déjà trouvée ? » restent trois prompts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence
from urllib.parse import urlparse

LogFn = Callable[[str], None]
HopFn = Callable[["YesNo"], bool]
UrlKeyFn = Callable[[str], str | None]

_TRUE = {"true", "1", "yes", "y", "oui", "vrai"}
_FALSE = {"false", "0", "no", "non", "n", "faux"}
_NULL_URL = {"", "null", "none", "n/a", "-", "undefined"}


@dataclass(frozen=True)
class YesNo:
    """Réponse normalisée. ``raw`` garde le JSON métier du spécialiste."""

    accepted: bool | None
    url: str | None
    reason: str
    engine: str
    raw: dict = field(default_factory=dict)


def as_bool(value: Any) -> bool | None:
    """True / False / None. ``bool("false")`` Python n'est pas un juge."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        low = value.strip().lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
    return None


def as_confidence(raw) -> int:
    """0-100. Les NIM renvoient souvent 0.9 au lieu de 90."""
    if raw is None or raw == "":
        return 0
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return 0
    if 0 < val <= 1:
        val *= 100
    return max(0, min(100, int(round(val))))


def normalize_listed_url(url: str | None) -> str | None:
    """Clé de comparaison : schéma, hôte sans www, chemin sans slash final."""
    raw = (url or "").strip()
    if not raw or raw.lower() in _NULL_URL:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    host = (parsed.netloc or "").lower()
    if not host:
        return None
    if host.startswith("www."):
        host = host[4:]
    path = (parsed.path or "").rstrip("/")
    return f"{(parsed.scheme or 'https').lower()}://{host}{path}"


def listed_url(
    raw,
    allowed: Sequence | None,
    *,
    key: UrlKeyFn | None = None,
) -> str | None:
    """Retourne l'URL candidate originale, ou None si hors liste / inventée."""
    if allowed is None:
        return None
    blob = ("" if raw is None else str(raw)).strip()
    if blob.lower() in _NULL_URL:
        return None
    norm = key or normalize_listed_url
    wanted: dict[str, str] = {}
    for item in allowed:
        url = item.get("url") if isinstance(item, dict) else item
        if not url:
            continue
        token = norm(str(url))
        if token and token not in wanted:
            wanted[token] = str(url).strip()
    got = norm(blob)
    if not got:
        return None
    return wanted.get(got)


def claude_engine_label(model: str | None) -> str:
    blob = (model or "").lower()
    if "sonnet" in blob:
        return "claude-sonnet"
    if "haiku" in blob:
        return "claude-haiku"
    return "claude"


def parse_yes_no(
    data: dict | None,
    *,
    engine: str = "",
    allowed_urls: Sequence | None = None,
    forbidden_urls: Sequence[str] | None = None,
    url_key: UrlKeyFn | None = None,
) -> YesNo:
    """``accept`` / ``is_poe`` / ``marine`` → accepted. URL seulement si listée."""
    data = data if isinstance(data, dict) else {}
    accepted: bool | None = None
    for field_name in ("accept", "is_poe", "marine"):
        if field_name in data:
            accepted = as_bool(data.get(field_name))
            break
    reason = str(data.get("reason") or "")[:300]
    url = None
    if allowed_urls is not None:
        url = listed_url(data.get("url"), allowed_urls, key=url_key)
        if url and forbidden_urls:
            banned = {
                (url_key or normalize_listed_url)(u)
                for u in forbidden_urls
                if u
            }
            token = (url_key or normalize_listed_url)(url)
            if token and token in banned:
                url = None
        if accepted is True and not url:
            accepted = False
            if not reason:
                reason = "url not in candidates"
    return YesNo(
        accepted=accepted,
        url=url,
        reason=reason,
        engine=engine,
        raw=data,
    )


def empty_yes_no(reason: str = "llm_error", engine: str = "") -> YesNo:
    return YesNo(
        accepted=None,
        url=None,
        reason=reason,
        engine=engine,
        raw={"reason": reason},
    )


async def complete_json_cascade(
    system: str,
    prompt: str,
    settings: dict | None = None,
    *,
    role: str = "json",
    max_tokens: int = 400,
    log: LogFn | None = None,
    nvidia_model: str | None = None,
    nvidia_fallback: bool = True,
    claude_model: str | None = None,
    claude_max_tokens: int | None = None,
    openrouter_max_tokens: int | None = None,
) -> tuple[dict, str]:
    """NVIDIA → OpenRouter → Claude. Un branchement pour JSON strict."""
    from app.core import claude, llm, nvidia

    last: Exception | None = None
    nv_tokens = int(max_tokens)
    or_tokens = int(openrouter_max_tokens if openrouter_max_tokens is not None else max_tokens)
    cl_tokens = int(
        claude_max_tokens if claude_max_tokens is not None else min(int(max_tokens), 800)
    )
    if nvidia.nvidia_enabled(settings):
        try:
            data, used = await nvidia.complete_json_nvidia_tracked(
                system, prompt, settings, max_tokens=nv_tokens, log=log,
                role=role, model=nvidia_model, fallback=nvidia_fallback)
            return data, nvidia.engine_label(used)
        except Exception as e:
            last = e
            if log:
                log(f"nvidia JSON épuisé: {str(e)[:120]}")
    if llm.get_llm_key(settings):
        try:
            data = await llm._json_openrouter(prompt, system, settings, or_tokens)
            return data, "openrouter"
        except Exception as e:
            last = e
            if log:
                log(f"openrouter JSON: {str(e)[:120]}")
    if claude.claude_enabled(settings) and claude.budget_allows_call(settings):
        try:
            data = await claude.complete_json_claude(
                system, prompt, settings,
                model=claude_model,
                max_tokens=cl_tokens, log=log)
            return data, claude_engine_label(claude_model or claude.CLAUDE_HAIKU_MODEL)
        except Exception as e:
            last = e
            if log:
                log(f"claude JSON (dernier): {str(e)[:120]}")
    if last:
        raise last
    raise RuntimeError("no LLM backend")


async def _nvidia_one(
    system: str,
    prompt: str,
    settings: dict | None,
    *,
    model: str,
    role: str,
    max_tokens: int,
    log: LogFn | None,
) -> YesNo | None:
    from app.core import nvidia

    try:
        parsed = await nvidia.complete_json_nvidia(
            system, prompt, settings, model=model, max_tokens=max_tokens,
            log=log, role=role, fallback=False)
        return parse_yes_no(parsed, engine=nvidia.engine_label(model))
    except Exception as e:
        if log:
            log(f"NVIDIA {nvidia.engine_label(model)}: {type(e).__name__}: {str(e)[:80]}")
        return None


async def _nvidia_hop(
    system: str,
    prompt: str,
    settings: dict | None,
    *,
    role: str,
    max_tokens: int,
    log: LogFn | None,
    hop_if: HopFn,
    parse_kwargs: dict,
) -> YesNo | None:
    from app.core import nvidia

    tried: list[str] = []
    last: YesNo | None = None
    chain = nvidia.models_for(role)
    for model in chain:
        if model in tried:
            continue
        tried.append(model)
        extra = await _nvidia_one(
            system, prompt, settings, model=model, role=role,
            max_tokens=max_tokens, log=log)
        if extra is None:
            continue
        extra = parse_yes_no(extra.raw, engine=extra.engine, **parse_kwargs)
        last = extra
        if not hop_if(extra):
            return extra
        for nxt in chain:
            if nxt in tried:
                continue
            tried.append(nxt)
            alt = await _nvidia_one(
                system, prompt, settings, model=nxt, role=role,
                max_tokens=max_tokens, log=log)
            if alt is not None:
                return parse_yes_no(alt.raw, engine=alt.engine, **parse_kwargs)
        return extra
    return last


async def ask_yes_no(
    system: str,
    prompt: str,
    *,
    settings: dict | None = None,
    log: LogFn | None = None,
    role: str = "json",
    max_tokens: int = 400,
    nvidia_max_tokens: int | None = None,
    openrouter_max_tokens: int | None = None,
    claude_max_tokens: int | None = None,
    allowed_urls: Sequence | None = None,
    forbidden_urls: Sequence[str] | None = None,
    url_key: UrlKeyFn | None = None,
    hop_if: HopFn | None = None,
    claude_models: Sequence[str] | None = None,
    on_empty: str = "raise",
) -> YesNo:
    """Envoie un prompt, reçoit un YesNo. Un câble, pas un juge unique.

    ``on_empty`` : ``raise`` (gatekeeper → heuristique) ou ``inconclusive``
    (bottom-up / AMP : pas d'invention).
    """
    from app.core import claude, llm

    parse_kwargs = dict(
        allowed_urls=allowed_urls,
        forbidden_urls=forbidden_urls,
        url_key=url_key,
    )
    nv_tokens = int(nvidia_max_tokens if nvidia_max_tokens is not None else max_tokens)
    or_tokens = int(openrouter_max_tokens if openrouter_max_tokens is not None else max_tokens)
    cl_tokens = int(claude_max_tokens if claude_max_tokens is not None else min(int(max_tokens), 800))
    last_err: Exception | None = None

    if hop_if is not None:
        from app.core import nvidia
        if nvidia.nvidia_enabled(settings):
            hopped = await _nvidia_hop(
                system, prompt, settings, role=role, max_tokens=nv_tokens,
                log=log, hop_if=hop_if, parse_kwargs=parse_kwargs)
            if hopped is not None:
                return hopped
    else:
        try:
            data, engine = await complete_json_cascade(
                system, prompt, settings, role=role, max_tokens=nv_tokens,
                log=log, openrouter_max_tokens=or_tokens,
                claude_max_tokens=cl_tokens)
            return parse_yes_no(data, engine=engine, **parse_kwargs)
        except Exception as e:
            if on_empty == "raise":
                raise
            last_err = e
            if log:
                log(f"juge: {type(e).__name__}: {str(e)[:80]}")
            return empty_yes_no()

    # Hop : NVIDIA n'a pas tranché (ou pas de clé). OpenRouter, puis Claude.
    or_result: YesNo | None = None
    if llm.get_llm_key(settings):
        try:
            data = await llm._json_openrouter(prompt, system, settings, or_tokens)
            or_result = parse_yes_no(data, engine="openrouter", **parse_kwargs)
            # Décision nette : on ne passe pas à Claude (listing y compris).
            if or_result.accepted is not None:
                return or_result
        except Exception as e:
            last_err = e
            if log:
                log(f"OpenRouter juge: {type(e).__name__}: {str(e)[:80]}")

    result = or_result
    models = list(claude_models or (claude.CLAUDE_HAIKU_MODEL,))
    for model in models:
        if result is not None and hop_if is not None and not hop_if(result):
            return result
        if not (claude.claude_enabled(settings) and claude.budget_allows_call(settings)):
            break
        try:
            parsed = await claude.complete_json_claude(
                system, prompt, settings, model=model, max_tokens=cl_tokens,
                log=log)
            result = parse_yes_no(
                parsed, engine=claude_engine_label(model), **parse_kwargs)
        except Exception as e:
            last_err = e
            if log:
                log(f"Claude {claude_engine_label(model)}: {type(e).__name__}: {str(e)[:80]}")
    if result is not None:
        return result
    if on_empty == "raise":
        if last_err:
            raise last_err
        raise RuntimeError("no LLM backend")
    return empty_yes_no()
