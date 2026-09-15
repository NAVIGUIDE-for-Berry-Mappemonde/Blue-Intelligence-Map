"""Sac `ici()` — ce qu’il y a autour du bateau, pas toute la carte.

Étape 2 : ZEE (MarineRegions), PoE de cette ZEE, AMP / projets /
marinas-capit-WPI / une poignée de fiches Science dans 20–30 nm.
AMP = cache `/export/amp.geojson` (pas ProtectedSeas). Pas de Tavily,
pas de LLM.
"""
from __future__ import annotations

import asyncio
import math
import os
import re
import time
from typing import Any

import httpx

from gebco_lookup import attach_depth_offshore, reset_gebco_cache

ICI_RADIUS_NM = 30
MAX_POE = 4
MAX_AMP = 5
MAX_PROJECTS = 5
MAX_NEARBY = 3
MAX_SCIENCE = 5
EEZ_ACCEPT_NM = 240
R_NM = 3440.065

# Path-style (query LatLng has been 404 since 2026).
MRGID_LATLON_URL = "https://www.marineregions.org/rest/getGazetteerRecordsByLatLong.json"
USER_AGENT = "NAVIGUIDE-simulator/0.2 (Berry-Mappemonde expedition)"
WPI_URL = "https://msi.nga.mil/api/publications/world-port-index"

# MRGID VLIZ v12 → territoire FR (copie locale, pas d’import backend/).
FRENCH_EEZ_MRGID: dict[int, str] = {
    5677: "france_metropolitaine",
    48966: "france_metropolitaine",
    48976: "france_metropolitaine",
    8440: "polynesie_francaise",
    8312: "nouvelle_caledonie",
    48948: "nouvelle_caledonie",
    33178: "martinique",
    33177: "guadeloupe",
    48952: "saint_barthelemy",
    8495: "saint_martin",
    8462: "guyane",
    8454: "wallis_et_futuna",
    8338: "la_reunion",
    48944: "mayotte",
    8494: "saint_pierre_et_miquelon",
    48946: "taaf",
    48945: "taaf",
    8341: "taaf",
    8339: "taaf",
    8340: "taaf",
    8386: "taaf",
    8385: "taaf",
    8387: "taaf",
}

_DMS_RE = re.compile(
    r"""(\d+)\s*[°d]\s*(\d+)\s*[''′]\s*(\d+(?:\.\d+)?)\s*[""″]?\s*([NSEW]?)""",
    re.IGNORECASE,
)

_fc_cache: dict[str, dict] = {}
_FC_TTL = 3600.0
_wpi_cache: dict = {"data": None, "ts": 0.0}
_WPI_TTL = 86_400.0


def reset_caches() -> None:
    _fc_cache.clear()
    _wpi_cache["data"] = None
    _wpi_cache["ts"] = 0.0
    reset_gebco_cache()


def bi_base() -> str:
    return (os.getenv("BI_API_URL") or "http://127.0.0.1:8001/api").rstrip("/")


def empty_dossier(lat: float, lon: float, radius_nm: float = ICI_RADIUS_NM) -> dict:
    return {
        "version": 1,
        "at": {"lat": lat, "lon": lon},
        "radiusNm": radius_nm,
        "zee": None,
        "poe": [],
        "amp": [],
        "projects": [],
        "nearby": {"marinas": [], "capitaineries": [], "wpi": []},
        "marks": [],
        "science": None,
        "weather": None,
        "polar": None,
        "event": None,
        "sources": {"zee": None, "bi": None, "gebco": None},
        "depthOffshore": None,
    }


def parse_coord(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    m = _DMS_RE.search(s)
    if not m:
        return None
    deg, mins, secs, hemi = m.groups()
    decimal = float(deg) + float(mins) / 60.0 + float(secs) / 3600.0
    if hemi and hemi.upper() in ("S", "W"):
        decimal = -decimal
    return decimal


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    def rad(d: float) -> float:
        return d * math.pi / 180.0

    dlat = rad(lat2 - lat1)
    dlon = lon2 - lon1
    while dlon > 180:
        dlon -= 360
    while dlon < -180:
        dlon += 360
    dlon = rad(dlon)
    a = math.sin(dlat / 2) ** 2 + math.cos(rad(lat1)) * math.cos(rad(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * R_NM * math.asin(min(1.0, math.sqrt(a)))


def radius_bbox(lat: float, lon: float, nm: float) -> tuple[float, float, float, float]:
    dlat = nm / 60.0
    clat = max(0.2, abs(math.cos(math.radians(lat))))
    dlon = nm / (60.0 * clat)
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


def feature_latlon(feat: dict) -> tuple[float, float] | None:
    props = feat.get("properties") or {}
    plat, plon = props.get("lat"), props.get("lon")
    if isinstance(plat, (int, float)) and isinstance(plon, (int, float)):
        return float(plat), float(plon)
    geom = feat.get("geometry") or {}
    coords = geom.get("coordinates")
    kind = geom.get("type")
    if not coords:
        return None
    if kind == "Point" and len(coords) >= 2:
        return float(coords[1]), float(coords[0])

    def first_pair(node) -> tuple[float, float] | None:
        if not isinstance(node, (list, tuple)) or not node:
            return None
        if isinstance(node[0], (int, float)) and len(node) >= 2:
            return float(node[1]), float(node[0])
        return first_pair(node[0])

    return first_pair(coords)


def feature_name(feat: dict) -> str:
    p = feat.get("properties") or {}
    for key in ("name", "title", "site_name", "portName", "geoname", "pref_name"):
        val = p.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def feature_url(feat: dict) -> str | None:
    p = feat.get("properties") or {}
    urls = p.get("source_urls") or []
    if isinstance(urls, list) and urls:
        first = urls[0]
        if isinstance(first, str) and first.startswith("http"):
            return first
        if isinstance(first, dict) and str(first.get("url") or "").startswith("http"):
            return first["url"]
    for key in ("url", "url_bu", "visit_url", "href"):
        val = p.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
        if isinstance(val, dict) and str(val.get("url") or "").startswith("http"):
            return val["url"]
    return None


def slim_place(feat: dict, lat0: float, lon0: float, extra_keys: tuple[str, ...] = ()) -> dict | None:
    ll = feature_latlon(feat)
    if not ll:
        return None
    lat, lon = ll
    name = feature_name(feat)
    if not name:
        return None
    item = {
        "name": name,
        "lat": round(lat, 5),
        "lon": round(lon, 5),
        "nm": round(haversine_nm(lat0, lon0, lat, lon), 1),
        "url": feature_url(feat),
    }
    props = feat.get("properties") or {}
    for key in extra_keys:
        val = props.get(key)
        if val not in (None, ""):
            item[key] = val
    return item


def slim_science(feat: dict, lat0: float, lon0: float) -> dict | None:
    item = slim_place(feat, lat0, lon0, extra_keys=("source", "kind", "wmo", "provider"))
    if not item:
        return None
    props = feat.get("properties") or {}
    if not item.get("source"):
        if props.get("kind") == "argo_float":
            item["source"] = "argo"
        elif props.get("kind") == "cruise":
            item["source"] = "csr"
    return item


def nearest_places(
    features: list,
    lat: float,
    lon: float,
    radius_nm: float,
    limit: int,
    extra_keys: tuple[str, ...] = (),
    slim=None,
) -> list[dict]:
    slim_fn = slim or (lambda f, a, b: slim_place(f, a, b, extra_keys))
    found: list[dict] = []
    for feat in features or []:
        item = slim_fn(feat, lat, lon)
        if item and item["nm"] <= radius_nm + 0.05:
            found.append(item)
    found.sort(key=lambda x: x["nm"])
    return found[:limit]


def _place_type(rec: dict) -> str:
    return str(rec.get("placeType") or rec.get("place_type") or "").upper()


def eez_records(records: list) -> list[dict]:
    return [rec for rec in records or [] if _place_type(rec) == "EEZ"]


def pick_eez_record(records: list) -> dict | None:
    found = eez_records(records)
    return found[0] if found else None


def eez_plausible(rec: dict | None, lat: float, lon: float) -> bool:
    """Le gazetteer colle parfois une ZEE lointaine (bbox immense). On garde
    seulement si le point représentatif est à portée d’une ZEE (~200 nm)."""
    if not rec or _place_type(rec) != "EEZ":
        return False
    try:
        elat = float(rec.get("latitude"))
        elon = float(rec.get("longitude"))
    except (TypeError, ValueError):
        return False
    return haversine_nm(lat, lon, elat, elon) <= EEZ_ACCEPT_NM


def zee_from_record(rec: dict | None) -> dict:
    if not rec:
        return {"name": "Haute mer", "mrgid": None, "territory": None, "gold": False}
    name = rec.get("preferredGazetteerName") or rec.get("name") or "ZEE"
    raw = rec.get("MRGID") or rec.get("mrgid")
    try:
        mrgid = int(raw) if raw is not None else None
    except (TypeError, ValueError):
        mrgid = None
    territory = FRENCH_EEZ_MRGID.get(mrgid) if mrgid is not None else None
    return {
        "name": name,
        "mrgid": mrgid,
        "territory": territory,
        "gold": False,
    }


async def _gazetteer_list(client: httpx.AsyncClient, lat: float, lon: float) -> list:
    r = await client.get(
        f"{MRGID_LATLON_URL}/{lat:.5f}/{lon:.5f}/",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=8.0,
    )
    r.raise_for_status()
    payload = r.json()
    return payload if isinstance(payload, list) else []


def _first_plausible(records: list, lat: float, lon: float) -> dict | None:
    for rec in eez_records(records):
        if eez_plausible(rec, lat, lon):
            return rec
    return None


async def lookup_zee(client: httpx.AsyncClient, lat: float, lon: float) -> tuple[dict | None, str]:
    """ZEE autour du bateau. Un point à quai n’est parfois pas dans le
    polygone : on sonde alors 8 points à ~12 nm. Une ZEE trop loin
    (gazetteer bavard) est refusée → haute mer."""
    try:
        here = await _gazetteer_list(client, lat, lon)
        rec = _first_plausible(here, lat, lon)
        if rec:
            return zee_from_record(rec), "marineregions"
        if eez_records(here):
            return zee_from_record(None), "marineregions"
        ashore = _ashore_from_records(here)
        step = 0.2
        probes = [
            (lat, lon - step), (lat, lon + step),
            (lat - step, lon), (lat + step, lon),
            (lat - step, lon - step), (lat - step, lon + step),
            (lat + step, lon - step), (lat + step, lon + step),
        ]
        found = await asyncio.gather(
            *[_gazetteer_list(client, plat, plon) for plat, plon in probes],
            return_exceptions=True,
        )
        for item in found:
            if isinstance(item, Exception) or not item:
                continue
            rec = _first_plausible(item, lat, lon)
            if rec:
                return zee_from_record(rec), "marineregions"
        if ashore:
            return ashore, "marineregions"
        return zee_from_record(None), "marineregions"
    except Exception:
        return zee_from_record(None), "marineregions"


def _ashore_from_records(records: list) -> dict | None:
    for rec in records or []:
        if _place_type(rec) != "NATION":
            continue
        name = rec.get("preferredGazetteerName") or rec.get("name")
        if not name:
            continue
        return {
            "name": f"À terre ({name})",
            "mrgid": None,
            "territory": None,
            "gold": False,
            "ashore": True,
        }
    return None


async def _get_json(client: httpx.AsyncClient, url: str, timeout: float = 4.0) -> Any:
    r = await client.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=timeout)
    r.raise_for_status()
    return r.json()


async def _cached_fc(client: httpx.AsyncClient, url: str) -> list:
    now = time.time()
    hit = _fc_cache.get(url)
    if hit and now - hit["ts"] < _FC_TTL:
        return hit["features"]
    data = await _get_json(client, url, timeout=20.0)
    features = data.get("features") if isinstance(data, dict) else []
    if not isinstance(features, list):
        features = []
    _fc_cache[url] = {"ts": now, "features": features}
    return features


async def fetch_wpi_features(client: httpx.AsyncClient | None = None) -> list:
    now = time.time()
    if _wpi_cache["data"] is not None and now - _wpi_cache["ts"] < _WPI_TTL:
        return _wpi_cache["data"]
    own = client is None
    http = client or httpx.AsyncClient()
    try:
        resp = await http.get(
            WPI_URL,
            params={"output": "json"},
            headers={"User-Agent": USER_AGENT},
            timeout=20.0,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception:
        return _wpi_cache["data"] or []
    finally:
        if own:
            await http.aclose()
    ports = raw if isinstance(raw, list) else raw.get("ports", [])
    features = []
    for p in ports or []:
        lat = parse_coord(p.get("latitude") if p.get("latitude") is not None else p.get("lat"))
        lon = parse_coord(p.get("longitude") if p.get("longitude") is not None else p.get("lon"))
        if lat is None or lon is None:
            continue
        if lat == 0.0 and lon == 0.0:
            continue
        name = p.get("portName") or p.get("name") or ""
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "name": name,
                "country": p.get("countryName") or "",
            },
        })
    _wpi_cache["data"] = features
    _wpi_cache["ts"] = time.time()
    return features


def _poe_from_fc(data: Any, lat: float, lon: float) -> list[dict]:
    features = data.get("features") if isinstance(data, dict) else []
    out = []
    for feat in features or []:
        item = slim_place(feat, lat, lon)
        if item:
            out.append(item)
    out.sort(key=lambda x: x["nm"])
    return out[:MAX_POE]


def _assign_result(d: dict, key: str, value: Any) -> bool:
    if isinstance(value, Exception):
        return False
    if key == "poe":
        d["poe"] = value
    elif key == "amp":
        d["amp"] = value
    elif key == "projects":
        d["projects"] = value
    elif key == "marinas":
        d["nearby"]["marinas"] = value
    elif key == "capitaineries":
        d["nearby"]["capitaineries"] = value
    elif key == "wpi":
        d["nearby"]["wpi"] = value
    elif key == "science":
        d["science"] = {"nearby": value}
    return True


async def fill_dossier(
    lat: float,
    lon: float,
    radius_nm: float = ICI_RADIUS_NM,
    client: httpx.AsyncClient | None = None,
) -> dict:
    d = empty_dossier(lat, lon, radius_nm)
    bi = bi_base()

    own = client is None
    http = client or httpx.AsyncClient()

    async def poe_task(mrgid: int) -> list[dict]:
        data = await _get_json(http, f"{bi}/poe/ports?mrgid={int(mrgid)}", timeout=4.0)
        return _poe_from_fc(data, lat, lon)

    async def amp_task() -> list[dict]:
        # Mongo cache (centroids). A small GET /amp?bbox= triggers ProtectedSeas.
        feats = await _cached_fc(http, f"{bi}/export/amp.geojson")
        return nearest_places(feats, lat, lon, radius_nm, MAX_AMP)

    async def projects_task() -> list[dict]:
        feats = await _cached_fc(http, f"{bi}/export/geojson")
        return nearest_places(feats, lat, lon, radius_nm, MAX_PROJECTS)

    async def marinas_task() -> list[dict]:
        # /marinas = BI memory cache; the export rebuilds all of Mongo.
        feats = await _cached_fc(http, f"{bi}/marinas")
        return nearest_places(feats, lat, lon, radius_nm, MAX_NEARBY)

    async def capit_task() -> list[dict]:
        feats = await _cached_fc(http, f"{bi}/capitaineries")
        return nearest_places(feats, lat, lon, radius_nm, MAX_NEARBY)

    async def science_task() -> list[dict]:
        feats = await _cached_fc(http, f"{bi}/export/science.geojson")
        return nearest_places(feats, lat, lon, radius_nm, MAX_SCIENCE, slim=slim_science)

    async def wpi_task() -> list[dict]:
        feats = await fetch_wpi_features(http)
        return nearest_places(feats, lat, lon, radius_nm, MAX_NEARBY)

    try:
        amp_t = asyncio.create_task(amp_task())
        proj_t = asyncio.create_task(projects_task())
        mar_t = asyncio.create_task(marinas_task())
        cap_t = asyncio.create_task(capit_task())
        sci_t = asyncio.create_task(science_task())
        wpi_t = asyncio.create_task(wpi_task())

        zee, zee_src = await lookup_zee(http, lat, lon)
        d["zee"] = zee
        d["sources"]["zee"] = zee_src

        mrgid = zee.get("mrgid") if zee else None
        poe_t = asyncio.create_task(poe_task(mrgid)) if mrgid else None

        nearby = await asyncio.gather(amp_t, proj_t, mar_t, cap_t, sci_t, wpi_t, return_exceptions=True)
        keys = ("amp", "projects", "marinas", "capitaineries", "science", "wpi")
        bi_ok = 0
        bi_fail = 0
        for key, value in zip(keys, nearby):
            if key == "wpi":
                _assign_result(d, key, value)
                continue
            if _assign_result(d, key, value):
                bi_ok += 1
            else:
                bi_fail += 1

        if poe_t is not None:
            try:
                poe_val = await poe_t
            except Exception as exc:
                poe_val = exc
            if _assign_result(d, "poe", poe_val):
                bi_ok += 1
            else:
                bi_fail += 1

        if bi_ok and not bi_fail:
            d["sources"]["bi"] = "ok"
        elif bi_ok:
            d["sources"]["bi"] = "partial"
        else:
            d["sources"]["bi"] = "unavailable"

        await attach_depth_offshore(d, http)
    finally:
        if own:
            await http.aclose()

    if d["zee"] and d["zee"].get("mrgid") in FRENCH_EEZ_MRGID:
        d["zee"]["gold"] = bool(d["poe"])
    return d
