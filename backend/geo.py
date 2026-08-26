"""
geo.py — Wrapper de rétrocompatibilité au-dessus de geo_core (Core mutualisé).
"""
from geo_core import (  # noqa: F401
    coast_distance_km,
    geocode,
    haversine_km,
    is_ocean,
    ocean_fallback_coords,
    snap_to_ocean,
)
