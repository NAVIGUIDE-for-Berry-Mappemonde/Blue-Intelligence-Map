"""
NAVIGUIDE — Critical Shallow-Water Hazard Zones  (GEBCO Option C)
=================================================================
Pre-computed shallow-water hazard database for circumnavigation routing.

Each zone represents an area where typical/minimum depths fall below safe
thresholds for offshore passage-making (reef platforms, sand banks, shoals).
Main navigable channels *within* straits are intentionally left open — only
the impassable shallow banks surrounding them are blocked.

Data sources & methodology
--------------------------
- GEBCO 2023 15-arc-second bathymetry (visual analysis)
- Admiralty Pilot (NP series, volumes 1–8)
- Ocean Passages for the World — NP136 (UKHO)
- OpenCPN routing community hazard reports
- Noonsite passage notes for cruising sailors

Severity levels
---------------
  "impassable"  — avg/typ depth < 5 m; coral/sand platform; never routable
  "hazardous"   — typ depth 5–15 m; reefs or violent tide rips; strong caution
  "caution"     — typ depth 15–50 m; shoal-prone shelf; route with care

GEBCO note
----------
For pixel-accurate depth queries (e.g., min-depth safety check for multihulls
drawing 1.5 m), the full GEBCO 2023 15-arc-second netCDF raster (~8 GB) would
be required. This Option-C database covers the ~30 most critical zones for a
global circumnavigation and is sufficient for isochrone-level routing.
"""

from typing import Dict, List, NamedTuple, Optional


# ── Zone definition ───────────────────────────────────────────────────────────

class ShallowZone(NamedTuple):
    name:        str
    lat_min:     float
    lat_max:     float
    lon_min:     float
    lon_max:     float
    severity:    str    # "impassable" | "hazardous" | "caution"
    typ_depth_m: float  # Typical shallowest depth (m)
    note:        str


# ── Circumnavigation shallow-water hazard database ────────────────────────────

SHALLOW_ZONES: List[ShallowZone] = [

    # ════════════════════════════════════════════════════════════════════════════
    # PACIFIC & AUSTRALASIA
    # ════════════════════════════════════════════════════════════════════════════

    # Torres Strait — Western reef platforms (W of Prince of Wales Channel)
    ShallowZone(
        "Torres Strait — W reef platforms",
        -10.8, -9.5, 141.0, 142.1,
        "impassable", 2.0,
        "Extensive coral/sand platform 0–3 m; navigable Prince of Wales "
        "Channel runs 142.1–142.5 E and is intentionally left open.",
    ),
    # Torres Strait — Eastern reefs (E of Thursday Island)
    ShallowZone(
        "Torres Strait — E reef platforms",
        -10.6, -9.7, 142.6, 143.6,
        "impassable", 3.0,
        "Adolphus Channel eastern approaches; reef-strewn < 5 m over broad areas.",
    ),

    # Swain Reefs — outer Great Barrier Reef (QLD)
    ShallowZone(
        "Swain Reefs (outer GBR)",
        -22.5, -21.0, 151.5, 153.2,
        "impassable", 1.0,
        "Outermost GBR coral platform 0–3 m; virtually impassable without local pilot.",
    ),

    # Spratly Islands — Dangerous Ground (South China Sea)
    ShallowZone(
        "Dangerous Ground — Spratly Islands",
        6.5, 12.0, 111.0, 117.5,
        "hazardous", 1.0,
        "Vast reef/shoal complex > 500 000 km²; many uncharted pinnacles 0–5 m; "
        "route well E or W of this area.",
    ),

    # Luconia Shoals — South China Sea, NW of Borneo
    ShallowZone(
        "Luconia Shoals (S China Sea)",
        4.5, 6.5, 111.5, 113.5,
        "impassable", 5.0,
        "Carbonate platform 0–10 m over large area; route E (deepwater) or W.",
    ),

    # One Fathom Bank — central Malacca Strait
    ShallowZone(
        "One Fathom Bank (Malacca Strait)",
        2.8, 3.4, 100.5, 101.2,
        "hazardous", 2.0,
        "Notorious 1.8 m shoal mid-strait; main shipping fairway passes E; "
        "avoid centre of strait in this latitude band.",
    ),

    # Gulf of Thailand — central shoals
    ShallowZone(
        "Gulf of Thailand — central shoals",
        8.0, 11.5, 100.5, 103.0,
        "caution", 20.0,
        "Very shallow shelf < 50 m with numerous shoal patches; strong tidal "
        "streams and dense fishing-gear zones.",
    ),

    # Gulf of Martaban (Myanmar)
    ShallowZone(
        "Gulf of Martaban (Myanmar)",
        14.0, 17.5, 95.5, 98.5,
        "caution", 15.0,
        "Extremely shallow (< 20 m) with strong tidal currents and poor "
        "visibility; avoid in SW monsoon.",
    ),

    # Gulf of Carpentaria — inner SW shoals (N Australia)
    ShallowZone(
        "Gulf of Carpentaria — SW shoals",
        -16.5, -13.5, 135.0, 137.5,
        "caution", 15.0,
        "Very shallow inshore zone; tidal streams > 3 kn; avoid in SE trades.",
    ),

    # ════════════════════════════════════════════════════════════════════════════
    # CARIBBEAN & BAHAMAS
    # ════════════════════════════════════════════════════════════════════════════

    # Great Bahama Bank — central platform
    ShallowZone(
        "Great Bahama Bank — central",
        22.5, 25.0, -79.2, -76.5,
        "impassable", 2.0,
        "0–5 m sand bank across > 100 nm; NW Providence Channel (N of 25.5 N) "
        "and Tongue of the Ocean (E edge) are deep-water alternatives.",
    ),

    # Little Bahama Bank
    ShallowZone(
        "Little Bahama Bank",
        26.5, 27.5, -79.2, -77.0,
        "impassable", 2.0,
        "< 3 m over wide area; circumnavigate via NE Providence Channel or "
        "route N of 27.5 N.",
    ),

    # Caicos Bank (Turks & Caicos Islands)
    ShallowZone(
        "Caicos Bank (Turks & Caicos)",
        21.4, 22.1, -72.8, -71.5,
        "impassable", 1.5,
        "1–2 m sand bank; use Caicos Passage (W, 72.8 W) or "
        "Turks Island Passage (E, 71.4 W).",
    ),

    # ════════════════════════════════════════════════════════════════════════════
    # INDIAN OCEAN
    # ════════════════════════════════════════════════════════════════════════════

    # Saya de Malha Bank (central Indian Ocean)
    ShallowZone(
        "Saya de Malha Bank",
        -11.0, -8.5, 60.5, 63.5,
        "impassable", 5.0,
        "Massive isolated carbonate platform 35 000 km²; 0–15 m over virtually "
        "the entire area; major obstacle for any Indian Ocean crossing.",
    ),

    # Cargados Carajos Shoals / St Brandon (Mauritius EEZ)
    ShallowZone(
        "Cargados Carajos / St Brandon Shoals",
        -16.8, -15.8, 59.3, 60.0,
        "impassable", 1.0,
        "Remote reef platform with numerous awash rocks and drying heads.",
    ),

    # Great Chagos Bank / Peros Banhos
    ShallowZone(
        "Great Chagos Bank",
        -6.5, -4.5, 71.0, 73.0,
        "hazardous", 5.0,
        "Vast submerged atoll rim 0–30 m; central lagoon can be deep but "
        "approaches are reef-strewn.",
    ),

    # Maldives — northern outer atolls
    ShallowZone(
        "Maldives — N outer atolls",
        4.0, 7.5, 72.5, 74.0,
        "caution", 5.0,
        "Atoll reef edges 0–3 m; interior lagoons < 1 m; deep water begins "
        "W of 72 E; most yachts use North or South Maldives Channels.",
    ),
    # Maldives — southern outer atolls
    ShallowZone(
        "Maldives — S outer atolls",
        -0.5, 4.0, 72.5, 73.5,
        "caution", 5.0,
        "South Maldives atoll fringe; route W of 72 E for open-ocean passage.",
    ),

    # Agulhas Bank inner shelf (South Africa)
    ShallowZone(
        "Agulhas Bank — inner shelf",
        -34.5, -33.0, 24.0, 28.0,
        "caution", 30.0,
        "< 50 m shelf coinciding with Agulhas current retroflection; "
        "dangerous breaking seas in SW gales; stay in > 200 m water.",
    ),

    # ════════════════════════════════════════════════════════════════════════════
    # RED SEA & GULF OF ADEN
    # ════════════════════════════════════════════════════════════════════════════

    # Gulf of Suez — northern shoals (Sinai / Saudi coast)
    ShallowZone(
        "Gulf of Suez — northern shoals",
        27.5, 29.2, 32.5, 34.2,
        "hazardous", 5.0,
        "Shoal-strewn northern Red Sea; numerous coral heads, wrecks and "
        "unlit hazards; use the main TSS route.",
    ),

    # Red Sea — Farasan Banks (Saudi Arabia, central Red Sea)
    ShallowZone(
        "Farasan Banks (Red Sea — Saudi)",
        16.5, 18.0, 41.0, 43.0,
        "hazardous", 3.0,
        "Extensive reef/shoal complex on Saudi side; 0–5 m over broad areas; "
        "major shipping and yacht routes stay on Ethiopian/Eritrean (W) side.",
    ),

    # Red Sea — Dahlak Archipelago (Eritrea)
    ShallowZone(
        "Dahlak Archipelago (Eritrea)",
        15.0, 16.5, 39.5, 41.5,
        "hazardous", 2.0,
        "Dense reef/islet complex; < 3 m over most of the archipelago; "
        "impassable without local knowledge and detailed charts.",
    ),

    # Bab-el-Mandeb — western shoals (Yemen / Djibouti coast)
    ShallowZone(
        "Bab-el-Mandeb — W shoals",
        11.5, 12.8, 43.0, 43.8,
        "hazardous", 5.0,
        "Shoal patches and reefs on Yemen/Djibouti side; main E channel "
        "(43.5 E+) is deep and well-marked.",
    ),

    # ════════════════════════════════════════════════════════════════════════════
    # EUROPE / NORTH ATLANTIC
    # ════════════════════════════════════════════════════════════════════════════

    # Goodwin Sands (Dover Strait, UK)
    ShallowZone(
        "Goodwin Sands (Dover Strait)",
        51.1, 51.5, 1.28, 1.76,
        "impassable", 0.5,
        "Drying sandbank off East Kent; shifts with tidal cycles; "
        "responsible for > 50 wrecks historically.",
    ),

    # Varne Bank (Dover Strait)
    ShallowZone(
        "Varne Bank (Dover Strait)",
        50.88, 51.08, 1.15, 1.55,
        "hazardous", 3.0,
        "< 4 m over crest; lies in the main TSS south-west lane; "
        "marked by Varne lightvessel.",
    ),

    # Colbart North Shoal (Pas de Calais, French side)
    ShallowZone(
        "Colbart North Shoal (Pas de Calais)",
        50.88, 51.2, 1.55, 2.0,
        "caution", 8.0,
        "Shoal area close to French coast; < 10 m patches; strong tidal "
        "streams and heavy traffic in North Sea separation scheme.",
    ),
]


# ─── Severity ordering ────────────────────────────────────────────────────────

_SEVERITY_LEVEL = {"caution": 0, "hazardous": 1, "impassable": 2}


# ─── Public API ───────────────────────────────────────────────────────────────

def is_shallow_hazard(
    lat: float,
    lon: float,
    severity_threshold: str = "hazardous",
) -> bool:
    """
    Return True if (lat, lon) falls within a shallow-water hazard zone whose
    severity is at or above *severity_threshold*.

    severity_threshold options
    --------------------------
    "impassable"  → block only truly impassable zones (< 5 m)
    "hazardous"   → block impassable + hazardous zones  ← recommended default
    "caution"     → block all zones including caution (most conservative)
    """
    threshold = _SEVERITY_LEVEL.get(severity_threshold, 1)
    for z in SHALLOW_ZONES:
        if _SEVERITY_LEVEL.get(z.severity, 0) < threshold:
            continue
        if z.lat_min <= lat <= z.lat_max and z.lon_min <= lon <= z.lon_max:
            return True
    return False


def get_hazard_zone(lat: float, lon: float) -> Optional[ShallowZone]:
    """
    Return the most severe ShallowZone that contains (lat, lon), or None.
    Useful for generating warning annotations on route waypoints.
    """
    best: Optional[ShallowZone] = None
    for z in SHALLOW_ZONES:
        if z.lat_min <= lat <= z.lat_max and z.lon_min <= lon <= z.lon_max:
            if best is None or _SEVERITY_LEVEL[z.severity] > _SEVERITY_LEVEL[best.severity]:
                best = z
    return best


def get_all_zones_geojson() -> Dict:
    """
    Return all shallow zones as a GeoJSON FeatureCollection.
    Suitable for overlay rendering in MapLibre GL / QGIS / Leaflet.

    Each Feature carries properties:
      name, severity, typ_depth_m, note
    Colours suggested for MapLibre:
      impassable → #e74c3c (red)
      hazardous  → #e67e22 (orange)
      caution    → #f1c40f (yellow)
    """
    features = []
    for z in SHALLOW_ZONES:
        features.append({
            "type": "Feature",
            "properties": {
                "name":        z.name,
                "severity":    z.severity,
                "typ_depth_m": z.typ_depth_m,
                "note":        z.note,
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [z.lon_min, z.lat_min],
                    [z.lon_max, z.lat_min],
                    [z.lon_max, z.lat_max],
                    [z.lon_min, z.lat_max],
                    [z.lon_min, z.lat_min],
                ]],
            },
        })
    return {
        "type": "FeatureCollection",
        "metadata": {
            "source":       "NAVIGUIDE Bathymetry (GEBCO Option C)",
            "zones":        len(SHALLOW_ZONES),
            "impassable":   sum(1 for z in SHALLOW_ZONES if z.severity == "impassable"),
            "hazardous":    sum(1 for z in SHALLOW_ZONES if z.severity == "hazardous"),
            "caution":      sum(1 for z in SHALLOW_ZONES if z.severity == "caution"),
            "coverage":     "Circumnavigation-critical zones (global)",
        },
        "features": features,
    }
