#!/usr/bin/env python3
"""Aligne backend/.env sur les secrets du process (Atlas, NIM).

Le fichier est gitignoré. On ne logue jamais les valeurs — seulement les
hôtes (localhost vs Atlas). Remplace un MONGO_URL localhost si le process
a déjà une URI mongodb.net / mongodb+srv.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

_ATLAS_MARKERS = ("mongodb.net", "mongodb+srv://")
_LOCAL_MARKERS = ("localhost", "127.0.0.1")
_KEYS = (
    "MONGO_URL",
    "DB_NAME",
    "NVIDIA_API_KEY",
    "OPENROUTER_API_KEY",
    "TINYFISH_API_KEY",
    "GEONAMES_USERNAME",
    "ANTHROPIC_API_KEY",
)


def mongo_kind(uri: str) -> str:
    u = (uri or "").strip()
    if any(m in u for m in _ATLAS_MARKERS):
        return "atlas"
    if any(m in u for m in _LOCAL_MARKERS):
        return "localhost"
    return "other" if u else "empty"


def parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        out[key] = val
    return out


def render_env(values: dict[str, str], original: str | None = None) -> str:
    """Préserve commentaires / clés inconnues ; met à jour les clés gérées."""
    managed = set(_KEYS)
    seen: set[str] = set()
    lines: list[str] = []
    if original:
        for raw in original.splitlines():
            if "=" in raw and not raw.lstrip().startswith("#"):
                key = raw.split("=", 1)[0]
                if key in managed:
                    lines.append(f"{key}={values.get(key, '')}")
                    seen.add(key)
                    continue
            lines.append(raw)
    for key in _KEYS:
        if key in seen:
            continue
        if key in values:
            lines.append(f"{key}={values[key]}")
    if lines and lines[-1] != "":
        lines.append("")
    return "\n".join(lines) if lines[-1:] == [""] else ("\n".join(lines) + "\n")


def plan_sync(file_vals: dict[str, str], proc: dict[str, str]) -> dict[str, str]:
    """Calcule le .env cible. Process Atlas gagne sur un fichier localhost."""
    out = dict(file_vals)
    proc_mongo = (proc.get("MONGO_URL") or "").strip()
    file_mongo = (out.get("MONGO_URL") or "").strip()
    if mongo_kind(proc_mongo) == "atlas" and mongo_kind(file_mongo) != "atlas":
        out["MONGO_URL"] = proc_mongo
    elif not file_mongo and proc_mongo:
        out["MONGO_URL"] = proc_mongo
    elif not file_mongo:
        out["MONGO_URL"] = "mongodb://localhost:27017"

    for key in _KEYS:
        if key == "MONGO_URL":
            continue
        pv = (proc.get(key) or "").strip()
        if pv and not (out.get(key) or "").strip():
            out[key] = pv
    return out


def sync_file(path: Path, proc: dict[str, str] | None = None) -> dict:
    env = proc if proc is not None else os.environ
    existed = path.exists()
    original = path.read_text(encoding="utf-8") if existed else ""
    before = parse_env(original)
    after = plan_sync(before, env)
    text = render_env(after, original if existed else None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    changed = [k for k in _KEYS if (before.get(k) or "") != (after.get(k) or "")]
    return {
        "created": not existed,
        "changed": changed,
        "mongo_before": mongo_kind(before.get("MONGO_URL") or ""),
        "mongo_after": mongo_kind(after.get("MONGO_URL") or ""),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--env-file", type=Path, required=True)
    args = p.parse_args()
    info = sync_file(args.env_file)
    action = "created" if info["created"] else "updated"
    keys = ",".join(info["changed"]) or "none"
    print(
        f"backend/.env {action}: mongo {info['mongo_before']} -> "
        f"{info['mongo_after']}; keys {keys}",
        flush=True,
    )


if __name__ == "__main__":
    main()
