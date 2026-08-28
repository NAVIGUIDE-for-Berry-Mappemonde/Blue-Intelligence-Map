"""Iteration 2: GeoJSON import + regression tests (4420 projects state).

Tests focus on:
- POST /api/import/geojson: valid FC, dedup, invalid coords, invalid payload
- Regression: /api/projects (feature count, category/image props), /api/funders (~854),
  /api/swarm/status, /api/audit KPIs, /api/export/geojson.
"""
import os
import uuid
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")


def _cleanup_fixtures():
    """Supprime les projets TEST_Import_* créés par cette suite (idempotent)."""
    from pathlib import Path as _P
    from dotenv import dotenv_values
    from pymongo import MongoClient
    env = dotenv_values(_P(__file__).resolve().parent.parent / ".env")
    db = MongoClient(env["MONGO_URL"])[env["DB_NAME"]]
    db.projects.delete_many({"url": {"$regex": r"test\.example\.com"}})


import atexit
atexit.register(_cleanup_fixtures)
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def s():
    return requests.Session()


# ---------- GeoJSON Import ----------
def _fc_payload():
    tag = uuid.uuid4().hex[:10]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-30.0, 15.0]},
                "properties": {
                    "title": f"TEST_Import_A_{tag}",
                    "url": f"https://test.example.com/a/{tag}",
                    "funder": "TEST_Funder_A",
                    "description": "Sample imported project A",
                    "image": "https://example.com/img_a.jpg",
                    "category": "research",
                    "s_ocean": 0.82,
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [45.5, -20.5]},
                "properties": {
                    "title": f"TEST_Import_B_{tag}",
                    "url": f"https://test.example.com/b/{tag}",
                    "funder": "TEST_Funder_B",
                    "description": "Sample imported project B",
                    "category": "conservation",
                },
            },
            {  # invalid coords - counts as invalid
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [200, 95]},
                "properties": {"title": "TEST_Bad", "url": f"https://bad.example.com/{tag}"},
            },
        ],
    }


def test_import_invalid_payload(s):
    r = s.post(f"{API}/import/geojson", json={"type": "x"})
    assert r.status_code == 400


def test_import_valid_and_dedup(s):
    payload = _fc_payload()
    r1 = s.post(f"{API}/import/geojson", json=payload, timeout=60)
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["imported"] == 2, d1
    assert d1["invalid"] == 1, d1
    assert d1["total_projects"] >= 4420
    total_after_first = d1["total_projects"]

    # Re-import same payload -> dedup via URL
    r2 = s.post(f"{API}/import/geojson", json=payload, timeout=60)
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2["skipped_existing"] == 2, d2
    assert d2["imported"] == 0, d2
    assert d2["invalid"] == 1, d2
    # No new docs created
    assert d2["total_projects"] == total_after_first


# ---------- Regression ----------
def test_projects_count_and_props(s):
    r = s.get(f"{API}/projects")
    assert r.status_code == 200
    fc = r.json()
    assert fc["type"] == "FeatureCollection"
    feats = fc["features"]
    assert len(feats) >= 4420, f"expected >=4420 features, got {len(feats)}"
    # At least one feature should include category and image props (imported ones)
    has_category = any(f["properties"].get("category") for f in feats)
    has_image = any(f["properties"].get("image") for f in feats)
    assert has_category, "no feature has category property"
    assert has_image, "no feature has image property"


def test_funders_totals(s):
    r = s.get(f"{API}/funders")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] >= 4420
    # ~854 funders (allow some tolerance since import adds TEST_Funder_A/B)
    assert isinstance(d.get("funders"), list)
    assert 800 <= len(d["funders"]) <= 900, f"funder count out of range: {len(d['funders'])}"


def test_swarm_status(s):
    r = s.get(f"{API}/swarm/status")
    assert r.status_code == 200
    d = r.json()
    for k in ("running", "mode", "llm", "tinyfish", "active", "queued", "agents", "logs"):
        assert k in d


def test_audit_kpis(s):
    r = s.get(f"{API}/stats")
    assert r.status_code == 200
    d = r.json()
    for k in ("total_extractions", "success_rate", "projects_mapped"):
        assert k in d


def test_export_geojson(s):
    r = s.get(f"{API}/export/geojson")
    assert r.status_code == 200
    # Might return JSON directly
    body = r.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) >= 4420
