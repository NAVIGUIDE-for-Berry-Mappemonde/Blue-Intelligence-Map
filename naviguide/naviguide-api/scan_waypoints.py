"""
Scan all ITINERARY_POINTS for land classification and snap them to the
nearest ocean point when needed.

Run from the naviguide-api directory:
    python3 scan_waypoints.py
"""

import sys
import math

sys.path.insert(0, ".")
from main import _is_land_hires, _snap_to_ocean_fine, Geodesic

geod = Geodesic.WGS84

# ── Mirror of naviguide-app/src/constants/itineraryPoints.ts ─────────────────
ITINERARY_POINTS = [
    {"name": "Saint-Maur (Berry, Indre)",             "lat": 46.8075,   "lon": 1.6358},
    {"name": "La Rochelle",                            "lat": 46.1591,   "lon": -1.152},
    {"name": "Point intermédiaire Avant Corse",        "lat": 41.181,    "lon": 8.438},
    {"name": "Ajaccio (Corse)",                        "lat": 41.9192,   "lon": 8.7386},
    {"name": "Point intermédiaire Après Corse",        "lat": 43.30582,  "lon": 8.66402},
    {"name": "Point intermédiaire Après Corse",        "lat": 42.22093,  "lon": 9.84376},
    {"name": "Iles Canari",                            "lat": 29.325,    "lon": -15.181},
    {"name": "Point intermédiaire Cap Verde",          "lat": 13.919,    "lon": -24.531},
    {"name": "Sainte Lucie",                           "lat": 13.499,    "lon": -61.498},
    {"name": "Fort-de-France (Martinique)",            "lat": 14.6037,   "lon": -61.0731},
    {"name": "Pointe-à-Pitre (Guadeloupe)",            "lat": 16.2415,   "lon": -61.5331},
    {"name": "Gustavia (Saint-Barthélemy)",            "lat": 17.8962,   "lon": -62.8498},
    {"name": "Marigot (Saint-Martin)",                 "lat": 18.0679,   "lon": -63.0822},
    {"name": "Halifax (Nouvelle-Écosse)",              "lat": 44.6488,   "lon": -63.5752},
    {"name": "Saint-Pierre (Saint-Pierre-et-Miquelon)","lat": 46.7811,   "lon": -56.1778},
    {"name": "Cayenne (Guyane)",                       "lat": 4.9333,    "lon": -52.3333},
    {"name": "Papeete (Polynésie française)",          "lat": -17.5516,  "lon": -149.5585},
    {"name": "Mata-Utu (Wallis-et-Futuna)",            "lat": -13.2825,  "lon": -176.1736},
    {"name": "Nouméa (Nouvelle-Calédonie)",            "lat": -22.2758,  "lon": 166.4572},
    {"name": "Point intermédiaire haut Australie",     "lat": -8.9755,   "lon": 135.776},
    {"name": "Point intermédiaire haut Australie",     "lat": -9.3652,   "lon": 105.0926},
    {"name": "Point intermédiaire haut Australie",     "lat": 6.3727,    "lon": 88.6064},
    {"name": "Sri Lanka",                              "lat": 6.7957,    "lon": 81.7454},
    {"name": "Maldives",                               "lat": -0.01196,  "lon": 73.3465},
    {"name": "Seichelles",                             "lat": -4.7955,   "lon": 55.5308},
    {"name": "Dzaoudzi (Mayotte)",                     "lat": -12.7871,  "lon": 45.275},
    {"name": "Tromelin (TAAF)",                        "lat": -15.89,    "lon": 54.52},
    {"name": "Saint-Gilles (La Réunion)",              "lat": -21.0594,  "lon": 55.2242},
    {"name": "Europa (TAAF)",                          "lat": -22.3635,  "lon": 40.3476},
    {"name": "Pt Cap de la Bonne Espérance",           "lat": -33.5830,  "lon": 14.0837},
    {"name": "Pt Sainte Hélène",                       "lat": -15.9415,  "lon": -5.7142},
    {"name": "Pt Ascension",                           "lat": -7.9492,   "lon": -14.3441},
    {"name": "Pt Ascension - Cap Verde",               "lat": 4.6494,    "lon": -24.5951},
    {"name": "Point intermédiaire Cap Verde (retour)", "lat": 13.919,    "lon": -24.531},
    {"name": "La Rochelle (retour)",                   "lat": 46.1591,   "lon": -1.152},
]

# ── Skip purely inland non-maritime points ────────────────────────────────────
INLAND_SKIP = {"Saint-Maur (Berry, Indre)"}

# ── Results ───────────────────────────────────────────────────────────────────
land_points = []
ocean_points = []

print(f"\n{'='*90}")
print(f"{'Point':<45} {'Status':<8} {'Lat orig':>10} {'Lon orig':>11} {'Lat new':>10} {'Lon new':>11} {'Dist km':>8}")
print(f"{'='*90}")

for pt in ITINERARY_POINTS:
    name = pt["name"]
    lat, lon = pt["lat"], pt["lon"]

    if name in INLAND_SKIP:
        print(f"{name:<45} {'SKIP':<8}")
        continue

    is_land = _is_land_hires(lat, lon)

    if not is_land:
        print(f"{name:<45} {'ocean':<8} {lat:>10.5f} {lon:>11.5f}")
        ocean_points.append(pt)
        continue

    # Land — find nearest ocean point
    snapped = _snap_to_ocean_fine(lat, lon, radius_deg=0.2, grid=0.005)
    if snapped is None:
        # Widen search
        snapped = _snap_to_ocean_fine(lat, lon, radius_deg=0.5, grid=0.01)

    if snapped:
        new_lon, new_lat = snapped
        dist_m = geod.Inverse(lat, lon, new_lat, new_lon)["s12"]
        dist_km = dist_m / 1000
        print(f"{name:<45} {'LAND→fix':<8} {lat:>10.5f} {lon:>11.5f} {new_lat:>10.5f} {new_lon:>11.5f} {dist_km:>8.2f}")
        land_points.append({**pt, "new_lat": new_lat, "new_lon": new_lon, "dist_km": dist_km})
    else:
        print(f"{name:<45} {'LAND!':8} {lat:>10.5f} {lon:>11.5f} {'NO FIX FOUND':>32}")
        land_points.append({**pt, "new_lat": None, "new_lon": None, "dist_km": None})

print(f"{'='*90}")
print(f"\n{len(land_points)} point(s) on land, {len(ocean_points)} already in ocean\n")

# ── Summary of changes needed ─────────────────────────────────────────────────
if land_points:
    print("Corrections to apply in itineraryPoints.ts:")
    print("-" * 70)
    for p in land_points:
        if p["new_lat"] is not None:
            print(f"  {p['name']}")
            print(f"    lat: {p['lat']} → {p['new_lat']:.6f}")
            print(f"    lon: {p['lon']} → {p['new_lon']:.6f}  ({p['dist_km']:.2f} km offshore)")
