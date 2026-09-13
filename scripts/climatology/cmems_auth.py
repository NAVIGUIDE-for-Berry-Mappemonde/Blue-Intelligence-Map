"""Charge COPERNICUS_* depuis l'environnement et les .env gitignorés.

Ne jamais imprimer le mot de passe. Les scripts de génération passent
username/password à ``copernicusmarine.open_dataset``.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_ENV_FILES = (
    ROOT / "backend" / ".env",
    ROOT / "naviguide" / "naviguide-api" / ".env",
)


def load_cmems_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None
    if load_dotenv is not None:
        for path in _ENV_FILES:
            if path.is_file():
                load_dotenv(path, override=False)
        return
    for path in _ENV_FILES:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            os.environ.setdefault(key, value)


def credentials() -> tuple[str, str]:
    load_cmems_env()
    user = (
        os.environ.get("COPERNICUS_USERNAME")
        or os.environ.get("COPERNICUS_USER")
        or os.environ.get("COPERNICUSMARINE_SERVICE_USERNAME")
        or ""
    ).strip()
    password = (
        os.environ.get("COPERNICUS_PASSWORD")
        or os.environ.get("COPERNICUSMARINE_SERVICE_PASSWORD")
        or ""
    ).strip()
    if not user or not password:
        raise SystemExit(
            "COPERNICUS_USERNAME et COPERNICUS_PASSWORD manquent. "
            "À mettre dans backend/.env (fichier non commité) ou dans l'environnement."
        )
    return user, password


def login() -> bool:
    user, password = credentials()
    import copernicusmarine

    os.environ.setdefault("COPERNICUSMARINE_SERVICE_USERNAME", user)
    os.environ.setdefault("COPERNICUSMARINE_SERVICE_PASSWORD", password)
    return bool(
        copernicusmarine.login(
            username=user,
            password=password,
            force_overwrite=True,
        )
    )


def open_dataset(**kwargs):
    user, password = credentials()
    import copernicusmarine

    kwargs.setdefault("username", user)
    kwargs.setdefault("password", password)
    return copernicusmarine.open_dataset(**kwargs)
