"""
NAVIGUIDE Agent 3 — Risk Assessment Engine
==========================================
RiskAssessmentEngine implements the four risk dimension assessors
(weather, piracy, medical, cyclone) and the composite scoring logic.

Module-level constants PIRACY_ZONES, CYCLONE_BASINS, WEATHER_WINDOWS
are exposed for the API /zones endpoint.
"""

import math
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("agent3.risk_engine")


# ══════════════════════════════════════════════════════════════════════════════
# Reference data
# ══════════════════════════════════════════════════════════════════════════════

PIRACY_ZONES: List[Dict[str, Any]] = [
    {"name": "Gulf of Guinea",           "lon_min": -10,  "lat_min": -5,  "lon_max":  20, "lat_max": 10,  "score": 0.82, "risk_level": "HIGH",     "source": "IMB 2024"},
    {"name": "Gulf of Aden",             "lon_min":  42,  "lat_min":  10, "lon_max":  57, "lat_max": 16,  "score": 0.78, "risk_level": "HIGH",     "source": "IMB/MDAT 2024"},
    {"name": "Red Sea (Houthi)",         "lon_min":  30,  "lat_min":  12, "lon_max":  45, "lat_max": 30,  "score": 0.90, "risk_level": "CRITICAL", "source": "UKMTO 2024"},
    {"name": "Strait of Malacca",        "lon_min":  97,  "lat_min":   0, "lon_max": 110, "lat_max":  7,  "score": 0.42, "risk_level": "MODERATE", "source": "ReCAAP 2024"},
    {"name": "Indian Ocean (Somalia)",   "lon_min":  45,  "lat_min":  -5, "lon_max":  75, "lat_max": 15,  "score": 0.38, "risk_level": "MODERATE", "source": "IMB 2024"},
    {"name": "Mozambique Channel N",     "lon_min":  38,  "lat_min": -16, "lon_max":  45, "lat_max":  -8, "score": 0.18, "risk_level": "LOW",      "source": "IMB 2024"},
    {"name": "Caribbean (rare)",         "lon_min": -85,  "lat_min":   8, "lon_max": -55, "lat_max": 25,  "score": 0.08, "risk_level": "LOW",      "source": "IMB 2024"},
    {"name": "North Atlantic",           "lon_min": -75,  "lat_min":  30, "lon_max": -10, "lat_max": 60,  "score": 0.03, "risk_level": "LOW",      "source": "IMB 2024"},
    {"name": "South Pacific",            "lon_min": 130,  "lat_min": -35, "lon_max": 210, "lat_max":  0,  "score": 0.02, "risk_level": "LOW",      "source": "IMB 2024"},
    {"name": "Mediterranean",            "lon_min":  -5,  "lat_min":  30, "lon_max":  40, "lat_max": 46,  "score": 0.05, "risk_level": "LOW",      "source": "IMB 2024"},
]

CYCLONE_BASINS: List[Dict[str, Any]] = [
    {
        "name":           "North Atlantic (NHC)",
        "season_months":  [6, 7, 8, 9, 10, 11],
        "peak_months":    [8, 9, 10],
        "lat_min": 5,  "lat_max": 50, "lon_min": -100, "lon_max": -10,
        "avg_storms_yr":  14, "agency": "NHC",
    },
    {
        "name":           "Eastern Pacific (NHC)",
        "season_months":  [5, 6, 7, 8, 9, 10, 11],
        "peak_months":    [8, 9, 10],
        "lat_min": 5,  "lat_max": 30, "lon_min": -140, "lon_max": -80,
        "avg_storms_yr":  15, "agency": "NHC",
    },
    {
        "name":           "Western Pacific (JTWC)",
        "season_months":  list(range(1, 13)),
        "peak_months":    [8, 9, 10],
        "lat_min": 0,  "lat_max": 40, "lon_min": 100,  "lon_max": 180,
        "avg_storms_yr":  26, "agency": "JTWC",
    },
    {
        "name":           "North Indian Ocean (IMD)",
        "season_months":  [4, 5, 6, 10, 11, 12],
        "peak_months":    [5, 11],
        "lat_min": 0,  "lat_max": 25, "lon_min": 40,   "lon_max": 100,
        "avg_storms_yr":  5,  "agency": "IMD",
    },
    {
        "name":           "South Indian Ocean (RSMC)",
        "season_months":  [11, 12, 1, 2, 3, 4],
        "peak_months":    [1, 2, 3],
        "lat_min": -30, "lat_max": 0,  "lon_min": 20,   "lon_max": 115,
        "avg_storms_yr":  9,  "agency": "RSMC La Réunion",
    },
    {
        "name":           "South Pacific (RSMC)",
        "season_months":  [11, 12, 1, 2, 3, 4],
        "peak_months":    [1, 2, 3],
        "lat_min": -25, "lat_max": 0,  "lon_min": 135,  "lon_max": -130,
        "avg_storms_yr":  9,  "agency": "RSMC Nadi",
    },
]

# Per-waypoint weather windows (score = 0=good, 1=poor/dangerous)
WEATHER_WINDOWS: List[Dict[str, Any]] = [
    {
        "name": "La Rochelle",     "lat": 46.16, "lon": -1.15,
        "good_months": [5, 6, 7, 8, 9],
        "note": "Bay of Biscay — avoid Nov-Mar (heavy westerly depressions)",
        "score_seasonal": {1:0.60,2:0.55,3:0.45,4:0.30,5:0.15,6:0.10,7:0.08,8:0.10,9:0.20,10:0.40,11:0.60,12:0.65},
    },
    {
        "name": "Ajaccio (Corse)", "lat": 41.92, "lon": 8.74,
        "good_months": [5, 6, 7, 8, 9, 10],
        "note": "Western Mediterranean — mistral risk Nov-Apr",
        "score_seasonal": {1:0.45,2:0.40,3:0.35,4:0.25,5:0.15,6:0.10,7:0.08,8:0.08,9:0.15,10:0.25,11:0.45,12:0.50},
    },
    {
        "name": "Îles Canaries",   "lat": 28.55, "lon": -16.15,
        "good_months": list(range(1, 13)),
        "note": "Year-round favourable — NE trade winds reliable",
        "score_seasonal": {1:0.15,2:0.12,3:0.10,4:0.10,5:0.10,6:0.12,7:0.12,8:0.12,9:0.15,10:0.15,11:0.18,12:0.18},
    },
    {
        "name": "Fort-de-France (Martinique)", "lat": 14.60, "lon": -61.07,
        "good_months": [12, 1, 2, 3, 4, 5, 6],
        "note": "Avoid hurricane season Jun-Nov",
        "score_seasonal": {1:0.10,2:0.10,3:0.12,4:0.15,5:0.25,6:0.55,7:0.65,8:0.75,9:0.80,10:0.70,11:0.50,12:0.15},
    },
    {
        "name": "Pointe-à-Pitre (Guadeloupe)", "lat": 16.24, "lon": -61.53,
        "good_months": [12, 1, 2, 3, 4, 5],
        "note": "Same hurricane exposure as Martinique",
        "score_seasonal": {1:0.10,2:0.10,3:0.12,4:0.15,5:0.28,6:0.58,7:0.68,8:0.78,9:0.82,10:0.72,11:0.52,12:0.15},
    },
    {
        "name": "Gustavia (Saint-Barthélemy)", "lat": 17.90, "lon": -62.85,
        "good_months": [12, 1, 2, 3, 4, 5],
        "note": "N Leeward Islands — hurricane season risk",
        "score_seasonal": {1:0.10,2:0.10,3:0.12,4:0.15,5:0.28,6:0.58,7:0.65,8:0.75,9:0.80,10:0.70,11:0.50,12:0.15},
    },
    {
        "name": "Marigot (Saint-Martin)", "lat": 18.07, "lon": -63.08,
        "good_months": [12, 1, 2, 3, 4, 5],
        "note": "N Leeward Islands — hurricane season risk",
        "score_seasonal": {1:0.10,2:0.10,3:0.12,4:0.15,5:0.28,6:0.58,7:0.65,8:0.75,9:0.80,10:0.70,11:0.50,12:0.15},
    },
    {
        "name": "Halifax (Nouvelle-Écosse)", "lat": 44.65, "lon": -63.58,
        "good_months": [6, 7, 8, 9],
        "note": "N Atlantic — severe winter storms, dense fog Oct-Apr",
        "score_seasonal": {1:0.80,2:0.82,3:0.75,4:0.60,5:0.45,6:0.30,7:0.22,8:0.22,9:0.35,10:0.55,11:0.72,12:0.80},
    },
    {
        "name": "Saint-Pierre (Saint-Pierre-et-Miquelon)", "lat": 46.78, "lon": -56.18,
        "good_months": [6, 7, 8, 9],
        "note": "Sub-arctic North Atlantic — fog, ice, gales in winter",
        "score_seasonal": {1:0.78,2:0.80,3:0.75,4:0.60,5:0.42,6:0.28,7:0.22,8:0.22,9:0.35,10:0.55,11:0.72,12:0.78},
    },
    {
        "name": "Cayenne (Guyane française)", "lat": 4.93, "lon": -52.33,
        "good_months": [8, 9, 10, 11, 12, 1, 2],
        "note": "Equatorial — hot/humid year-round, two rainy seasons",
        "score_seasonal": {1:0.25,2:0.25,3:0.35,4:0.45,5:0.55,6:0.50,7:0.35,8:0.20,9:0.20,10:0.22,11:0.25,12:0.25},
    },
    {
        "name": "Papeete (Polynésie française)", "lat": -17.55, "lon": -149.56,
        "good_months": [5, 6, 7, 8, 9, 10],
        "note": "South Pacific cyclone season Nov-Apr",
        "score_seasonal": {1:0.55,2:0.58,3:0.50,4:0.35,5:0.15,6:0.12,7:0.10,8:0.12,9:0.18,10:0.25,11:0.45,12:0.55},
    },
    {
        "name": "Mata-Utu (Wallis-et-Futuna)", "lat": -13.28, "lon": -176.17,
        "good_months": [5, 6, 7, 8, 9, 10],
        "note": "SW Pacific cyclone season; very limited port infrastructure",
        "score_seasonal": {1:0.60,2:0.62,3:0.55,4:0.40,5:0.18,6:0.14,7:0.12,8:0.14,9:0.20,10:0.28,11:0.48,12:0.58},
    },
    {
        "name": "Nouméa (Nouvelle-Calédonie)", "lat": -22.28, "lon": 166.46,
        "good_months": [5, 6, 7, 8, 9, 10],
        "note": "SW Pacific cyclone season Nov-Apr; good port infrastructure",
        "score_seasonal": {1:0.52,2:0.55,3:0.48,4:0.32,5:0.15,6:0.12,7:0.10,8:0.12,9:0.18,10:0.25,11:0.42,12:0.50},
    },
    {
        "name": "Dzaoudzi (Mayotte)", "lat": -12.79, "lon": 45.28,
        "good_months": [5, 6, 7, 8, 9, 10],
        "note": "S Indian Ocean cyclone season; tropical disease risk year-round",
        "score_seasonal": {1:0.62,2:0.65,3:0.58,4:0.42,5:0.20,6:0.15,7:0.12,8:0.12,9:0.18,10:0.28,11:0.50,12:0.60},
    },
    {
        "name": "Tromelin (TAAF)", "lat": -15.89, "lon": 54.52,
        "good_months": [5, 6, 7, 8, 9, 10],
        "note": "Isolated island — no harbour, sea swell 3-5 m common; cyclone season Nov-Apr",
        "score_seasonal": {1:0.75,2:0.78,3:0.72,4:0.55,5:0.28,6:0.22,7:0.20,8:0.22,9:0.30,10:0.42,11:0.65,12:0.72},
    },
    {
        "name": "Saint-Gilles (La Réunion)", "lat": -21.06, "lon": 55.22,
        "good_months": [5, 6, 7, 8, 9, 10],
        "note": "SW Indian Ocean cyclone season; can receive intense cyclones",
        "score_seasonal": {1:0.58,2:0.60,3:0.55,4:0.38,5:0.18,6:0.14,7:0.12,8:0.12,9:0.18,10:0.28,11:0.48,12:0.56},
    },
    {
        "name": "Europa (TAAF)", "lat": -22.36, "lon": 40.35,
        "good_months": [5, 6, 7, 8, 9, 10],
        "note": "Mozambique Channel — extremely remote, cyclone Season Nov-Apr, no medical facility",
        "score_seasonal": {1:0.78,2:0.80,3:0.75,4:0.58,5:0.30,6:0.22,7:0.18,8:0.22,9:0.32,10:0.45,11:0.68,12:0.76},
    },
    {
        "name": "La Rochelle (retour)", "lat": 46.16, "lon": -1.15,
        "good_months": [5, 6, 7, 8, 9],
        "note": "Same conditions as departure port",
        "score_seasonal": {1:0.60,2:0.55,3:0.45,4:0.30,5:0.15,6:0.10,7:0.08,8:0.10,9:0.20,10:0.40,11:0.60,12:0.65},
    },
]

# Medical access index per waypoint
# medevac_hours: estimated hours to reach an ICU-equipped hospital
_MEDICAL_DB: List[Dict[str, Any]] = [
    {"name": "La Rochelle",                             "level": "advanced",  "medevac_hours":  1, "score": 0.05, "notes": "CHU La Rochelle; SAMU available"},
    {"name": "Ajaccio (Corse)",                         "level": "good",      "medevac_hours":  2, "score": 0.12, "notes": "Hôpital de la Miséricorde; helicopter evac to mainland 1h"},
    {"name": "Îles Canaries",                           "level": "good",      "medevac_hours":  3, "score": 0.12, "notes": "Hospital Universitario de Gran Canaria"},
    {"name": "Fort-de-France (Martinique)",             "level": "advanced",  "medevac_hours":  2, "score": 0.15, "notes": "CHU de Martinique; strong French medical presence"},
    {"name": "Pointe-à-Pitre (Guadeloupe)",             "level": "advanced",  "medevac_hours":  2, "score": 0.15, "notes": "CHU de Guadeloupe; emergency air transport available"},
    {"name": "Gustavia (Saint-Barthélemy)",             "level": "basic",     "medevac_hours":  6, "score": 0.32, "notes": "Hôpital de Bruyn — limited capacity; transfer to Martinique"},
    {"name": "Marigot (Saint-Martin)",                  "level": "basic",     "medevac_hours":  5, "score": 0.28, "notes": "Louis Constant Fleming Hospital; transfer to Martinique for complex cases"},
    {"name": "Halifax (Nouvelle-Écosse)",               "level": "advanced",  "medevac_hours":  1, "score": 0.05, "notes": "QEII Health Sciences Centre; level-1 trauma"},
    {"name": "Saint-Pierre (Saint-Pierre-et-Miquelon)", "level": "basic",     "medevac_hours": 12, "score": 0.45, "notes": "Small hospital; evacuation to Saint John's 1.5h by air"},
    {"name": "Cayenne (Guyane française)",              "level": "moderate",  "medevac_hours":  4, "score": 0.55, "notes": "CHAR Cayenne; tropical disease expertise; limited ICU capacity"},
    {"name": "Papeete (Polynésie française)",           "level": "moderate",  "medevac_hours":  3, "score": 0.30, "notes": "Centre Hospitalier de Polynésie Française; reasonable care"},
    {"name": "Mata-Utu (Wallis-et-Futuna)",             "level": "limited",   "medevac_hours": 48, "score": 0.75, "notes": "Sia Hospital — very basic; medevac to Nouméa 4h by air"},
    {"name": "Nouméa (Nouvelle-Calédonie)",             "level": "good",      "medevac_hours":  2, "score": 0.18, "notes": "Gaston Bourret Medical Centre; good facilities"},
    {"name": "Dzaoudzi (Mayotte)",                      "level": "limited",   "medevac_hours": 36, "score": 0.82, "notes": "Mayotte Hospital — chronically overloaded; dengue/malaria endemic"},
    {"name": "Tromelin (TAAF)",                         "level": "none",      "medevac_hours": 72, "score": 0.90, "notes": "No medical facility on island; helicopter rescue from La Réunion 3-4h"},
    {"name": "Saint-Gilles (La Réunion)",               "level": "good",      "medevac_hours":  2, "score": 0.18, "notes": "CHU Félix Guyon; good French-standard hospital"},
    {"name": "Europa (TAAF)",                           "level": "none",      "medevac_hours": 96, "score": 0.95, "notes": "Uninhabited — no facility; helicopter rescue from Réunion/Mayotte 5-6h"},
    {"name": "La Rochelle (retour)",                    "level": "advanced",  "medevac_hours":  1, "score": 0.05, "notes": "Return to home port — full French medical system available"},
]


# ══════════════════════════════════════════════════════════════════════════════
# Risk Assessment Engine
# ══════════════════════════════════════════════════════════════════════════════

class RiskAssessmentEngine:
    """
    Four-dimensional maritime risk assessor for expedition planning.
    Dimensions: weather windows · piracy · medical access · cyclone exposure
    """

    # Composite score weights (must sum to 1.0)
    # Medical weighted higher — isolation/medevac is a permanent risk regardless of season
    WEIGHTS = {
        "weather": 0.25,
        "piracy":  0.20,
        "medical": 0.30,
        "cyclone": 0.25,
    }

    # ── Weather ───────────────────────────────────────────────────────────────

    def assess_weather_windows(
        self,
        waypoints: List[Dict],
        departure_month: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Assess seasonal weather quality for each waypoint.
        Uses WEATHER_WINDOWS lookup; falls back to a moderate score for unknowns.
        """
        month = departure_month or 7   # default: July (Northern summer)
        results = []

        for wp in waypoints:
            name   = wp.get("name", "Unknown")
            record = self._find_weather_window(name)

            if record:
                score = record["score_seasonal"].get(month, 0.30)
                good  = score < 0.25
                results.append({
                    "name":         name,
                    "score":        round(score, 3),
                    "quality":      "good" if good else ("acceptable" if score < 0.50 else "poor"),
                    "good_months":  record["good_months"],
                    "note":         record.get("note", ""),
                    "month":        month,
                })
            else:
                # Unknown waypoint — assign moderate score
                results.append({
                    "name":     name,
                    "score":    0.30,
                    "quality":  "acceptable",
                    "good_months": [5, 6, 7, 8, 9, 10],
                    "note":     "No specific data — moderate risk assumed",
                    "month":    month,
                })

        return results

    # ── Piracy ────────────────────────────────────────────────────────────────

    def assess_piracy(self, waypoints: List[Dict]) -> List[Dict[str, Any]]:
        """
        Check each waypoint against PIRACY_ZONES by bounding-box proximity.
        """
        results = []
        for wp in waypoints:
            name = wp.get("name", "Unknown")
            lon  = wp.get("lon", 0.0)
            lat  = wp.get("lat", 0.0)

            best_zone  = None
            best_score = 0.0

            for zone in PIRACY_ZONES:
                if self._in_zone(lon, lat, zone):
                    if zone["score"] > best_score:
                        best_score = zone["score"]
                        best_zone  = zone

            if best_zone:
                results.append({
                    "name":       name,
                    "score":      best_score,
                    "risk_level": best_zone["risk_level"],
                    "zone":       best_zone["name"],
                    "source":     best_zone.get("source", ""),
                })
            else:
                results.append({
                    "name":       name,
                    "score":      0.02,
                    "risk_level": "LOW",
                    "zone":       "Open Ocean",
                    "source":     "No active piracy zone",
                })

        return results

    # ── Medical ───────────────────────────────────────────────────────────────

    def assess_medical(self, waypoints: List[Dict]) -> List[Dict[str, Any]]:
        """
        Rate medical infrastructure and medevac time for each stopover.
        """
        results = []
        for wp in waypoints:
            name   = wp.get("name", "Unknown")
            record = self._find_medical(name)

            if record:
                results.append({
                    "name":           name,
                    "score":          record["score"],
                    "hospital_level": record["level"],
                    "medevac_hours":  record["medevac_hours"],
                    "notes":          record.get("notes", ""),
                })
            else:
                # Unknown — assume moderate
                results.append({
                    "name":           name,
                    "score":          0.35,
                    "hospital_level": "moderate",
                    "medevac_hours":  12,
                    "notes":          "No specific data available",
                })

        return results

    # ── Cyclone ───────────────────────────────────────────────────────────────

    def assess_cyclones(
        self,
        waypoints: List[Dict],
        departure_month: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Check each waypoint against CYCLONE_BASINS for seasonal exposure.
        """
        month = departure_month or 7
        results = []

        for wp in waypoints:
            name = wp.get("name", "Unknown")
            lon  = wp.get("lon", 0.0)
            lat  = wp.get("lat", 0.0)

            active_basins = []

            for basin in CYCLONE_BASINS:
                if self._in_cyclone_basin(lon, lat, basin):
                    season_active = month in basin["season_months"]
                    in_peak       = month in basin["peak_months"]

                    if season_active:
                        active_basins.append({
                            "basin":          basin["name"],
                            "season_active":  True,
                            "in_peak":        in_peak,
                            "agency":         basin["agency"],
                        })

            if active_basins:
                # Pick the highest-risk basin (peak > active)
                peak_basins = [b for b in active_basins if b["in_peak"]]
                chosen = peak_basins[0] if peak_basins else active_basins[0]
                score  = 0.85 if chosen["in_peak"] else 0.55
                results.append({
                    "name":          name,
                    "score":         score,
                    "season_active": True,
                    "in_peak":       chosen["in_peak"],
                    "basin":         chosen["basin"],
                    "agency":        chosen["agency"],
                    "month":         month,
                })
            else:
                results.append({
                    "name":          name,
                    "score":         0.05,
                    "season_active": False,
                    "in_peak":       False,
                    "basin":         "Outside cyclone basins",
                    "agency":        "N/A",
                    "month":         month,
                })

        return results

    # ── Composite scoring ─────────────────────────────────────────────────────

    def compute_overall_scores(
        self,
        weather_list: List[Dict],
        piracy_list:  List[Dict],
        medical_list: List[Dict],
        cyclone_list: List[Dict],
    ) -> List[Dict[str, Any]]:
        """
        Join the four dimension arrays by waypoint name and compute
        weighted composite scores.

        Returns a list of:
          {
            "name":       str,
            "overall":    float,        # 0-1
            "level":      str,          # LOW / MODERATE / HIGH / CRITICAL
            "components": {             # individual raw scores
              "weather_score", "piracy_score", "medical_score", "cyclone_score"
            }
          }
        """
        # Index by waypoint name for O(1) lookup
        wx = {a["name"]: a["score"] for a in weather_list}
        px = {a["name"]: a["score"] for a in piracy_list}
        mx = {a["name"]: a["score"] for a in medical_list}
        cx = {a["name"]: a["score"] for a in cyclone_list}

        # Union of all waypoint names
        names = list(dict.fromkeys(
            [a["name"] for a in weather_list] +
            [a["name"] for a in piracy_list]  +
            [a["name"] for a in medical_list] +
            [a["name"] for a in cyclone_list]
        ))

        W = self.WEIGHTS
        results = []

        for name in names:
            w_score = wx.get(name, 0.20)
            p_score = px.get(name, 0.05)
            m_score = mx.get(name, 0.20)
            c_score = cx.get(name, 0.05)

            overall = (
                W["weather"] * w_score +
                W["piracy"]  * p_score +
                W["medical"] * m_score +
                W["cyclone"] * c_score
            )
            overall = round(min(1.0, max(0.0, overall)), 4)

            # Base level from composite score
            level = (
                "CRITICAL" if overall >= 0.55 else
                "HIGH"     if overall >= 0.30 else
                "MODERATE" if overall >= 0.15 else
                "LOW"
            )

            # Override: a single extreme dimension always upgrades the level
            # (e.g. Europa TAAF with medical=0.95 must be CRITICAL regardless of season)
            max_dim = max(w_score, p_score, m_score, c_score)
            if max_dim >= 0.88 and level not in ("CRITICAL",):
                level = "CRITICAL"
            elif max_dim >= 0.70 and level not in ("CRITICAL", "HIGH"):
                level = "HIGH"

            results.append({
                "name":    name,
                "overall": overall,
                "level":   level,
                "components": {
                    "weather_score": round(w_score, 4),
                    "piracy_score":  round(p_score, 4),
                    "medical_score": round(m_score, 4),
                    "cyclone_score": round(c_score, 4),
                },
            })

        return results

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _in_zone(lon: float, lat: float, zone: Dict) -> bool:
        """Bounding-box containment check."""
        lon_min = zone.get("lon_min", -180)
        lon_max = zone.get("lon_max",  180)
        lat_min = zone.get("lat_min",  -90)
        lat_max = zone.get("lat_max",   90)
        # Handle zones that wrap around the antimeridian (e.g. South Pacific)
        if lon_min > lon_max:
            in_lon = (lon >= lon_min) or (lon <= lon_max)
        else:
            in_lon = lon_min <= lon <= lon_max
        return in_lon and (lat_min <= lat <= lat_max)

    @staticmethod
    def _in_cyclone_basin(lon: float, lat: float, basin: Dict) -> bool:
        """Like _in_zone but for cyclone basins (same bounding-box logic)."""
        lon_min = basin.get("lon_min", -180)
        lon_max = basin.get("lon_max",  180)
        lat_min = basin.get("lat_min",  -90)
        lat_max = basin.get("lat_max",   90)
        if lon_min > lon_max:
            in_lon = (lon >= lon_min) or (lon <= lon_max)
        else:
            in_lon = lon_min <= lon <= lon_max
        return in_lon and (lat_min <= lat <= lat_max)

    @staticmethod
    def _find_weather_window(name: str) -> Optional[Dict]:
        """Look up a weather window record by waypoint name (case-insensitive prefix)."""
        name_lower = name.lower()
        for rec in WEATHER_WINDOWS:
            if rec["name"].lower() in name_lower or name_lower in rec["name"].lower():
                return rec
        return None

    @staticmethod
    def _find_medical(name: str) -> Optional[Dict]:
        """Look up a medical record by waypoint name."""
        name_lower = name.lower()
        for rec in _MEDICAL_DB:
            if rec["name"].lower() in name_lower or name_lower in rec["name"].lower():
                return rec
        return None
