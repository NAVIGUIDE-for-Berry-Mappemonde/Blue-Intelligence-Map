"""
Diagnostic complet — pipeline Nouméa → Cap York WP → Torres WP
Trace chaque étape pour identifier l'origine exacte du détour Coral Sea.
"""
import sys, copy
sys.path.insert(0, ".")
import searoute as sr
from main import (
    _is_land_hires, _segment_crosses_land, _find_land_crossing_detour,
    _densify_coords, _sanitize_route_coords, avoid_land,
    _normalize_antimeridian, Geodesic
)
geod = Geodesic.WGS84

NOUMEA   = [166.4572, -22.2958]
CAPYORK  = [145.5,    -14.5]
TORRES   = [142.217514, -9.742273]
ARAFURA  = [135.7760571767464, -8.975505823887872]

def is_coral(p):
    """Détour Coral Sea aberrant : lon > 145°E ET lat entre -8 et -16"""
    return p[0] > 145 and -16 < p[1] < -8

def fmt(p):
    return f"[{p[1]:.4f}, {p[0]:.4f}]"

def check_all_segments(coords, label=""):
    crossings = []
    for i in range(len(coords)-1):
        a, b = coords[i], coords[i+1]
        if _segment_crosses_land(a[0], a[1], b[0], b[1]):
            d = geod.Inverse(a[1], a[0], b[1], b[0])["s12"]/1000
            crossings.append((i, a, b, d))
    if crossings:
        print(f"  ⚠️  {label} — {len(crossings)} crossing(s):")
        for i, a, b, d in crossings:
            print(f"    seg[{i}] {fmt(a)} → {fmt(b)}  {d:.0f}km")
    else:
        print(f"  ✅ {label} — aucun crossing")
    return crossings

# ═══════════════════════════════════════════════════════════════════
print("\n" + "═"*70)
print("SEGMENT 1 : Nouméa → Cap York WP")
print("═"*70)

print("\n── 1a. searoute brut ──")
r1 = sr.searoute((NOUMEA[0], NOUMEA[1]), (CAPYORK[0], CAPYORK[1]))
raw1 = r1["geometry"]["coordinates"]
print(f"  {len(raw1)} pts:")
for p in raw1:
    coral_tag = "  ← CORAL SEA ⚠️" if is_coral(p) else ""
    print(f"    {fmt(p)}{coral_tag}")

# Prepend/append
coords1 = list(raw1)
sd = geod.Inverse(NOUMEA[1], NOUMEA[0], coords1[0][1], coords1[0][0])["s12"]
if sd > 1000:
    coords1.insert(0, list(NOUMEA))
ed = geod.Inverse(coords1[-1][1], coords1[-1][0], CAPYORK[1], CAPYORK[0])["s12"]
if ed > 1000:
    coords1.append(list(CAPYORK))
print(f"\n  Après prepend/append: {len(coords1)} pts")

print("\n── 1b. Step 1 — avoid_land ──")
crossings1 = check_all_segments(coords1, "pré-avoid_land")
print("  Détours appliqués:")
for i, a, b, d in crossings1:
    det = _find_land_crossing_detour(a, b)
    print(f"    {fmt(a)} → {fmt(b)}: {len(det)} pts → {[fmt(p) for p in det]}")
coords1_s1 = avoid_land(coords1)
print(f"  Résultat Step 1: {len(coords1_s1)} pts")
coral1_s1 = [p for p in coords1_s1 if is_coral(p)]
if coral1_s1:
    print(f"  ⚠️  Coral Sea après Step 1: {[fmt(p) for p in coral1_s1]}")

print("\n── 1c. Step 2 — densify ──")
coords1_s2 = _densify_coords(coords1_s1, max_km=75)
print(f"  {len(coords1_s1)} → {len(coords1_s2)} pts")
coral1_s2 = [p for p in coords1_s2 if is_coral(p)]
if coral1_s2:
    print(f"  ⚠️  Coral Sea après Step 2 ({len(coral1_s2)} pts):")
    for p in coral1_s2:
        print(f"    {fmt(p)}")

print("\n── 1d. Step 3 — sanitize ──")
coords1_s3 = _sanitize_route_coords(coords1_s2)
print(f"  {len(coords1_s2)} → {len(coords1_s3)} pts")

print("\n── 1e. Step 4 — avoid_land (2nd pass) ──")
crossings1_s4 = check_all_segments(coords1_s3, "pré-Step4")
for i, a, b, d in crossings1_s4[:5]:
    det = _find_land_crossing_detour(a, b)
    coral_det = [p for p in det if is_coral(p)]
    print(f"    Détour {fmt(a)}→{fmt(b)}: {[fmt(p) for p in det]}")
    if coral_det:
        print(f"    ⚠️  CORAL SEA INJECTÉ ICI: {[fmt(p) for p in coral_det]}")
coords1_s4 = avoid_land(coords1_s3, max_iterations=5)
coral1_s4 = [p for p in coords1_s4 if is_coral(p)]
print(f"  Résultat Step 4: {len(coords1_s4)} pts | Coral Sea: {len(coral1_s4)}")
if coral1_s4:
    print(f"  ⚠️  {[fmt(p) for p in coral1_s4]}")

# ═══════════════════════════════════════════════════════════════════
print("\n" + "═"*70)
print("SEGMENT 2 : Cap York WP → Torres WP")
print("═"*70)

print("\n── 2a. searoute brut ──")
r2 = sr.searoute((CAPYORK[0], CAPYORK[1]), (TORRES[0], TORRES[1]))
raw2 = r2["geometry"]["coordinates"]
print(f"  {len(raw2)} pts:")
for p in raw2:
    coral_tag = "  ← CORAL SEA ⚠️" if is_coral(p) else ""
    print(f"    {fmt(p)}{coral_tag}")

coords2 = list(raw2)
ed2 = geod.Inverse(coords2[-1][1], coords2[-1][0], TORRES[1], TORRES[0])["s12"]
if ed2 > 1000:
    coords2.append(list(TORRES))

print("\n── 2b. Step 1 — avoid_land ──")
crossings2 = check_all_segments(coords2, "pré-avoid_land")
for i, a, b, d in crossings2:
    det = _find_land_crossing_detour(a, b)
    print(f"    Détour: {[fmt(p) for p in det]}")
coords2_s1 = avoid_land(coords2)

print("\n── 2c. Step 2 — densify ──")
coords2_s2 = _densify_coords(coords2_s1, max_km=75)
print(f"  {len(coords2_s1)} → {len(coords2_s2)} pts")
coral2_s2 = [p for p in coords2_s2 if is_coral(p)]
if coral2_s2:
    print(f"  ⚠️  Coral Sea après densify: {[fmt(p) for p in coral2_s2]}")

print("\n── 2d. Step 4 — avoid_land (2nd pass) ──")
coords2_s3 = _sanitize_route_coords(coords2_s2)
crossings2_s4 = check_all_segments(coords2_s3, "pré-Step4")
for i, a, b, d in crossings2_s4[:5]:
    det = _find_land_crossing_detour(a, b)
    coral_det = [p for p in det if is_coral(p)]
    print(f"    Détour {fmt(a)}→{fmt(b)}: {[fmt(p) for p in det]}")
    if coral_det:
        print(f"    ⚠️  CORAL SEA INJECTÉ ICI")
coords2_s4 = avoid_land(coords2_s3, max_iterations=5)
coral2_s4 = [p for p in coords2_s4 if is_coral(p)]
print(f"  Résultat: {len(coords2_s4)} pts | Coral Sea: {len(coral2_s4)}")
if coral2_s4:
    print(f"  ⚠️  {[fmt(p) for p in coral2_s4]}")

# ═══════════════════════════════════════════════════════════════════
print("\n" + "═"*70)
print("ROUTE COMBINÉE via searoute_with_exact_end")
print("═"*70)
from main import searoute_with_exact_end

for label, s, e in [
    ("Nouméa → Cap York WP",   tuple(NOUMEA),  tuple(CAPYORK)),
    ("Cap York WP → Torres WP", tuple(CAPYORK), tuple(TORRES)),
    ("Torres WP → Arafura",    tuple(TORRES),  tuple(ARAFURA)),
]:
    r = searoute_with_exact_end(s, e)
    c = r["geometry"]["coordinates"]
    coral = [p for p in c if is_coral(p)]
    land  = [p for p in c[1:-1] if _is_land_hires(p[1], p[0])]
    status = "✅" if not coral and not land else "⚠️"
    print(f"\n{label}: {len(c)} pts {status}")
    if coral:
        print(f"  ⚠️  CORAL SEA ({len(coral)} pts):")
        for p in coral: print(f"    {fmt(p)}")
    if land:
        print(f"  ⚠️  TERRE ({len(land)} pts):")
        for p in land[:5]: print(f"    {fmt(p)}")
    if not coral and not land:
        print(f"  0 Coral Sea, 0 terre")

print("\nFin diagnostic.")
