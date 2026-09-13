"""Mode Climatologie — kind, terre=null, IBTrACS, P90 ≠ mean, catalogue."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "bi_test_climatology")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.export_meta import versioned_fc
from app.core.run_rules import load_catalog, rules_for_mode
from app.routers.climatology import router
from app.services import climatology_common as common
from app.services import climatology_current as current_mod
from app.services import climatology_cyclones as cyc
from app.services import climatology_wave as wave_mod
from app.services import climatology_wind as wind_mod
from app.services.climatology_common import (
    KIND,
    current_to_uv,
    is_land,
    wind_from_uv,
)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Contrats HTTP
# ---------------------------------------------------------------------------

def test_meta_kind_and_periods():
    data = _client().get("/api/climatology/meta", params={"month": 9}).json()
    assert data["kind"] == KIND
    assert data["month"] == 9
    assert data["review"] is False
    assert data["periods"]["wind"] == "1994-2020"
    assert data["periods"]["wave"] == "1993-2019"
    assert data["periods"]["current"] == "1993-2016"
    assert data["periods"]["cyclone"].startswith("1980")
    assert data["snapshot"]["cyclones"] is True
    assert data["snapshot"]["wind"] is False
    assert "Generated using E.U. Copernicus Marine Service Information" in data["attribution"]["cmems"]
    assert "IBTrACS" in data["attribution"]["ibtracs"]


def test_point_sea_without_cmems_snapshot_is_null_not_invented():
    data = _client().get("/api/climatology/point", params={
        "lat": 15.0, "lon": -25.0, "month": 3,
    }).json()
    assert data["kind"] == KIND
    assert data["coordinates"]["cell_selection"] == "sea"
    assert data["wind_atlas"] is None
    assert data["wave"] is None
    assert data["current"] is None
    assert data["cyclone"]["tracks_in_month"] >= 0


def test_point_land_blocks_null():
    data = _client().get("/api/climatology/point", params={
        "lat": 23.0, "lon": 5.0, "month": 3,
    }).json()
    assert data["coordinates"]["cell_selection"] == "land"
    assert data["wind_atlas"] is None
    assert data["wave"] is None
    assert data["current"] is None


def test_geojson_kind_and_empty_wind_without_snapshot():
    data = _client().get("/api/climatology/wind.geojson", params={"month": 3}).json()
    assert data["type"] == "FeatureCollection"
    assert data["features"] == []
    assert data["metadata"]["kind"] == KIND
    assert data["metadata"]["month"] == 3
    assert data["metadata"]["period"] == "1994-2020"
    assert data["metadata"]["source_ids"] == ["WIND_GLO_PHY_L4_MY_012_006"]
    assert data["metadata"]["snapshot_present"] is False
    assert "disclaimer_fr" in data["metadata"]


def test_cyclones_geojson_september_has_tracks():
    data = _client().get("/api/climatology/cyclones.geojson", params={"month": 9}).json()
    assert data["metadata"]["kind"] == KIND
    assert data["metadata"]["source_ids"] == ["IBTrACS_v04r01"]
    assert len(data["features"]) > 50
    assert all(f["properties"]["kind"] == KIND for f in data["features"][:5])


def test_crossings_martinique_azores():
    # Recette NAVIGUIDE n°4
    sept = _client().get("/api/climatology/crossings", params={
        "lat1": 14.6, "lon1": -61.0, "lat2": 38.7, "lon2": -27.2, "month": 9,
    }).json()
    mar = _client().get("/api/climatology/crossings", params={
        "lat1": 14.6, "lon1": -61.0, "lat2": 38.7, "lon2": -27.2, "month": 3,
    }).json()
    assert sept["kind"] == KIND
    assert sept["count"] > 0
    assert mar["count"] == 0
    assert isinstance(sept["storms"], list)


# ---------------------------------------------------------------------------
# Terre / conventions
# ---------------------------------------------------------------------------

def test_land_mask_recipe():
    assert is_land(23.0, 5.0) is True          # Sahara
    assert is_land(-33.0, -70.0) is True       # Andes
    assert is_land(15.0, -25.0) is False       # alizés Atlantique
    assert is_land(26.0, -80.0) is False       # Gulf Stream
    assert is_land(-40.0, 10.0) is False       # 40°S mer


def test_wind_from_uv_comes_from():
    # u ouest→est, v sud→nord : vent d'où ? atan2(-u,-v)
    kn, coming = wind_from_uv(5.0, 0.0)
    assert kn == pytest.approx(5.0 * 1.94384)
    assert coming == pytest.approx(270.0, abs=0.5)


def test_current_to_uv_goes_to():
    kn, going = current_to_uv(0.5, 0.5)
    assert kn > 0
    assert going == pytest.approx(45.0, abs=0.5)


# ---------------------------------------------------------------------------
# IBTrACS recette A
# ---------------------------------------------------------------------------

def test_ibtracs_basin_recipe():
    na_sep = [s for s in cyc.storms_for_month(9) if s.get("basin") == "NA"]
    na_feb = [s for s in cyc.storms_for_month(2) if s.get("basin") == "NA"]
    sp_jfm = []
    for m in (1, 2, 3):
        sp_jfm.extend(s for s in cyc.storms_for_month(m) if s.get("basin") == "SP")
    assert len(na_sep) > 20
    assert len(na_feb) == 0
    assert len(sp_jfm) > 10


# ---------------------------------------------------------------------------
# Snapshots CMEMS honnêtes + fixtures locales
# ---------------------------------------------------------------------------

def test_atlas_absent_returns_none():
    assert wind_mod.atlas_at(15.0, -25.0, 3) is None
    assert wind_mod.wind_at(15.0, -25.0, 3) is None
    assert wave_mod.wave_at(-40.0, 10.0, 7) is None
    assert wave_mod.is_wave_hazard(-40.0, 10.0, 7) is None
    assert current_mod.current_at(26.0, -80.0, 2) is None


def _write_grid(path: Path, **arrays):
    np.savez(path, **arrays)


def test_wind_atlas_ne_dominant(tmp_path, monkeypatch):
    wind_dir = tmp_path / "wind"
    wind_dir.mkdir()
    lats = np.array([14.5, 15.0, 15.5])
    lons = np.array([-25.5, -25.0, -24.5])
    # 8 secteurs : NE (index 1 = 45°) dominant
    pct = np.zeros((3, 3, 8), dtype=float)
    spd = np.zeros((3, 3, 8), dtype=float)
    pct[:, :, 1] = 55.0
    spd[:, :, 1] = 16.0
    pct[:, :, 2] = 20.0
    spd[:, :, 2] = 12.0
    _write_grid(
        wind_dir / "wind-03.npz",
        lats=lats, lons=lons,
        sector_pct=pct, sector_spd=spd,
        calm_pct=np.full((3, 3), 4.0),
        gale_pct=np.full((3, 3), 1.0),
        u_mean=np.full((3, 3), -2.0),
        v_mean=np.full((3, 3), -4.0),
        sample_count=np.full((3, 3), 1800, dtype=int),
        sea_mask=np.ones((3, 3), dtype=bool),
    )
    monkeypatch.setattr(wind_mod, "wind_dir", lambda: wind_dir)
    wind_mod._load_month.cache_clear()
    rose = wind_mod.atlas_at(15.0, -25.0, 3)
    assert rose is not None
    assert rose["most_likely"]["dir_deg"] == 45
    assert rose["most_likely"]["speed_knots"] == 16.0
    assert rose["vector_mean"]["speed_knots"] != rose["most_likely"]["speed_knots"]
    assert rose["sample_count"] == 1800
    ml = wind_mod.wind_at(15.0, -25.0, 3, mode="most_likely")
    avg = wind_mod.wind_at(15.0, -25.0, 3, mode="average")
    assert ml != avg


def test_wave_mean_is_not_labelled_p90(tmp_path, monkeypatch):
    wave_dir = tmp_path / "wave"
    wave_dir.mkdir()
    lats = np.array([-40.5, -40.0, -39.5])
    lons = np.array([9.5, 10.0, 10.5])
    _write_grid(
        wave_dir / "wave-07.npz",
        lats=lats, lons=lons,
        hs_mean=np.full((3, 3), 3.2),
        period=np.full((3, 3), 10.0),
        dir=np.full((3, 3), 240.0),
        sea_mask=np.ones((3, 3), dtype=bool),
        stat=np.array(["mean"]),
    )
    monkeypatch.setattr(wave_mod, "wave_dir", lambda: wave_dir)
    wave_mod._load_month.cache_clear()
    w = wave_mod.wave_at(-40.0, 10.0, 7)
    assert w["stat"] == "mean"
    assert w["hs_p90_m"] is None
    assert w["hs_p50_m"] is None
    assert w["hs_mean_m"] == 3.2
    assert wave_mod.is_wave_hazard(-40.0, 10.0, 7) is None
    fc = wave_mod.wave_geojson(7, stat="p90")
    assert fc["_climatology"]["snapshot_stat"] == "mean"
    assert fc["features"] == []


def test_wave_p90_gt_p50(tmp_path, monkeypatch):
    wave_dir = tmp_path / "wave"
    wave_dir.mkdir()
    lats = np.array([-40.5, -40.0, -39.5])
    lons = np.array([9.5, 10.0, 10.5])
    _write_grid(
        wave_dir / "wave-07.npz",
        lats=lats, lons=lons,
        hs_p50=np.full((3, 3), 2.1),
        hs_p90=np.full((3, 3), 4.4),
        period=np.full((3, 3), 11.0),
        dir=np.full((3, 3), 250.0),
        sea_mask=np.ones((3, 3), dtype=bool),
        stat=np.array(["p50_p90"]),
    )
    monkeypatch.setattr(wave_mod, "wave_dir", lambda: wave_dir)
    wave_mod._load_month.cache_clear()
    w = wave_mod.wave_at(-40.0, 10.0, 7)
    assert w["hs_p90_m"] > w["hs_p50_m"] > 0
    assert w["stat"] == "p50_p90"
    assert wave_mod.is_wave_hazard(-40.0, 10.0, 7) is True


def test_current_below_threshold_flagged(tmp_path, monkeypatch):
    cur_dir = tmp_path / "current"
    cur_dir.mkdir()
    lats = np.array([25.5, 26.0, 26.5])
    lons = np.array([-80.5, -80.0, -79.5])
    # ~0.05 m/s → < 0.15 kn
    _write_grid(
        cur_dir / "current-02.npz",
        lats=lats, lons=lons,
        uo=np.full((3, 3), 0.02),
        vo=np.full((3, 3), 0.02),
        sea_mask=np.ones((3, 3), dtype=bool),
    )
    monkeypatch.setattr(current_mod, "current_dir", lambda: cur_dir)
    current_mod._load_month.cache_clear()
    rec = current_mod.current_at(26.0, -80.0, 2)
    assert rec is not None
    assert rec["below_threshold"] is True
    assert rec["speed_knots"] == 0.0


def test_current_gulf_stream_fixture(tmp_path, monkeypatch):
    cur_dir = tmp_path / "current"
    cur_dir.mkdir()
    lats = np.array([25.5, 26.0, 26.5])
    lons = np.array([-80.5, -80.0, -79.5])
    # 0.8 m/s NE ≈ 1.55 kn
    _write_grid(
        cur_dir / "current-02.npz",
        lats=lats, lons=lons,
        uo=np.full((3, 3), 0.6),
        vo=np.full((3, 3), 0.6),
        sea_mask=np.ones((3, 3), dtype=bool),
    )
    monkeypatch.setattr(current_mod, "current_dir", lambda: cur_dir)
    current_mod._load_month.cache_clear()
    rec = current_mod.current_at(26.0, -80.0, 2)
    assert rec["speed_knots"] > 1.0
    assert 20 < rec["direction_to_deg"] < 70
    assert rec["below_threshold"] is False
    assert current_mod.current_at(23.0, 5.0, 2) is None  # Sahara


# ---------------------------------------------------------------------------
# Catalogue + metadata
# ---------------------------------------------------------------------------

def test_catalog_has_climatology_family():
    ids = {r["id"] for r in load_catalog()["rules"]}
    for rid in (
        "climatology.kind_is_climatology",
        "climatology.no_llm_for_numbers",
        "climatology.wind_calm_kn",
        "climatology.wind_gale_kn",
        "climatology.wind_sectors",
        "climatology.wind_min_sector_pct",
        "climatology.wind_grid_deg",
        "climatology.wave_nogo_m",
        "climatology.wave_stat",
        "climatology.wave_period",
        "climatology.current_min_kn",
        "climatology.current_depth_m",
        "climatology.current_period",
        "climatology.cyclone_first_year",
        "climatology.cyclone_dayrange",
        "climatology.cyclone_radius_nm",
        "climatology.cyclone_min_kn",
        "climatology.avoid_cyclone_tracks",
    ):
        assert rid in ids
    rules = rules_for_mode("climatology", include_shared=False)
    assert len(rules) == 18
    laws = {r["id"] for r in rules if r["kind"] == "loi"}
    assert "climatology.kind_is_climatology" in laws
    assert "climatology.no_llm_for_numbers" in laws
    assert "climatology.wave_stat" in laws


def test_versioned_fc_climatology_fields():
    out = versioned_fc(
        {"type": "FeatureCollection", "features": []},
        "climatology-wind",
        license_note="CMEMS",
        period="1994-2020",
        month=3,
        source_ids=["WIND_GLO_PHY_L4_MY_012_006"],
        doi="10.48670/moi-00183",
        extra_metadata={"kind": KIND, "stat": "most_likely"},
    )
    meta = out["metadata"]
    assert meta["period"] == "1994-2020"
    assert meta["month"] == 3
    assert meta["source_ids"] == ["WIND_GLO_PHY_L4_MY_012_006"]
    assert meta["doi"] == "10.48670/moi-00183"
    assert meta["kind"] == KIND
    assert meta["disclaimer_fr"].startswith("Ne convient pas")


def test_bad_month_400():
    r = _client().get("/api/climatology/point", params={"lat": 0, "lon": 0, "month": 13})
    assert r.status_code == 422


def test_naviguide_query_not_painted():
    ng_api = Path(__file__).resolve().parents[2] / "naviguide" / "naviguide-api"
    sys.path.insert(0, str(ng_api))
    import climatology_query as nq
    meta = nq.meta(9)
    assert meta["kind"] == KIND
    assert meta["painted"] is False
    pt = nq.point(14.6, -61.0, 9, dest_lat=38.7, dest_lon=-27.2)
    assert pt["painted"] is False
    assert pt["cyclone"]["crossings_if_leg"]["count"] > 0
    mar = nq.crossings(14.6, -61.0, 38.7, -27.2, 3)
    assert mar["count"] == 0


def test_meteo_agent_cites_ibtracs_integer():
    ng_api = Path(__file__).resolve().parents[2] / "naviguide" / "naviguide-api"
    sys.path.insert(0, str(ng_api))
    from agents.meteo_agent import fetch_ibtracs_node, get_streaming_prompt

    state = fetch_ibtracs_node({
        "from_stop": "Fort-de-France",
        "to_stop": "Horta",
        "lat": 14.6,
        "lon": -61.0,
        "dest_lat": 38.7,
        "dest_lon": -27.2,
        "month": 9,
        "nm_remaining": 2500,
        "language": "fr",
        "messages": [],
    })
    count = state["ibtracs"]["count"]
    assert isinstance(count, int) and count > 0
    prompt = get_streaming_prompt(
        from_stop="Fort-de-France",
        to_stop="Horta",
        lat=14.6,
        lon=-61.0,
        nm_remaining=2500,
        language="fr",
        dest_lat=38.7,
        dest_lon=-27.2,
        month=9,
    )
    assert "IBTrACS" in prompt
    assert str(count) in prompt
    assert "hurricane season" in prompt.lower() or "Cite this integer" in prompt
