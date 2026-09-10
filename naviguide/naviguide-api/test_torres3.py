"""
Final validation: full searoute_with_exact_end pipeline — no Coral Sea detour.
Also validates the Torres→Arafura segment and the combined Nouméa→Arafura leg.
"""
import sys
sys.path.insert(0, ".")
from main import searoute_with_exact_end, _is_land_hires, Geodesic
geod = Geodesic.WGS84

NOUMEA   = [166.4572, -22.2958]
TORRES   = [141.9,    -10.7]
ARAFURA  = [135.7760571767464, -8.975505823887872]

def check_route(label, start, end):
    r = searoute_with_exact_end(start, end)
    if not r:
        print(f"  {label}: ❌ No route returned")
        return
    coords = r["geometry"]["coordinates"]
    coral   = [p for p in coords if p[1] > -14 and p[0] > 147]
    land_pts = [p for p in coords[1:-1] if _is_land_hires(p[1], p[0])]
    print(f"  {label}: {len(coords)} pts | Coral Sea pts: {len(coral)} | Land pts: {len(land_pts)}")
    if coral:
        print(f"    ⚠️  Coral Sea: {[[round(p[1],3), round(p[0],3)] for p in coral[:5]]}")
    else:
        print(f"    ✅ No Coral Sea detour")
    if land_pts:
        print(f"    ⚠️  Land pts: {[[round(p[1],4), round(p[0],4)] for p in land_pts[:3]]}")
    else:
        print(f"    ✅ No intermediate land pts")
    # Show all pts if small enough
    if len(coords) <= 20:
        for c in coords:
            print(f"      [{c[1]:.4f}, {c[0]:.4f}]")

print("\n" + "="*70)
print("FULL PIPELINE VALIDATION — TORRES STRAIT")
print("="*70 + "\n")

check_route("Nouméa → Torres WP",     tuple(NOUMEA), tuple(TORRES))
check_route("Torres WP → Arafura",    tuple(TORRES), tuple(ARAFURA))
# Reverse legs
check_route("Torres WP → Nouméa",     tuple(TORRES), tuple(NOUMEA))
check_route("Arafura → Torres WP",    tuple(ARAFURA), tuple(TORRES))

print("\nDone.")
