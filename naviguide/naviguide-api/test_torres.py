"""
Torres Strait diagnostic — find waypoint combination that routes cleanly
around Cape York without triggering a Coral Sea detour.

Run from naviguide-api/:
    python3 test_torres.py
"""
import sys
sys.path.insert(0, ".")
from main import (
    _is_land_hires, _segment_crosses_land, _find_land_crossing_detour,
    _densify_coords, avoid_land, searoute_with_exact_end, Geodesic
)
import searoute as sr

geod = Geodesic.WGS84

print("\n" + "="*80)
print("PHASE 1 — Water check for candidate waypoints near Cape York / Torres Strait")
print("="*80)

candidates = [
    # (label, lat, lon)
    # Current waypoint (west of tip, Prince of Wales Channel)
    ("Current Torres WP (-10.7, 141.9)",         -10.7,   141.9),
    # East of tip (Coral Sea side)
    ("East of tip (-10.4, 142.8)",               -10.4,   142.8),
    ("East of tip (-10.5, 143.0)",               -10.5,   143.0),
    ("East of tip (-10.6, 143.0)",               -10.6,   143.0),
    ("East of tip (-10.8, 143.5)",               -10.8,   143.5),
    ("East of tip (-11.0, 143.5)",               -11.0,   143.5),
    ("East of tip (-11.5, 143.5)",               -11.5,   143.5),
    ("East of tip (-11.5, 144.0)",               -11.5,   144.0),
    ("East of tip (-12.0, 144.0)",               -12.0,   144.0),
    # North of tip (Torres Strait, between Aus and PNG)
    ("North of tip (-10.2, 142.5)",              -10.2,   142.5),
    ("North of tip (-10.3, 142.5)",              -10.3,   142.5),
    ("North of tip (-10.3, 143.0)",              -10.3,   143.0),
    ("North of tip (-10.0, 142.5)",              -10.0,   142.5),
    ("North of tip (-9.8, 142.5)",               -9.8,    142.5),
]

water_pts = []
for label, lat, lon in candidates:
    land = _is_land_hires(lat, lon)
    status = "LAND" if land else "WATER ✓"
    print(f"  {status:9}  {label}")
    if not land:
        water_pts.append((label, lat, lon))

print(f"\n{len(water_pts)} water candidate(s) found.\n")

# ── PHASE 2: segment crossing tests ────────────────────────────────────────────
print("="*80)
print("PHASE 2 — Segment crossing tests (key arcs involving Cape York)")
print("="*80)

# Nouméa (snapped) → Torres WP (current)
NOUMEA = [166.4572, -22.2958]
TORRES_WP_CURRENT = [141.9, -10.7]
ARAFURA = [135.7760571767464, -8.975505823887872]

# Known problem arc from searoute graph
ARC_A = [145.40, -14.70]   # east Australia Coral Sea node
ARC_B = [142.133, -10.55]  # Thursday Island node

print(f"\nKnown-bad geodesic arc (searoute graph edge):")
cross = _segment_crosses_land(ARC_A[0], ARC_A[1], ARC_B[0], ARC_B[1])
dist = geod.Inverse(ARC_A[1], ARC_A[0], ARC_B[1], ARC_B[0])["s12"]/1000
print(f"  ({ARC_A[1]},{ARC_A[0]}) → ({ARC_B[1]},{ARC_B[0]})  dist={dist:.0f}km  crosses_land={cross}")

print(f"\nCross-test: water candidates → Torres WP current / → Arafura:")
for label, lat, lon in water_pts:
    wp = [lon, lat]
    # seg1: new candidate → current Torres WP
    c1 = _segment_crosses_land(wp[0], wp[1], TORRES_WP_CURRENT[0], TORRES_WP_CURRENT[1])
    d1 = geod.Inverse(wp[1], wp[0], TORRES_WP_CURRENT[1], TORRES_WP_CURRENT[0])["s12"]/1000
    # seg2: Nouméa → new candidate (via searoute shape — check geodesic for now)
    c2 = _segment_crosses_land(NOUMEA[0], NOUMEA[1], wp[0], wp[1])
    d2 = geod.Inverse(NOUMEA[1], NOUMEA[0], wp[1], wp[0])["s12"]/1000
    print(f"  {label}")
    print(f"    Nouméa→candidate: dist={d2:.0f}km  crosses={c2}")
    print(f"    candidate→Torres WP current: dist={d1:.0f}km  crosses={c1}")

# ── PHASE 3: full pipeline test with best candidates ─────────────────────────
print("\n" + "="*80)
print("PHASE 3 — Full searoute pipeline test")
print("  Simulating what searoute_with_exact_end does for each inter-waypoint segment")
print("="*80)

# Test the current configuration: Nouméa → (-10.7, 141.9) → Arafura
print("\n--- Config A (CURRENT): Nouméa → (-10.7, 141.9) → Arafura ---")
import searoute as sr

def test_route(start, end, label):
    try:
        r = sr.searoute(start, end)
        coords = r["geometry"]["coordinates"] if r else []
        print(f"  searoute {label}: {len(coords)} pts")
        if len(coords) <= 8:
            for c in coords:
                print(f"    [{c[1]:.4f}, {c[0]:.4f}]")
        else:
            print(f"    first: {coords[0]}, last: {coords[-1]}")
        return coords
    except Exception as e:
        print(f"  searoute ERROR: {e}")
        return []

coords_a = test_route((NOUMEA[0], NOUMEA[1]), (TORRES_WP_CURRENT[0], TORRES_WP_CURRENT[1]),
                      "Nouméa→Torres(-10.7,141.9)")
coords_b = test_route((TORRES_WP_CURRENT[0], TORRES_WP_CURRENT[1]), (ARAFURA[0], ARAFURA[1]),
                      "Torres→Arafura")

# Now test with a promising intermediate: try (-10.4, 142.8) and (-10.0, 142.5)
promising = [(p[1], p[2]) for p in [
    (l, la, lo) for (l, la, lo) in candidates
    if not _is_land_hires(la, lo) and lo > 142.5
]]
if promising:
    for lat2, lon2 in promising[:3]:
        print(f"\n--- Config B: Nouméa → ({lat2},{lon2}) → Torres(-10.7,141.9) → Arafura ---")
        c1 = test_route((NOUMEA[0], NOUMEA[1]), (lon2, lat2), f"Nouméa→({lat2},{lon2})")
        c2 = test_route((lon2, lat2), (TORRES_WP_CURRENT[0], TORRES_WP_CURRENT[1]),
                         f"({lat2},{lon2})→Torres")
        # Check if avoid_land would corrupt the stitched route
        stitched = c1 + c2[1:] if c1 and c2 else []
        if stitched:
            before = len(stitched)
            avoided = avoid_land(stitched)
            coral_sea = [p for p in avoided if p[1] > -14 and p[0] > 147]
            print(f"  stitched: {before} pts → avoid_land: {len(avoided)} pts")
            if coral_sea:
                print(f"  ⚠️  Coral Sea detour pts: {coral_sea}")
            else:
                print(f"  ✅ No Coral Sea detour detected")

# ── PHASE 4: Full API pipeline test ──────────────────────────────────────────
print("\n" + "="*80)
print("PHASE 4 — Full searoute_with_exact_end pipeline for current Torres WP")
print("="*80)

r1 = searoute_with_exact_end((NOUMEA[0], NOUMEA[1]), (TORRES_WP_CURRENT[0], TORRES_WP_CURRENT[1]))
if r1:
    coords = r1["geometry"]["coordinates"]
    print(f"  Nouméa→Torres WP: {len(coords)} pts")
    coral = [p for p in coords if p[1] > -14 and p[0] > 147]
    if coral:
        print(f"  ⚠️  Coral Sea pts detected: {coral[:5]}")
    else:
        print(f"  ✅ No Coral Sea detour")
    # Show all pts if manageable
    if len(coords) <= 15:
        for c in coords:
            print(f"    [{c[1]:.4f}, {c[0]:.4f}]")

print("\nDone.")
