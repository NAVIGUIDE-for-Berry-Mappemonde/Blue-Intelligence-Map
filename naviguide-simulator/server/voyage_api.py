"""API voyage — bateau virtuel (Simulation B), port 8010."""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from forecast_blend import FORECAST_BLEND_END_HOURS, make_wind_fn
from forecast_cube import (
    CACHE_TTL_H,
    CUBE_MAX_BYTES,
    build_voyage_cube,
    load_cube,
    save_cube,
)
from isochrone import haversine, run_leg_isochrone
from grib_fetch import maybe_refresh_official
from saildocs import (
    DAILY_RADIUS_NM,
    GRIB_MISSING,
    GRIB_PRODUCTS,
    absent_payload,
    dest_eta_at_next_download,
    ingest_daily,
    last_ready_cycle,
    load_latest,
    public_grib,
    saildocs_queries,
    saildocs_query,
    scan_inbox,
    track_from_clock,
    utc_day,
    wind_at_daily,
)
from voyage_clock import (
    OFFICIAL_T0,
    OFFICIAL_VOYAGE_ID,
    build_voyage_clock,
    parse_iso,
    sample_clock_at_time,
    to_iso,
)
from voyage_store import load_voyage, save_voyage, update_voyage

log = logging.getLogger("naviguide-simulator.voyage")
router = APIRouter()

try:
    from polar_api import _load_polar_data
except Exception:  # pragma: no cover
    _load_polar_data = None


class VoyageCreate(BaseModel):
    t0: str
    expedition_id: str = "berry-mappemonde-2026"
    routeKind: str = "berry"
    follow: bool = True
    forecast: bool = True
    startAt: str = "la-rochelle"
    official: bool = False
    points: List[Dict[str, Any]]
    marks: List[Dict[str, Any]] = Field(default_factory=list)


class RecomputeBody(BaseModel):
    to_name: Optional[str] = None
    t: Optional[str] = None


class DailyGribIn(BaseModel):
    model: str = "GFS"
    source: str = "saildocs"
    day: Optional[str] = None
    issued: Optional[str] = None
    around: Optional[Dict[str, Any]] = None
    bbox: Optional[List[float]] = None
    radiusNm: float = DAILY_RADIUS_NM
    samples: List[Dict[str, Any]] = Field(default_factory=list)
    query: Optional[str] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _polar_raw(expedition_id: str) -> Optional[dict]:
    if not _load_polar_data:
        return None
    try:
        polar = _load_polar_data(expedition_id)
        return {
            "twa_rows": list(polar.twa_rows),
            "tws_cols": list(polar.tws_cols),
            "matrix": polar.matrix.tolist(),
        }
    except Exception:
        return None


def _climo_clock(voy: dict) -> dict:
    return build_voyage_clock(
        voy.get("points") or [],
        voy.get("marks") or [],
        voy["t0"],
        polar_raw=_polar_raw(voy.get("expedition_id") or ""),
        start_at=voy.get("startAt") or "la-rochelle",
        wind_fn=None,
    )


def _clock_with_cube(voy: dict, cube) -> dict:
    t0 = parse_iso(voy["t0"])
    return build_voyage_clock(
        voy.get("points") or [],
        voy.get("marks") or [],
        t0,
        polar_raw=_polar_raw(voy.get("expedition_id") or ""),
        start_at=voy.get("startAt") or "la-rochelle",
        wind_fn=make_wind_fn(t0, cube),
    )


def _fill_forecast(voyage_id: str) -> None:
    voy = load_voyage(voyage_id)
    if voy is None:
        return
    try:
        t0 = parse_iso(voy["t0"])
        live_nm = 0.0
        clock = voy.get("clock")
        if clock:
            sample = sample_clock_at_time(clock, _now())
            if sample:
                live_nm = float(sample.get("sailNm") or 0)
        cube = build_voyage_cube(voy.get("points") or [], t0, from_sail_nm=live_nm)
        if cube.estimate_bytes() > CUBE_MAX_BYTES:
            log.warning("cube trop gros (%s o), on réduit", cube.estimate_bytes())
            cube.samples = cube.samples[: max(4, len(cube.samples) // 2)]
        save_cube(voyage_id, cube)
        clock = _clock_with_cube(voy, cube)
        update_voyage(
            voyage_id,
            forecastStatus="ready",
            forecastModel=cube.model,
            waveModel=cube.wave_model,
            cubeBytes=cube.estimate_bytes(),
            forecastRefreshedAt=to_iso(_now()),
            clock=clock,
        )
    except Exception as exc:
        log.warning("prévision indisponible pour %s: %s", voyage_id, exc)
        voy = load_voyage(voyage_id) or voy
        update_voyage(
            voyage_id,
            forecastStatus="unavailable",
            forecastModel=None,
            clock=voy.get("clock") or _climo_clock(voy),
        )


def _is_official(voyage_id: str) -> bool:
    return voyage_id == OFFICIAL_VOYAGE_ID


def _public_meta(voy: dict) -> dict:
    official = voy.get("official") or _is_official(voy.get("voyageId") or "")
    return {
        "voyageId": voy["voyageId"],
        "t0": voy["t0"],
        "expedition_id": voy.get("expedition_id"),
        "routeKind": voy.get("routeKind"),
        "routeRev": voy.get("routeRev", 0),
        "follow": voy.get("follow", True),
        "official": official,
        "forecastStatus": voy.get("forecastStatus"),
        "forecastModel": voy.get("forecastModel"),
        "waveModel": voy.get("waveModel"),
        "startAt": voy.get("startAt"),
        "cubeBytes": voy.get("cubeBytes"),
        "forecastRefreshedAt": voy.get("forecastRefreshedAt"),
        "disclaimer": {
            "notForNav": "Ne convient pas à la navigation.",
        },
    }


def _flag_marks(marks: List[dict]) -> List[dict]:
    out = []
    for m in marks or []:
        name = str(m.get("name") or "")
        if m.get("flag") is False:
            continue
        out.append(m)
    return out


def _next_flag(marks: List[dict], sail_nm: float, to_name: Optional[str] = None) -> Optional[dict]:
    ordered = sorted(marks or [], key=lambda m: float(m.get("nm") or m.get("filmNm") or 0))
    if to_name:
        for m in ordered:
            if to_name.lower() in str(m.get("name") or "").lower():
                return m
    for m in ordered:
        nm = float(m.get("nm") or m.get("filmNm") or 0)
        if nm > sail_nm + 1:
            return m
    return ordered[-1] if ordered else None


def _leg_coords(points: List[dict], from_nm: float, to_nm: float) -> List[tuple]:
    coords = []
    for p in points or []:
        nm = float(p.get("cumNm") or 0)
        if from_nm - 0.5 <= nm <= to_nm + 0.5 and not p.get("jump"):
            coords.append((p["lat"], p["lon"]))
    return coords


def _recompute_cum(points: List[dict]) -> List[dict]:
    out = []
    cum = 0.0
    film = 0.0
    prev = None
    for p in points:
        q = dict(p)
        if prev is not None:
            if q.get("jump"):
                film += 80.0
            else:
                d = haversine(prev["lat"], prev["lon"], q["lat"], q["lon"])
                cum += d
                film += d
        q["cumNm"] = round(cum, 4)
        q["filmCum"] = round(film, 4)
        out.append(q)
        prev = q
    return out


def _splice_points(points: List[dict], from_nm: float, to_nm: float,
                   new_coords: List[List[float]]) -> List[dict]:
    """new_coords = [lon, lat]. Amont inchangé, jambe remplacée, aval intact."""
    before = [p for p in points if float(p.get("cumNm") or 0) < from_nm - 0.05]
    after = [p for p in points if float(p.get("cumNm") or 0) > to_nm + 0.05]
    mid = []
    for lon, lat in new_coords:
        mid.append({"lat": lat, "lon": lon, "jump": False, "nonMaritime": False})
    return _recompute_cum(before + mid + after)


@router.post("/voyage")
def create_voyage(body: VoyageCreate, background: BackgroundTasks):
    if not body.points:
        raise HTTPException(400, "points requis")
    try:
        parse_iso(body.t0)
    except Exception as exc:
        raise HTTPException(400, f"t0 invalide: {exc}") from exc
    voyage_id = str(uuid.uuid4())
    voy = {
        "voyageId": voyage_id,
        "t0": to_iso(parse_iso(body.t0)),
        "expedition_id": body.expedition_id,
        "routeKind": body.routeKind,
        "routeRev": 0,
        "follow": body.follow,
        "forecast": body.forecast,
        "forecastStatus": "pending" if body.forecast else "unavailable",
        "forecastModel": None,
        "startAt": body.startAt,
        "points": body.points,
        "marks": body.marks,
        "draft": None,
        "createdAt": to_iso(_now()),
    }
    voy["clock"] = _climo_clock(voy)
    save_voyage(voy)
    if body.forecast:
        background.add_task(_fill_forecast, voyage_id)
    return {**_public_meta(voy), "clock": voy["clock"]}


def _build_official(body: VoyageCreate) -> dict:
    voy = {
        "voyageId": OFFICIAL_VOYAGE_ID,
        "t0": OFFICIAL_T0,
        "expedition_id": body.expedition_id or "berry-mappemonde-2026",
        "routeKind": "berry",
        "routeRev": 0,
        "follow": True,
        "forecast": False,
        "official": True,
        "forecastStatus": "unavailable",
        "forecastModel": None,
        "startAt": "la-rochelle",
        "points": body.points,
        "marks": body.marks,
        "draft": None,
        "createdAt": to_iso(_now()),
    }
    voy["clock"] = _climo_clock(voy)
    save_voyage(voy)
    return voy


def _kick_official_grib() -> None:
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    if not voy:
        return
    around = _grib_around_from_live(voy, _now())
    maybe_refresh_official(OFFICIAL_VOYAGE_ID, around, _now(), force=True)


@router.put("/voyage/official")
def ensure_official(body: VoyageCreate, background: BackgroundTasks):
    if not body.points:
        raise HTTPException(400, "points requis")
    existing = load_voyage(OFFICIAL_VOYAGE_ID)
    if existing and existing.get("points"):
        changed = False
        if (
            len(body.points) > len(existing["points"])
            and int(existing.get("routeRev") or 0) == 0
        ):
            existing["points"] = body.points
            existing["marks"] = body.marks
            existing["t0"] = OFFICIAL_T0
            existing["official"] = True
            changed = True
        if body.expedition_id and body.expedition_id != existing.get("expedition_id"):
            existing["expedition_id"] = body.expedition_id
            changed = True
        if changed:
            existing["clock"] = _climo_clock(existing)
            save_voyage(existing)
        background.add_task(_kick_official_grib)
        return {**_public_meta(existing), "clock": existing.get("clock") or _climo_clock(existing)}
    voy = _build_official(body)
    background.add_task(_kick_official_grib)
    return {**_public_meta(voy), "clock": voy["clock"]}


@router.get("/voyage/official")
def get_official():
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    if voy is None:
        raise HTTPException(404, "voyage officiel absent")
    return {
        **_public_meta(voy),
        "points": voy.get("points"),
        "marks": voy.get("marks"),
    }


@router.get("/voyage/official/clock")
def get_official_clock():
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    if voy is None:
        raise HTTPException(404, "voyage officiel absent")
    return voy.get("clock") or _climo_clock(voy)


def _grib_around_from_live(voy: Optional[dict], when: datetime) -> Optional[dict]:
    """Couloir horloge : ici → position à l’ETA du prochain téléchargement."""
    if not voy:
        return None
    clock = voy.get("clock") or _climo_clock(voy)
    around = track_from_clock(clock, when)
    if around:
        return around
    sample = sample_clock_at_time(clock, when)
    if not sample:
        return None
    return {"lat": sample.get("lat"), "lon": sample.get("lon")}


def _saildocs_query_from_around(around: dict) -> str:
    return saildocs_query(
        float(around["lat"]),
        float(around["lon"]),
        dest=around.get("dest"),
        waypoints=around.get("waypoints"),
    )


def _saildocs_queries_from_around(around: dict) -> list:
    return saildocs_queries(
        float(around["lat"]),
        float(around["lon"]),
        dest=around.get("dest"),
        waypoints=around.get("waypoints"),
    )


def _latest_official_grib(around: Optional[dict], when) -> Optional[dict]:
    record = load_latest(OFFICIAL_VOYAGE_ID, utc_day(when))
    refreshed = maybe_refresh_official(OFFICIAL_VOYAGE_ID, around, when)
    return refreshed if refreshed is not None else record


@router.get("/voyage/official/at")
def official_at(t: Optional[str] = Query(None)):
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    if voy is None:
        raise HTTPException(404, "voyage officiel absent")
    clock = voy.get("clock") or _climo_clock(voy)
    when = parse_iso(t) if t else _now()
    sample = sample_clock_at_time(clock, when)
    if sample is None:
        raise HTTPException(404, "horloge vide")
    sample["voyageId"] = OFFICIAL_VOYAGE_ID
    sample["t"] = to_iso(when)
    around = _grib_around_from_live(voy, when)
    grib = _latest_official_grib(around, when)
    wind = wind_at_daily(grib, float(sample.get("lat") or 0), float(sample.get("lon") or 0), when)
    if wind:
        sample["kind"] = "forecast"
        sample["model"] = wind.get("model")
        sample["waveModel"] = wind.get("waveModel")
        sample["currentModel"] = wind.get("currentModel")
        sample["windKnots"] = wind.get("windKnots")
        sample["dirFromDeg"] = wind.get("dirFromDeg")
        sample["pressHpa"] = wind.get("pressHpa")
        sample["rainMm"] = wind.get("rainMm")
        sample["hs"] = wind.get("hs")
        sample["gribStatus"] = "ready"
        sample["gribWarning"] = None
    else:
        sample["kind"] = "absent"
        sample["model"] = None
        sample["leadHours"] = None
        sample["windKnots"] = None
        sample["dirFromDeg"] = None
        sample["gribStatus"] = "absent"
        sample["gribWarning"] = GRIB_MISSING
    return sample


@router.get("/voyage/official/grib")
def get_official_grib(
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    t: Optional[str] = Query(None),
):
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    when = parse_iso(t) if t else _now()
    around = _grib_around_from_live(voy, when) if voy else None
    if around is None and lat is not None and lon is not None:
        around = {"lat": lat, "lon": lon}
    record = load_latest(OFFICIAL_VOYAGE_ID, utc_day(when))
    if record is None and around:
        record = scan_inbox(OFFICIAL_VOYAGE_ID, utc_day(when), around)
    if around:
        record = maybe_refresh_official(OFFICIAL_VOYAGE_ID, around, when) or record
    body = public_grib(record, OFFICIAL_VOYAGE_ID, around, when)
    if lat is not None and lon is not None and record:
        body["wind"] = wind_at_daily(record, lat, lon, when)
    return body


@router.post("/voyage/official/grib")
def post_official_grib(body: DailyGribIn):
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    around = body.around
    if around is None and voy:
        around = _grib_around_from_live(voy, _now())
    try:
        record = ingest_daily(OFFICIAL_VOYAGE_ID, body.model_dump(), around=around)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return public_grib(record, OFFICIAL_VOYAGE_ID, around or body.around, _now())


@router.post("/voyage/official/grib/refresh")
def refresh_official_grib():
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    around = _grib_around_from_live(voy, _now()) if voy else None
    record = maybe_refresh_official(OFFICIAL_VOYAGE_ID, around, _now(), force=True)
    if record is None and around:
        record = scan_inbox(OFFICIAL_VOYAGE_ID, utc_day(), around)
    return public_grib(record, OFFICIAL_VOYAGE_ID, around, _now())


@router.post("/voyage/official/grib/scan")
def scan_official_grib():
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    around = _grib_around_from_live(voy, _now()) if voy else None
    record = scan_inbox(OFFICIAL_VOYAGE_ID, utc_day(), around)
    if record is None:
        return absent_payload(OFFICIAL_VOYAGE_ID, utc_day(), around)
    return public_grib(record, OFFICIAL_VOYAGE_ID, around, _now())


@router.get("/voyage/official/saildocs-query")
def official_saildocs_query(
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
):
    voy = load_voyage(OFFICIAL_VOYAGE_ID)
    around = _grib_around_from_live(voy, _now()) if voy else None
    if around is None and lat is not None and lon is not None:
        around = {"lat": lat, "lon": lon}
    if not around:
        raise HTTPException(400, "position bateau inconnue")
    queries = _saildocs_queries_from_around(around)
    return {
        "query": queries[0]["query"],
        "queries": queries,
        "around": around,
        "radiusNm": DAILY_RADIUS_NM,
        "model": "GFS",
        "models": [p["model"] for p in GRIB_PRODUCTS],
        "nextDownloadAt": around.get("nextDownloadAt") or to_iso(dest_eta_at_next_download()),
        "horizonHours": around.get("horizonHours"),
        "cycle": around.get("cycle") or to_iso(last_ready_cycle()),
    }


@router.get("/voyage/{voyage_id}")
def get_voyage(voyage_id: str):
    voy = load_voyage(voyage_id)
    if voy is None:
        raise HTTPException(404, "voyage inconnu")
    return {
        **_public_meta(voy),
        "points": voy.get("points"),
        "marks": voy.get("marks"),
    }


@router.get("/voyage/{voyage_id}/clock")
def get_clock(voyage_id: str):
    voy = load_voyage(voyage_id)
    if voy is None:
        raise HTTPException(404, "voyage inconnu")
    return voy.get("clock") or _climo_clock(voy)


@router.get("/voyage/{voyage_id}/at")
def get_at(voyage_id: str, t: Optional[str] = Query(None)):
    voy = load_voyage(voyage_id)
    if voy is None:
        raise HTTPException(404, "voyage inconnu")
    clock = voy.get("clock") or _climo_clock(voy)
    when = parse_iso(t) if t else _now()
    sample = sample_clock_at_time(clock, when)
    if sample is None:
        raise HTTPException(404, "horloge vide")
    t0 = parse_iso(voy["t0"])
    hours = (when - t0).total_seconds() / 3600.0
    if hours > FORECAST_BLEND_END_HOURS and sample.get("kind") == "forecast":
        sample["kind"] = "climatology"
        sample["leadHours"] = None
        sample["model"] = None
    sample["voyageId"] = voyage_id
    sample["forecastStatus"] = voy.get("forecastStatus")
    sample["forecastModel"] = voy.get("forecastModel")
    sample["t"] = to_iso(when)
    if sample.get("kind") == "forecast":
        # Lead time = hours since t0 (not the wind at the start of the edge).
        sample["leadHours"] = round(max(0.0, hours), 1)
        if not sample.get("model"):
            sample["model"] = voy.get("forecastModel")
    return sample


@router.post("/voyage/{voyage_id}/refresh-forecast")
def refresh_forecast(voyage_id: str, background: BackgroundTasks):
    voy = load_voyage(voyage_id)
    if voy is None:
        raise HTTPException(404, "voyage inconnu")
    update_voyage(voyage_id, forecastStatus="pending")
    background.add_task(_fill_forecast, voyage_id)
    return _public_meta(load_voyage(voyage_id) or voy)


def _maybe_auto_refresh(voy: dict) -> None:
    refreshed = voy.get("forecastRefreshedAt")
    if not refreshed or voy.get("forecastStatus") != "ready":
        return
    age = (_now() - parse_iso(refreshed)).total_seconds() / 3600.0
    if age >= CACHE_TTL_H and voy.get("follow"):
        threading.Thread(target=_fill_forecast, args=(voy["voyageId"],), daemon=True).start()


@router.post("/voyage/{voyage_id}/recompute")
def recompute(voyage_id: str, body: Optional[RecomputeBody] = None):
    body = body or RecomputeBody()
    if _is_official(voyage_id):
        raise HTTPException(403, "recalcul interdit sur le voyage officiel")
    voy = load_voyage(voyage_id)
    if voy is None:
        raise HTTPException(404, "voyage inconnu")
    _maybe_auto_refresh(voy)
    clock = voy.get("clock") or _climo_clock(voy)
    when = parse_iso(body.t) if body.t else _now()
    live = sample_clock_at_time(clock, when)
    if live is None:
        raise HTTPException(400, "pas de position live")
    if live.get("vehicle") in ("plane", "side"):
        raise HTTPException(409, "recalcul désactivé en phase air / relais")
    dest = _next_flag(voy.get("marks") or [], float(live.get("sailNm") or 0),
                      body.to_name)
    if dest is None:
        raise HTTPException(400, "aucune escale à drapeau devant")
    cube = load_cube(voyage_id)
    t0 = parse_iso(voy["t0"])
    wind_fn = make_wind_fn(t0, cube)
    from_nm = float(live.get("sailNm") or 0)
    to_nm = float(dest.get("nm") or dest.get("filmNm") or 0)
    searoute = _leg_coords(voy.get("points") or [], from_nm, to_nm)
    versus_hours = None
    for m in clock.get("marks") or []:
        if m.get("name") == dest.get("name"):
            versus_hours = max(0.0, float(m["tHours"]) - float(live.get("tHours") or 0))
            break
    versus_nm = max(0.0, to_nm - from_nm)

    if dest.get("lat") is not None and dest.get("lon") is not None:
        dst_lat, dst_lon = float(dest["lat"]), float(dest["lon"])
    elif searoute:
        dst_lat, dst_lon = searoute[-1]
    else:
        dst_lat, dst_lon = float(live["lat"]), float(live["lon"])

    result = run_leg_isochrone(
        dep_lat=float(live["lat"]),
        dep_lon=float(live["lon"]),
        dst_lat=dst_lat,
        dst_lon=dst_lon,
        departure_time=when if live.get("status") != "waiting" else t0,
        wind_fn=wind_fn,
        polar_raw=_polar_raw(voy.get("expedition_id") or ""),
        searoute_coords=searoute,
    )
    old_coords = [[lon, lat] for lat, lon in searoute]
    draft = {
        **result,
        "versus_searoute": {
            "hours": round(versus_hours, 2) if versus_hours is not None else None,
            "distance_nm": round(versus_nm, 2),
        },
        "old_geojson": {
            "type": "Feature",
            "properties": {"role": "searoute-leg"},
            "geometry": {"type": "LineString", "coordinates": old_coords},
        },
        "from_sail_nm": from_nm,
        "to_sail_nm": to_nm,
        "to_name": dest.get("name"),
        "from_lat": live["lat"],
        "from_lon": live["lon"],
    }
    update_voyage(voyage_id, draft=draft)
    return draft


@router.get("/voyage/{voyage_id}/draft")
def get_draft(voyage_id: str):
    voy = load_voyage(voyage_id)
    if voy is None:
        raise HTTPException(404, "voyage inconnu")
    if not voy.get("draft"):
        raise HTTPException(404, "pas de brouillon")
    return voy["draft"]


@router.post("/voyage/{voyage_id}/accept")
def accept_draft(voyage_id: str):
    voy = load_voyage(voyage_id)
    if voy is None:
        raise HTTPException(404, "voyage inconnu")
    draft = voy.get("draft")
    if not draft:
        raise HTTPException(404, "pas de brouillon")
    coords = (draft.get("draft_geojson") or {}).get("geometry", {}).get("coordinates") or []
    if len(coords) < 2:
        raise HTTPException(400, "brouillon sans géométrie")
    new_points = _splice_points(
        voy.get("points") or [],
        float(draft["from_sail_nm"]),
        float(draft["to_sail_nm"]),
        coords,
    )
    voy["points"] = new_points
    voy["routeRev"] = int(voy.get("routeRev") or 0) + 1
    cube = load_cube(voyage_id)
    voy["clock"] = _clock_with_cube(voy, cube) if cube else _climo_clock(voy)
    voy["draft"] = None
    voy["acceptedAlt"] = draft.get("old_geojson")
    save_voyage(voy)
    return {**_public_meta(voy), "clock": voy["clock"], "points": voy["points"]}


@router.post("/voyage/{voyage_id}/reject")
def reject_draft(voyage_id: str):
    voy = load_voyage(voyage_id)
    if voy is None:
        raise HTTPException(404, "voyage inconnu")
    update_voyage(voyage_id, draft=None)
    return {"ok": True, "voyageId": voyage_id}

