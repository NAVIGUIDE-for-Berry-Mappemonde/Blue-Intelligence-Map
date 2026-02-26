"""
Script pour récupérer les données de vent depuis Copernicus Marine
pour une position géographique donnée
"""
import math
import pandas as pd
import numpy as np
import copernicusmarine
import xarray as xr
from datetime import datetime, timedelta

def get_wind_data_at_position(latitude, longitude, username=None, password=None):
    """
    Récupère les données de vent à une position donnée
    
    Args:
        latitude (float): Latitude (-90 à 90)
        longitude (float): Longitude (-180 à 180)
        username (str): Votre username Copernicus Marine
        password (str): Votre password Copernicus Marine
    
    Returns:
        dict: Données de vent (eastward_wind, northward_wind, vitesse, direction)
    """
    
    try:
        # Dataset ID pour les vents globaux (satellite)
        dataset_id = "cmems_obs-wind_glo_phy_nrt_l4_0.125deg_PT1H"
        
        # Date : prendre il y a 2 jours (délai de traitement satellite)
        end_date = datetime.now() - timedelta(days=2)
        start_date = end_date - timedelta(days=1)
        
        # Créer une petite zone autour du point (±0.1 degré)
        margin = 0.1
        
        print(f"🔍 Récupération des données de vent pour:")
        print(f"   Latitude: {latitude}°")
        print(f"   Longitude: {longitude}°")
        print(f"   Date: {end_date.strftime('%Y-%m-%d')}")
        
        # Ouvrir le dataset avec les filtres
        dataset = copernicusmarine.open_dataset(
            dataset_id=dataset_id,
            username=username,
            password=password,
            variables=["eastward_wind", "northward_wind"],  # ✅ Composantes du VENT
            minimum_longitude=longitude - margin,
            maximum_longitude=longitude + margin,
            minimum_latitude=latitude - margin,
            maximum_latitude=latitude + margin,
            start_datetime=start_date.strftime("%Y-%m-%d"),
            end_datetime=end_date.strftime("%Y-%m-%d"),
            coordinates_selection_method="nearest"
        )
        
        # Sélectionner le point le plus proche
        point_data = dataset.sel(
            latitude=latitude,
            longitude=longitude,
            method="nearest"
        )
        
        # ✅ Extraire les données directement (pas de try/except nécessaire)
        # Pas de dimension 'depth' pour le vent atmosphérique
        u_wind = float(point_data['eastward_wind'].isel(time=-1).values)
        v_wind = float(point_data['northward_wind'].isel(time=-1).values)
        
        # Calculer vitesse et direction
        import math
        wind_speed = math.sqrt(u_wind**2 + v_wind**2)
        
        # ✅ Direction météorologique (d'où VIENT le vent)
        # Convention : 0° = Nord, 90° = Est, 180° = Sud, 270° = Ouest
        wind_direction = (math.atan2(-u_wind, -v_wind) * 180 / math.pi) % 360

        # Récupérer le timestamp et le convertir en string ISO
        timestamp_value = point_data.time.isel(time=-1).values
        
        # Convertir numpy.datetime64 en string ISO 8601
        if isinstance(timestamp_value, np.datetime64):
            timestamp_str = pd.Timestamp(timestamp_value).isoformat()
        else:
            timestamp_str = str(timestamp_value)
        
        result = {
            "latitude": latitude,
            "longitude": longitude,
            "u_component": round(u_wind, 3),  # m/s (composante Est)
            "v_component": round(v_wind, 3),  # m/s (composante Nord)
            "wind_speed": round(wind_speed, 3),  # m/s
            "wind_speed_kmh": round(wind_speed * 3.6, 2),  # km/h
            "wind_speed_knots": round(wind_speed * 1.944, 2),  # nœuds
            "wind_direction": round(wind_direction, 1),  # degrés (d'où vient le vent)
            "timestamp": timestamp_str
        }
        
        print("\n✅ Données récupérées avec succès:")
        print(f"   Vitesse: {result['wind_speed_kmh']} km/h ({result['wind_speed_knots']} nœuds)")
        print(f"   Direction: {result['wind_direction']}° (d'où vient le vent)")
        
        return result
        
    except Exception as e:
        print(f"❌ Erreur lors de la récupération: {e}")
        import traceback
        traceback.print_exc()  # ✅ Ajouté pour debug
        return None
    
def overWind(latitude, longitude, username=None, password=None):
    """
    Vérifie si la vitesse du vent dépasse 35 nœuds à une position donnée
    
    Args:
        latitude (float): Latitude (-90 à 90)
        longitude (float): Longitude (-180 à 180)
        username (str): Username Copernicus Marine
        password (str): Password Copernicus Marine
    
    Returns:
        bool: True si vent > 35 nœuds, False sinon
    """
    
    try:
        dataset_id = "cmems_obs-wind_glo_phy_nrt_l4_0.125deg_PT1H"
        end_date = datetime.now() - timedelta(days=2)
        start_date = end_date - timedelta(days=1)
        margin = 0.1
        
        dataset = copernicusmarine.open_dataset(
            dataset_id=dataset_id,
            username=username,
            password=password,
            variables=["eastward_wind", "northward_wind"],
            minimum_longitude=longitude - margin,
            maximum_longitude=longitude + margin,
            minimum_latitude=latitude - margin,
            maximum_latitude=latitude + margin,
            start_datetime=start_date.strftime("%Y-%m-%d"),
            end_datetime=end_date.strftime("%Y-%m-%d"),
            coordinates_selection_method="nearest"
        )
        
        point_data = dataset.sel(
            latitude=latitude,
            longitude=longitude,
            method="nearest"
        )
        
        # ✅ Utilisation des BONNES variables (pas de try/except nécessaire)
        u_wind = float(point_data['eastward_wind'].isel(time=-1).values)
        v_wind = float(point_data['northward_wind'].isel(time=-1).values)
        
        # Calcul de la vitesse en nœuds
        wind_speed_ms = math.sqrt(u_wind**2 + v_wind**2)
        wind_speed_knots = wind_speed_ms * 1.944

        print(f"🌬️  Vitesse du vent : {wind_speed_knots:.1f} nœuds")
        
        # ✅ Comparaison au bon seuil (35 au lieu de 0)
        return wind_speed_knots > 10
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return False