"""
Script pour récupérer les données de courants marins depuis Copernicus Marine
pour une position géographique donnée.

Dataset : cmems_mod_glo_phy_anfc_0.083deg_PT1H-m
Variables : uo (eastward_sea_water_velocity), vo (northward_sea_water_velocity)
"""
import math
import pandas as pd
import numpy as np
import copernicusmarine
from datetime import datetime, timedelta


def get_current_data_at_position(latitude, longitude, username=None, password=None):
    """
    Récupère les données de courant marin de surface à une position donnée.

    Args:
        latitude  (float) : Latitude  (-90 à 90)
        longitude (float) : Longitude (-180 à 180)
        username  (str)   : Username Copernicus Marine
        password  (str)   : Password Copernicus Marine

    Returns:
        dict | None : Données de courant (vitesse m/s, nœuds, direction °)
                      ou None en cas d'erreur.
    """
    try:
        # Global Ocean Physics Analysis and Forecast — currents at surface
        dataset_id = "cmems_mod_glo_phy_anfc_0.083deg_PT1H-m"

        # Fenêtre temporelle : hier (délai de traitement d'1 jour)
        end_date   = datetime.now() - timedelta(days=1)
        start_date = end_date - timedelta(days=1)

        margin = 0.2   # zone ±0.2° autour du point

        print(f"🌊 Récupération des courants marins pour:")
        print(f"   Latitude  : {latitude}°")
        print(f"   Longitude : {longitude}°")
        print(f"   Date      : {end_date.strftime('%Y-%m-%d')}")

        dataset = copernicusmarine.open_dataset(
            dataset_id=dataset_id,
            username=username,
            password=password,
            variables=["uo", "vo"],          # eastward / northward current
            minimum_longitude=longitude - margin,
            maximum_longitude=longitude + margin,
            minimum_latitude=latitude  - margin,
            maximum_latitude=latitude  + margin,
            start_datetime=start_date.strftime("%Y-%m-%d"),
            end_datetime=end_date.strftime("%Y-%m-%d"),
            coordinates_selection_method="nearest",
        )

        # Sélectionner le point le plus proche
        point_data = dataset.sel(
            latitude=latitude,
            longitude=longitude,
            method="nearest"
        )

        # Surface (depth=0 ou premier niveau)
        def _extract_surface(var_name):
            da = point_data[var_name].isel(time=-1)
            # If depth dimension exists, take surface (index 0)
            if "depth" in da.dims:
                da = da.isel(depth=0)
            return float(da.values)

        u_current = _extract_surface("uo")   # m/s — composante Est
        v_current = _extract_surface("vo")   # m/s — composante Nord

        # Guard: NaN means point is on land or outside dataset coverage
        if math.isnan(u_current) or math.isnan(v_current):
            print("⚠️  u/v current is NaN — point may be on land or outside dataset coverage")
            return None

        # Vitesse scalaire (m/s → nœuds)
        speed_ms     = math.sqrt(u_current**2 + v_current**2)
        speed_knots  = speed_ms * 1.94384
        speed_kmh    = speed_ms * 3.6

        # Direction vers laquelle va le courant (océanographique)
        # 0° = Nord, 90° = Est, 180° = Sud, 270° = Ouest
        direction_deg = (math.atan2(u_current, v_current) * 180.0 / math.pi) % 360

        result = {
            "latitude":        latitude,
            "longitude":       longitude,
            "u_component":     round(u_current,  4),  # m/s (Est)
            "v_component":     round(v_current,  4),  # m/s (Nord)
            "speed_ms":        round(speed_ms,   3),
            "speed_knots":     round(speed_knots, 2),
            "speed_kmh":       round(speed_kmh,  2),
            "direction_deg":   round(direction_deg, 1),
        }

        # Timestamp
        try:
            ts = point_data.time.isel(time=-1).values
            if isinstance(ts, np.datetime64):
                result["timestamp"] = pd.Timestamp(ts).isoformat()
        except Exception:
            pass

        print(f"✅ Courant de surface : {result['speed_knots']} nœuds → {result['direction_deg']}°")
        return result

    except Exception as e:
        print(f"❌ Erreur récupération courants : {e}")
        import traceback
        traceback.print_exc()
        return None


def overCurrent(latitude, longitude, threshold_knots=2.0, username=None, password=None):
    """
    Retourne True si la vitesse du courant dépasse le seuil donné (défaut 2 nœuds).
    Utilisé pour marquer les points d'alerte sur la route.
    """
    data = get_current_data_at_position(latitude, longitude, username, password)
    if data is None:
        return False
    return data["speed_knots"] > threshold_knots
