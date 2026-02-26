"""
NAVIGUIDE Weather Routing — Global Climatological Wind Model
============================================================
Provides a month-aware wind model covering all ocean basins relevant
to the Berry-Mappemonde circumnavigation.

Sources / references
--------------------
- NOAA Global Wind Climatology
- Pilot Charts (NGA)
- Ruttkowski & Cornell Ocean Atlas
- BA Wind Pilot (North & South Atlantic / Indian / Pacific)

All directions are "FROM" (meteorological convention).
Returns (wind_speed_knots: float, wind_direction_from: float).
"""

import math
from typing import Tuple


# ── Helpers ───────────────────────────────────────────────────────────────────

def _interp(v, v0, v1, r0, r1):
    """Linear interpolation."""
    if v1 == v0:
        return r0
    t = max(0.0, min(1.0, (v - v0) / (v1 - v0)))
    return r0 + t * (r1 - r0)


def _blend_direction(d1: float, d2: float, t: float) -> float:
    """Circular blend of two wind directions (0–360)."""
    diff = ((d2 - d1 + 180) % 360) - 180
    return (d1 + t * diff) % 360


# ── Main wind function ────────────────────────────────────────────────────────

def get_climatological_wind(
    lat: float,
    lon: float,
    month: int,           # 1–12
) -> Tuple[float, float]:
    """
    Return (wind_speed_knots, wind_direction_from_degrees) for the given
    position and month using a multi-zone global climatological model.

    Zones (evaluated in order, first match wins):
      1. Polar (|lat| > 60)
      2. North Atlantic subtropical high / Azores High
      3. NE Trade Winds (5–25°N, Atlantic)
      4. South Atlantic / SE Trades
      5. North Indian Ocean (monsoon-driven)
      6. South Indian Ocean SE Trades
      7. North Pacific NE Trades
      8. South Pacific SE Trades
      9. Westerlies band (35–60° N or S)
     10. Roaring Forties / Furious Fifties (40–60°S)
     11. ITCZ / doldrums (±10° of equator)
     12. Default fallback
    """
    # ── 1. Polar regions ─────────────────────────────────────────────────────
    if lat > 60:
        spd = 18.0 + 4 * math.sin(math.radians(month * 30))
        return (round(spd, 1), 240.0)  # predominantly westerly
    if lat < -60:
        spd = 28.0 + 5 * math.sin(math.radians(month * 30))
        return (round(spd, 1), 270.0)  # strong westerlies

    # ── Helpers for longitude sectors ────────────────────────────────────────
    in_atlantic  = -80 <= lon <= 20
    in_indian    = 20  <= lon <= 120
    in_pacific   = (lon >= 120) or (lon <= -80)
    in_med       = -10 <= lon <= 40 and 30 <= lat <= 47

    # ── 2. Mediterranean Sea ─────────────────────────────────────────────────
    if in_med:
        if month in (6, 7, 8):           # summer: Mistral / Etesian (N/NW)
            return (14.0, 340.0)
        elif month in (12, 1, 2):        # winter: SW depressions
            return (16.0, 220.0)
        else:
            return (10.0, 300.0)

    # ── 3. North Atlantic — Azores High (25–40°N) ────────────────────────────
    if in_atlantic and 25 <= lat <= 40:
        if month in (6, 7, 8, 9):        # summer: high extended N, light winds
            return (10.0, 260.0)         # westerly on N flank
        else:                            # winter: more variable
            return (14.0, 240.0)

    # ── 4. NE Trade Winds — North Atlantic (5–25°N) ──────────────────────────
    if in_atlantic and 5 <= lat <= 25:
        if month in (12, 1, 2, 3):       # peak trades season
            spd = 18.0
        elif month in (6, 7, 8, 9):      # lighter (ITCZ displaced N)
            spd = 12.0
        else:
            spd = 15.0
        return (spd, 50.0)               # NE direction

    # ── 5. SE Trade Winds — South Atlantic (5–25°S) ─────────────────────────
    if in_atlantic and -25 <= lat <= 5:
        if month in (6, 7, 8):           # austral winter, stronger SE
            spd = 16.0
        else:
            spd = 13.0
        return (spd, 130.0)              # SE direction

    # ── 6. South Atlantic westerlies (25–50°S) ───────────────────────────────
    if in_atlantic and -50 <= lat <= -25:
        spd = 20.0 + 5 * (_interp(lat, -25, -50, 0, 1))
        return (round(spd, 1), 270.0)   # westerly

    # ── 7. North Indian Ocean — Arabian Sea / Bay of Bengal ──────────────────
    if in_indian and lat >= 5:
        if month in (6, 7, 8, 9):       # SW Monsoon
            return (20.0, 225.0)
        elif month in (12, 1, 2, 3):    # NE Monsoon
            return (14.0, 45.0)
        else:
            return (8.0, 90.0)          # transition

    # ── 8. SE Trades — South Indian Ocean (5–25°S) ───────────────────────────
    if in_indian and -25 <= lat <= 5:
        if month in (6, 7, 8):
            spd = 17.0
        else:
            spd = 13.0
        return (spd, 135.0)             # SE

    # ── 9. South Indian Ocean westerlies / Roaring 40s (25–60°S, Indian) ────
    if in_indian and -60 <= lat <= -25:
        spd = 22.0 + 8 * (_interp(lat, -25, -60, 0, 1))
        return (round(spd, 1), 270.0)

    # ── 10. NE Trade Winds — North Pacific (5–25°N) ─────────────────────────
    if in_pacific and 5 <= lat <= 25:
        if month in (12, 1, 2, 3):
            spd = 17.0
        elif month in (7, 8, 9):
            spd = 12.0
        else:
            spd = 14.0
        return (spd, 55.0)              # NE

    # ── 11. SE Trade Winds — South Pacific (5–30°S) ─────────────────────────
    if in_pacific and -30 <= lat <= 5:
        if month in (6, 7, 8, 9):
            spd = 16.0
        else:
            spd = 13.0
        return (spd, 120.0)             # ESE

    # ── 12. North Pacific westerlies (35–60°N) ───────────────────────────────
    if in_pacific and 35 <= lat <= 60:
        if month in (12, 1, 2, 3):      # stormy winter
            spd = 25.0
        else:
            spd = 16.0
        return (spd, 260.0)

    # ── 13. South Pacific westerlies / Roaring 40s (30–60°S) ────────────────
    if in_pacific and -60 <= lat <= -30:
        spd = 20.0 + 7 * (_interp(lat, -30, -60, 0, 1))
        return (round(spd, 1), 270.0)

    # ── 14. North Atlantic westerlies (40–60°N) ──────────────────────────────
    if in_atlantic and 40 <= lat <= 60:
        if month in (12, 1, 2):         # winter lows
            spd = 22.0
        else:
            spd = 15.0
        return (spd, 255.0)

    # ── 15. ITCZ / doldrums (within ±8° of equator) ─────────────────────────
    if abs(lat) <= 8:
        # ITCZ displacement: N in boreal summer, S in austral summer
        itcz_lat = 5 * math.sin(math.radians((month - 7) * 30))
        if abs(lat - itcz_lat) < 4:
            return (4.0, 200.0)         # very light variable

    # ── 16. Global Roaring Forties / Furious Fifties (40–60°S) ─────────────
    if -60 <= lat <= -40:
        spd = 25.0 + 5 * (_interp(lat, -40, -60, 0, 1))
        return (round(spd, 1), 275.0)

    # ── 17. Fallback ─────────────────────────────────────────────────────────
    return (10.0, 270.0)


def wind_at(lat: float, lon: float, month: int) -> Tuple[float, float]:
    """Public alias for get_climatological_wind."""
    return get_climatological_wind(lat, lon, month)
