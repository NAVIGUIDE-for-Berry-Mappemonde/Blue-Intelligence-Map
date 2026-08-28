"""
geo_core.py — Module géospatial unifié (Core mutualisé PoE / Projets).

Regroupe : géocodage multi-source (Nominatim → GeoNames) avec rate-limit et
cache, masque terrestre (global_land_mask), snap_to_ocean, distance côtière,
validation point-in-EEZ (shapely), variantes de noms de ports, re-ranking des
candidats de géocodage, et détection d'anomalies spatiales (scikit-learn).
"""
import asyncio
import hashlib
import math
import os
import re
import time

import httpx
from global_land_mask import globe

UA = "BerryMappemonde-BlueIntelligence/1.0 (+https://berrymappemonde.org; contact: clementfilisetti@berrymappemonde.org)"

_geo_cache: dict = {}
_nominatim_lock = asyncio.Lock()
_last_nominatim = 0.0


# ---------------------------------------------------------------------------
# Géométrie de base
# ---------------------------------------------------------------------------
def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def destination_point(lat, lon, bearing_deg, dist_km):
    r = 6371.0
    br = math.radians(bearing_deg)
    p1 = math.radians(lat)
    l1 = math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(dist_km / r) + math.cos(p1) * math.sin(dist_km / r) * math.cos(br))
    l2 = l1 + math.atan2(math.sin(br) * math.sin(dist_km / r) * math.cos(p1),
                         math.cos(dist_km / r) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), ((math.degrees(l2) + 180) % 360) - 180


# ---------------------------------------------------------------------------
# Masque terrestre / océan
# ---------------------------------------------------------------------------
def is_ocean(lat: float, lon: float) -> bool:
    lat = max(-89.9, min(89.9, lat))
    lon = ((lon + 180) % 360) - 180
    return bool(globe.is_ocean(lat, lon))


def snap_to_ocean(lat: float, lon: float, max_km: float = 500.0):
    """Point océanique le plus proche → (lat, lon, snapped_bool)."""
    if is_ocean(lat, lon):
        return lat, lon, False
    for radius in [10, 25, 50, 75, 100, 150, 200, 300, 400, int(max_km)]:
        if radius > max_km:
            break
        for bearing in range(0, 360, 20):
            nlat, nlon = destination_point(lat, lon, bearing, radius)
            if is_ocean(nlat, nlon):
                return nlat, nlon, True
    return lat, lon, False


def coast_distance_km(lat: float, lon: float) -> float:
    if is_ocean(lat, lon):
        return 0.0
    for radius in [10, 25, 50, 75, 100, 150, 200, 300, 400, 500]:
        for bearing in range(0, 360, 30):
            nlat, nlon = destination_point(lat, lon, bearing, radius)
            if is_ocean(nlat, nlon):
                return float(radius)
    return 999.0


OCEAN_REGIONS = [
    (-170, -110, -30, 30),
    (-50, -20, -30, 30),
    (60, 90, -30, 10),
    (140, 170, -30, 10),
]


def ocean_fallback_coords(title: str):
    h = int(hashlib.md5(title.encode()).hexdigest(), 16)
    region = OCEAN_REGIONS[h % len(OCEAN_REGIONS)]
    lon = region[0] + (h % 1000) / 1000 * (region[1] - region[0])
    lat = region[2] + ((h >> 10) % 1000) / 1000 * (region[3] - region[2])
    return lat, lon


# ---------------------------------------------------------------------------
# Géocodage multi-source : Nominatim (rate-limité) → GeoNames
# ---------------------------------------------------------------------------
async def _nominatim_rows(query: str, country_code: str | None = None, limit: int = 1) -> list[dict]:
    global _last_nominatim
    async with _nominatim_lock:
        wait = 1.1 - (time.time() - _last_nominatim)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_nominatim = time.time()
    params = {"q": query, "format": "json", "limit": limit}
    if country_code:
        params["countrycodes"] = country_code.lower()
    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA}) as client:
            r = await client.get("https://nominatim.openstreetmap.org/search", params=params)
            return r.json() if r.status_code == 200 else []
    except Exception:
        return []


_geonames_lock = asyncio.Lock()
_last_geonames = 0.0
_geonames_disabled_reason: str | None = None


def geonames_status() -> str:
    """'ok' | 'no_account' | raison de désactivation (401, quota, compte non activé)."""
    if not (os.environ.get("GEONAMES_USERNAME") or "").strip():
        return "no_account"
    return _geonames_disabled_reason or "ok"


async def _geonames_rows(query: str, country_code: str | None = None, limit: int = 1) -> list[dict]:
    global _last_geonames, _geonames_disabled_reason
    gn_user = (os.environ.get("GEONAMES_USERNAME") or "").strip()
    if not gn_user or _geonames_disabled_reason:
        return []
    async with _geonames_lock:  # politesse ~1 req/s (quota gratuit 1000/h)
        wait = 1.0 - (time.time() - _last_geonames)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_geonames = time.time()
    params = {"q": query, "maxRows": limit, "username": gn_user}
    if country_code:
        params["country"] = country_code.upper()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get("http://api.geonames.org/searchJSON", params=params)
            body = r.json() if "json" in (r.headers.get("content-type") or "") else {}
            status = (body or {}).get("status") or {}
            # 10 = authorization exception (compte absent / webservice non activé),
            # 18/19/20 = quotas — on désactive pour la suite du process (évite
            # des centaines d'appels voués à l'échec).
            if r.status_code in (401, 403) or status.get("value") in (10, 18, 19, 20):
                _geonames_disabled_reason = (status.get("message")
                                             or f"http {r.status_code}")[:120]
                return []
            return (body.get("geonames") or []) if r.status_code == 200 else []
    except Exception:
        return []


async def geocode(query: str, country_code: str | None = None):
    """Géocodage simple avec cache : Nominatim → GeoNames. Retourne (lat, lon) | None."""
    if not query:
        return None
    key = (query.strip().lower(), (country_code or "").lower())
    if key in _geo_cache:
        return _geo_cache[key]
    rows = await _nominatim_rows(query, country_code)
    if rows:
        coords = (float(rows[0]["lat"]), float(rows[0]["lon"]))
        _geo_cache[key] = coords
        return coords
    rows = await _geonames_rows(query, country_code)
    if rows:
        coords = (float(rows[0]["lat"]), float(rows[0]["lng"]))
        _geo_cache[key] = coords
        return coords
    _geo_cache[key] = None
    return None


# ---------------------------------------------------------------------------
# Géocodage de PoE (variantes de noms + re-ranking sémantique)
# ---------------------------------------------------------------------------
def port_name_variants(name: str) -> list[str]:
    variants = []
    deparen = re.sub(r"\s*\([^)]*\)", "", name).strip()
    if deparen and deparen.lower() != name.lower():
        variants.append(deparen)
    variants.append(name)
    stripped = re.sub(r"^(port|puerto|porto|harbour|harbor)\s+(of|de|du|di|da|d')\s*", "", name, flags=re.I).strip()
    if stripped and stripped.lower() != name.lower():
        variants.append(stripped)
    stripped2 = re.sub(r"\s+(port|harbour|harbor|marina|wharf|jetty|terminal)$", "", name, flags=re.I).strip()
    if stripped2 and stripped2.lower() not in {v.lower() for v in variants}:
        variants.append(stripped2)
    return variants


def _rerank_rows(query_ctx: str, rows: list[dict], name_key: str) -> dict:
    """Re-ranking des candidats de géocodage par similarité sémantique (rag_core)."""
    if len(rows) <= 1:
        return rows[0]
    try:
        from app.core.rag import rerank_candidates
        labels = [str(r.get(name_key) or "") for r in rows]
        best_idx = rerank_candidates(query_ctx, labels)[0][0]
        return rows[best_idx]
    except Exception:
        return rows[0]


def _port_queries(port: dict, zone: dict) -> tuple[list[str], str]:
    """Échelle de requêtes de géocodage d'un port + contexte de re-ranking."""
    name = port["name"]
    territory = zone.get("name") or ""
    variants = port_name_variants(name)
    queries = []
    if port.get("city"):
        queries.append(f"{name}, {port['city']}, {territory}")
    for v in variants:
        queries.append(f"{v}, {territory}")
    if port.get("city"):
        queries.append(f"{port['city']}, {territory}")
    queries.append(f"{name} port, {zone.get('sovereign') or territory}")
    ctx = f"{name} port harbour marina customs, {territory}"
    return queries, ctx


async def _geocode_port_nominatim(port: dict, zone: dict) -> tuple[float, float] | None:
    queries, ctx = _port_queries(port, zone)
    cc = (zone.get("iso2") or "").lower() or None
    for q in queries:
        rows = await _nominatim_rows(q, cc, limit=3)
        if rows:
            best = _rerank_rows(ctx, rows, "display_name")
            return float(best["lat"]), float(best["lon"])
    return None


async def _geocode_port_geonames(port: dict, zone: dict) -> tuple[float, float] | None:
    name = port["name"]
    territory = zone.get("name") or ""
    _, ctx = _port_queries(port, zone)
    cc = (zone.get("iso2") or "").upper() or None
    for q, country in ((name, cc), (f"{name} {territory}", None)):
        rows = await _geonames_rows(q, country, limit=3)
        if rows:
            best = _rerank_rows(ctx, rows, "name")
            return float(best["lat"]), float(best["lng"])
    return None


async def geocode_port_dual(port: dict, zone: dict, log=None) -> dict:
    """GÉOCODAGE PARALLÈLE COMPARÉ : Nominatim (données OSM) ∥ GeoNames (base
    indépendante) — plus de cascade. L'accord des deux fournisseurs à < 2 km
    est un signal de confiance fort ; le désaccord est arbitré en aval
    (point-in-EEZ). Retourne :
      {nominatim: [lat, lon]|None, geonames: [lat, lon]|None,
       agreement_km: float|None, agree: bool|None, geonames_available: bool}
    agree=None quand un seul fournisseur a répondu (GeoNames absent/désactivé)."""
    log = log or (lambda m: None)
    nomi, geon = await asyncio.gather(
        _geocode_port_nominatim(port, zone),
        _geocode_port_geonames(port, zone),
    )
    agreement_km = None
    agree = None
    if nomi and geon:
        agreement_km = round(haversine_km(nomi[0], nomi[1], geon[0], geon[1]), 2)
        agree = agreement_km <= 2.0
    if not nomi and not geon:
        log(f"géocodage: aucun résultat pour « {port['name']} »")
    return {
        "nominatim": list(nomi) if nomi else None,
        "geonames": list(geon) if geon else None,
        "agreement_km": agreement_km,
        "agree": agree,
        "geonames_available": geonames_status() == "ok",
    }


# ---------------------------------------------------------------------------
# Validation spatiale point-in-EEZ (shapely)
# ---------------------------------------------------------------------------
def point_in_eez(lat: float, lon: float, geom, prepared=None, tol_deg: float = 0.5):
    """Retourne (validated: bool, dist_km: float|None). tol_deg ≈ 55 km côtiers."""
    try:
        from shapely.geometry import Point
        pt = Point(lon, lat)
        if prepared is not None and prepared.contains(pt):
            return True, 0.0
        if prepared is None and geom.contains(pt):
            return True, 0.0
        d = geom.distance(pt)
        return d <= tol_deg, round(d * 111.0, 1)
    except Exception:
        return False, None


# ---------------------------------------------------------------------------
# Détection d'anomalies spatiales (scikit-learn — bootstrappé sur la BDD)
# ---------------------------------------------------------------------------
def isolation_forest_scores(features: list[list[float]], contamination: float = 0.05):
    """Retourne (labels[-1|1], scores). features = [[dx_km, dy_km, dist_km], ...]"""
    from sklearn.ensemble import IsolationForest
    import numpy as np
    X = np.array(features, dtype=float)
    clf = IsolationForest(contamination=contamination, random_state=42, n_estimators=200)
    labels = clf.fit_predict(X)
    scores = clf.decision_function(X)
    return labels.tolist(), scores.tolist()


def dbscan_noise_flags(coords: list[tuple[float, float]], eps_km: float = 150.0, min_samples: int = 2):
    """DBSCAN haversine par zone : True = point isolé (bruit)."""
    from sklearn.cluster import DBSCAN
    import numpy as np
    if len(coords) < min_samples + 1:
        return [False] * len(coords)
    X = np.radians(np.array(coords, dtype=float))
    labels = DBSCAN(eps=eps_km / 6371.0, min_samples=min_samples, metric="haversine").fit_predict(X)
    return [bool(l == -1) for l in labels]
