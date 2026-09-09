"""
Diagnostic ciblé — trouver le bon intermédiaire pour casser l'arc Cape York.

Problème racine:
  searoute donne l'arc (-14.7,145.4)→(-10.55,142.13) comme arête directe.
  La géodésique de cet arc traverse la péninsule Cape York.
  avoid_land insère un détour perpendiculaire à (-11.51,145.20) — mauvaise direction.

Objectif: trouver un point intermédiaire P tel que:
  seg1: (-14.7,145.4) → P  ne traverse pas de terre
  seg2: P → (-10.55,142.13)  ne traverse pas de terre
  et P est WATER
"""
import sys; sys.path.insert(0, ".")
import searoute as sr
from main import _is_land_hires, _segment_crosses_land, Geodesic
geod = Geodesic.WGS84

ARC_A = [145.40, -14.70]
ARC_B = [142.133, -10.55]
NOUMEA  = [166.4572, -22.2958]
TORRES  = [142.217514, -9.742273]

print("\n" + "="*70)
print("1. Vérification: quels nœuds searoute existent entre (-14.7,145.4) et (-10.55,142.13)?")
print("="*70)

# Tester des positions intermédiaires variées pour voir si searoute les "snape" sur de nouveaux nœuds
test_intermediates = [
    (-13.0, 145.0), (-13.0, 144.5), (-13.0, 144.0), (-13.0, 143.5),
    (-12.0, 144.5), (-12.0, 144.0), (-12.0, 143.5), (-12.0, 143.0),
    (-11.5, 144.0), (-11.5, 143.5), (-11.5, 143.0), (-11.5, 142.5),
    (-11.0, 143.5), (-11.0, 143.0), (-11.0, 142.8), (-11.0, 142.5),
    (-10.8, 143.5), (-10.8, 143.0), (-10.8, 142.8), (-10.8, 142.5),
    (-10.5, 143.0), (-10.5, 142.8), (-10.5, 142.5), (-10.5, 142.3),
    (-10.3, 143.0), (-10.3, 142.8), (-10.3, 142.5), (-10.3, 142.3),
]

print(f"\n  {'Candidat':<22} {'Water':>6}  {'seg1_cross':>12}  {'seg2_cross':>12}  Status")
print("  " + "─"*65)
clean_candidates = []
for lat, lon in test_intermediates:
    water = not _is_land_hires(lat, lon)
    if not water:
        continue
    c1 = _segment_crosses_land(ARC_A[0], ARC_A[1], lon, lat)
    c2 = _segment_crosses_land(lon, lat, ARC_B[0], ARC_B[1])
    d1 = geod.Inverse(ARC_A[1], ARC_A[0], lat, lon)["s12"]/1000
    d2 = geod.Inverse(lat, lon, ARC_B[1], ARC_B[0])["s12"]/1000
    ok = not c1 and not c2
    status = "✅ CLEAN" if ok else ("⚠️  seg1" if c1 else "⚠️  seg2")
    print(f"  ({lat:.1f},{lon:.1f}){'':<14} {'✓':>6}  {str(c1):>12}  {str(c2):>12}  {status}")
    if ok:
        clean_candidates.append((lat, lon, d1, d2))

print(f"\n  → {len(clean_candidates)} candidat(s) clean trouvé(s): {[(c[0],c[1]) for c in clean_candidates]}")

print("\n" + "="*70)
print("2. Que fait searoute pour les candidats clean?")
print("   (route: ARC_A → candidat → ARC_B)")
print("="*70)
for lat, lon, d1, d2 in clean_candidates:
    r1 = sr.searoute((ARC_A[0], ARC_A[1]), (lon, lat))
    r2 = sr.searoute((lon, lat), (ARC_B[0], ARC_B[1]))
    c1 = r1["geometry"]["coordinates"] if r1 else []
    c2 = r2["geometry"]["coordinates"] if r2 else []
    coral1 = [p for p in c1 if p[0] > 147 and -16 < p[1] < -8]
    coral2 = [p for p in c2 if p[0] > 147 and -16 < p[1] < -8]
    print(f"  ({lat:.1f},{lon:.1f}): ARC_A→cand={len(c1)}pts coral={len(coral1)} | cand→ARC_B={len(c2)}pts coral={len(coral2)}")

print("\n" + "="*70)
print("3. Full pipeline via searoute_with_exact_end pour les candidats clean")
print("   (Nouméa → candidat → Torres WP → Arafura)")
print("="*70)
from main import searoute_with_exact_end
ARAFURA = (135.7760571767464, -8.975505823887872)

for lat, lon, d1, d2 in clean_candidates[:6]:
    WP = (lon, lat)
    r1 = searoute_with_exact_end(tuple(NOUMEA), WP)
    r2 = searoute_with_exact_end(WP, tuple(TORRES))
    c1 = r1["geometry"]["coordinates"] if r1 else []
    c2 = r2["geometry"]["coordinates"] if r2 else []
    # Critère coral aberrant: lon > 147 (pas 145 — les nœuds côtiers à 145 sont légitimes)
    co1 = [p for p in c1 if p[0] > 147 and -16 < p[1] < -8]
    co2 = [p for p in c2 if p[0] > 147 and -16 < p[1] < -8]
    la1 = [p for p in c1[1:-1] if _is_land_hires(p[1], p[0])]
    la2 = [p for p in c2[1:-1] if _is_land_hires(p[1], p[0])]
    ok = len(co1)==0 and len(co2)==0 and len(la1)==0 and len(la2)==0
    print(f"\n  WP ({lat:.1f},{lon:.1f}): {'✅ CLEAN' if ok else '⚠️ PROBLÈME'}")
    print(f"    Nouméa→WP:      {len(c1):>4}pts | coral(>147)={len(co1):>2} | land={len(la1):>2}")
    print(f"    WP→Torres:      {len(c2):>4}pts | coral(>147)={len(co2):>2} | land={len(la2):>2}")
    if co1: print(f"    ⚠️ coral_seg1 lon: {sorted([round(p[0],2) for p in co1], reverse=True)[:5]}")
    if co2: print(f"    ⚠️ coral_seg2 lon: {sorted([round(p[0],2) for p in co2], reverse=True)[:5]}")
    if la1: print(f"    ⚠️ land_seg1: {[[round(p[1],3),round(p[0],3)] for p in la1[:3]]}")
    if la2: print(f"    ⚠️ land_seg2: {[[round(p[1],3),round(p[0],3)] for p in la2[:3]]}")
    # Montrer les pts max lon dans chaque segment
    if c1:
        max_lon_pt = max(c1, key=lambda p: p[0])
        print(f"    lon max seg1: {round(max_lon_pt[0],2)}°E à lat={round(max_lon_pt[1],2)}")
    if c2:
        max_lon_pt2 = max(c2, key=lambda p: p[0])
        print(f"    lon max seg2: {round(max_lon_pt2[0],2)}°E à lat={round(max_lon_pt2[1],2)}")

print("\nFin.")
