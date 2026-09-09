"""Identité : deux règles, deux codes.

Même famille taxonomique (« est-ce déjà là ? »), deux décisions métier.
On ne les mélange pas.

* ``same_site`` — fusionner deux fiches du même *lieu d'action*
  (Projets / ports d'entrée). 500 m **et** un nom proche, ou 90 % de
  similarité seule. Une seule fiche enrichie.
* ``find_building`` — superposer un calque officiel (SHOM / NOAA) sur un
  bureau OSM. 250 m, **distance seule**. Un nom différent n'empêche pas
  le calque ; un nom proche à 400 m ne colle pas deux bureaux.

Réutiliser ``same_site`` pour les capitaineries collerait des bureaux trop
loin, ou refuserait un calque légitime. Ce n'est pas un chantier
d'unification Overpass (déjà partagé). C'est un garde-fou.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from app.core.dedup import is_duplicate
from app.core.geo import haversine_km

OVERLAY_RADIUS_KM = 0.25
_KM_PER_DEG = 111.32
_BBOX_SLACK = 1.05


@dataclass(frozen=True)
class OverlayHit:
    """Calque : le bureau le plus proche, et à quelle distance."""

    doc: dict
    distance_km: float


def same_site(
    doc_a: dict,
    doc_b: dict,
    lat_key: str = "lat",
    lon_key: str = "lon",
    title_key: str = "title",
) -> bool:
    """Même site d'action (Projets / PoE). Pas un calque de bâtiment."""
    return is_duplicate(
        doc_a, doc_b, lat_key=lat_key, lon_key=lon_key, title_key=title_key,
    )


def building_radius_km() -> float:
    """Rayon du calque OSM↔SHOM↔NOAA. Catalogue ``capitaineries.merge_km``."""
    from app.core.run_rules import get_rule
    return float(get_rule("capitaineries.merge_km", OVERLAY_RADIUS_KM))


def coords_of(doc: dict, lat_key: str = "lat", lon_key: str = "lon"):
    """(lat, lon) ou None. Pas de NaN, pas de chaîne vide déguisée."""
    try:
        lat, lon = doc.get(lat_key), doc.get(lon_key)
        if lat is None or lon is None or lat == "" or lon == "":
            return None
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError, AttributeError):
        return None
    if not math.isfinite(lat_f) or not math.isfinite(lon_f):
        return None
    if not -90.0 <= lat_f <= 90.0:
        return None
    return lat_f, lon_f


def _lon_delta_deg(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _in_bbox(lat: float, lon: float, plat: float, plon: float, radius_km: float) -> bool:
    """Préfiltre degré : évite un haversine sur tout le dump mondial."""
    reach = radius_km * _BBOX_SLACK
    if abs(plat - lat) * _KM_PER_DEG > reach:
        return False
    km_lon = _KM_PER_DEG * max(abs(math.cos(math.radians(lat))), 0.05)
    return _lon_delta_deg(plon, lon) * km_lon <= reach


def find_building(
    lat: float,
    lon: float,
    pts: Sequence[dict] | Iterable[dict],
    radius_km: float | None = None,
    lat_key: str = "lat",
    lon_key: str = "lon",
) -> OverlayHit | None:
    """Bureau le plus proche à ≤ ``radius_km`` (défaut 250 m).

    Distance seule : le nom n'entre pas dans la décision. En cas d'égalité
    stricte, le premier document de la liste gagne (stable, pas last-wins).
    """
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(lat_f) or not math.isfinite(lon_f):
        return None
    radius = float(radius_km if radius_km is not None else building_radius_km())
    if radius < 0:
        return None
    best: OverlayHit | None = None
    for doc in pts or ():
        xy = coords_of(doc, lat_key=lat_key, lon_key=lon_key)
        if xy is None:
            continue
        plat, plon = xy
        if not _in_bbox(lat_f, lon_f, plat, plon, radius):
            continue
        dist = haversine_km(lat_f, lon_f, plat, plon)
        if dist > radius:
            continue
        if best is None or dist < best.distance_km:
            best = OverlayHit(doc=doc, distance_km=dist)
    return best
