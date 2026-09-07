"""Règles de publication d'un site projet (CDC v2).

Pas de snap_to_ocean, pas de ocean_fallback_coords : un point n'est
publiable que s'il est déjà en mer ou assez près de la côte (havre).
Les seuils viennent des settings, pas de constantes magiques du pipeline.
"""
from app.core.geo import coast_distance_km, is_ocean


def valid_coords(lat, lon) -> bool:
    try:
        return (
            lat is not None
            and lon is not None
            and -90 <= float(lat) <= 90
            and -180 <= float(lon) <= 180
            and not (float(lat) == 0 and float(lon) == 0)
        )
    except (TypeError, ValueError):
        return False


def site_publishable(lat, lon, settings: dict | None = None) -> tuple[bool, str]:
    """(ok, reason) — reason ∈ ocean | coastal | no_coords | inland."""
    s = settings or {}
    if not valid_coords(lat, lon):
        return False, "no_coords"
    lat_f, lon_f = float(lat), float(lon)
    if is_ocean(lat_f, lon_f):
        return True, "ocean"
    max_inland = float(s.get("max_inland_km", 15))
    dist = coast_distance_km(lat_f, lon_f)
    if dist <= max_inland:
        return True, "coastal"
    return False, "inland"
