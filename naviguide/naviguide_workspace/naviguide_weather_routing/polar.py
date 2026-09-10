"""
NAVIGUIDE Weather Routing — Berry-Mappemonde Boat Polar (Real Data)
====================================================================
Exact polar matrix provided by Berry-Mappemonde.
Performance profile is consistent with a high-performance offshore multihull
(peak beam-reach speed ~14 kn @ TWS 30+ kn).

Bilinear interpolation on a 24-row (TWA) × 15-column (TWS) matrix.
No-go zone: TWA < 30° (all zeros).
Polar plateaus above TWS 30 kn (reef/sail management built in).
"""

import bisect
import math
from typing import Tuple


class BoatPolar:
    """
    Real Berry-Mappemonde VPP polar.

    Usage
    -----
    polar = BoatPolar()
    speed = polar.get_speed(tws=20, twa=90)    # -> 12.3 kn
    vmg   = polar.best_vmg_upwind(tws=12)      # -> (twa, spd, vmg)
    """

    # ── True Wind Angles (rows) ───────────────────────────────────────────────
    TWA_ANGLES = [
        0, 30, 35, 40, 45, 50, 52, 60, 75, 90,
        92, 102, 110, 111, 113, 115, 120, 135,
        150, 152, 160, 161, 170, 180,
    ]

    # ── True Wind Speeds (columns, knots) ────────────────────────────────────
    TWS_SPEEDS = [0, 4, 6, 8, 10, 12, 14, 16, 20, 25, 30, 35, 40, 50, 60]

    # ── Speed matrix [twa_idx][tws_idx] in knots ─────────────────────────────
    # Provided by Berry-Mappemonde (real polar file)
    SPEED_MATRIX = [
        # TWA   0kn   4kn   6kn   8kn  10kn  12kn  14kn  16kn  20kn  25kn  30kn  35kn  40kn  50kn  60kn
        [0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],  # TWA   0°
        [0.00, 2.80, 3.50, 4.20, 4.80, 5.20, 5.40, 5.50, 5.60, 5.70, 5.75, 5.75, 5.75, 5.75, 5.75],  # TWA  30°
        [0.00, 3.50, 4.20, 5.00, 5.60, 6.00, 6.20, 6.30, 6.40, 6.50, 6.55, 6.55, 6.55, 6.55, 6.55],  # TWA  35°
        [0.00, 4.20, 5.00, 5.80, 6.20, 6.40, 6.50, 6.60, 6.70, 6.85, 6.95, 6.95, 6.95, 6.95, 6.95],  # TWA  40°
        [0.00, 4.75, 5.37, 6.00, 6.30, 6.50, 6.62, 6.70, 6.83, 7.00, 7.15, 7.15, 7.15, 7.15, 7.15],  # TWA  45°
        [0.00, 5.10, 5.70, 6.20, 6.40, 6.58, 6.70, 6.80, 6.95, 7.12, 7.28, 7.28, 7.28, 7.28, 7.28],  # TWA  50°
        [0.00, 5.20, 5.80, 6.27, 6.42, 6.60, 6.72, 6.82, 6.98, 7.15, 7.32, 7.32, 7.32, 7.32, 7.32],  # TWA  52°
        [0.00, 5.50, 6.20, 6.80, 7.20, 7.50, 7.70, 7.90, 8.20, 8.50, 8.75, 8.75, 8.75, 8.75, 8.75],  # TWA  60°
        [0.00, 5.80, 6.70, 7.80, 8.50, 9.00, 9.40, 9.80,10.50,11.20,11.80,11.80,11.80,11.80,11.80],  # TWA  75°
        [0.00, 6.00, 7.20, 8.80, 9.90,10.60,11.10,11.50,12.30,13.10,13.80,13.80,13.80,13.80,13.80],  # TWA  90°
        [0.00, 6.12, 7.30, 9.00,10.10,10.80,11.30,11.70,12.50,13.30,14.00,14.00,14.00,14.00,14.00],  # TWA  92°
        [0.00, 6.10, 7.28, 9.20,10.34,11.10,11.60,12.10,13.00,13.90,14.70,14.70,14.70,14.70,14.70],  # TWA 102°
        [0.00, 6.00, 7.20, 9.10,10.50,11.40,12.00,12.42,13.25,14.10,14.90,14.90,14.90,14.90,14.90],  # TWA 110°
        [0.00, 6.00, 7.20, 9.10,10.50,11.70,12.10,12.50,13.30,14.17,15.00,15.00,15.00,15.00,15.00],  # TWA 111°
        [0.00, 5.95, 7.15, 9.00,10.45,11.65,12.14,12.55,13.35,14.20,15.10,15.10,15.10,15.10,15.10],  # TWA 113°
        [0.00, 5.90, 7.10, 8.90,10.40,11.60,12.10,12.50,13.30,14.15,15.15,15.15,15.15,15.15,15.15],  # TWA 115°
        [0.00, 5.80, 7.00, 8.70,10.20,11.40,11.90,12.30,13.10,13.95,14.80,14.80,14.80,14.80,14.80],  # TWA 120°
        [0.00, 5.50, 6.70, 8.20, 9.60,10.70,11.20,11.60,12.40,13.20,13.90,13.90,13.90,13.90,13.90],  # TWA 135°
        [0.00, 4.80, 5.49, 6.50, 7.80, 8.90, 9.50,10.00,11.00,12.00,12.80,12.80,12.80,12.80,12.80],  # TWA 150°
        [0.00, 4.75, 5.45, 6.40, 7.70, 8.80, 9.40, 9.90,10.90,11.90,12.70,12.70,12.70,12.70,12.70],  # TWA 152°
        [0.00, 4.50, 5.10, 6.00, 7.20, 8.30, 8.90, 9.40,10.40,11.40,12.20,12.20,12.20,12.20,12.20],  # TWA 160°
        [0.00, 4.48, 5.08, 5.98, 7.18, 8.28, 8.88, 9.38,10.38,11.38,12.18,12.18,12.18,12.18,12.18],  # TWA 161°
        [0.00, 4.00, 4.60, 5.40, 6.50, 7.50, 8.10, 8.60, 9.60,10.60,11.40,11.40,11.40,11.40,11.40],  # TWA 170°
        [0.00, 3.50, 4.10, 4.80, 5.90, 6.90, 7.50, 8.00, 9.00,10.00,10.80,10.80,10.80,10.80,10.80],  # TWA 180°
    ]

    def get_speed(self, tws: float, twa: float) -> float:
        """
        Bilinear-interpolated boat speed (knots) for given TWS and TWA.
        TWA is normalised to [0, 180] (port/starboard symmetric).
        Returns 0.0 for TWA < 30° (no-go zone).
        """
        # Normalise TWA to [0, 180]
        twa = abs(float(twa) % 360)
        if twa > 180:
            twa = 360.0 - twa

        if twa < 30.0:
            return 0.0

        tws = max(0.0, min(float(tws), self.TWS_SPEEDS[-1]))
        twa = max(0.0, min(twa, 180.0))

        # Grid indices with clamping
        ci = max(0, min(bisect.bisect_right(self.TWS_SPEEDS, tws) - 1,
                        len(self.TWS_SPEEDS) - 2))
        ri = max(0, min(bisect.bisect_right(self.TWA_ANGLES, twa) - 1,
                        len(self.TWA_ANGLES) - 2))

        tws0, tws1 = self.TWS_SPEEDS[ci], self.TWS_SPEEDS[ci + 1]
        twa0, twa1 = self.TWA_ANGLES[ri], self.TWA_ANGLES[ri + 1]

        t = (tws - tws0) / (tws1 - tws0) if tws1 > tws0 else 0.0
        u = (twa - twa0) / (twa1 - twa0) if twa1 > twa0 else 0.0

        s00 = self.SPEED_MATRIX[ri    ][ci    ]
        s01 = self.SPEED_MATRIX[ri    ][ci + 1]
        s10 = self.SPEED_MATRIX[ri + 1][ci    ]
        s11 = self.SPEED_MATRIX[ri + 1][ci + 1]

        speed = ((1 - t) * (1 - u) * s00 + t * (1 - u) * s01
               + (1 - t) *      u  * s10 + t *      u  * s11)
        return round(speed, 2)

    def best_vmg_upwind(self, tws: float) -> Tuple[float, float, float]:
        """Best upwind VMG: scan TWA 30–80°. Returns (twa, speed, vmg)."""
        best = (45.0, 0.0, 0.0)
        for deg in range(30, 81):
            spd = self.get_speed(tws, deg)
            vmg = spd * math.cos(math.radians(deg))
            if vmg > best[2]:
                best = (float(deg), spd, round(vmg, 2))
        return best

    def best_vmg_downwind(self, tws: float) -> Tuple[float, float, float]:
        """Best downwind VMG: scan TWA 100–175°. Returns (twa, speed, vmg)."""
        best = (150.0, 0.0, 0.0)
        for deg in range(100, 176):
            spd = self.get_speed(tws, deg)
            vmg = spd * math.cos(math.radians(180 - deg))
            if vmg > best[2]:
                best = (float(deg), spd, round(vmg, 2))
        return best

    def polar_summary(self, tws: float) -> dict:
        up_twa, up_spd, up_vmg   = self.best_vmg_upwind(tws)
        dn_twa, dn_spd, dn_vmg   = self.best_vmg_downwind(tws)
        return {
            "tws_knots":        tws,
            "upwind_twa":       up_twa,
            "upwind_speed":     up_spd,
            "upwind_vmg":       up_vmg,
            "beam_reach_speed": self.get_speed(tws, 90),
            "downwind_twa":     dn_twa,
            "downwind_speed":   dn_spd,
            "downwind_vmg":     dn_vmg,
        }
