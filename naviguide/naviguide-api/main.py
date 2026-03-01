import os
import re
import math
import json
import time
import asyncio
from typing import Optional, Union, List
from dotenv import load_dotenv
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import httpx
import searoute as sr
from geographiclib.geodesic import Geodesic
from copernicus.getWind import get_wind_data_at_position
from copernicus.getWave import get_wave_data_at_position
from copernicus.getCurrent import get_current_data_at_position
from utils.addWindProperties import add_wind_properties_to_route

try:
    from global_land_mask import globe as _globe
    _LAND_MASK_AVAILABLE = True
except ImportError:
    _globe = None
    _LAND_MASK_AVAILABLE = False

# ── High-resolution land mask (Natural Earth 1:10m + minor islands) ───────────
import pathlib, shapely.geometry, shapely.strtree

_NE_TREE: Optional[shapely.strtree.STRtree] = None

def _load_ne_land_tree() -> Optional[shapely.strtree.STRtree]:
    """
    Load Natural Earth 1:10m land + minor-islands shapefiles and build an
    STRtree for fast point-in-polygon queries.  Returns None on failure.
    """
    try:
        import shapefile as pyshp
        geo_dir = pathlib.Path(__file__).parent / "geo_data"
        polys: list = []
        for fname in ("ne_10m_land.shp", "ne_10m_minor_islands.shp"):
            shp = geo_dir / fname
            if not shp.exists():
                continue
            sf = pyshp.Reader(str(shp))
            for shape in sf.shapes():
                geo = shapely.geometry.shape(shape.__geo_interface__)
                if geo.geom_type == "Polygon":
                    if geo.is_valid and not geo.is_empty:
                        polys.append(geo)
                elif geo.geom_type == "MultiPolygon":
                    for sub in geo.geoms:
                        if sub.is_valid and not sub.is_empty:
                            polys.append(sub)
        if not polys:
            return None
        return shapely.strtree.STRtree(polys)
    except Exception:
        return None

_NE_TREE = _load_ne_land_tree()

def _is_on_land_ne(lat: float, lon: float) -> bool:
    """Return True if the point is on land according to the NE shapefile tree."""
    if _NE_TREE is None:
        return False
    pt = shapely.geometry.Point(lon, lat)
    candidates = _NE_TREE.query(pt)
    for idx in candidates:
        if _NE_TREE.geometries[idx].contains(pt):
            return True
    return False

def is_on_land(lat: float, lon: float) -> bool:
    """
    Multi-layer land check:
    1. Natural Earth 1:10m shapefiles (most accurate, handles islands)
    2. global_land_mask fallback
    """
    # Layer 1: Natural Earth high-resolution shapefile
    if _NE_TREE is not None:
        return _is_on_land_ne(lat, lon)
    # Layer 2: global_land_mask fallback
    if _LAND_MASK_AVAILABLE and _globe is not None:
        try:
            return bool(_globe.is_land(lat, lon))
        except Exception:
            pass
    return False

load_dotenv()

app = FastAPI()

# ── CORS ──────────────────────────────────────────────────────────────────────
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*")
if ALLOWED_ORIGINS == "*":
    origins = ["*"]
else:
    origins = [o.strip() for o in ALLOWED_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Copernicus credentials ────────────────────────────────────────────────────
COPERNICUS_USERNAME = os.getenv("COPERNICUS_USERNAME", "")
COPERNICUS_PASSWORD = os.getenv("COPERNICUS_PASSWORD", "")

# ── OpenAI / Anthropic / Mistral ─────────────────────────────────────────────
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MISTRAL_API_KEY   = os.getenv("MISTRAL_API_KEY", "")

# ── Models ────────────────────────────────────────────────────────────────────
class PositionRequest(BaseModel):
    latitude: float
    longitude: float

class RouteRequest(BaseModel):
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float

class IsLandRequest(BaseModel):
    latitude: float
    longitude: float

class RouteWindRequest(BaseModel):
    waypoints: list
    interval_nm: Optional[float] = 50.0

class AdviceRequest(BaseModel):
    latitude: float
    longitude: float
    destination_name: Optional[str] = None
    wind_speed_knots: Optional[float] = None
    wind_direction: Optional[float] = None
    wave_height_m: Optional[float] = None
    current_speed_knots: Optional[float] = None
    nm_remaining: Optional[float] = None

# ── Helpers ───────────────────────────────────────────────────────────────────

def haversine_nm(lat1, lon1, lat2, lon2):
    R = 3440.065
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def bearing(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1)*math.sin(phi2) - math.sin(phi1)*math.cos(phi2)*math.cos(dlambda)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "NaviGuide API is running"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/is-land")
def check_is_land(request: IsLandRequest):
    """Vérifie si une position est sur terre."""
    result = is_on_land(request.latitude, request.longitude)
    return {"latitude": request.latitude, "longitude": request.longitude, "is_land": result}

@app.post("/route")
def get_route(request: RouteRequest):
    """Calcule une route maritime entre deux points."""
    try:
        origin = [request.start_lon, request.start_lat]
        destination = [request.end_lon, request.end_lat]
        route = sr.searoute(origin, destination, units="naut")
        coords = route["geometry"]["coordinates"]
        waypoints = [{"latitude": lat, "longitude": lon} for lon, lat in coords]
        total_nm = route["properties"].get("length", 0)
        return {
            "waypoints": waypoints,
            "total_distance_nm": round(total_nm, 2),
            "num_waypoints": len(waypoints),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Copernicus simulation fallbacks ─────────────────────────────────────────
# Returned when Copernicus Marine API is unavailable (dev / offline mode).
# Values are deterministic per lat/lon so the same position always returns
# the same simulated reading within a session.
import hashlib as _hashlib
import math as _math
from datetime import datetime as _dt, timezone as _tz

def _mock_wind(lat: float, lon: float) -> dict:
    """Simulated wind data when Copernicus is unavailable."""
    seed = int(_hashlib.md5(f"{lat:.2f}|{lon:.2f}|w".encode()).hexdigest(), 16) % 10000
    speed_ms = 4.0 + (seed % 120) / 20.0          # 4–10 m/s
    direction = (seed * 37) % 360
    u = speed_ms * _math.sin(_math.radians(direction))
    v = speed_ms * _math.cos(_math.radians(direction))
    return {
        "latitude": lat, "longitude": lon,
        "u_component": round(u, 3), "v_component": round(v, 3),
        "wind_speed": round(speed_ms, 3),
        "wind_speed_kmh": round(speed_ms * 3.6, 2),
        "wind_speed_knots": round(speed_ms * 1.944, 2),
        "wind_direction": round(direction, 1),
        "timestamp": _dt.now(_tz.utc).isoformat(),
        "simulation": True, "source": "estimated (Copernicus unavailable)",
    }

def _mock_wave(lat: float, lon: float) -> dict:
    """Simulated wave data when Copernicus is unavailable."""
    seed = int(_hashlib.md5(f"{lat:.2f}|{lon:.2f}|s".encode()).hexdigest(), 16) % 10000
    height = 0.5 + (seed % 30) / 10.0             # 0.5–3.5 m
    period = 6.0 + (seed % 80) / 10.0             # 6–14 s
    direction = (seed * 53) % 360
    return {
        "latitude": lat, "longitude": lon,
        "significant_wave_height": round(height, 2),
        "mean_wave_period": round(period, 1),
        "wave_direction": round(direction, 1),
        "timestamp": _dt.now(_tz.utc).isoformat(),
        "simulation": True, "source": "estimated (Copernicus unavailable)",
    }

def _mock_current(lat: float, lon: float) -> dict:
    """Simulated current data when Copernicus is unavailable."""
    seed = int(_hashlib.md5(f"{lat:.2f}|{lon:.2f}|c".encode()).hexdigest(), 16) % 10000
    speed_ms = (seed % 80) / 100.0                # 0–0.80 m/s
    direction = (seed * 71) % 360
    u = speed_ms * _math.sin(_math.radians(direction))
    v = speed_ms * _math.cos(_math.radians(direction))
    return {
        "latitude": lat, "longitude": lon,
        "u_component": round(u, 4), "v_component": round(v, 4),
        "current_speed": round(speed_ms, 3),
        "current_speed_knots": round(speed_ms * 1.944, 2),
        "current_direction": round(direction, 1),
        "timestamp": _dt.now(_tz.utc).isoformat(),
        "simulation": True, "source": "estimated (Copernicus unavailable)",
    }


@app.post("/wind")
def get_wind(request: PositionRequest):
    """Récupère les données de vent via Copernicus Marine. Fallback simulation si indisponible."""
    try:
        if COPERNICUS_USERNAME and COPERNICUS_PASSWORD:
            wind_data = get_wind_data_at_position(
                latitude=request.latitude,
                longitude=request.longitude,
                username=COPERNICUS_USERNAME,
                password=COPERNICUS_PASSWORD,
            )
            if wind_data is not None:
                return wind_data
    except Exception:
        pass
    return _mock_wind(request.latitude, request.longitude)

@app.post("/wave")
def get_wave(request: PositionRequest):
    """Récupère les données de vague via Copernicus Marine. Fallback simulation si indisponible."""
    try:
        if COPERNICUS_USERNAME and COPERNICUS_PASSWORD:
            wave_data = get_wave_data_at_position(
                latitude=request.latitude,
                longitude=request.longitude,
                username=COPERNICUS_USERNAME,
                password=COPERNICUS_PASSWORD,
            )
            if wave_data is not None:
                return wave_data
    except Exception:
        pass
    return _mock_wave(request.latitude, request.longitude)

@app.post("/current")
def get_current(request: PositionRequest):
    """Récupère les données de courant marin via Copernicus Marine. Fallback simulation si indisponible."""
    try:
        if COPERNICUS_USERNAME and COPERNICUS_PASSWORD:
            current_data = get_current_data_at_position(
                latitude=request.latitude,
                longitude=request.longitude,
                username=COPERNICUS_USERNAME,
                password=COPERNICUS_PASSWORD,
            )
            if current_data is not None:
                return current_data
    except Exception:
        pass
    return _mock_current(request.latitude, request.longitude)

@app.post("/route-wind")
def get_route_wind(request: RouteWindRequest):
    """Récupère les données de vent pour chaque waypoint d'une route."""
    if not COPERNICUS_USERNAME or not COPERNICUS_PASSWORD:
        raise HTTPException(
            status_code=503,
            detail="Copernicus credentials not configured"
        )
    try:
        result = add_wind_properties_to_route(
            waypoints=request.waypoints,
            interval_nm=request.interval_nm,
            username=COPERNICUS_USERNAME,
            password=COPERNICUS_PASSWORD
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── AI Advice endpoint ────────────────────────────────────────────────────────

@app.post("/advice")
async def get_advice(req: AdviceRequest):
    """
    Streaming sailing advice from the best available AI model.
    Priority: Claude (Anthropic) → GPT-4o (OpenAI) → Mistral → fallback.
    """

    # ── Build the prompt ──────────────────────────────────────────────────────
    dest_str  = f" en route vers **{req.destination_name}**" if req.destination_name else ""
    wind_str  = (
        f"Vent : **{req.wind_speed_knots:.1f} nœuds** "
        f"(direction {req.wind_direction:.0f}°). "
        if req.wind_speed_knots is not None and req.wind_direction is not None else ""
    )
    wave_str  = (
        f"Vagues : **{req.wave_height_m:.1f} m**. "
        if req.wave_height_m is not None else ""
    )
    curr_str  = (
        f"Courant : **{req.current_speed_knots:.2f} nœuds**. "
        if req.current_speed_knots is not None else ""
    )
    dist_str  = (
        f"Distance restante : **{req.nm_remaining:.0f} nm**. "
        if req.nm_remaining is not None else ""
    )

    user_message = (
        f"Je suis un navigateur à la position "
        f"lat {req.latitude:.4f}, lon {req.longitude:.4f}{dest_str}.\n"
        f"{wind_str}{wave_str}{curr_str}{dist_str}\n\n"
        f"Donne-moi des conseils de navigation pratiques et concis pour ces conditions, "
        f"en tenant compte des risques météorologiques et des bonnes pratiques à bord."
    )

    system_prompt = (
        "Tu es un expert en navigation maritime côtière et hauturière. "
        "Tu fournis des conseils pratiques, clairs et sûrs aux navigateurs. "
        "Réponds toujours en français, de façon structurée et concise."
    )

    # ── Try Claude (Anthropic) ────────────────────────────────────────────────
    if ANTHROPIC_API_KEY:
        async def generator():
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    async with client.stream(
                        "POST",
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": ANTHROPIC_API_KEY,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json={
                            "model": "claude-opus-4-5",
                            "max_tokens": 1024,
                            "stream": True,
                            "system": system_prompt,
                            "messages": [{"role": "user", "content": user_message}],
                        },
                    ) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            raw = line[5:].strip()
                            if not raw or raw == "[DONE]":
                                continue
                            try:
                                evt = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            if evt.get("type") == "content_block_delta":
                                delta = evt.get("delta", {})
                                token = delta.get("text", "")
                                if token:
                                    yield f"data: {json.dumps({'token': token})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(generator(), media_type="text/event-stream")

    # ── Try GPT-4o (OpenAI) ───────────────────────────────────────────────────
    if OPENAI_API_KEY:
        async def generator():
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    async with client.stream(
                        "POST",
                        "https://api.openai.com/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {OPENAI_API_KEY}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "gpt-4o",
                            "stream": True,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user",   "content": user_message},
                            ],
                        },
                    ) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            raw = line[5:].strip()
                            if not raw or raw == "[DONE]":
                                continue
                            try:
                                chunk = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            token = (
                                chunk.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content", "")
                            )
                            if token:
                                yield f"data: {json.dumps({'token': token})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(generator(), media_type="text/event-stream")

    # ── Try Mistral ───────────────────────────────────────────────────────────
    if MISTRAL_API_KEY:
        async def generator():
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    async with client.stream(
                        "POST",
                        "https://api.mistral.ai/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {MISTRAL_API_KEY}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "mistral-large-latest",
                            "stream": True,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user",   "content": user_message},
                            ],
                        },
                    ) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            raw = line[5:].strip()
                            if not raw or raw == "[DONE]":
                                continue
                            try:
                                chunk = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            token = (
                                chunk.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content", "")
                            )
                            if token:
                                yield f"data: {json.dumps({'token': token})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(generator(), media_type="text/event-stream")

    # ── Static fallback ───────────────────────────────────────────────────────
    async def generator():
        fallback = (
            f"Aucune clé API disponible. Voici quelques conseils généraux :\n\n"
            f"- Surveillez régulièrement la météo et adaptez votre route.\n"
            f"- Maintenez une veille permanente (VHF canal 16).\n"
            f"- Consultez les ressources en ligne :\n"
            f"- 🌊 [Météo Consult Marine](https://marine.meteoconsult.fr)\n"
            f"- ⚓ [Noonsite](https://www.noonsite.com)\n"
            f"- 🌐 [Cruisers Forum](https://www.cruisersforum.com)\n\n"
            f"Distance remaining: **{req.nm_remaining:.0f} nm**."
        )
        yield f"data: {json.dumps({'token': fallback})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3007))
    uvicorn.run(app, host="0.0.0.0", port=port)
