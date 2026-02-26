"""
Script pour récupérer les données de vague depuis Copernicus Marine
pour une position géographique donnée
"""
import math
import pandas as pd
import numpy as np
import copernicusmarine
from datetime import datetime, timedelta


def get_wave_data_at_position(latitude, longitude, username=None, password=None):
    """
    Récupère les données de vague à une position donnée

    Args:
        latitude (float): Latitude (-90 à 90)
        longitude (float): Longitude (-180 à 180)
        username (str): Username Copernicus Marine
        password (str): Password Copernicus Marine

    Returns:
        dict: Données de vague (hauteur significative, période, direction)
    """
    try:
        # Dataset ID pour le modèle de vagues globales
        dataset_id = "cmems_mod_glo_wav_anfc_0.083deg_PT3H-i"

        # Date : données récentes (délai de 1 jour)
        end_date = datetime.now() - timedelta(days=1)
        start_date = end_date - timedelta(days=1)

        # Zone autour du point (±0.2 degré)
        margin = 0.2

        print(f"🌊 Récupération des données de vague pour:")
        print(f"   Latitude: {latitude}°")
        print(f"   Longitude: {longitude}°")
        print(f"   Date: {end_date.strftime('%Y-%m-%d')}")

        # Ouvrir le dataset avec les filtres
        dataset = copernicusmarine.open_dataset(
            dataset_id=dataset_id,
            username=username,
            password=password,
            variables=["VHM0", "VTM02", "VMDR"],
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

        # Hauteur significative des vagues (m)
        vhm0 = float(point_data['VHM0'].isel(time=-1).values)

        result = {
            "latitude": latitude,
            "longitude": longitude,
            "significant_wave_height_m": round(vhm0, 2),
        }

        # Période moyenne (optionnel)
        try:
            vtm02 = float(point_data['VTM02'].isel(time=-1).values)
            if not math.isnan(vtm02):
                result["mean_wave_period"] = round(vtm02, 1)
        except Exception:
            pass

        # Direction moyenne (optionnel)
        try:
            vmdr = float(point_data['VMDR'].isel(time=-1).values)
            if not math.isnan(vmdr):
                result["mean_wave_direction"] = round(vmdr, 1)
        except Exception:
            pass

        # Timestamp
        try:
            timestamp_value = point_data.time.isel(time=-1).values
            if isinstance(timestamp_value, np.datetime64):
                result["timestamp"] = pd.Timestamp(timestamp_value).isoformat()
        except Exception:
            pass

        print(f"✅ Hauteur significative: {result['significant_wave_height_m']} m")
        return result

    except Exception as e:
        print(f"❌ Erreur lors de la récupération des vagues: {e}")
        import traceback
        traceback.print_exc()
        return None
