"""
NAVIGUIDE Agent 1 — Berry-Mappemonde Pre-configured Waypoints
Official 18-stop circumnavigation of French overseas territories.
"""

BERRY_MAPPEMONDE_WAYPOINTS = [
    {"name": "La Rochelle",                             "lat":  46.1591, "lon":  -1.1520, "mandatory": True},
    {"name": "Ajaccio (Corse)",                         "lat":  41.9192, "lon":   8.7386, "mandatory": True},
    {"name": "Îles Canaries",                           "lat":  28.5521, "lon": -16.1529, "mandatory": True},
    {"name": "Fort-de-France (Martinique)",             "lat":  14.6037, "lon": -61.0731, "mandatory": True},
    {"name": "Pointe-à-Pitre (Guadeloupe)",             "lat":  16.2415, "lon": -61.5331, "mandatory": True},
    {"name": "Gustavia (Saint-Barthélemy)",             "lat":  17.8962, "lon": -62.8498, "mandatory": True},
    {"name": "Marigot (Saint-Martin)",                  "lat":  18.0679, "lon": -63.0822, "mandatory": True},
    {"name": "Halifax (Nouvelle-Écosse)",               "lat":  44.6488, "lon": -63.5752, "mandatory": True,
     "skip_maritime": True},   # air/land travel leg
    {"name": "Saint-Pierre (Saint-Pierre-et-Miquelon)", "lat":  46.7811, "lon": -56.1778, "mandatory": True},
    {"name": "Cayenne (Guyane française)",              "lat":   4.9333, "lon": -52.3333, "mandatory": True},
    {"name": "Papeete (Polynésie française)",           "lat": -17.5516, "lon":-149.5585, "mandatory": True},
    {"name": "Mata-Utu (Wallis-et-Futuna)",             "lat": -13.2825, "lon":-176.1736, "mandatory": True},
    {"name": "Nouméa (Nouvelle-Calédonie)",             "lat": -22.2758, "lon": 166.4572, "mandatory": True},
    {"name": "Dzaoudzi (Mayotte)",                      "lat": -12.7871, "lon":  45.2750, "mandatory": True},
    {"name": "Tromelin (TAAF)",                         "lat": -15.8900, "lon":  54.5200, "mandatory": True},
    {"name": "Saint-Gilles (La Réunion)",               "lat": -21.0594, "lon":  55.2242, "mandatory": True},
    {"name": "Europa (TAAF)",                           "lat": -22.3635, "lon":  40.3476, "mandatory": True},
    {"name": "La Rochelle (retour)",                    "lat":  46.1591, "lon":  -1.1520, "mandatory": True},
]
