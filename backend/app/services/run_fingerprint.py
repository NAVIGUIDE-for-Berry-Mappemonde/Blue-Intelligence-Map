"""Empreinte code d'un run PoE — relie poe_runs.params à un commit et des flags.

Aucun secret : seulement des booléens / SHA / plafonds. Les runs déjà
terminés ne sont pas rétro-étiquetés.
"""
from __future__ import annotations

import importlib
import os
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _module_has(mod: str, name: str) -> bool:
    try:
        m = importlib.import_module(mod)
        return hasattr(m, name)
    except Exception:
        return False


def git_state(cwd: Path | None = None) -> tuple[str | None, bool | None]:
    """Retourne (sha, dirty). (None, None) si git est indisponible."""
    root = str(cwd or _REPO_ROOT)
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root, stderr=subprocess.DEVNULL, text=True, timeout=3,
        ).strip()
    except Exception:
        return None, None
    try:
        dirty_out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=root, stderr=subprocess.DEVNULL, text=True, timeout=3,
        )
        dirty = bool(dirty_out.strip())
    except Exception:
        dirty = None
    return sha or None, dirty


def _key_configured(*candidates: str) -> bool:
    return any(bool((c or "").strip()) for c in candidates)


def build_code_fingerprint(settings: dict | None = None,
                           zone_timeout_s: int | None = None) -> dict:
    """Snapshot du code et des flags (pas des secrets) au moment du run."""
    from app.core import claude

    s = settings or {}
    sha, dirty = git_state()
    timeout = 900 if zone_timeout_s is None else zone_timeout_s

    env_or = os.environ.get("OPENROUTER_API_KEY") or ""
    env_tf = os.environ.get("TINYFISH_API_KEY") or ""
    env_searx = (os.environ.get("SEARXNG_URL") or "").strip().rstrip("/") or None

    return {
        "git_sha": sha,
        "git_dirty": dirty,
        "claude_enabled": claude.claude_enabled(s),
        "claude_allows_call": claude.budget_allows_call(s),
        "claude_model": claude.CLAUDE_MODEL,
        "claude_budget_usd": claude.get_claude_budget_usd(s),
        "openrouter_configured": _key_configured(
            s.get("openrouter_api_key"), env_or),
        "tinyfish_configured": _key_configured(
            s.get("tinyfish_api_key"), env_tf),
        "searxng_url": env_searx,
        "catalog_skip": True,
        "zone_timeout_s": timeout,
        "features": {
            "p0_pdf_isolated": _module_has("app.core.pdf_worker", "extract_pdf_file"),
            "p0_geocode_cache": _module_has("app.core.geo", "geocode_cache_id"),
            "p0_exceptions_lock": _module_has(
                "app.services.poe_pipeline", "save_exceptions"),
            "listing_control": _module_has(
                "app.services.listing_control", "compare_to_listing"),
            "claude_adapter": _module_has("app.core.claude", "extract_ports_claude"),
            "haiku_source_coords": _module_has("app.core.llm", "coords_appear_in_text"),
            "geocode_name_veto": _module_has("app.core.extract", "is_geocodeable_name"),
            "haiku_geocode_tiebreak": _module_has(
                "app.core.claude", "arbitrate_geocode_claude"),
            "seed_union": _module_has("app.services.poe_seeds", "build_seed_union"),
            "seed_verify": _module_has("app.services.poe_seeds", "verdict_for_seed"),
            "seed_osm": _module_has("app.services.osm_seeds", "refresh_osm_cache"),
            "seed_enrich": _module_has("app.services.poe_seed_enrich", "execute_enrich"),
            "tinyfish_poe_agent": _module_has("app.core.tinyfish", "tf_poe_agent"),
            "claude_sonnet_judge": _module_has("app.core.claude", "complete_json_claude"),
        },
    }


def merge_run_params(base: dict, fingerprint: dict) -> dict:
    """Fusionne l'empreinte sous params.code sans écraser variant / label."""
    out = dict(base)
    out["code"] = fingerprint
    return out


def resume_params(existing: dict, current_fingerprint: dict) -> dict:
    """Garde l'empreinte d'origine ; note le SHA de reprise s'il diffère."""
    params = dict(existing or {})
    orig = params.get("code") if isinstance(params.get("code"), dict) else {}
    orig_sha = orig.get("git_sha")
    now_sha = current_fingerprint.get("git_sha")
    params["resumed"] = True
    if orig_sha and now_sha and orig_sha != now_sha:
        params["resume_git_sha"] = now_sha
    elif not orig:
        params["code"] = current_fingerprint
    return params
