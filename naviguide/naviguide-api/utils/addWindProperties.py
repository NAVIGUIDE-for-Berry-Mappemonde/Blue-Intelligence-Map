from copernicus.getWind import overWind

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
    
    high_wind_points = []
    
    # Extraire les coordonnées selon le type de GeoJSON
    if route_geojson.get("type") == "Feature":
        geometry = route_geojson.get("geometry", {})
        coords = geometry.get("coordinates", [])
        
        if geometry.get("type") == "LineString":
            for i in range(0, len(coords), sample_rate):
                lon, lat = coords[i][0], coords[i][1]
                
                if overWind(lat, lon, username, password):
                    high_wind_points.append({
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [lon, lat]
                        },
                        "properties": {
                            "highWind": True,
                            "warning": "Vent supérieur à 35 nœuds"
                        }
                    })
        
        elif geometry.get("type") == "MultiLineString":
            for line in coords:
                for i in range(0, len(line), sample_rate):
                    lon, lat = line[i][0], line[i][1]
                    
                    if overWind(lat, lon, username, password):
                        high_wind_points.append({
                            "type": "Feature",
                            "geometry": {
                                "type": "Point",
                                "coordinates": [lon, lat]
                            },
                            "properties": {
                                "highWind": True,
                                "warning": "Vent supérieur à 35 nœuds"
                            }
                        })
    
    elif route_geojson.get("type") == "FeatureCollection":
        for feature in route_geojson.get("features", []):
            geometry = feature.get("geometry", {})
            coords = geometry.get("coordinates", [])
            
            if geometry.get("type") == "LineString":
                for i in range(0, len(coords), sample_rate):
                    lon, lat = coords[i][0], coords[i][1]
                    
                    if overWind(lat, lon, username, password):
                        high_wind_points.append({
                            "type": "Feature",
                            "geometry": {
                                "type": "Point",
                                "coordinates": [lon, lat]
                            },
                            "properties": {
                                "highWind": True,
                                "warning": "Vent supérieur à 35 nœuds"
                            }
                        })
    
    # Retourner une FeatureCollection avec la route + les points de vent fort
    return {
        "type": "FeatureCollection",
        "features": [
            route_geojson,
            *high_wind_points
        ]
    }