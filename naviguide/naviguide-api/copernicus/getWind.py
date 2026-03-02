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
    
def _climatological_wind_knots(latitude: float, longitude: float) -> float:
    """
    Simple built-in climatological wind estimate (annual average) used as
    fallback when Copernicus Marine is unavailable.
    Returns approximate wind speed in knots for the given position.
    """
    lat = abs(latitude)
    in_atlantic = -80 <= longitude <= 20
    in_indian   =  20 <= longitude <= 120
    # Polar
    if lat > 60:
        return 20.0
    # Roaring Forties / Furious Fifties
    if 40 <= lat <= 60:
        return 22.0 + (lat - 40) * 0.4   # 22–30 kn
    # Westerlies
    if 35 <= lat <= 40:
        return 18.0
    # Trade winds
    if 5 <= lat <= 30:
        return 15.0
    # Doldrums / ITCZ
    if lat <= 5:
        return 5.0
    return 12.0


def overWind(latitude, longitude, username=None, password=None):
    """
    Returns True if wind speed exceeds threshold at the given position.

    Primary: Copernicus Marine real-time data (threshold > 10 kn).
    Fallback: built-in climatological model (threshold > 20 kn) when
    Copernicus is unavailable (no credentials, network error, etc.).
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

        u_wind = float(point_data['eastward_wind'].isel(time=-1).values)
        v_wind = float(point_data['northward_wind'].isel(time=-1).values)
        wind_speed_ms = math.sqrt(u_wind**2 + v_wind**2)
        wind_speed_knots = wind_speed_ms * 1.944
        print(f"🌬️  Vitesse du vent (Copernicus): {wind_speed_knots:.1f} kn")
        return wind_speed_knots > 10

    except Exception as e:
        # Copernicus unavailable — use built-in climatological fallback
        print(f"⚠️  Copernicus unavailable ({type(e).__name__}), using climatological fallback")
        spd = _climatological_wind_knots(latitude, longitude)
        print(f"🌬️  Vitesse du vent (climatologie): {spd:.1f} kn")
        return spd > 20