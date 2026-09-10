from copernicus.getWind import overWind
from copernicus.getWave import overWave

def add_wind_properties_to_route(route_geojson, username=None, password=None, sample_rate=10):
    """
    Ajoute des points avec propriétés "highWind" pour chaque position où le vent > 35 nœuds
    
    Args:
        route_geojson (dict): GeoJSON de la route retourné par searoute
        username (str): Username Copernicus Marine
        password (str): Password Copernicus Marine
        sample_rate (int): Vérifier 1 point tous les N points (pour optimiser les appels API)
    
    Returns:
        dict: FeatureCollection avec la route originale + points de vent fort
    """
    
    alert_points = []

    def _check_point(lon, lat):
        """Check wind + wave at a sampled coordinate and add alert markers."""
        if overWind(lat, lon, username, password):
            alert_points.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {"highWind": True, "warning": "Vent fort détecté (>20 kn)"}
            })
        if overWave(lat, lon, username, password):
            alert_points.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {"highWave": True, "warning": "Vague significative détectée (>2 m)"}
            })

    def _scan_coords(coords):
        for i in range(0, len(coords), sample_rate):
            lon, lat = coords[i][0], coords[i][1]
            _check_point(lon, lat)

    # Handle Feature (LineString / MultiLineString)
    if route_geojson.get("type") == "Feature":
        geometry = route_geojson.get("geometry", {})
        coords   = geometry.get("coordinates", [])
        if geometry.get("type") == "LineString":
            _scan_coords(coords)
        elif geometry.get("type") == "MultiLineString":
            for line in coords:
                _scan_coords(line)

    # Handle FeatureCollection
    elif route_geojson.get("type") == "FeatureCollection":
        for feature in route_geojson.get("features", []):
            geometry = feature.get("geometry", {})
            coords   = geometry.get("coordinates", [])
            if geometry.get("type") == "LineString":
                _scan_coords(coords)
            elif geometry.get("type") == "MultiLineString":
                for line in coords:
                    _scan_coords(line)

    return {
        "type": "FeatureCollection",
        "features": [route_geojson, *alert_points]
    }