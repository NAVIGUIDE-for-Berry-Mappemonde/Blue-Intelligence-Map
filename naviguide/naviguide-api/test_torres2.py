"""
Targeted diagnostic: trace exactly which segment triggers the Coral Sea detour
and what _find_land_crossing_detour returns for it.
"""
import sys
sys.path.insert(0, ".")
import searoute as sr
from main import (
    _is_land_hires, _segment_crosses_land, _find_land_crossing_detour,
    _densify_coords, _sanitize_route_coords, avoid_land, Geodesic
)
geod = Geodesic.WGS84

NOUMEA = [166.4572, -22.2958]
TORRES = [141.9, -10.7]
ARAFURA = [135.7760571767464, -8.975505823887872]

# Step 1: get raw searoute output
print("\n1. Raw searoute Nouméa → Torres WP:")
r = sr.searoute((NOUMEA[0], NOUMEA[1]), (TORRES[0], TORRES[1]))
raw = r["geometry"]["coordinates"]
print(f"   {len(raw)} pts:")
for c in raw:
    print(f"     [{c[1]:.5f}, {c[0]:.5f}]")

print("\n2. Land check on each segment of raw searoute output:")
for i in range(len(raw)-1):
    a, b = raw[i], raw[i+1]
    cross = _segment_crosses_land(a[0], a[1], b[0], b[1])
    dist = geod.Inverse(a[1], a[0], b[1], b[0])["s12"] / 1000
    mark = "  ⚠️  LAND" if cross else "  ✓"
    print(f"   seg {i}: [{a[1]:.4f},{a[0]:.4f}]→[{b[1]:.4f},{b[0]:.4f}]  {dist:.0f}km{mark}")

# Check the specific known-bad arc
print("\n3. _find_land_crossing_detour for the bad arc [-14.70,145.40]→[-10.55,142.133]:")
bad_a = [145.40, -14.70]
bad_b = [142.133, -10.55]
detour = _find_land_crossing_detour(bad_a, bad_b)
print(f"   Result ({len(detour)} pts):")
for p in detour:
    print(f"     [{p[1]:.5f}, {p[0]:.5f}]")

# What does searoute return for this specific sub-segment?
print("\n4. sr.searoute for bad arc:")
try:
    r2 = sr.searoute((bad_a[0], bad_a[1]), (bad_b[0], bad_b[1]))
    sc = r2["geometry"]["coordinates"]
    print(f"   {len(sc)} pts:")
    for c in sc:
        print(f"     [{c[1]:.5f}, {c[0]:.5f}]")
except Exception as e:
    print(f"   ERROR: {e}")

# Also check: appended exact endpoint segment
print("\n5. Check exact-endpoint segment [-10.55,142.133]→[-10.7,141.9]:")
seg_a = [142.133, -10.55]
seg_b = [141.9, -10.7]
print(f"   _is_land_hires(-10.55, 142.133) = {_is_land_hires(-10.55, 142.133)}")
print(f"   _is_land_hires(-10.7, 141.9) = {_is_land_hires(-10.7, 141.9)}")
cross = _segment_crosses_land(seg_a[0], seg_a[1], seg_b[0], seg_b[1])
dist = geod.Inverse(seg_a[1], seg_a[0], seg_b[1], seg_b[0])["s12"] / 1000
print(f"   crosses_land={cross}  dist={dist:.1f}km")

# Step-by-step pipeline trace
print("\n6. Step-by-step pipeline trace for Nouméa→Torres WP:")
import copy

# Replicate searoute_with_exact_end logic
start = (NOUMEA[0], NOUMEA[1])
end = (TORRES[0], TORRES[1])
route = sr.searoute(start, end)
coords = list(route["geometry"]["coordinates"])

# Prepend start if needed
first_pt = coords[0]
sd = geod.Inverse(start[1], start[0], first_pt[1], first_pt[0])["s12"]
if sd > 1000:
    coords.insert(0, list(start))
    print(f"   Prepended start (was {sd:.0f}m away)")

# Append exact end if needed
last_pt = coords[-1]
ed = geod.Inverse(last_pt[1], last_pt[0], end[1], end[0])["s12"]
if ed > 1000:
    coords.append(list(end))
    print(f"   Appended exact end (was {ed:.0f}m away)")
print(f"   After append: {len(coords)} pts")

print("\n   Step 1 — avoid_land:")
print("   Segments that cross land:")
for i in range(len(coords)-1):
    a, b = coords[i], coords[i+1]
    if _segment_crosses_land(a[0], a[1], b[0], b[1]):
        dist = geod.Inverse(a[1], a[0], b[1], b[0])["s12"]/1000
        print(f"     seg [{a[1]:.4f},{a[0]:.4f}]→[{b[1]:.4f},{b[0]:.4f}] {dist:.0f}km")
        detour = _find_land_crossing_detour(a, b)
        print(f"     detour ({len(detour)} pts): {[[round(p[1],4), round(p[0],4)] for p in detour]}")

coords_step1 = avoid_land(coords)
print(f"   Step 1 result: {len(coords_step1)} pts")
coral1 = [p for p in coords_step1 if p[1] > -14 and p[0] > 147]
if coral1:
    print(f"   ⚠️ Coral Sea pts after Step 1: {[[round(p[1],4),round(p[0],4)] for p in coral1]}")

print("\n   Step 2 — densify (75km):")
coords_step2 = _densify_coords(coords_step1, max_km=75)
print(f"   {len(coords_step1)} → {len(coords_step2)} pts")

print("\n   Step 3 — sanitize:")
coords_step3 = _sanitize_route_coords(coords_step2)
print(f"   {len(coords_step2)} → {len(coords_step3)} pts")

print("\n   Step 4 — avoid_land (5 iterations):")
print("   Segments that cross land (from densified set):")
flagged = []
for i in range(len(coords_step3)-1):
    a, b = coords_step3[i], coords_step3[i+1]
    if _segment_crosses_land(a[0], a[1], b[0], b[1]):
        dist = geod.Inverse(a[1], a[0], b[1], b[0])["s12"]/1000
        print(f"     seg [{a[1]:.4f},{a[0]:.4f}]→[{b[1]:.4f},{b[0]:.4f}] {dist:.0f}km")
        flagged.append((a, b))

if flagged:
    print(f"   {len(flagged)} crossing(s) detected in Step 3 output")
    for a, b in flagged[:3]:
        detour = _find_land_crossing_detour(a, b)
        print(f"   Detour for [{a[1]:.4f},{a[0]:.4f}]→[{b[1]:.4f},{b[0]:.4f}]:")
        print(f"   ({len(detour)} pts): {[[round(p[1],4),round(p[0],4)] for p in detour]}")
        coral_d = [p for p in detour if p[1] > -14 and p[0] > 147]
        if coral_d:
            print(f"   ⚠️ Coral Sea in detour!")
else:
    print("   No crossings — Step 4 adds nothing")

print("\nDone.")
