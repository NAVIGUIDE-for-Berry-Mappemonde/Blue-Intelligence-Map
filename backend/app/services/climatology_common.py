"""Contrats partagés du mode Climatologie (kind, périodes, terre, unités).

Les snapshots vivent dans ``backend/data/climatology/`` et sont générés hors
VPS (Mac). Ici on les sert, on n'invente pas un vent / une Hs / un courant.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

KIND = "climatology"

_BACKEND_DIR = Path(__file__).resolve().parents[2]
CLIMATOLOGY_DIR = _BACKEND_DIR / "data" / "climatology"

try:
    from app.core.run_rules import catalog_default as _catalog_default
except Exception:  # pragma: no cover — import NAVIGUIDE sans Mongo
    _catalog_default = None

_RULE_FALLBACKS = {
    "climatology.wind_calm_kn": 3,
    "climatology.wind_gale_kn": 34,
    "climatology.wind_min_sector_pct": 2.5,
    "climatology.wave_nogo_m": 2.5,
    "climatology.current_min_kn": 0.15,
    "climatology.current_depth_m": 0.5,
    "climatology.cyclone_dayrange": 21,
    "climatology.cyclone_radius_nm": 120,
    "climatology.cyclone_min_kn": 34,
    "climatology.avoid_cyclone_tracks": True,
}

# Périodes nominatives — chaque produit a la sienne. Le champ `period` du
# point est un résumé, pas une vérité unique (voir le plan §15).
PERIOD_SUMMARY = "1980-2020"
WIND_PERIOD = "1994-2020"
WAVE_PERIOD = "1993-2019"
CURRENT_PERIOD = "1993-2016"
CYCLONE_PERIOD = "1980-present"

PROVENANCE = {
    "wind": "CMEMS WIND_GLO_PHY_L4_MY_012_006 · cmems_obs-wind_glo_phy_my_l4_0.25deg_PT1H",
    "wind_average": (
        "CMEMS WIND_GLO_PHY_CLIMATE_L4_MY_012_003 · "
        "cmems_obs-wind_glo_phy_my_l4_P1M · AVERAGE only (not a rose)"
    ),
    "wave": "WAVERYS GLOBAL_MULTIYEAR_WAV_001_032",
    "current": "GLORYS12 GLOBAL_MULTIYEAR_PHY_001_030 climatology_P1M-m",
    "cyclone": "IBTrACS v04r01 since1980 · NOAA NCEI",
}

DOI = {
    "wind": "10.48670/moi-00183",
    "wave": "10.48670/moi-00022",
    "current": "10.48670/moi-00021",
}

SOURCE_IDS = {
    "wind": "WIND_GLO_PHY_L4_MY_012_006",
    "wave": "GLOBAL_MULTIYEAR_WAV_001_032",
    "current": "GLOBAL_MULTIYEAR_PHY_001_030",
    "cyclone": "IBTrACS_v04r01",
}

CMEMS_CREDIT = (
    "Generated using E.U. Copernicus Marine Service Information"
)
IBTRACS_CREDIT = "IBTrACS v04r01, NOAA NCEI"
LICENSE_CMEMS = (
    f"{CMEMS_CREDIT}. Copernicus Marine Service licence. "
    "Not for navigation."
)
LICENSE_IBTRACS = (
    f"{IBTRACS_CREDIT}. Redistribution unrestricted (ERDDAP). "
    "Not for navigation."
)

MS_TO_KN = 1.94384
SECTORS = 8
SECTOR_DEG = 45.0

# Boîtes terre (repli si global_land_mask n'est pas installé).
# Recette : Sahara et Andes doivent tomber dedans ; 15°N 25°W, 40°S, 26°N 80°W hors.
_LAND_BOXES = [
    (30, 72, -130, -60),     # Amérique du Nord intérieure
    (14, 32, -115, -88),     # Mexique / SW US
    (7, 18, -92, -77),       # Amérique centrale
    (-50, 10, -75, -40),     # Amérique du Sud intérieure (Andes)
    (36, 71, -10, 40),       # Europe intérieure
    (12, 37, -17, 50),       # Sahara / Afrique N + Sahel
    (-34, 15, 10, 42),       # Afrique intérieure
    (12, 32, 35, 60),        # Arabie
    (8, 35, 68, 97),         # Inde
    (-8, 28, 95, 122),       # Asie du SE
    (18, 54, 73, 135),       # Chine / Asie centrale
    (-38, -12, 114, 152),    # Australie intérieure
    (-90, -63, -180, 180),   # Antarctique
    (60, 84, -75, -12),      # Groenland
    (-25, -12, 43, 50),      # Madagascar
]


try:
    from global_land_mask import globe as _globe
    _HAS_LAND_MASK = True
except Exception:  # pragma: no cover - optionnel
    _globe = None
    _HAS_LAND_MASK = False


def climatology_dir() -> Path:
    return Path(CLIMATOLOGY_DIR)


def rule(rule_id: str, fallback: Any = None) -> Any:
    if _catalog_default is not None:
        try:
            return _catalog_default(rule_id, fallback)
        except Exception:
            pass
    if fallback is not None:
        return fallback
    return _RULE_FALLBACKS.get(rule_id)


def parse_month(month: int | str) -> int:
    try:
        m = int(month)
    except (TypeError, ValueError) as exc:
        raise ValueError("month must be an integer 1–12") from exc
    if m < 1 or m > 12:
        raise ValueError("month must be an integer 1–12")
    return m


def wrap_lon(lon: float) -> float:
    return ((float(lon) + 180.0) % 360.0) - 180.0


def is_land(lat: float, lon: float) -> bool:
    """True sur terre. Ne jamais inventer un vent / une Hs / un courant là."""
    if not (-90.0 <= lat <= 90.0):
        return True
    lon = wrap_lon(lon)
    if _HAS_LAND_MASK and _globe is not None:
        try:
            return bool(_globe.is_land(float(lat), float(lon)))
        except Exception:
            pass
    for la, lb, loa, lob in _LAND_BOXES:
        if la <= lat <= lb and loa <= lon <= lob:
            return True
    return False


def wind_from_uv(u_ms: float, v_ms: float) -> tuple[float, float]:
    """Direction d'où vient le vent (conv. météo) + vitesse en kn.

    ``atan2(-u, -v)`` — déjà la convention de ``getWind.py``.
    """
    spd_kn = math.hypot(u_ms, v_ms) * MS_TO_KN
    coming_from = (math.degrees(math.atan2(-u_ms, -v_ms)) + 360.0) % 360.0
    return spd_kn, coming_from


def current_to_uv(u_ms: float, v_ms: float) -> tuple[float, float]:
    """Direction vers où ça porte + vitesse en kn.

    ``atan2(u, v)`` — déjà la convention de ``getCurrent.py``.
    """
    spd_kn = math.hypot(u_ms, v_ms) * MS_TO_KN
    going_to = (math.degrees(math.atan2(u_ms, v_ms)) + 360.0) % 360.0
    return spd_kn, going_to


def sector_index(dir_from_deg: float, n: int = SECTORS) -> int:
    step = 360.0 / n
    return int((float(dir_from_deg) + step / 2.0) % 360.0 // step)


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_nm = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(wrap_lon(lon2 - lon1))
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * r_nm * math.asin(min(1.0, math.sqrt(a)))


def point_to_segment_nm(
    lat: float, lon: float, lat1: float, lon1: float, lat2: float, lon2: float,
) -> float:
    """Distance approx. d'un point à un segment (échantillons le long du GC)."""
    best = min(
        haversine_nm(lat, lon, lat1, lon1),
        haversine_nm(lat, lon, lat2, lon2),
    )
    dlon = wrap_lon(lon2 - lon1)
    for i in range(1, 8):
        t = i / 8.0
        plat = lat1 + t * (lat2 - lat1)
        plon = wrap_lon(lon1 + t * dlon)
        best = min(best, haversine_nm(lat, lon, plat, plon))
    return best


def empty_blocks() -> dict:
    return {
        "wind_atlas": None,
        "wave": None,
        "current": None,
        "cyclone": {"tracks_in_month": 0, "crossings_if_leg": None},
    }


def _sidecar_stat(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    stat = data.get("stat")
    return str(stat) if stat else None


def snapshot_status() -> dict:
    root = climatology_dir()
    wind_dir = root / "wind"
    wave_dir = root / "wave"
    current_dir = root / "current"
    cyc = root / "cyclones" / "ibtracs_since1980.json"
    wind_present = (wind_dir / "wind-01.npz").is_file()
    wave_present = (wave_dir / "wave-01.npz").is_file()
    wind_stat = _sidecar_stat(wind_dir / "wind-01.atlas.json")
    if wind_present and not wind_stat:
        wind_stat = "rose"
    wave_stat = _sidecar_stat(wave_dir / "wave-01.json")
    return {
        "wind": wind_present,
        "wave": wave_present,
        "current": (current_dir / "current-01.npz").is_file(),
        "cyclones": cyc.is_file(),
        "wind_stat": wind_stat,
        "wave_stat": wave_stat,
    }


def product_meta(product: str) -> dict:
    periods = {
        "wind": WIND_PERIOD,
        "wave": WAVE_PERIOD,
        "current": CURRENT_PERIOD,
        "cyclone": CYCLONE_PERIOD,
    }
    dois = {
        "wind": DOI["wind"],
        "wave": DOI["wave"],
        "current": DOI["current"],
        "cyclone": None,
    }
    snaps = snapshot_status()
    provenance = PROVENANCE[product]
    source_id = SOURCE_IDS[product]
    doi = dois[product]
    if product == "wind" and snaps.get("wind_stat") == "average":
        provenance = PROVENANCE["wind_average"]
        source_id = "WIND_GLO_PHY_CLIMATE_L4_MY_012_003"
        doi = None
    return {
        "kind": KIND,
        "source_id": source_id,
        "provenance": provenance,
        "period": periods[product],
        "doi": doi,
        "snapshot_present": snaps["cyclones" if product == "cyclone" else product],
        "stat": snaps.get("wind_stat" if product == "wind" else (
            "wave_stat" if product == "wave" else None
        )),
    }
