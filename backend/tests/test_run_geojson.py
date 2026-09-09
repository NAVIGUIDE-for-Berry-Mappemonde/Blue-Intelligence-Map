"""Sélecteur de run carte : GeoJSON des runs + import v1 (projets, AMP)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "bi_test_run_geojson")

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

import import_v1_runs as iv1
from app.services.project_runs import run_projects_to_geojson


def test_run_projects_to_geojson_keeps_image_and_filters_unlocated():
    docs = [
        {"_id": "v1:a", "title": "A", "url": "https://a", "lat": 43.3, "lon": 5.4,
         "funder": "Fondation X", "image": "https://img/a.jpg",
         "category_group": "Conservation", "verdict": "site"},
        {"_id": "v1:b", "title": "B", "url": "https://b", "lat": None, "lon": None},
        {"_id": "v1:c", "title": "C", "url": "https://c", "lat": 1.0, "lon": 2.0,
         "funders": ["F1", "F2"]},
    ]
    fc = run_projects_to_geojson("v1", docs)
    assert fc["type"] == "FeatureCollection"
    assert fc["run_id"] == "v1"
    assert fc["wrote_projects"] is False
    assert len(fc["features"]) == 2          # b est écarté (pas de coords)
    a = fc["features"][0]["properties"]
    assert a["image"] == "https://img/a.jpg"
    assert a["funder"] == "Fondation X"
    assert a["run_id"] == "v1"
    assert fc["features"][0]["geometry"]["coordinates"] == [5.4, 43.3]
    c = fc["features"][1]["properties"]
    assert c["funder"] == "F1, F2"           # funders (liste) → chaîne


def test_feature_to_run_project_preserves_photo():
    feat = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [88.62, -13.88]},
        "properties": {
            "id": "df93faae", "title": "Plastics Initiative",
            "url": "https://oceanfdn.org/initiatives/plastics-initiative/",
            "description": "desc", "funder": "The Ocean Foundation",
            "location": None, "s_ocean": 1.0, "snapped": False,
            "image": "https://oceanfdn.org/wp-content/uploads/Plastic-Beach.jpg",
            "category": None, "category_group": None,
        },
    }
    doc = iv1.feature_to_run_project(feat)
    assert doc["_id"] == "v1:df93faae"
    assert doc["run_id"] == "v1"
    assert doc["image"] == "https://oceanfdn.org/wp-content/uploads/Plastic-Beach.jpg"
    assert doc["lat"] == -13.88 and doc["lon"] == 88.62
    assert doc["wrote_projects"] is False
    assert doc["verdict"] == "site"
    assert doc["funders"] == ["The Ocean Foundation"]


def test_feature_to_run_project_rejects_incomplete():
    assert iv1.feature_to_run_project({"properties": {"id": "x", "url": "https://x"},
                                       "geometry": {"coordinates": []}}) is None
    assert iv1.feature_to_run_project({"properties": {"id": "", "url": "https://x"},
                                       "geometry": {"coordinates": [1, 2]}}) is None


def test_amp_site_to_run_doc_keeps_geometry_and_isolation():
    live = {
        "_id": "AMP123", "site_id": "AMP123", "name": "Parc marin",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        "lat": 0.5, "lon": 0.5, "lfp": 3,
    }
    doc = iv1.amp_site_to_run_doc(live)
    assert doc["_id"] == "v1:AMP123"
    assert doc["run_id"] == "v1"
    assert doc["source_id"] == "AMP123"
    assert doc["wrote_amp_sites"] is False
    assert doc["geometry"]["type"] == "Polygon"
    assert live.get("run_id") is None        # le doc live n'est pas muté


def test_mongo_kind_guard():
    assert iv1.mongo_kind("mongodb+srv://u:p@cluster0.abc.mongodb.net/db") == "atlas"
    assert iv1.mongo_kind("mongodb://localhost:27017") == "local"
    assert iv1.mongo_kind("mongodb://127.0.0.1:27017") == "local"
    assert iv1.mongo_kind("") == "empty"
