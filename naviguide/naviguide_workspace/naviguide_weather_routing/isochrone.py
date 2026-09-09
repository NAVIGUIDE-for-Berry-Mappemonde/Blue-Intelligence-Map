"""
NAVIGUIDE Weather Routing — Isochrone Engine
============================================
Implements the classical isochrone algorithm used in OpenCPN Weather Routing.

Algorithm overview
------------------
1. Start with a single point (departure).
2. Each step: from every live point, propagate on all headings using
   boat speed from polar + local wind from climatology model.
3. Keep only the outer envelope per angular sector (pruning).
4. Repeat until destination is enclosed or max iterations reached.
5. Trace back through parent chain to reconstruct optimal route.

Obstacle avoidance
------------------
Two layered checks are applied to every candidate propagation point:

1. Land mask — global_land_mask (1/4° GSHHS) or conservative bounding-box
   fallback. Points that fall on land are discarded.

2. Shallow-water hazard zones — GEBCO Option-C database (bathymetry.py):
   ~30 pre-computed critical zones (Torres Strait, Bahama Banks, Red Sea
   shoals, Dangerous Ground / Spratly Islands, etc.) at "hazardous" severity
   threshold by default. Navigable channels within straits are intentionally
   left open; only the surrounding impassable reef/bank platforms are blocked.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, List, Optional, Tuple

try:
    from global_land_mask import globe as _globe
    _USE_GLOBAL_LAND_MASK = True
except ImportError:
    _USE_GLOBAL_LAND_MASK = False

from .polar       import BoatPolar
from .climatology import wind_at
from .bathymetry  import is_shallow_hazard


# ── Geodetic utilities ────────────────────────────────────────────────────────

_R_NM = 3440.065   # Earth radius, nautical miles

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi  = math.radians(lat2 - lat1)
    dlam  = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return 2 * _R_NM * math.asin(math.sqrt(a))


def move_position(lat: float, lon: float,
                  bearing_deg: float, dist_nm: float) -> Tuple[float, float]:
    """
    Return (lat2, lon2) after moving `dist_nm` nautical miles on `bearing_deg`
    from (lat, lon). Uses spherical Earth.
    """
    d    = dist_nm / _R_NM       # angular distance (radians)
    b    = math.radians(bearing_deg)
    φ1   = math.radians(lat)
    λ1   = math.radians(lon)

    φ2 = math.asin(
        math.sin(φ1)*math.cos(d) + math.cos(φ1)*math.sin(d)*math.cos(b)
    )
    λ2 = λ1 + math.atan2(
        math.sin(b)*math.sin(d)*math.cos(φ1),
        math.cos(d) - math.sin(φ1)*math.sin(φ2)
    )
    lat2 = math.degrees(φ2)
    lon2 = (math.degrees(λ2) + 540) % 360 - 180   # normalise to [-180, 180]
    return (round(lat2, 5), round(lon2, 5))


def bearing_to(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2 (0–360°)."""
    φ1 = math.radians(lat1);  φ2 = math.radians(lat2)
    Δλ = math.radians(lon2 - lon1)
    x  = math.sin(Δλ) * math.cos(φ2)
    y  = math.cos(φ1)*math.sin(φ2) - math.sin(φ1)*math.cos(φ2)*math.cos(Δλ)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


# ── Land mask ─────────────────────────────────────────────────────────────────
# Uses global_land_mask (1/4° GSHHS-derived, ~1.8 MB) when available,
# falling back to conservative bounding boxes for robustness.
#
# GEBCO bathymetry (shallow-water avoidance, min depth check) would be the
# next layer to add for complete routing safety — currently not implemented.

_LAND_BOXES_FALLBACK = [
    (30,  65, -125, -58),   # North America interior
    (9,   20, -88,  -76),   # Central America
    (-45, 8,  -72,  -40),   # South America interior
    (42,  65,  5,   35),    # Europe interior
    (-28, 32,  0,   42),    # Africa interior
    (15,  28, 38,   58),    # Arabian Peninsula
    (10,  28, 72,   85),    # Indian subcontinent
    (-5,  22, 95,  115),    # South-East Asia
    (-38, -18, 120, 145),   # Australia interior
    (-90, -63, -180, 180),  # Antarctica
    (62,  82, -52,  -20),   # Greenland interior
    (-23, -13, 44,   49),   # Madagascar interior
]


def _is_land(lat: float, lon: float) -> bool:
    """
    Returns True if (lat, lon) is on land.
    Uses global_land_mask (1/4° resolution) when available,
    otherwise falls back to interior bounding boxes.
    """
    if _USE_GLOBAL_LAND_MASK:
        try:
            return bool(_globe.is_land(lat, lon))
        except Exception:
            pass
    # Fallback: conservative bounding boxes
    for (la, lb, loa, lob) in _LAND_BOXES_FALLBACK:
        if la <= lat <= lb and loa <= lon <= lob:
            return True
    return False


# Number of intermediate samples along each propagation segment.
# global_land_mask resolution ≈ 1/4° ≈ 15 nm.
# At 6 h × 15 kn = 90 nm max step, checking every 90/8 ≈ 11 nm catches
# any land feature wider than one grid cell (≥ 15 nm), including the
# Iberian Peninsula, Morocco, Gulf of Guinea bulge, etc.
_PATH_SAMPLES = 8


def _is_path_clear(lat1: float, lon1: float,
                   lat2: float, lon2: float) -> bool:
    """
    Return True if the great-circle segment from (lat1,lon1) to (lat2,lon2)
    is entirely free of land AND shallow hazards.

    Samples _PATH_SAMPLES intermediate positions along the path (linear
    interpolation, good enough for ≤ 90 nm segments) plus the endpoint.
    The departure point (lat1, lon1) is assumed already validated.

    This catches the "land-crossing" bug where both endpoints are ocean but
    the straight-line step passes through a peninsula (e.g. Iberia, Morocco,
    Gulf of Guinea, SE Asia land bridges).
    """
    n = _PATH_SAMPLES
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    # Handle antimeridian wrapping for longitude interpolation
    if dlon > 180:
        dlon -= 360
    elif dlon < -180:
        dlon += 360

    for i in range(1, n + 1):          # i=1…n includes the endpoint
        t = i / n
        lat = lat1 + t * dlat
        lon = (lon1 + t * dlon + 540) % 360 - 180
        if _is_land(lat, lon):
            return False
        # Only check shallow hazards at the endpoint (zones are large enough
        # that intermediate checks would be redundant and expensive)
        if i == n and is_shallow_hazard(lat, lon, "hazardous"):
            return False
    return True


# ── Isochrone point ───────────────────────────────────────────────────────────

@dataclass
class IsoPoint:
    lat:         float
    lon:         float
    time:        datetime
    heading:     float        = 0.0
    boat_speed:  float        = 0.0
    wind_speed:  float        = 0.0
    wind_dir:    float        = 0.0
    parent:      Optional['IsoPoint'] = field(default=None, repr=False)

    def to_dict(self):
        return {
            "lat":        self.lat,
            "lon":        self.lon,
            "time":       self.time.isoformat(),
            "heading":    self.heading,
            "boat_speed": self.boat_speed,
            "wind_speed": self.wind_speed,
            "wind_dir":   self.wind_dir,
        }


# ── Isochrone propagation ─────────────────────────────────────────────────────

def _propagate(
    prev_points:       List[IsoPoint],
    polar:             BoatPolar,
    time_step_h:       float,
    heading_step_deg:  int,
    current_time:      datetime,
) -> List[IsoPoint]:
    """
    Expand one isochrone step: for every live point, try all headings.
    Returns the full (unpruned) list of candidate next positions.
    """
    month  = current_time.month
    next_t = current_time + timedelta(hours=time_step_h)
    result = []

    for pt in prev_points:
        wind_spd, wind_dir = wind_at(pt.lat, pt.lon, month)

        for hdg in range(0, 360, heading_step_deg):
            # True Wind Angle
            twa = (hdg - wind_dir + 360) % 360
            if twa > 180:
                twa = 360 - twa

            spd = polar.get_speed(wind_spd, twa)
            if spd < 0.3:
                continue                     # no-go zone or calm

            dist_nm = spd * time_step_h
            nlat, nlon = move_position(pt.lat, pt.lon, hdg, dist_nm)

            # Bounds check
            if not (-85 <= nlat <= 85):
                continue
            # Path-clear check: samples _PATH_SAMPLES points along the
            # full segment (not just the endpoint) to catch land-crossing
            # trajectories through peninsulas, isthmuses, etc.
            # Also validates shallow hazards at the endpoint.
            if not _is_path_clear(pt.lat, pt.lon, nlat, nlon):
                continue

            result.append(IsoPoint(
                lat        = nlat,
                lon        = nlon,
                time       = next_t,
                heading    = float(hdg),
                boat_speed = spd,
                wind_speed = wind_spd,
                wind_dir   = wind_dir,
                parent     = pt,
            ))

    return result


def _prune(points: List[IsoPoint], sectors: int = 72) -> List[IsoPoint]:
    """
    Keep only the point furthest from the global centroid in each angular
    sector.  This gives the outer convex-ish envelope of the isochrone.
    """
    if not points:
        return []

    # Centroid (ignore antimeridian wrapping for simplicity — works well
    # for typical voyage legs that don't span > 180° of longitude)
    cen_lat = sum(p.lat for p in points) / len(points)
    cen_lon = sum(p.lon for p in points) / len(points)

    sec_size = 360.0 / sectors
    best: dict[int, Tuple[float, IsoPoint]] = {}

    for p in points:
        brg = bearing_to(cen_lat, cen_lon, p.lat, p.lon)
        sec = int(brg / sec_size) % sectors
        dist = haversine(cen_lat, cen_lon, p.lat, p.lon)
        if sec not in best or dist > best[sec][0]:
            best[sec] = (dist, p)

    return [v[1] for v in best.values()]


# ── Main algorithm ────────────────────────────────────────────────────────────

def run_isochrones(
    dep_lat:          float,
    dep_lon:          float,
    dst_lat:          float,
    dst_lon:          float,
    departure_time:   datetime,
    polar:            Optional[BoatPolar] = None,
    time_step_h:      float = 6.0,
    heading_step_deg: int   = 10,
    max_steps:        int   = 120,
    arrival_radius_nm:float = 50.0,
    prune_sectors:    int   = 72,
) -> dict:
    """
    Run the isochrone algorithm between (dep_lat, dep_lon) and (dst_lat, dst_lon).

    Returns a dict with:
      - "status"          : "arrived" | "max_steps_reached"
      - "route"           : list of IsoPoint dicts (departure → destination)
      - "isochrones"      : list of isochrone snapshots for visualisation
      - "duration_hours"  : estimated voyage time
      - "distance_nm"     : great-circle departure→destination distance
      - "avg_speed_knots" : average speed over the route
    """
    if polar is None:
        polar = BoatPolar()

    start = IsoPoint(lat=dep_lat, lon=dep_lon, time=departure_time)
    current_iso = [start]
    all_isos: List[List[dict]] = [[start.to_dict()]]

    best_arrival: Optional[IsoPoint] = None
    steps_taken  = 0
    gc_dist      = haversine(dep_lat, dep_lon, dst_lat, dst_lon)

    for step in range(max_steps):
        current_time = departure_time + timedelta(hours=step * time_step_h)

        # --- propagate ---
        candidates = _propagate(current_iso, polar, time_step_h,
                                 heading_step_deg, current_time)
        if not candidates:
            break

        # --- check arrival ---
        for pt in candidates:
            d = haversine(pt.lat, pt.lon, dst_lat, dst_lon)
            if d <= arrival_radius_nm:
                best_arrival = pt
                break

        if best_arrival:
            steps_taken = step + 1
            break

        # --- prune to envelope ---
        current_iso = _prune(candidates, prune_sectors)
        all_isos.append([p.to_dict() for p in current_iso])
        steps_taken = step + 1

    # ── Trace-back route ──────────────────────────────────────────────────────
    route_points: List[IsoPoint] = []
    if best_arrival:
        node: Optional[IsoPoint] = best_arrival
        while node is not None:
            route_points.append(node)
            node = node.parent
        route_points.reverse()
        # Append destination marker
        dest_time = best_arrival.time + timedelta(
            hours=haversine(best_arrival.lat, best_arrival.lon,
                            dst_lat, dst_lon) / max(best_arrival.boat_speed, 0.1)
        )
        route_points.append(IsoPoint(lat=dst_lat, lon=dst_lon, time=dest_time))
        status = "arrived"
    else:
        # Return closest point to destination from last isochrone
        if current_iso:
            closest = min(current_iso,
                          key=lambda p: haversine(p.lat, p.lon, dst_lat, dst_lon))
            node = closest
            while node:
                route_points.append(node)
                node = node.parent
            route_points.reverse()
        status = "max_steps_reached"

    # ── Statistics ────────────────────────────────────────────────────────────
    duration_h = steps_taken * time_step_h
    avg_speed  = gc_dist / duration_h if duration_h > 0 else 0.0

    return {
        "status":          status,
        "route":           [p.to_dict() for p in route_points],
        "isochrones":      all_isos,
        "duration_hours":  round(duration_h, 1),
        "duration_days":   round(duration_h / 24, 1),
        "distance_nm":     round(gc_dist, 1),
        "avg_speed_knots": round(avg_speed, 2),
        "steps_computed":  steps_taken,
    }
