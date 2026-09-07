"""Catalogue des règles modulables — résolution, snapshot, lecture.

Un chiffre n'est pas une opinion. Il est soit une loi (contrat), soit une
mesure (phénomène physique), soit une calibration (jeu étiqueté), soit un
budget (quota opérateur). Le catalogue (`data/run_rules.json`) porte le
défaut, l'intervalle et le principe. Un run peut déplacer une règle
*dans* l'intervalle ; le snapshot fige ce qui a vraiment été utilisé.

Ordre de résolution : override de run > profil > settings Mongo > défaut.
Les règles `kind=loi` sont consignées mais refusent toute surcharge.
"""
from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.config import DATA_DIR

CATALOG_FILE = DATA_DIR / "run_rules.json"

_catalog_cache: dict | None = None
_current: ContextVar[dict | None] = ContextVar("run_rules_snapshot", default=None)

MODES = ("projects", "formalities", "marinas", "shared")
KINDS = ("loi", "geometrie", "score", "budget")


class RuleError(ValueError):
    """Surcharge hors intervalle, loi touchée, ou identifiant inconnu."""


def catalog_path() -> Path:
    return CATALOG_FILE


def load_catalog(*, force: bool = False) -> dict:
    global _catalog_cache
    if _catalog_cache is None or force:
        with CATALOG_FILE.open(encoding="utf-8") as fh:
            _catalog_cache = json.load(fh)
        _validate_catalog(_catalog_cache)
    return _catalog_cache


def _validate_catalog(cat: dict) -> None:
    rules = cat.get("rules")
    if not isinstance(rules, list) or not rules:
        raise RuleError("catalogue vide ou invalide")
    seen: set[str] = set()
    for rule in rules:
        rid = rule.get("id")
        if not rid or rid in seen:
            raise RuleError(f"règle sans id ou doublon: {rid}")
        seen.add(rid)
        if rule.get("mode") not in MODES:
            raise RuleError(f"{rid}: mode inconnu {rule.get('mode')}")
        if rule.get("kind") not in KINDS:
            raise RuleError(f"{rid}: kind inconnu {rule.get('kind')}")
        if rule.get("kind") != "loi":
            _assert_in_interval(rid, rule.get("value"), rule.get("interval"))


def reload_catalog() -> dict:
    return load_catalog(force=True)


def all_rules() -> list[dict]:
    return list(load_catalog()["rules"])


def get_rule_def(rule_id: str) -> dict:
    for rule in all_rules():
        if rule["id"] == rule_id:
            return rule
    raise RuleError(f"règle inconnue: {rule_id}")


def catalog_default(rule_id: str, fallback: Any = None) -> Any:
    try:
        return deepcopy(get_rule_def(rule_id)["value"])
    except RuleError:
        return fallback


def rules_for_mode(mode: str | None = None, *, include_shared: bool = True) -> list[dict]:
    """Règles d'un mode (+ shared). `mode=None` → tout le catalogue."""
    if mode and mode not in ("projects", "formalities", "marinas"):
        raise RuleError(f"mode inconnu: {mode}")
    out = []
    for rule in all_rules():
        if mode is None or rule["mode"] == mode or (include_shared and rule["mode"] == "shared"):
            out.append(rule)
    return out


def profiles() -> dict:
    return dict(load_catalog().get("profiles") or {})


def _assert_in_interval(rule_id: str, value: Any, interval: Any) -> None:
    if interval is None or value is None:
        return
    if isinstance(value, bool):
        return
    if not isinstance(interval, (list, tuple)) or len(interval) != 2:
        raise RuleError(f"{rule_id}: intervalle invalide")
    lo, hi = interval
    if isinstance(value, (int, float)) and isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
        if value < lo or value > hi:
            raise RuleError(f"{rule_id}: {value} hors intervalle [{lo}, {hi}]")


def _coerce(rule: dict, raw: Any) -> Any:
    sample = rule.get("value")
    if isinstance(sample, bool):
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.lower() in ("true", "1", "yes", "oui"):
            return True
        if isinstance(raw, str) and raw.lower() in ("false", "0", "no", "non"):
            return False
        raise RuleError(f"{rule['id']}: booléen attendu")
    if isinstance(sample, int) and not isinstance(sample, bool):
        return int(raw)
    if isinstance(sample, float):
        return float(raw)
    if isinstance(sample, str):
        return str(raw)
    return raw


def _source_and_value(rule: dict, settings: dict, profile_vals: dict, overrides: dict) -> tuple[Any, str]:
    rid = rule["id"]
    if rule.get("kind") == "loi" or rule.get("vary") is False:
        if rid in overrides:
            raise RuleError(f"{rid}: règle de loi / non modulable")
        return deepcopy(rule["value"]), "loi" if rule.get("kind") == "loi" else "catalog"
    if rid in overrides:
        val = _coerce(rule, overrides[rid])
        _assert_in_interval(rid, val, rule.get("interval"))
        return val, "override"
    if rid in profile_vals:
        val = _coerce(rule, profile_vals[rid])
        _assert_in_interval(rid, val, rule.get("interval"))
        return val, "profile"
    sk = rule.get("settings_key")
    if sk and settings and settings.get(sk) is not None:
        val = _coerce(rule, settings[sk])
        _assert_in_interval(rid, val, rule.get("interval"))
        return val, "settings"
    return deepcopy(rule["value"]), "catalog"


def resolve_rules(*, mode: str | None = None, settings: dict | None = None,
                  overrides: dict | None = None, profile: str | None = None,
                  include_shared: bool = True) -> dict:
    """Résout les valeurs effectives pour un mode (ou tout le catalogue)."""
    cat = load_catalog()
    settings = settings or {}
    overrides = dict(overrides or {})
    profile_name = profile or "cdc_default"
    known = profiles()
    if profile_name not in known:
        raise RuleError(f"profil inconnu: {profile_name}")
    profile_vals = dict(known[profile_name].get("overrides") or {})

    unknown = [k for k in overrides if k not in {r["id"] for r in all_rules()}]
    if unknown:
        raise RuleError(f"règles inconnues: {', '.join(sorted(unknown))}")

    chosen: dict[str, dict] = {}
    for rule in rules_for_mode(mode, include_shared=include_shared):
        value, source = _source_and_value(rule, settings, profile_vals, overrides)
        chosen[rule["id"]] = {
            "value": value,
            "unit": rule.get("unit"),
            "kind": rule["kind"],
            "source": source,
            "vary": bool(rule.get("vary")),
            "interval": rule.get("interval"),
            "principle": rule.get("principle"),
            "cdc": rule.get("cdc"),
        }
    return {
        "catalog_version": cat.get("version"),
        "profile": profile_name,
        "mode": mode,
        "chosen": chosen,
        "overrides": {k: overrides[k] for k in overrides if k in chosen},
    }


def rules_hash(chosen: dict) -> str:
    """Empreinte stable des valeurs (sans principes ni secrets)."""
    payload = {k: chosen[k]["value"] for k in sorted(chosen)}
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def snapshot_for_run(*, mode: str | None, settings: dict | None = None,
                     overrides: dict | None = None, profile: str | None = None) -> dict:
    """Snapshot consignable dans `params.rules` — aucun secret."""
    resolved = resolve_rules(mode=mode, settings=settings,
                             overrides=overrides, profile=profile)
    chosen = resolved["chosen"]
    resolved["hash"] = rules_hash(chosen)
    resolved["counts"] = {
        "total": len(chosen),
        "overridden": sum(1 for c in chosen.values() if c["source"] == "override"),
        "from_profile": sum(1 for c in chosen.values() if c["source"] == "profile"),
        "from_settings": sum(1 for c in chosen.values() if c["source"] == "settings"),
        "loi": sum(1 for c in chosen.values() if c["kind"] == "loi"),
    }
    return resolved


def public_catalog(mode: str | None = None) -> dict:
    """Vue API : principe + profils + règles (sans secrets)."""
    cat = load_catalog()
    return {
        "version": cat.get("version"),
        "updated": cat.get("updated"),
        "principle": cat.get("principle"),
        "kinds": cat.get("kinds"),
        "profiles": {
            name: {
                "label": spec.get("label"),
                "overrides": spec.get("overrides") or {},
            }
            for name, spec in profiles().items()
        },
        "rules": [
            {
                "id": r["id"],
                "mode": r["mode"],
                "kind": r["kind"],
                "value": r["value"],
                "unit": r.get("unit"),
                "interval": r.get("interval"),
                "vary": bool(r.get("vary")),
                "settings_key": r.get("settings_key"),
                "principle": r.get("principle"),
                "cdc": r.get("cdc"),
                "code": r.get("code") or [],
                "legacy": bool(r.get("legacy")),
            }
            for r in rules_for_mode(mode)
        ],
    }


def bind_rules(snapshot: dict | None):
    """Active le snapshot pour le thread/async context courant."""
    return _current.set(snapshot)


def reset_rules(token) -> None:
    _current.reset(token)


def current_snapshot() -> dict | None:
    return _current.get()


def get_rule(rule_id: str, fallback: Any = None) -> Any:
    """Valeur effective : snapshot du run s'il existe, sinon défaut catalogue."""
    snap = _current.get()
    if snap:
        chosen = snap.get("chosen") or {}
        if rule_id in chosen:
            return chosen[rule_id]["value"]
    return catalog_default(rule_id, fallback)


def attach_rules(params: dict, snapshot: dict) -> dict:
    """Pose le snapshot sous `params.rules` sans écraser `code` / variant."""
    out = dict(params)
    out["rules"] = snapshot
    return out
