"""Backend API tests for Blue Intelligence."""
import os
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def s():
    return requests.Session()


# ---------- Health ----------
def test_health(s):
    r = s.get(f"{API}/")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "Blue Intelligence"
    assert body["status"] == "operational"


# ---------- Swarm status ----------
def test_swarm_status_shape(s):
    r = s.get(f"{API}/swarm/status")
    assert r.status_code == 200
    d = r.json()
    for k in ("running", "mode", "llm", "tinyfish", "active", "queued", "agents", "logs"):
        assert k in d, f"missing {k}"
    assert isinstance(d["agents"], list)
    assert isinstance(d["logs"], list)
    # Indicateurs de capacité — dépendent des clés configurées, on ne teste que la forme
    assert isinstance(d["tinyfish"], bool)
    assert isinstance(d["llm"], bool)
    assert d["engine"] == "openrouter"


# ---------- Projects & GeoJSON ----------
def test_projects_geojson(s):
    r = s.get(f"{API}/projects")
    assert r.status_code == 200
    fc = r.json()
    assert fc["type"] == "FeatureCollection"
    assert isinstance(fc["features"], list)
    # There should be existing projects
    assert len(fc["features"]) >= 1
    f0 = fc["features"][0]
    assert f0["type"] == "Feature"
    assert f0["geometry"]["type"] == "Point"
    coords = f0["geometry"]["coordinates"]
    assert len(coords) == 2
    props = f0["properties"]
    for k in ("id", "title", "url", "funder"):
        assert k in props


def test_funders(s):
    r = s.get(f"{API}/funders")
    assert r.status_code == 200
    d = r.json()
    assert "total" in d
    assert isinstance(d["funders"], list)
    names = [f["name"] for f in d["funders"]]
    assert any("Ocean Foundation" in n for n in names)


def test_export_geojson(s):
    r = s.get(f"{API}/export/geojson")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")
    fc = r.json()
    assert fc["type"] == "FeatureCollection"


# ---------- Stats / telemetry / failed ----------
def test_stats(s):
    r = s.get(f"{API}/stats")
    assert r.status_code == 200
    d = r.json()
    for k in ("total_extractions", "success_rate", "projects_mapped"):
        assert k in d
    assert d["projects_mapped"] >= 1


def test_telemetry_list(s):
    r = s.get(f"{API}/telemetry")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_failed_list(s):
    r = s.get(f"{API}/failed")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------- Settings ----------
def test_settings_defaults(s):
    r = s.get(f"{API}/settings")
    assert r.status_code == 200
    d = r.json()
    assert isinstance(d["openrouter_api_key_set"], bool)
    assert isinstance(d["tinyfish_api_key_set"], bool)
    assert isinstance(d["anthropic_api_key_set"], bool)
    assert "claude_budget_usd" in d
    assert "_id" not in d
    assert "extract_concurrency" in d
    assert "min_marine_score" in d


def test_settings_update_and_persist(s):
    # capture original
    orig = s.get(f"{API}/settings").json()
    new_conc = 5 if orig["extract_concurrency"] != 5 else 7
    new_score = 0.55
    r = s.put(f"{API}/settings", json={
        "extract_concurrency": new_conc,
        "min_marine_score": new_score,
    })
    assert r.status_code == 200
    updated = r.json()
    assert updated["extract_concurrency"] == new_conc
    assert abs(updated["min_marine_score"] - new_score) < 1e-6

    # verify persistence via GET
    got = s.get(f"{API}/settings").json()
    assert got["extract_concurrency"] == new_conc
    assert abs(got["min_marine_score"] - new_score) < 1e-6

    # restore
    s.put(f"{API}/settings", json={
        "extract_concurrency": orig["extract_concurrency"],
        "min_marine_score": orig["min_marine_score"],
    })


# ---------- Swarm deploy validation & stop-idle ----------
def test_deploy_bad_mode_400(s):
    r = s.post(f"{API}/swarm/deploy", json={"mode": "bogus"})
    assert r.status_code == 400


def test_stop_idle(s):
    r = s.post(f"{API}/swarm/stop")
    assert r.status_code == 200
    assert r.json()["status"] == "stopped"


# ---------- Manual downloads ----------
def test_manual_en_fr(s):
    r = s.get(f"{API}/manual", params={"lang": "en"})
    assert r.status_code == 200
    assert "Blue Intelligence" in r.text
    r2 = s.get(f"{API}/manual", params={"lang": "fr"})
    assert r2.status_code == 200
    assert "Manuel" in r2.text
