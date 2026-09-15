import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import forecast_cube
import saildocs
import voyage_store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_FORECAST_BACKEND", "synthetic")
    monkeypatch.setenv("NAVIGUIDE_VOYAGE_DIR", str(tmp_path / "voyages"))
    monkeypatch.setenv("NAVIGUIDE_FORECAST_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("NAVIGUIDE_GRIB_DIR", str(tmp_path / "grib"))
    monkeypatch.setenv("NAVIGUIDE_SAILDOCS_INBOX", str(tmp_path / "inbox"))
    monkeypatch.setenv("NAVIGUIDE_GRIB_AUTO", "0")
    voyage_store._DIR = tmp_path / "voyages"
    forecast_cube.CACHE_DIR = tmp_path / "cache"
    saildocs.GRIB_DIR = tmp_path / "grib"
    saildocs.INBOX_DIR = tmp_path / "inbox"
    from main import app
    return TestClient(app)


def _payload():
    return {
        "t0": "2026-06-01T08:00:00Z",
        "expedition_id": "berry-mappemonde-2026",
        "routeKind": "berry",
        "follow": True,
        "forecast": True,
        "startAt": "la-rochelle",
        "points": [
            {"lat": 46.15, "lon": -1.16, "cumNm": 0, "filmCum": 0, "jump": False, "nonMaritime": False},
            {"lat": 40.0, "lon": -15.0, "cumNm": 650, "filmCum": 650, "jump": False, "nonMaritime": False},
            {"lat": 14.6, "lon": -61.07, "cumNm": 3350, "filmCum": 3350, "jump": False, "nonMaritime": False},
        ],
        "marks": [
            {"name": "La Rochelle", "nm": 0, "filmNm": 0, "lat": 46.15, "lon": -1.16, "index": 0},
            {"name": "Fort-de-France (Martinique)", "nm": 3350, "filmNm": 3350, "lat": 14.6, "lon": -61.07, "index": 2},
        ],
    }


def test_official_unique_t0_and_no_recompute(client):
    r1 = client.put("/voyage/official", json=_payload())
    assert r1.status_code == 200
    body = r1.json()
    assert body["voyageId"] == "berry-mappemonde-2026-officiel"
    assert body["t0"].startswith("2026-05-15")
    assert body["official"] is True
    r2 = client.put("/voyage/official", json=_payload())
    assert r2.json()["voyageId"] == body["voyageId"]
    rec = client.post("/voyage/berry-mappemonde-2026-officiel/recompute")
    assert rec.status_code == 403


def test_official_put_updates_when_polar_arrives(client):
    first = _payload()
    first["expedition_id"] = "tmp-no-polar"
    client.put("/voyage/official", json=first)
    again = _payload()
    again["expedition_id"] = "berry-mappemonde-2026"
    again["points"] = again["points"] + [{
        "lat": -13.28, "lon": -176.17, "cumNm": 10200, "filmCum": 10200,
        "jump": False, "nonMaritime": False,
    }]
    r = client.put("/voyage/official", json=again)
    assert r.status_code == 200
    got = client.get("/voyage/official").json()
    assert len(got["points"]) == 4
    assert got.get("expedition_id") == "berry-mappemonde-2026"


def test_official_september_has_moved(client):
    client.put("/voyage/official", json=_payload())
    sample = client.get("/voyage/official/at", params={"t": "2026-09-15T12:00:00Z"}).json()
    assert sample["status"] in ("live", "arrived")
    assert float(sample.get("tHours") or 0) > 24


def test_grib_refresh_endpoint(client):
    client.put("/voyage/official", json=_payload())
    r = client.post("/voyage/official/grib/refresh")
    assert r.status_code == 200
    assert r.json()["status"] in ("absent", "ready")


def test_grib_absent_keeps_dest_corridor(client):
    client.put("/voyage/official", json=_payload())
    grib = client.get("/voyage/official/grib").json()
    dest = (grib.get("around") or {}).get("dest") or grib.get("dest")
    assert dest is not None
    assert dest.get("lat") is not None
    assert dest.get("lon") is not None
    south, north, west, east = saildocs.bbox_from_around(grib["around"])
    assert south <= dest["lat"] <= north
    assert west <= dest["lon"] <= east


def test_official_at_now_and_grib_absent(client):
    client.put("/voyage/official", json=_payload())
    sample = client.get("/voyage/official/at").json()
    assert sample["voyageId"] == "berry-mappemonde-2026-officiel"
    assert sample["status"] in ("live", "waiting", "arrived")
    grib = client.get("/voyage/official/grib", params={"lat": 46.15, "lon": -1.16}).json()
    assert grib["status"] == "absent"
    assert grib["warning"] == "dernière prévision absente"
    sample = client.get("/voyage/official/at").json()
    assert sample["kind"] != "climatology"
    assert sample["kind"] == "absent"
    assert sample["windKnots"] is None


def test_daily_grib_around_boat(client):
    client.put("/voyage/official", json=_payload())
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    r = client.post("/voyage/official/grib", json={
        "model": "GFS",
        "day": day,
        "around": {"lat": 46.15, "lon": -1.16},
        "samples": [{
            "lat": 46.15,
            "lon": -1.16,
            "t": f"{day}T08:00:00Z",
            "windKnots": 12,
            "dirFromDeg": 240,
        }],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["model"] == "GFS"
    assert body["samples"][0]["windKnots"] == 12
    south, north, _west, _east = body["bbox"]
    assert north - south < 12
    bad = client.post("/voyage/official/grib", json={
        "model": "GFS",
        "bbox": [-80, 80, -180, 180],
        "samples": [],
    })
    assert bad.status_code == 400


def test_scan_inbox_json(client, tmp_path, monkeypatch):
    import saildocs
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr(saildocs, "INBOX_DIR", inbox)
    monkeypatch.setattr(saildocs, "GRIB_DIR", tmp_path / "grib")
    client.put("/voyage/official", json=_payload())
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (inbox / f"{day.replace('-', '')}_gfs.json").write_text(json.dumps({
        "model": "GFS",
        "day": day,
        "around": {"lat": 46.15, "lon": -1.16},
        "samples": [{"lat": 46.15, "lon": -1.16, "t": f"{day}T12:00:00Z", "windKnots": 9, "dirFromDeg": 200}],
    }), encoding="utf-8")
    scanned = client.post("/voyage/official/grib/scan").json()
    assert scanned["status"] == "ready"
    assert scanned["model"] == "GFS"


def test_saildocs_query_covers_eta_next_download(client):
    client.put("/voyage/official", json=_payload())
    now = datetime.now(timezone.utc)
    here = client.get("/voyage/official/at", params={"t": now.strftime("%Y-%m-%dT%H:%M:%SZ")}).json()
    body = client.get("/voyage/official/saildocs-query").json()
    dest = body["around"]["dest"]
    assert dest is not None
    later = client.get("/voyage/official/at", params={"t": body["nextDownloadAt"]}).json()
    assert body["query"].startswith("GFS:")
    assert "WIND" in body["query"]
    assert "PRMSL" in body["query"]
    codes = [q["query"].split(":")[0] for q in body["queries"]]
    assert codes == ["GFS", "WW3", "RTOFS"]
    assert abs(dest["lat"] - later["lat"]) < 0.5
    assert abs(dest["lon"] - later["lon"]) < 0.5
    south, north, west, east = saildocs.bbox_from_around(body["around"])
    assert south <= dest["lat"] <= north
    assert west <= dest["lon"] <= east
    assert north - south < 12
    if here.get("status") == "live":
        assert (dest["lat"], dest["lon"]) != (here["lat"], here["lon"])
