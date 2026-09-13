"""N1 — point / crossings climatologie sans Source MapLibre.

Même snapshots que Blue Intelligence. NAVIGUIDE s'en sert (isochrone,
simulation, agent) ; il ne les peint pas.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2] / "backend"
if _BACKEND.is_dir() and str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _services():
    from app.services.climatology_common import (
        CURRENT_PERIOD,
        CYCLONE_PERIOD,
        KIND,
        PERIOD_SUMMARY,
        PROVENANCE,
        WAVE_PERIOD,
        WIND_PERIOD,
        empty_blocks,
        is_land,
        parse_month,
        snapshot_status,
    )
    from app.services.climatology_current import current_at
    from app.services.climatology_cyclones import crossings as cyclone_crossings
    from app.services.climatology_cyclones import nearby_count, tracks_in_month
    from app.services.climatology_wave import wave_at
    from app.services.climatology_wind import atlas_at
    return {
        "KIND": KIND,
        "PERIOD_SUMMARY": PERIOD_SUMMARY,
        "PROVENANCE": PROVENANCE,
        "WIND_PERIOD": WIND_PERIOD,
        "WAVE_PERIOD": WAVE_PERIOD,
        "CURRENT_PERIOD": CURRENT_PERIOD,
        "CYCLONE_PERIOD": CYCLONE_PERIOD,
        "empty_blocks": empty_blocks,
        "is_land": is_land,
        "parse_month": parse_month,
        "snapshot_status": snapshot_status,
        "current_at": current_at,
        "cyclone_crossings": cyclone_crossings,
        "nearby_count": nearby_count,
        "tracks_in_month": tracks_in_month,
        "wave_at": wave_at,
        "atlas_at": atlas_at,
    }


def meta(month: int = 1) -> dict:
    s = _services()
    month = s["parse_month"](month)
    return {
        "kind": s["KIND"],
        "month": month,
        "period": s["PERIOD_SUMMARY"],
        "periods": {
            "wind": s["WIND_PERIOD"],
            "wave": s["WAVE_PERIOD"],
            "current": s["CURRENT_PERIOD"],
            "cyclone": s["CYCLONE_PERIOD"],
        },
        "provenance": s["PROVENANCE"],
        "snapshot": s["snapshot_status"](),
        "painted": False,
    }


def point(lat: float, lon: float, month: int, dest_lat=None, dest_lon=None, day=None) -> dict:
    s = _services()
    month = s["parse_month"](month)
    land = s["is_land"](lat, lon)
    blocks = s["empty_blocks"]()
    if not land:
        blocks["wind_atlas"] = s["atlas_at"](lat, lon, month)
        blocks["wave"] = s["wave_at"](lat, lon, month)
        blocks["current"] = s["current_at"](lat, lon, month)
    blocks["cyclone"] = {
        "tracks_in_month": s["tracks_in_month"](month),
        "nearby": s["nearby_count"](lat, lon, month) if not land else 0,
        "crossings_if_leg": None,
    }
    if dest_lat is not None and dest_lon is not None:
        blocks["cyclone"]["crossings_if_leg"] = s["cyclone_crossings"](
            lat, lon, float(dest_lat), float(dest_lon), month, day=day,
        )
    return {
        "kind": s["KIND"],
        "month": month,
        "period": s["PERIOD_SUMMARY"],
        "provenance": s["PROVENANCE"],
        "coordinates": {
            "latitude": lat,
            "longitude": lon,
            "cell_selection": "land" if land else "sea",
        },
        "snapshot": s["snapshot_status"](),
        "painted": False,
        **blocks,
    }


def crossings(lat1, lon1, lat2, lon2, month, day=None, dayrange=None) -> dict:
    s = _services()
    return s["cyclone_crossings"](
        float(lat1), float(lon1), float(lat2), float(lon2),
        s["parse_month"](month), day=day, dayrange=dayrange,
    )
