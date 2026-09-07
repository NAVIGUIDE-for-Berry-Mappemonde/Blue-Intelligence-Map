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
# Géocodage de PoE (variantes de noms + score d'homonymes)
# ---------------------------------------------------------------------------
GEOCODE_CANDIDATE_LIMIT = 8
BASIN_SPLIT_KM = 1500.0
PEER_NEAR_KM = 300.0
PEER_FAR_KM = 500.0
AMBIGUOUS_SCORE_GAP = 12.0
INLAND_FAR_SCORE_KM = 30.0

_PAREN_HINT_RE = re.compile(r"\((.+)\)")
_PAREN_HINT_STOP = {
    "island", "islands", "city", "port", "harbour", "harbor", "marina",
    "coast", "west", "east", "north", "south", "the", "and", "of",
}


def paren_hint_tokens(*names: str) -> list[str]:
    """Tokens entre parenthèses (Bintan Island, Georgia) — contrainte, pas un strip."""
    tokens: list[str] = []
    for raw in names:
        if not raw:
            continue
        m = _PAREN_HINT_RE.search(raw)
        if not m:
            continue
        for bit in re.split(r"\s*[,/;&–-]\s*", m.group(1)):
            bit = bit.strip()
            if len(bit) >= 4:
                tokens.append(bit)
            for w in re.findall(r"[A-Za-zÀ-ÿ]{4,}", bit):
                if w.lower() not in _PAREN_HINT_STOP:
                    tokens.append(w)
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


def port_name_variants(name: str) -> list[str]:
    """Nom complet d'abord (parenthèses conservées), puis alias sans parenthèses."""
    variants: list[str] = []
    seen: set[str] = set()

    def _add(v: str) -> None:
        v = (v or "").strip()
        if not v:
            return
        k = v.lower()
        if k in seen:
            return
        seen.add(k)
        variants.append(v)

    _add(name)
    hints = paren_hint_tokens(name)
    deparen = re.sub(r"\s*\([^)]*\)", "", name).strip()
    if hints and deparen:
        _add(f"{deparen}, {', '.join(hints)}")
    _add(deparen)
    stripped = re.sub(
        r"^(port|puerto|porto|harbour|harbor)\s+(of|de|du|di|da|d')\s*",
        "", name, flags=re.I).strip()
    _add(stripped)
    stripped2 = re.sub(
        r"\s+(port|harbour|harbor|marina|wharf|jetty|terminal)$",
        "", deparen or name, flags=re.I).strip()
    _add(stripped2)
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
    listing_name = (port.get("listing_name") or "").strip()
    variants = port_name_variants(name)
    if listing_name and listing_name.lower() != name.lower():
        for v in port_name_variants(listing_name):
            if v.lower() not in {x.lower() for x in variants}:
                variants.append(v)
    queries = []
    if port.get("city"):
        queries.append(f"{name}, {port['city']}, {territory}")
    grp = (port.get("listing_group") or "").strip()
    if grp:
        queries.append(f"{variants[0] if variants else name}, {grp}")
    for v in variants:
        queries.append(f"{v}, {territory}")
    if port.get("city"):
        queries.append(f"{port['city']}, {territory}")
    queries.append(f"{name} port, {zone.get('sovereign') or territory}")
    ctx = f"{name} port harbour marina customs, {territory}"
    # Déduplique en gardant l'ordre (parenthèses / groupe listing d'abord).
    seen: set[str] = set()
    uniq: list[str] = []
    for q in queries:
        k = q.strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        uniq.append(q.strip())
    return uniq, ctx


def _zone_geom(zone: dict | None):
    zone = zone or {}
    geom = zone.get("_geom")
    prepared = zone.get("_prep")
    if geom is None and zone.get("geometry"):
        try:
            from shapely.geometry import shape
            geom = shape(zone["geometry"])
        except Exception:
            geom = None
    return geom, prepared


def listing_group_penalty(group: str, lat: float, lon: float) -> float:
    """Pénalité si le GPS contredit le bassin du listing (pas un centroïde)."""
    g = (group or "").lower()
    if not g:
        return 0.0
    if "west coast" in g and ("usa" in g or "united states" in g):
        return -45.0 if lon > -90.0 else 0.0
    if "east coast" in g and ("usa" in g or "united states" in g):
        return -45.0 if lon < -90.0 else 0.0
    if "atlantic" in g and "france" in g:
        return -45.0 if lon > 1.0 else 0.0
    if "north of rio" in g:
        return -45.0 if lat < -23.0 else 0.0
    return 0.0


def _core_name_token(name: str) -> str:
    n = re.sub(r"\([^)]*\)", " ", name or "")
    n = re.sub(
        r"\b(port of|porto de|puerto de|harbour|harbor|marina|tp)\b",
        " ", n, flags=re.I)
    n = re.sub(r"[^A-Za-zÀ-ÿ]+", "", n).lower()
    return n


def _cand_harbour_meta(cand: dict) -> dict:
    return {
        "osm_class": cand.get("osm_class") or "",
        "osm_type": cand.get("osm_type") or "",
        "geonames_fcode": cand.get("geonames_fcode") or cand.get("fcode") or "",
    }


def _has_decisive_hint(cand: dict, port: dict) -> bool:
    if cand.get("paren_hit"):
        return True
    if cand.get("peer_km") is not None and cand["peer_km"] <= PEER_NEAR_KM:
        return True
    if (cand.get("group_penalty") or 0) == 0 and (port.get("listing_group") or ""):
        if listing_group_penalty(
                port.get("listing_group") or "", cand["lat"], cand["lon"]) == 0:
            # Un groupe ouest/est USA qui ne pénalise pas EST un hint.
            g = (port.get("listing_group") or "").lower()
            if "west coast" in g or "east coast" in g or (
                    "atlantic" in g and "france" in g) or "north of rio" in g:
                return True
    return False


def score_geocode_candidate(
    cand: dict, port: dict, zone: dict | None, geom=None, prepared=None,
) -> dict:
    """Score un candidat Nominatim/GeoNames. Ne copie jamais le GPS d'un pair."""
    lat, lon = float(cand["lat"]), float(cand["lon"])
    label = str(cand.get("label") or "")
    meta = _cand_harbour_meta(cand)
    # Pas listing_role=poe → exception rivière 400 km (Safi inland).
    port_for_inland = {k: v for k, v in (port or {}).items() if k != "listing_role"}
    inland = inland_exception_flags(port_for_inland, zone or {}, meta)
    spatial = {"kind": "unknown", "validated": False, "dist_km": None}
    if geom is not None:
        spatial = classify_poe_point(lat, lon, geom, prepared, inland=inland)
    kind = spatial.get("kind")
    dist = spatial.get("dist_km")
    dist_f = float(dist) if dist is not None else None
    score = 0.0
    if kind == "in_eez":
        score += 50
    elif kind == "coastal_land":
        score += 40
    elif kind == "inland_river" and dist_f is not None and dist_f <= INLAND_FAR_SCORE_KM:
        score += 10
    elif kind in {"inland_river", "inland", "other_water"} and dist_f is not None:
        if dist_f > INLAND_FAR_SCORE_KM:
            score -= 40
        else:
            score -= 10
    osm = f"{meta.get('osm_class') or ''} {meta.get('osm_type') or ''}".lower()
    if any(tok in osm for tok in _HARBOUR_OSM):
        score += 25
    fcode = (meta.get("geonames_fcode") or "").upper()
    if fcode in _HARBOUR_GN:
        score += 25
    hints = paren_hint_tokens(
        port.get("name") or "", port.get("listing_name") or "")
    label_l = label.lower()
    paren_hit = False
    if hints:
        hits = sum(1 for h in hints if h.lower() in label_l)
        if hits:
            score += 20 * hits
            paren_hit = True
        else:
            score -= 10
    core = _core_name_token(port.get("name") or "")
    label_core = _core_name_token(label)
    if core and core in label_l.replace(" ", "").lower():
        score += 12
    elif core and core not in label_core:
        score -= 8
    group = port.get("listing_group") or ""
    group_penalty = listing_group_penalty(group, lat, lon)
    score += group_penalty
    peer_km = None
    peers = list(port.get("geocode_peers") or [])
    if peers:
        ds = []
        for p in peers:
            try:
                ds.append(haversine_km(lat, lon, float(p["lat"]), float(p["lon"])))
            except (TypeError, ValueError, KeyError):
                continue
        if ds:
            peer_km = min(ds)
            if peer_km <= PEER_NEAR_KM:
                score += 20
            elif peer_km > PEER_FAR_KM:
                score -= 25
    out = dict(cand)
    out.update({
        "lat": lat, "lon": lon, "score": score, "spatial": spatial,
        "paren_hit": paren_hit, "peer_km": peer_km,
        "group_penalty": group_penalty,
    })
    return out


def select_geocode_candidate(
    cands: list[dict], port: dict, zone: dict | None = None,
    geom=None, prepared=None,
) -> dict:
    """Choisit un candidat ou déclare ambiguous (deux bassins, pas de hint)."""
    if not cands:
        return {"status": "miss", "chosen": None, "ranked": []}
    ranked = [
        score_geocode_candidate(c, port, zone, geom, prepared)
        for c in cands
    ]
    ranked.sort(key=lambda c: (-c["score"], c.get("source") != "nominatim"))
    best = ranked[0]
    status = "ok"
    core = _core_name_token(port.get("name") or "")

    def _label_has_core(c: dict) -> bool:
        if not core:
            return False
        lab = (c.get("label") or "").lower().replace(" ", "")
        return core in lab

    # Port fluvial légitime (Sevilla) : ne pas sauter vers un quai lointain
    # dont le libellé n'est pas le toponyme.
    inland_named = []
    if core:
        for c in ranked:
            sp = c.get("spatial") or {}
            dist = sp.get("dist_km")
            if (sp.get("kind") in {"inland_river", "inland"}
                    and dist is not None and float(dist) <= 80
                    and _label_has_core(c)):
                inland_named.append(c)
    if inland_named and best is not inland_named[0]:
        try:
            jump = haversine_km(
                best["lat"], best["lon"],
                inland_named[0]["lat"], inland_named[0]["lon"])
        except (TypeError, ValueError):
            jump = 0.0
        if jump > PEER_NEAR_KM and not _label_has_core(best):
            best = inland_named[0]

    # Pair listing trop loin : homonyme dans une ZEE immense (Kingston ON vs NL).
    if (best.get("peer_km") is not None and best["peer_km"] >= BASIN_SPLIT_KM
            and not best.get("paren_hit")):
        status = "spatial_rejected"
        best = None
    if best is not None and len(ranked) >= 2:
        second = ranked[1]
        gap = best["score"] - second["score"]
        try:
            split = haversine_km(
                best["lat"], best["lon"], second["lat"], second["lon"])
        except (TypeError, ValueError):
            split = 0.0
        if (split >= BASIN_SPLIT_KM and gap <= AMBIGUOUS_SCORE_GAP
                and second["score"] >= 0):
            if _has_decisive_hint(best, port) and not _has_decisive_hint(second, port):
                status = "ok"
            elif _has_decisive_hint(second, port) and not _has_decisive_hint(best, port):
                best = second
                status = "ok"
            else:
                status = "ambiguous"
                best = None
    if status == "ok" and best is not None:
        kind = (best.get("spatial") or {}).get("kind")
        dist = (best.get("spatial") or {}).get("dist_km")
        if (kind in {"inland", "inland_river", "other_water"}
                and dist is not None and float(dist) > INLAND_FAR_SCORE_KM
                and best["score"] < 20):
            status = "spatial_rejected"
    return {"status": status, "chosen": best, "ranked": ranked}


def _xy(hit: dict | None) -> list[float] | None:
    if not hit:
        return None
    if hit.get("lat") is None or hit.get("lon") is None:
        return None
    return [hit["lat"], hit["lon"]]


def _nominatim_cand(row: dict) -> dict | None:
    try:
        return {
            "source": "nominatim",
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "label": str(row.get("display_name") or ""),
            "osm_class": row.get("class") or "",
            "osm_type": row.get("type") or "",
            "geonames_fcode": "",
        }
    except (TypeError, ValueError, KeyError):
        return None


def _geonames_cand(row: dict) -> dict | None:
    try:
        return {
            "source": "geonames",
            "lat": float(row["lat"]),
            "lon": float(row["lng"]),
            "label": str(row.get("name") or ""),
            "osm_class": "",
            "osm_type": "",
            "geonames_fcode": row.get("fcode") or "",
        }
    except (TypeError, ValueError, KeyError):
        return None


def _add_unique_cand(pool: list[dict], cand: dict | None) -> None:
    if not cand:
        return
    key = (round(cand["lat"], 4), round(cand["lon"], 4))
    for c in pool:
        if (round(c["lat"], 4), round(c["lon"], 4)) == key:
            return
    pool.append(cand)


def _pool_has_coastal(pool: list[dict], port: dict, zone: dict, geom, prepared) -> bool:
    if geom is None or not pool:
        return bool(pool)
    for c in pool:
        sc = score_geocode_candidate(c, port, zone, geom, prepared)
        kind = (sc.get("spatial") or {}).get("kind")
        if kind in {"in_eez", "coastal_land"}:
            return True
    return False


async def _collect_nominatim_candidates(port: dict, zone: dict) -> list[dict]:
    queries, _ctx = _port_queries(port, zone)
    cc = (zone.get("iso2") or "").lower() or None
    geom, prepared = _zone_geom(zone)
    pool: list[dict] = []
    for q in queries:
        rows = await _nominatim_rows(q, cc, limit=GEOCODE_CANDIDATE_LIMIT)
        for row in rows or []:
            _add_unique_cand(pool, _nominatim_cand(row))
        if len(pool) >= GEOCODE_CANDIDATE_LIMIT:
            break
        if pool and _pool_has_coastal(pool, port, zone, geom, prepared):
            break
        if pool and geom is None:
            break
    return pool[:GEOCODE_CANDIDATE_LIMIT]


async def _collect_geonames_candidates(port: dict, zone: dict) -> list[dict]:
    name = port["name"]
    territory = zone.get("name") or ""
    cc = (zone.get("iso2") or "").upper() or None
    geom, prepared = _zone_geom(zone)
    pool: list[dict] = []
    for q, country in ((name, cc), (f"{name} {territory}", None)):
        rows = await _geonames_rows(q, country, limit=GEOCODE_CANDIDATE_LIMIT)
        for row in rows or []:
            _add_unique_cand(pool, _geonames_cand(row))
        if len(pool) >= GEOCODE_CANDIDATE_LIMIT:
            break
        if pool and _pool_has_coastal(pool, port, zone, geom, prepared):
            break
        if pool and geom is None:
            break
    return pool[:GEOCODE_CANDIDATE_LIMIT]


async def _geocode_port_nominatim(port: dict, zone: dict) -> dict | None:
    """Meilleur Nominatim après score ; None si aucun hit."""
    pool = await _collect_nominatim_candidates(port, zone)
    if not pool:
        return None
    geom, prepared = _zone_geom(zone)
    sel = select_geocode_candidate(pool, port, zone, geom, prepared)
    chosen = sel.get("chosen") or pool[0]
    if chosen.get("lat") is None:
        chosen = pool[0]
    return {
        "lat": float(chosen["lat"]),
        "lon": float(chosen["lon"]),
        "osm_class": chosen.get("osm_class") or "",
        "osm_type": chosen.get("osm_type") or "",
        "candidates": pool,
        "pick_status": sel.get("status"),
    }


async def _geocode_port_geonames(port: dict, zone: dict) -> dict | None:
    pool = await _collect_geonames_candidates(port, zone)
    if not pool:
        return None
    geom, prepared = _zone_geom(zone)
    sel = select_geocode_candidate(pool, port, zone, geom, prepared)
    chosen = sel.get("chosen") or pool[0]
    if chosen.get("lat") is None:
        chosen = pool[0]
    return {
        "lat": float(chosen["lat"]),
        "lon": float(chosen["lon"]),
        "geonames_fcode": chosen.get("geonames_fcode") or "",
        "candidates": pool,
        "pick_status": sel.get("status"),
    }


async def geocode_port_dual(port: dict, zone: dict, log=None) -> dict:
    """Nominatim ∥ GeoNames, puis score d'homonymes (ZEE, parenthèses, listing).

    Retourne aussi `candidates` et `pick` pour pick_geocode. L'accord < 2 km
    reste un signal ; il ne départage pas deux homonymes identiques.
    """
    log = log or (lambda m: None)
    nomi, geon = await asyncio.gather(
        _geocode_port_nominatim(port, zone),
        _geocode_port_geonames(port, zone),
    )
    agreement_km = None
    agree = None
    if nomi and geon and nomi.get("lat") is not None and geon.get("lat") is not None:
        agreement_km = round(haversine_km(
            nomi["lat"], nomi["lon"], geon["lat"], geon["lon"]), 2)
        agree = agreement_km <= 2.0
    if not nomi and not geon:
        log(f"géocodage: aucun résultat pour « {port['name']} »")
    candidates: list[dict] = []
    for hit in (nomi, geon):
        for c in (hit or {}).get("candidates") or []:
            _add_unique_cand(candidates, c)
    geom, prepared = _zone_geom(zone)
    pick = select_geocode_candidate(candidates, port, zone, geom, prepared) if candidates else {
        "status": "miss", "chosen": None, "ranked": [],
    }
    return {
        "nominatim": _xy(nomi),
        "geonames": _xy(geon),
        "nominatim_meta": {
            "osm_class": (nomi or {}).get("osm_class") or "",
            "osm_type": (nomi or {}).get("osm_type") or "",
        },
        "geonames_meta": {
            "geonames_fcode": (geon or {}).get("geonames_fcode") or "",
        },
        "agreement_km": agreement_km,
        "agree": agree,
        "geonames_available": geonames_status() == "ok",
        "candidates": candidates,
        "pick": {
            "status": pick.get("status"),
            "chosen": pick.get("chosen"),
            "ranked": pick.get("ranked") or [],
        },
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


# Le polygone VLIZ est en mer. Un quai est souvent juste à terre.
# 0,02° ≈ 2,2 km : sliver « encore la ZEE » (pas le vieux tampon 0,5° / 55 km).
# 15 km : bord terrestre côtier. Au-delà : seulement l'exception rivière.
IN_EEZ_SLIVER_KM = 2.2
COASTAL_LAND_KM = 15.0
INLAND_RIVER_MAX_KM = 400.0

_HARBOUR_NAME_RE = re.compile(
    r"\b(port|harbour|harbor|haven|hafen|puerto|porto|terminal|dock|wharf|"
    r"quai|marina|capitan[ií]a)\b",
    re.I,
)
_HARBOUR_OSM = {
    "harbour", "port", "ferry_terminal", "dock", "basin", "marina", "pier",
    "boatyard", "shipyard", "quay", "slipway",
}
_HARBOUR_GN = {"HBR", "HBRX", "PRT", "MAR", "ANCH", "JTY", "WHF"}


def harbour_evidence(port: dict | None = None, meta: dict | None = None) -> bool:
    """Le point ressemble à un port / un quai, pas à une ville intérieure."""
    meta = meta or {}
    port = port or {}
    osm = f"{meta.get('osm_class') or ''} {meta.get('osm_type') or ''}".lower()
    if any(tok in osm for tok in _HARBOUR_OSM):
        return True
    fcode = (meta.get("fcode") or meta.get("geonames_fcode") or "").upper()
    if fcode in _HARBOUR_GN:
        return True
    name = f"{port.get('name') or ''} {port.get('city') or ''}"
    if _HARBOUR_NAME_RE.search(name):
        return True
    if (port.get("extraction_engine") or "") == "catalog" and port.get("lat") is not None:
        return True
    if port.get("listing_role") == "poe":
        return True
    return False


def inland_exception_flags(port: dict | None, zone: dict | None,
                           meta: dict | None = None, *,
                           official_list: bool = False) -> dict:
    """Preuves pour l'exception rivière : CE pays (iso2 de la zone, pas le
    souverain) et un vrai port — pas une ville intérieure à 100 km."""
    zone = zone or {}
    iso = (zone.get("iso2") or "").strip()
    return {
        "country_ok": bool(iso) or official_list,
        "harbour_like": harbour_evidence(port, meta),
    }


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
                       coastal_km: float = COASTAL_LAND_KM,
                       inland: dict | None = None) -> dict:
    """Classe un candidat PoE par rapport à CETTE ZEE (pas snap_to_ocean).

    - in_eez         : dans le polygone, ou sliver ≤ 2,2 km → accepté
    - coastal_land   : à terre, ≤ 15 km du trait de côte de cette ZEE → accepté
    - inland_river   : exception — à terre, dans CE pays, jusqu'à 400 km,
                       seulement si c'est un port (pas une ville intérieure)
    - other_water    : en mer hors de cette ZEE → rejeté
    - inland         : trop loin / pas un port → rejeté

    `inland` = {country_ok, harbour_like}. Sans les deux, pas d'exception.
    """
    inland = inland or {}
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
        if dist is not None and dist <= IN_EEZ_SLIVER_KM:
            return {"kind": "in_eez", "validated": True, "dist_km": dist}
        on_land = not is_ocean(lat, lon)
        if on_land and dist is not None and dist <= coastal_km:
            return {"kind": "coastal_land", "validated": True, "dist_km": dist}
        if (on_land and dist is not None and dist <= INLAND_RIVER_MAX_KM
                and inland.get("country_ok") and inland.get("harbour_like")):
            return {"kind": "inland_river", "validated": True, "dist_km": dist}
        if on_land:
            return {"kind": "inland", "validated": False, "dist_km": dist}
        return {"kind": "other_water", "validated": False, "dist_km": dist}
    except Exception:
        return {"kind": "unknown", "validated": False, "dist_km": None}


def spatial_class_for_point(lat: float, lon: float, geom, prepared=None,
                            inland: dict | None = None) -> dict:
    """Nom public pour l'audit GPS confirmed — même contrat que classify_poe_point."""
    return classify_poe_point(lat, lon, geom, prepared=prepared, inland=inland)


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
