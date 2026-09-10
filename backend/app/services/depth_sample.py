"""Profondeur d'approche — sondage ponctuel EMODnet Bathymetry.

``GET https://rest.emodnet-bathymetry.eu/depth_sample?geom=POINT(lon lat)``
renvoie le DTM (champ ``avg``, mètres). Convention mixte observée : une
valeur positive est une profondeur sous le niveau de la mer, une valeur
négative est une altitude DTM (on prend l'opposé).

Cache Mongo ``depth_samples`` (clé lat/lon arrondis à 4 décimales, ~11 m)
en upsert non destructif — le DTM ne bouge pas d'un jour à l'autre.
Les échecs réseau ne sont pas mis en cache, pour pouvoir réessayer.
"""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import httpx

from app.services.marina_build import USER_AGENT
from app.services.science_build import now_iso

DEPTH_URL = "https://rest.emodnet-bathymetry.eu/depth_sample"
SOURCE = "emodnet-bathymetry"
DECIMALS = 4
# Au-dessous de ce seuil (m), on considère le point émergé / estran.
DRY_M = 0.3

FetchDepth = Callable[[float, float], Awaitable[dict]]


def cache_key(lat: float, lon: float) -> str:
    return f"{lon:.{DECIMALS}f}:{lat:.{DECIMALS}f}"


def depth_from_emodnet(payload: dict | None) -> dict:
    """Interprète la réponse JSON ``depth_sample`` → profondeur positive sous NM."""
    if not isinstance(payload, dict) or payload.get("avg") is None:
        return {"depth_m": None, "on_land": None, "raw": None}
    try:
        raw = float(payload["avg"])
    except (TypeError, ValueError):
        return {"depth_m": None, "on_land": None, "raw": None}
    if raw >= 0:
        depth_m = raw
        on_land = raw < DRY_M
    else:
        depth_m = -raw
        on_land = False
    return {
        "depth_m": round(depth_m, 1),
        "on_land": bool(on_land),
        "raw": raw,
    }


async def fetch_emodnet_depth(lat: float, lon: float, client: httpx.AsyncClient | None = None) -> dict:
    geom = f"POINT({lon} {lat})"
    own = client is None
    http = client or httpx.AsyncClient(headers={"User-Agent": USER_AGENT})
    try:
        r = await http.get(
            DEPTH_URL,
            params={"geom": geom},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, dict) else {}
    finally:
        if own:
            await http.aclose()


def _public(doc: dict, *, cached: bool) -> dict:
    return {
        "lat": doc.get("lat"),
        "lon": doc.get("lon"),
        "depth_m": doc.get("depth_m"),
        "on_land": doc.get("on_land"),
        "source": SOURCE,
        "cached": cached,
    }


async def sample_depth(
    coll,
    lat: float,
    lon: float,
    *,
    fetch: Optional[FetchDepth] = None,
) -> dict:
    """Sondage (cache d'abord, sinon EMODnet). Jamais d'exception vers l'API."""
    key = cache_key(lat, lon)
    rlat, rlon = round(lat, DECIMALS), round(lon, DECIMALS)
    try:
        existing = await coll.find_one({"_id": key})
    except Exception:
        existing = None
    if existing and existing.get("depth_m") is not None:
        return _public(existing, cached=True)
    try:
        payload = await (fetch or fetch_emodnet_depth)(lat, lon)
        parsed = depth_from_emodnet(payload)
    except Exception as exc:
        return {
            "lat": rlat, "lon": rlon, "depth_m": None, "on_land": None,
            "source": SOURCE, "cached": False,
            "error": f"{type(exc).__name__}: {str(exc)[:120]}",
        }
    if parsed["depth_m"] is None:
        return {
            "lat": rlat, "lon": rlon, "depth_m": None, "on_land": None,
            "source": SOURCE, "cached": False,
        }
    doc = {
        "_id": key,
        "lat": rlat,
        "lon": rlon,
        "depth_m": parsed["depth_m"],
        "on_land": parsed["on_land"],
        "raw": parsed["raw"],
        "source": SOURCE,
        "fetched_at": now_iso(),
    }
    try:
        await coll.update_one({"_id": key}, {"$set": doc}, upsert=True)
    except Exception:
        pass
    return _public(doc, cached=False)
