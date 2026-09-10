"""
Regression test: verify all major route segments across the itinerary are clean
(no Coral Sea detour, no land points, no antimeridian corruption).
"""
import sys
sys.path.insert(0, ".")
from main import searoute_with_exact_end, _is_land_hires

SEGMENTS = [
    # label, (lon1,lat1), (lon2,lat2)
    ("La Rochelle→Ajaccio",         (-1.167,46.1541),  (8.7386,41.9192)),
    ("Ajaccio→Canaries",            (8.7386,41.9192),  (-15.181,29.325)),
    ("Canaries→Cap Verde",          (-15.181,29.325),  (-24.531,13.919)),
    ("Cap Verde→Sainte Lucie",      (-24.531,13.919),  (-61.498,13.499)),
    ("Sainte Lucie→Fort-de-France", (-61.498,13.499),  (-61.0731,14.5887)),
    ("Fort-de-France→Pointe-à-Pitre",(-61.0731,14.5887),(-61.5381,16.2365)),
    ("Pointe-à-Pitre→Gustavia",     (-61.5381,16.2365),(-62.8548,17.8912)),
    ("Gustavia→Marigot",            (-62.8548,17.8912),(-63.0922,18.0829)),
    ("Marigot→Halifax",             (-63.0922,18.0829),(-63.5652,44.6488)),
    ("Halifax→Saint-Pierre",        (-63.5652,44.6488),(-56.1628,46.7761)),
    ("Saint-Pierre→Cayenne",        (-56.1628,46.7761),(-52.3533,4.9333)),
    ("Cayenne→Papeete",             (-52.3533,4.9333), (-149.5685,-17.5116)),
    ("Papeete→Wallis-Futuna",       (-149.5685,-17.5116),(-176.2036,-13.2725)),
    ("Wallis-Futuna→Nouméa",        (-176.2036,-13.2725),(166.4572,-22.2958)),
    ("Nouméa→Torres WP",            (166.4572,-22.2958),(141.9,-10.7)),
    ("Torres WP→Arafura",           (141.9,-10.7),     (135.7760571767464,-8.975505823887872)),
    ("Arafura→haut Australie 2",    (135.7760571767464,-8.975505823887872),(105.09261288903605,-9.365171092340532)),
    ("haut Australie 2→haut Australie 3",(105.09261288903605,-9.365171092340532),(88.60640235539029,6.372651054775204)),
    ("haut Australie 3→Sri Lanka",  (88.60640235539029,6.372651054775204),(81.8354,6.7907)),
    ("Sri Lanka→Maldives",          (81.8354,6.7907),  (73.34654992443669,-0.011960820899744817)),
    ("Maldives→Seychelles",         (73.34654992443669,-0.011960820899744817),(55.5358,-4.7905)),
    ("Seychelles→Dzaoudzi",         (55.5358,-4.7905), (45.27,-12.7921)),
    ("Dzaoudzi→Tromelin",           (45.27,-12.7921),  (54.525,-15.89)),
    ("Tromelin→Réunion",            (54.525,-15.89),   (55.2242,-21.0594)),
    ("Réunion→Europa",              (55.2242,-21.0594), (40.3476,-22.3685)),
    ("Europa→Cap Bonne Espérance",  (40.3476,-22.3685),(14.083704115920511,-33.582958207198814)),
    ("Cap Bonne Espérance→Sainte Hélène", (14.083704115920511,-33.582958207198814),(-5.7392,-15.9165)),
    ("Sainte Hélène→Ascension",     (-5.7392,-15.9165),(-14.3291,-7.9692)),
    ("Ascension→Cap Verde (retour)",(-14.3291,-7.9692),(-24.531,13.919)),
    ("Cap Verde (retour)→La Rochelle",(-24.531,13.919),(-1.167,46.1541)),
]

print("\n" + "="*80)
print(f"{'Segment':<42} {'Pts':>5}  {'Coral':>5}  {'Land':>5}  Status")
print("="*80)

total_fail = 0
for label, start, end in SEGMENTS:
    r = searoute_with_exact_end(start, end)
    if not r:
        print(f"  {label:<42} {'N/A':>5}  {'N/A':>5}  {'N/A':>5}  ❌ NO ROUTE")
        total_fail += 1
        continue
    coords = r["geometry"]["coordinates"]
    coral = sum(1 for p in coords if p[1] > -14 and p[0] > 147)
    land  = sum(1 for p in coords[1:-1] if _is_land_hires(p[1], p[0]))
    ok = coral == 0 and land == 0
    status = "✅" if ok else "⚠️"
    if not ok:
        total_fail += 1
    print(f"  {label:<42} {len(coords):>5}  {coral:>5}  {land:>5}  {status}")

print("="*80)
if total_fail == 0:
    print(f"✅ ALL {len(SEGMENTS)} segments clean")
else:
    print(f"⚠️  {total_fail} segment(s) with issues")
print()
