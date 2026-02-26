"""
NAVIGUIDE — Weather Routing Service
====================================
FastAPI micro-service exposing the isochrone weather routing engine.
Port 3010 | URL https://4ocjcomc.run.complete.dev

Endpoints
---------
GET  /                              Health + capabilities
POST /api/v1/routing/leg            Optimal route for a single leg (A → B)
POST /api/v1/routing/expedition     Full expedition plan (N waypoints)
GET  /api/v1/routing/polar          Full polar table for the vessel
GET  /api/v1/routing/polar/summary  Polar summary at a given wind speed
GET  /api/v1/routing/wind           Climatological wind at a given position
"""

import os
import math
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .polar       import BoatPolar
from .isochrone   import run_isochrones, haversine, bearing_to
from .climatology import wind_at
from .bathymetry  import get_all_zones_geojson, get_hazard_zone, SHALLOW_ZONES

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(
    "/mnt/efs/spaces/ef014a98-8a1c-4b16-8e06-5d2c5b364d08"
    "/3838ab1e-0224-400b-b357-cd566e2f7d0b/logs"
)
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_DIR / "weather_routing.log"),
        logging.StreamHandler(),
    ],
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
)
log = logging.getLogger("weather_routing")

# ── Singleton polar ───────────────────────────────────────────────────────────
_polar = BoatPolar()

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="NAVIGUIDE Weather Routing",
    description=(
        "Isochrone-based sailing weather routing — "
        "mimics OpenCPN Weather Routing plugin for the Berry-Mappemonde expedition."
    ),
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic models ───────────────────────────────────────────────────────────

class LegRequest(BaseModel):
    dep_lat:           float
    dep_lon:           float
    dst_lat:           float
    dst_lon:           float
    departure_iso:     Optional[str] = None   # ISO-8601, defaults to now
    time_step_hours:   float = 6.0
    heading_step_deg:  int   = 10
    max_steps:         int   = 120
    arrival_radius_nm: float = 50.0


class WaypointIn(BaseModel):
    name: str
    lat:  float
    lon:  float


class ExpeditionRequest(BaseModel):
    waypoints:       List[WaypointIn]
    departure_iso:   Optional[str] = None
    time_step_hours: float = 6.0
    heading_step_deg:int   = 10


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_time(iso_str: Optional[str]) -> datetime:
    if not iso_str:
        return datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid datetime: {iso_str}")


def _result_to_geojson(result: dict, dep_name: str = "Departure",
                        dst_name: str = "Destination") -> dict:
    """Convert a run_isochrones result to a GeoJSON FeatureCollection."""
    features = []

    # Route line
    coords = [[p["lon"], p["lat"]] for p in result["route"]]
    if len(coords) >= 2:
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "type":             "optimal_route",
                "duration_hours":   result["duration_hours"],
                "duration_days":    result["duration_days"],
                "distance_nm":      result["distance_nm"],
                "avg_speed_knots":  result["avg_speed_knots"],
                "status":           result["status"],
            },
        })

    # Waypoint markers
    for i, pt in enumerate(result["route"]):
        label = dep_name if i == 0 else (dst_name if i == len(result["route"])-1 else f"WP{i}")
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [pt["lon"], pt["lat"]]},
            "properties": {
                "type":       "route_waypoint",
                "name":       label,
                "time":       pt["time"],
                "heading":    pt.get("heading"),
                "boat_speed": pt.get("boat_speed"),
                "wind_speed": pt.get("wind_speed"),
                "wind_dir":   pt.get("wind_dir"),
            },
        })

    # Isochrone snapshot lines (every 4th for brevity)
    for i, iso in enumerate(result["isochrones"]):
        if i % 4 != 0 or len(iso) < 3:
            continue
        iso_coords = [[p["lon"], p["lat"]] for p in iso]
        # Close the isochrone polygon
        iso_coords.append(iso_coords[0])
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": iso_coords},
            "properties": {
                "type":       "isochrone",
                "step":       i,
                "time":       iso[0]["time"],
                "point_count": len(iso),
            },
        })

    return {
        "type": "FeatureCollection",
        "metadata": {
            "source":          "NAVIGUIDE Weather Routing",
            "algorithm":       "Isochrone (climatological wind)",
            "status":          result["status"],
            "duration_days":   result["duration_days"],
            "distance_nm":     result["distance_nm"],
            "avg_speed_knots": result["avg_speed_knots"],
        },
        "features": features,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
def health():
    return {
        "service":    "NAVIGUIDE Weather Routing",
        "version":    "1.1.0",
        "status":     "operational",
        "algorithm":  "Isochrone (climatological wind model)",
        "polar":      "Berry-Mappemonde (high-performance multihull)",
        "obstacle_avoidance": {
            "land_mask":   "global_land_mask (1/4° GSHHS)",
            "shallow_zones": f"GEBCO Option-C ({len(SHALLOW_ZONES)} zones)",
        },
        "endpoints":  [
            "POST /api/v1/routing/leg",
            "POST /api/v1/routing/expedition",
            "GET  /api/v1/routing/polar",
            "GET  /api/v1/routing/polar/summary?tws=15",
            "GET  /api/v1/routing/wind?lat=20&lon=-30&month=1",
            "GET  /api/v1/routing/bathymetry/zones",
            "GET  /api/v1/routing/bathymetry/check?lat=10&lon=142",
        ],
    }


@app.post("/api/v1/routing/leg")
def route_leg(req: LegRequest):
    """
    Compute the time-optimal sailing route between two points.

    The engine runs isochrones using climatological wind and the vessel's
    polar curve, returning the fastest path through the prevailing conditions.
    """
    log.info(f"Leg routing: ({req.dep_lat},{req.dep_lon}) → ({req.dst_lat},{req.dst_lon})")
    dep_time = _parse_time(req.departure_iso)

    try:
        result = run_isochrones(
            dep_lat           = req.dep_lat,
            dep_lon           = req.dep_lon,
            dst_lat           = req.dst_lat,
            dst_lon           = req.dst_lon,
            departure_time    = dep_time,
            polar             = _polar,
            time_step_h       = req.time_step_hours,
            heading_step_deg  = req.heading_step_deg,
            max_steps         = req.max_steps,
            arrival_radius_nm = req.arrival_radius_nm,
        )
    except Exception as exc:
        log.error(f"Isochrone error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    geojson = _result_to_geojson(result)
    log.info(
        f"Leg complete: status={result['status']} "
        f"dur={result['duration_days']}d avg={result['avg_speed_knots']}kn"
    )
    return {
        "status":          result["status"],
        "duration_hours":  result["duration_hours"],
        "duration_days":   result["duration_days"],
        "distance_nm":     result["distance_nm"],
        "avg_speed_knots": result["avg_speed_knots"],
        "steps_computed":  result["steps_computed"],
        "geojson":         geojson,
    }


@app.post("/api/v1/routing/expedition")
def route_expedition(req: ExpeditionRequest):
    """
    Compute sequential weather-routed legs for a multi-waypoint expedition.
    Each leg departure time is estimated from the previous leg's arrival.

    Returns per-leg results + a merged GeoJSON FeatureCollection covering
    the full expedition.
    """
    if len(req.waypoints) < 2:
        raise HTTPException(status_code=422, detail="At least 2 waypoints required.")

    log.info(f"Expedition routing: {len(req.waypoints)} waypoints")
    dep_time = _parse_time(req.departure_iso)

    all_features: List[dict] = []
    legs_summary: List[dict] = []
    current_time = dep_time

    for i in range(len(req.waypoints) - 1):
        wp_a = req.waypoints[i]
        wp_b = req.waypoints[i + 1]

        log.info(f"  Leg {i+1}: {wp_a.name} → {wp_b.name}")
        try:
            result = run_isochrones(
                dep_lat          = wp_a.lat,
                dep_lon          = wp_a.lon,
                dst_lat          = wp_b.lat,
                dst_lon          = wp_b.lon,
                departure_time   = current_time,
                polar            = _polar,
                time_step_h      = req.time_step_hours,
                heading_step_deg = req.heading_step_deg,
                max_steps        = 150,
                arrival_radius_nm= 60.0,
            )
        except Exception as exc:
            log.error(f"  Leg {i+1} error: {exc}")
            result = {
                "status": "error",
                "duration_hours": 0,
                "duration_days": 0,
                "distance_nm": haversine(wp_a.lat, wp_a.lon, wp_b.lat, wp_b.lon),
                "avg_speed_knots": 0,
                "steps_computed": 0,
                "route": [],
                "isochrones": [],
            }

        geo = _result_to_geojson(result, dep_name=wp_a.name, dst_name=wp_b.name)
        # Tag each feature with leg info
        for f in geo["features"]:
            f["properties"]["leg_index"] = i + 1
            f["properties"]["leg_from"]  = wp_a.name
            f["properties"]["leg_to"]    = wp_b.name
        all_features.extend(geo["features"])

        # Wind at midpoint for context
        mid_lat = (wp_a.lat + wp_b.lat) / 2
        mid_lon = (wp_a.lon + wp_b.lon) / 2
        wind_spd, wind_dir = wind_at(mid_lat, mid_lon, current_time.month)

        legs_summary.append({
            "leg_index":       i + 1,
            "from":            wp_a.name,
            "to":              wp_b.name,
            "departure":       current_time.isoformat(),
            "duration_days":   result["duration_days"],
            "distance_nm":     result["distance_nm"],
            "avg_speed_knots": result["avg_speed_knots"],
            "status":          result["status"],
            "prevailing_wind": {
                "speed_knots":  wind_spd,
                "direction_from": wind_dir,
            },
        })

        # Advance current time by leg duration (+ 12 h port stop for waypoints)
        current_time += timedelta(hours=result["duration_hours"] + 12)

    total_nm   = sum(l["distance_nm"] for l in legs_summary)
    total_days = sum(l["duration_days"] for l in legs_summary)

    merged_geojson = {
        "type": "FeatureCollection",
        "metadata": {
            "source":        "NAVIGUIDE Weather Routing — Expedition",
            "algorithm":     "Isochrone (climatological wind)",
            "total_legs":    len(legs_summary),
            "total_nm":      round(total_nm, 1),
            "total_days":    round(total_days, 1),
            "departure":     req.departure_iso or "now",
        },
        "features": all_features,
    }

    log.info(
        f"Expedition complete: {len(legs_summary)} legs, "
        f"{round(total_nm)} nm, {round(total_days)} days"
    )
    return {
        "total_legs":      len(legs_summary),
        "total_nm":        round(total_nm, 1),
        "total_days":      round(total_days, 1),
        "estimated_arrival": current_time.isoformat(),
        "legs":            legs_summary,
        "geojson":         merged_geojson,
    }


@app.get("/api/v1/routing/polar")
def get_polar():
    """Return the full polar performance table for the vessel."""
    table = []
    for twa in _polar.TWA_ANGLES:
        row = {"twa": twa}
        for tws in _polar.TWS_SPEEDS:
            row[f"tws_{tws}"] = _polar.get_speed(tws, twa)
        table.append(row)
    return {
        "vessel":      "Berry-Mappemonde (bluewater cruiser ~13 m)",
        "twa_angles":  _polar.TWA_ANGLES,
        "tws_speeds":  _polar.TWS_SPEEDS,
        "polar_table": table,
    }


@app.get("/api/v1/routing/polar/summary")
def get_polar_summary(tws: float = Query(15.0, ge=0, le=60, description="True Wind Speed in knots")):
    """Return polar summary (upwind/beam/downwind VMG) at the given TWS."""
    return _polar.polar_summary(tws)


@app.get("/api/v1/routing/bathymetry/zones")
def get_bathymetry_zones():
    """
    Return all pre-computed shallow-water hazard zones as a GeoJSON
    FeatureCollection.  Use this to render danger overlays on the chart.

    Severity colour guide for MapLibre:
      impassable → #e74c3c (red)
      hazardous  → #e67e22 (orange)
      caution    → #f1c40f (yellow)
    """
    return get_all_zones_geojson()


@app.get("/api/v1/routing/bathymetry/check")
def check_bathymetry_point(
    lat: float = Query(..., ge=-90,  le=90,  description="Latitude"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude"),
):
    """
    Check if a specific coordinate falls within a shallow-water hazard zone.
    Useful for validating waypoints before departure.
    """
    zone = get_hazard_zone(lat, lon)
    if zone:
        return {
            "lat": lat,
            "lon": lon,
            "hazard": True,
            "zone_name":    zone.name,
            "severity":     zone.severity,
            "typ_depth_m":  zone.typ_depth_m,
            "note":         zone.note,
        }
    return {
        "lat":    lat,
        "lon":    lon,
        "hazard": False,
        "zone_name": None,
    }


@app.get("/api/v1/routing/wind")
def get_wind_climatology(
    lat:   float = Query(..., ge=-90,  le=90),
    lon:   float = Query(..., ge=-180, le=180),
    month: int   = Query(1,   ge=1,    le=12),
):
    """Return the climatological wind for a given position and month."""
    spd, direction = wind_at(lat, lon, month)
    return {
        "lat":             lat,
        "lon":             lon,
        "month":           month,
        "wind_speed_knots": spd,
        "wind_direction_from": direction,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", 3010))
    uvicorn.run("naviguide_weather_routing.main:app", host="0.0.0.0", port=port, reload=False)
