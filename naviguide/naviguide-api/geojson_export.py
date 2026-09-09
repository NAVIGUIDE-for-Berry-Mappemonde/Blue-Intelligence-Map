import searoute as sr
import geojson
from geographiclib.geodesic import Geodesic

points = [
    {
        "name": "Saint-Maur (Berry, Indre)",
        "lat": 46.8075,
        "lon": 1.6358,
    },
    {
        "name": "La Rochelle",
        "lat": 46.1591,
        "lon": -1.152,
    },
    {
        "name": "Point intermédiaire Avant Corse",
        "lat": 41.055680018451,
        "lon": 7.571686294801026,
    },
    {
        "name": "Ajaccio (Corse)",
        "lat": 41.9192,
        "lon": 8.7386,
    },
    {
        "name": "Point intermédiaire Après Corse",
        "lat": 43.30582034342319,
        "lon": 8.664023850795274,
    },
    {
        "name": "Point intermédiaire Après Corse",
        "lat": 42.220925515885995,
        "lon": 9.843755668349303,
    },
    {
        "name": "Iles Canari",
        "lat": 28.552146108993732,
        "lon": -16.152899853657026,
    },
    {
        "name": "Point intermédiaire Cap Verde",
        "lat": 15.368627983051251,
        "lon": -23.045223166200472,
    },
    {
        "name": "Sainte Lucie",
        "lat": 13.709584456467352,
        "lon": -60.94531985356372,
    },
    {
        "name": "Fort-de-France (Martinique)",
        "lat": 14.6037,
        "lon": -61.0731,
    },
    {
        "name": "Pointe-à-Pitre (Guadeloupe)",
        "lat": 16.2415,
        "lon": -61.5331,
    },
    {
        "name": "Gustavia (Saint-Barthélemy)",
        "lat": 17.8962,
        "lon": -62.8498,
    },
    {
        "name": "Marigot (Saint-Martin)",
        "lat": 18.0679,
        "lon": -63.0822,
    },
    {
        "name": "Halifax (Nouvelle-Écosse)",
        "lat": 44.6488,
        "lon": -63.5752,
    },
    {
        "name": "Saint-Pierre (Saint-Pierre-et-Miquelon)",
        "lat": 46.7811,
        "lon": -56.1778,
    },
    {
        "name": "Cayenne (Guyane)",
        "lat": 4.9333,
        "lon": -52.3333,
    },
    {
        "name": "Papeete (Polynésie française)",
        "lat": -17.5516,
        "lon": -149.5585,
    },
    {
        "name": "Mata-Utu (Wallis-et-Futuna)",
        "lat": -13.2825,
        "lon": -176.1736,
    },
    {
        "name": "Nouméa (Nouvelle-Calédonie)",
        "lat": -22.2758,
        "lon": 166.4572,
    },
    {
        "name": "Point intermédiaire haut Australie",
        "lat": -8.975505823887872,
        "lon": 135.7760571767464,
    },
    {
        "name": "Point intermédiaire haut Australie",
        "lat": -9.365171092340532,
        "lon": 105.09261288903605,
    },
    {
        "name": "Point intermédiaire haut Australie",
        "lat": 6.372651054775204,
        "lon": 88.60640235539029,
    },
    {
        "name": "Sri Lanka",
        "lat": 6.795662475285454,
        "lon": 81.74544471063405,
    },
    {
        "name": "Maldives",
        "lat": -0.011960820899744817,
        "lon": 73.34654992443669,
    },
    {
        "name": "Seichelles",
        "lat": -4.795530233666341,
        "lon": 55.53081114349709,
    },
    {
        "name": "Dzaoudzi (Mayotte)",
        "lat": -12.7871,
        "lon": 45.275,
    },
    {
        "name": "Tromelin (TAAF)",
        "lat": -15.89,
        "lon": 54.52,
    },
    {
        "name": "Saint-Gilles (La Réunion)",
        "lat": -21.0594,
        "lon": 55.2242,
    },
    {
        "name": "Europa (TAAF)",
        "lat": -22.36347142513217,
        "lon": 40.34757733809297,
    },
    {
        "name": "Point intermédiaire Cap de la Bonne Espérance",
        "lat": -33.582958207198814,
        "lon": 14.083704115920511,
    },
    {
        "name": "Point intermédiaire Sainte Hélène",
        "lat": -15.941485255147134,
        "lon": -5.714154676640543,
    },
    {
        "name": "Point intermédiaire Ascension",
        "lat": -7.949169371068545,
        "lon": -14.344106934299496,
    },
    {
        "name": "Point intermédiaire Ascension - Cap Verde",
        "lat": 4.649408270655059,
        "lon": -24.595104128163598,
    },
    {
        "name": "Point intermédiaire Cap Verde",
        "lat": 15.368627983051251,
        "lon": -23.045223166200472,
    },
    {
        "name": "La Rochelle",
        "lat": 46.1591,
        "lon": -1.152,
    },
]

def searoute_with_exact_end(start, end):
    """
    Calcule une route maritime entre deux points et ajoute un segment géodésique
    jusqu'à la destination exacte si searoute s'arrête trop tôt.
    Gère correctement le passage de l'antiméridien (180°/-180°).
    """
    try:
        route = sr.searoute(start, end)
    except Exception as e:
        print(f"⚠️ Erreur searoute: {e}")
        return None

    if not route or "geometry" not in route:
        return None

    coords = route["geometry"]["coordinates"]
    last_point = coords[-1]

    # Calcul de la distance entre le dernier point et le vrai point d'arrivée
    geod = Geodesic.WGS84
    dist = geod.Inverse(last_point[1], last_point[0], end[1], end[0])["s12"]  # mètres

    # Si la route ne va pas jusqu'au point exact, on ajoute une courte ligne géodésique
    if dist > 1000:  # seuil = 1 km
        n_points = max(2, int(dist // 5000))  # environ 1 point tous les 5 km
        line = geod.InverseLine(last_point[1], last_point[0], end[1], end[0])
        extra_coords = []
        
        for i in range(1, n_points):
            pos = line.Position(i * line.s13 / (n_points - 1))
            lon = pos["lon2"]
            lat = pos["lat2"]
            
            # Normaliser la longitude pour gérer le passage de l'antiméridien
            # On vérifie si on doit ajuster la longitude pour éviter le trait global
            if len(coords) > 0:
                prev_lon = coords[-1][0] if len(extra_coords) == 0 else extra_coords[-1][0]
                
                # Si la différence est > 180°, on ajuste
                if lon - prev_lon > 180:
                    lon -= 360
                elif lon - prev_lon < -180:
                    lon += 360
            
            extra_coords.append([lon, lat])
        
        coords.extend(extra_coords)

    route["geometry"]["coordinates"] = coords
    return route


def compute_full_route(points):
    """
    Calcule toutes les routes maritimes entre les points successifs du tableau,
    en s'assurant que chaque route atteint précisément le point défini.
    
    :param points: liste de dictionnaires contenant 'lat' et 'lon'
    :return: objet GeoJSON (FeatureCollection)
    """
    features = []

    for i in range(len(points) - 1):
        # Skip la connexion 12->13 (Marigot -> Halifax)
        # et 14->15 (Saint-Pierre -> Cayenne) pour dissocier Halifax et Saint-Pierre
        if i == 12 or i == 14:
            continue
            
        start = (points[i]["lon"], points[i]["lat"])
        end = (points[i + 1]["lon"], points[i + 1]["lat"])

        try:
            route = searoute_with_exact_end(start, end)
            if route and isinstance(route, dict) and "geometry" in route:
                features.append(
                    geojson.Feature(
                        geometry=route["geometry"],
                        properties={
                            "from": points[i]["name"],
                            "to": points[i + 1]["name"],
                            "distance_km": route.get("properties", {}).get("length", None),
                        },
                    )
                )
        except Exception as e:
            print(f"⚠️ Erreur lors du calcul entre {points[i]['name']} et {points[i+1]['name']}: {e}")

    # Ajouter la connexion directe Marigot (12) -> Cayenne (15)
    try:
        start = (points[12]["lon"], points[12]["lat"])
        end = (points[15]["lon"], points[15]["lat"])
        route = searoute_with_exact_end(start, end)
        if route and isinstance(route, dict) and "geometry" in route:
            features.append(
                geojson.Feature(
                    geometry=route["geometry"],
                    properties={
                        "from": points[12]["name"],
                        "to": points[15]["name"],
                        "distance_km": route.get("properties", {}).get("length", None),
                    },
                )
            )
    except Exception as e:
        print(f"⚠️ Erreur Marigot->Cayenne: {e}")

    # Ajouter le segment isolé Halifax (13) -> Saint-Pierre (14)
    try:
        start = (points[13]["lon"], points[13]["lat"])
        end = (points[14]["lon"], points[14]["lat"])
        route = searoute_with_exact_end(start, end)
        if route and isinstance(route, dict) and "geometry" in route:
            features.append(
                geojson.Feature(
                    geometry=route["geometry"],
                    properties={
                        "from": points[13]["name"],
                        "to": points[14]["name"],
                        "distance_km": route.get("properties", {}).get("length", None),
                    },
                )
            )
    except Exception as e:
        print(f"⚠️ Erreur Halifax->Saint-Pierre: {e}")

    full_geojson = geojson.FeatureCollection(features)
    return full_geojson


# Exemple d'utilisation : test
result = compute_full_route(points)
with open("routes.geojson", "w") as f:
    geojson.dump(result, f)
print("✅ Fichier routes.geojson généré avec succès.")