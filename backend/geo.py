import asyncio
import hashlib
import math

import httpx
from global_land_mask import globe

_geo_cache = {}
_geo_lock = asyncio.Lock()


def is_ocean(lat: float, lon: float) -> bool:
    lat = max(-89.9, min(89.9, lat))
    lon = ((lon + 180) % 360) - 180
    return bool(globe.is_ocean(lat, lon))


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _destination(lat, lon, bearing_deg, dist_km):
    r = 6371.0
    br = math.radians(bearing_deg)
    p1 = math.radians(lat)
    l1 = math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(dist_km / r) + math.cos(p1) * math.sin(dist_km / r) * math.cos(br))
    l2 = l1 + math.atan2(math.sin(br) * math.sin(dist_km / r) * math.cos(p1),
                         math.cos(dist_km / r) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), ((math.degrees(l2) + 180) % 360) - 180


def snap_to_ocean(lat: float, lon: float, max_km: float = 500.0):
    """Return nearest ocean point (lat, lon, snapped_bool)."""
    if is_ocean(lat, lon):
        return lat, lon, False
    for radius in [10, 25, 50, 75, 100, 150, 200, 300, 400, int(max_km)]:
        if radius > max_km:
            break
        for bearing in range(0, 360, 20):
            nlat, nlon = _destination(lat, lon, bearing, radius)
            if is_ocean(nlat, nlon):
                return nlat, nlon, True
    return lat, lon, False


def coast_distance_km(lat: float, lon: float) -> float:
    """Approximate distance from an inland point to the nearest ocean."""
    if is_ocean(lat, lon):
        return 0.0
    for radius in [10, 25, 50, 75, 100, 150, 200, 300, 400, 500]:
        for bearing in range(0, 360, 30):
            nlat, nlon = _destination(lat, lon, bearing, radius)
            if is_ocean(nlat, nlon):
                return float(radius)
    return 999.0


async def geocode(query: str):
    if not query:
        return None
    key = query.strip().lower()
    if key in _geo_cache:
        return _geo_cache[key]
    async with _geo_lock:
        if key in _geo_cache:
            return _geo_cache[key]
        try:
            await asyncio.sleep(1.1)
            async with httpx.AsyncClient(timeout=12) as client:
                r = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": query, "format": "json", "limit": 1},
                    headers={"User-Agent": "BlueIntelligence/1.0 (osint@blueintelligence.online)"},
                )
                data = r.json()
                if data:
                    coords = (float(data[0]["lat"]), float(data[0]["lon"]))
                    _geo_cache[key] = coords
                    return coords
        except Exception:
            pass
        _geo_cache[key] = None
        return None


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
