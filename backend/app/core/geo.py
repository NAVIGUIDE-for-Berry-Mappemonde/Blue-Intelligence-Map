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
from datetime import datetime, timedelta, timezone

import httpx
from global_land_mask import globe

UA = "BerryMappemonde-BlueIntelligence/1.0 (+https://berrymappemonde.org; contact: clementfilisetti@berrymappemonde.org)"

_geo_cache: dict = {}
_nominatim_lock = asyncio.Lock()
_last_nominatim = 0.0

# Cache L2 Mongo (partagé entre workers) + L1 process. Les hits ne consomment
# pas le quota Nominatim/GeoNames — condition pour tenir un run mondial.
NOMINATIM_INTERVAL_S = 1.1
GEONAMES_INTERVAL_S = 1.0
GEOCODE_TTL_HIT_S = 180 * 86400
GEOCODE_TTL_MISS_S = 14 * 86400
_ROW_MEM_MAX = 4096
_row_mem: dict[str, tuple[float, list]] = {}
_THROTTLE_ATTEMPTS = 40


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
# Cache géocode + rate limiter partagé (Mongo)
# ---------------------------------------------------------------------------
def _geodb():
    """Hookable depuis les tests (base dédiée). Défaut : app.db.db."""
    from app.db import db
    return db


def geocode_cache_id(provider: str, query: str, country_code: str | None, limit: int) -> str:
    raw = f"{provider}\0{(query or '').strip().lower()}\0{(country_code or '').lower()}\0{limit}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _mem_get(cid: str) -> list | None:
    item = _row_mem.get(cid)
    if not item:
        return None
    exp, rows = item
    if exp < time.time():
        _row_mem.pop(cid, None)
        return None
    return rows


def _mem_set(cid: str, rows: list, ttl_s: float) -> None:
    if len(_row_mem) >= _ROW_MEM_MAX:
        now = time.time()
        for k, (exp, _) in list(_row_mem.items()):
            if exp < now:
                _row_mem.pop(k, None)
        while len(_row_mem) >= _ROW_MEM_MAX:
            _row_mem.pop(next(iter(_row_mem)))
    _row_mem[cid] = (time.time() + ttl_s, rows)


def _ttl_s(rows: list) -> float:
    return GEOCODE_TTL_HIT_S if rows else GEOCODE_TTL_MISS_S


def _expires_at(ttl_s: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=ttl_s)


def _is_expired(exp) -> bool:
    if exp is None:
        return False
    if isinstance(exp, datetime):
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp < datetime.now(timezone.utc)
    try:
        return float(exp) < time.time()
    except (TypeError, ValueError):
        return False


async def _geocode_cache_get(provider: str, query: str, country_code: str | None,
                             limit: int) -> list | None:
    cid = geocode_cache_id(provider, query, country_code, limit)
    hit = _mem_get(cid)
    if hit is not None:
        return hit
    try:
        doc = await _geodb().geocode_cache.find_one({"_id": cid})
    except Exception:
        return None
    if not doc or _is_expired(doc.get("expires_at")):
        return None
    rows = list(doc.get("rows") or [])
    _mem_set(cid, rows, _ttl_s(rows))
    return rows


async def _geocode_cache_set(provider: str, query: str, country_code: str | None,
                             limit: int, rows: list) -> None:
    cid = geocode_cache_id(provider, query, country_code, limit)
    ttl = _ttl_s(rows)
    _mem_set(cid, list(rows), ttl)
    try:
        await _geodb().geocode_cache.update_one(
            {"_id": cid},
            {"$set": {
                "provider": provider,
                "query": query,
                "country_code": country_code,
                "limit": limit,
                "rows": rows,
                "fetched_at": datetime.now(timezone.utc),
                "expires_at": _expires_at(ttl),
            }},
            upsert=True,
        )
    except Exception:
        pass


async def _mongo_claim_slot(provider: str, interval: float) -> None:
    """Réserve un créneau global (1 req / interval) via Mongo.

    Dégradation silencieuse si Mongo est injoignable : le lock process-local
    reste le filet. Après trop de collisions on cède (mieux un 429 qu'un hang).
    """
    if interval <= 0:
        return
    try:
        coll = _geodb().geo_rate_limit
    except Exception:
        return
    for _ in range(_THROTTLE_ATTEMPTS):
        now = time.time()
        try:
            doc = await coll.find_one({"_id": provider})
        except Exception:
            return
        if doc is None:
            try:
                await coll.insert_one({"_id": provider, "last_ts": now})
                return
            except Exception:
                continue
        last = float(doc.get("last_ts") or 0)
        wait = interval - (now - last)
        if wait > 0:
            await asyncio.sleep(wait)
            continue
        try:
            claimed = await coll.find_one_and_update(
                {"_id": provider, "last_ts": {"$lte": now - interval}},
                {"$set": {"last_ts": time.time()}},
            )
        except Exception:
            return
        if claimed is not None:
            return
    return


async def _throttle(provider: str, interval: float, last_attr: str) -> None:
    """Filet local (même process) puis créneau Mongo (tous les workers)."""
    last = float(globals()[last_attr])
    wait = interval - (time.time() - last)
    if wait > 0:
        await asyncio.sleep(wait)
    await _mongo_claim_slot(provider, interval)
    globals()[last_attr] = time.time()


async def ensure_geo_indexes(db=None) -> None:
    target = db if db is not None else _geodb()
    await target.geocode_cache.create_index("expires_at", expireAfterSeconds=0)
    await target.geo_rate_limit.create_index("last_ts")


# ---------------------------------------------------------------------------
# Géocodage multi-source : Nominatim (rate-limité) → GeoNames
# ---------------------------------------------------------------------------
async def _nominatim_rows(query: str, country_code: str | None = None, limit: int = 1) -> list[dict]:
    cached = await _geocode_cache_get("nominatim", query, country_code, limit)
    if cached is not None:
        return cached
    async with _nominatim_lock:
        cached = await _geocode_cache_get("nominatim", query, country_code, limit)
        if cached is not None:
            return cached
        await _throttle("nominatim", NOMINATIM_INTERVAL_S, "_last_nominatim")
        params = {"q": query, "format": "json", "limit": limit}
        if country_code:
            params["countrycodes"] = country_code.lower()
        try:
            async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA}) as client:
                r = await client.get("https://nominatim.openstreetmap.org/search", params=params)
                if r.status_code != 200:
                    return []
                payload = r.json()
                rows = payload if isinstance(payload, list) else []
        except Exception:
            return []
        await _geocode_cache_set("nominatim", query, country_code, limit, rows)
        return rows


_geonames_lock = asyncio.Lock()
_last_geonames = 0.0
_geonames_disabled_reason: str | None = None


def geonames_status() -> str:
    """'ok' | 'no_account' | raison de désactivation (401, quota, compte non activé)."""
    if not (os.environ.get("GEONAMES_USERNAME") or "").strip():
        return "no_account"
    return _geonames_disabled_reason or "ok"


async def _geonames_rows(query: str, country_code: str | None = None, limit: int = 1) -> list[dict]:
    global _geonames_disabled_reason
    gn_user = (os.environ.get("GEONAMES_USERNAME") or "").strip()
    if not gn_user or _geonames_disabled_reason:
        return []
    cached = await _geocode_cache_get("geonames", query, country_code, limit)
    if cached is not None:
        return cached
    async with _geonames_lock:  # politesse ~1 req/s (quota gratuit 1000/h)
        cached = await _geocode_cache_get("geonames", query, country_code, limit)
        if cached is not None:
            return cached
        await _throttle("geonames", GEONAMES_INTERVAL_S, "_last_geonames")
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
                if r.status_code != 200:
                    return []
                rows = body.get("geonames") or []
        except Exception:
            return []
        await _geocode_cache_set("geonames", query, country_code, limit, rows)
        return rows


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
    """Retourne (validated: bool, dist_km: float|None). tol_deg ≈ 55 km côtiers.

    Conservé pour les appels historiques. Le pipeline PoE utilise
    classify_poe_point (ZEE stricte ou bord terrestre, pas de tampon 55 km)."""
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


# Bord terrestre d'une ZEE : le quai est à terre, le polygone est en mer.
# Quelques kilomètres, pas 300 — un port du pays voisin doit être rejeté.
COASTAL_LAND_KM = 12.0


def _dist_km_to_geom(lat: float, lon: float, geom) -> float | None:
    """Distance haversine au bord du polygone (degrés shapely trop grossiers)."""
    try:
        from shapely.geometry import Point
        from shapely.ops import nearest_points
        pt = Point(lon, lat)
        if geom.contains(pt):
            return 0.0
        nearest = nearest_points(geom, pt)[0]
        return round(haversine_km(lat, lon, nearest.y, nearest.x), 1)
    except Exception:
        try:
            from shapely.geometry import Point
            return round(geom.distance(Point(lon, lat)) * 111.0, 1)
        except Exception:
            return None


def classify_poe_point(lat: float, lon: float, geom, prepared=None,
                       coastal_km: float = COASTAL_LAND_KM) -> dict:
    """Classe un candidat PoE par rapport à CETTE ZEE (pas snap_to_ocean).

    - in_eez        : dans le polygone (mer de la zone) → accepté
    - coastal_land  : à terre, collé au trait de côte de cette ZEE → accepté
    - other_water   : en mer hors de cette ZEE (souvent les eaux d'à côté) → rejeté
    - inland        : trop loin dans les terres → rejeté
    """
    try:
        from shapely.geometry import Point
        pt = Point(lon, lat)
        inside = False
        if prepared is not None and prepared.contains(pt):
            inside = True
        elif prepared is None and geom.contains(pt):
            inside = True
        dist = _dist_km_to_geom(lat, lon, geom)
        if inside:
            return {"kind": "in_eez", "validated": True, "dist_km": 0.0}
        on_land = not is_ocean(lat, lon)
        if on_land and dist is not None and dist <= coastal_km:
            return {"kind": "coastal_land", "validated": True, "dist_km": dist}
        if on_land:
            return {"kind": "inland", "validated": False, "dist_km": dist}
        return {"kind": "other_water", "validated": False, "dist_km": dist}
    except Exception:
        return {"kind": "unknown", "validated": False, "dist_km": None}


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
