"""Pont vers les snapshots BI (même fichiers, pas de couche carte)."""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[3] / "backend"
if _BACKEND.is_dir() and str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def atlas_wind(lat: float, lon: float, month: int, mode: str = "most_likely"):
    try:
        from app.services.climatology_wind import wind_at
        return wind_at(lat, lon, month, mode=mode)
    except Exception:
        return None


def atlas_current(lat: float, lon: float, month: int):
    try:
        from app.services.climatology_current import current_at
        return current_at(lat, lon, month)
    except Exception:
        return None


def atlas_wave_hazard(lat: float, lon: float, month: int):
    try:
        from app.services.climatology_wave import is_wave_hazard
        return is_wave_hazard(lat, lon, month)
    except Exception:
        return None


def atlas_crossings(lat1, lon1, lat2, lon2, month, day=None):
    try:
        from app.services.climatology_cyclones import crossings
        return crossings(lat1, lon1, lat2, lon2, month, day=day)
    except Exception:
        return {"kind": "climatology", "count": 0, "storms": [], "snapshot_present": False}


def cyclone_cells(month: int) -> set[tuple[int, int]]:
    try:
        from app.services.climatology_cyclones import storms_for_month
        cells: set[tuple[int, int]] = set()
        for s in storms_for_month(month):
            for pt in s.get("coords") or []:
                if len(pt) >= 2:
                    cells.add((int(round(pt[1])), int(round(pt[0]))))
        return cells
    except Exception:
        return set()
