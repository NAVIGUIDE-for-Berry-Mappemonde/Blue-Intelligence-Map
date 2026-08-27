"""Backend tests — Formalities refactor [EEZ -> Ports of Entry] pipeline endpoints."""
import os

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")


@pytest.fixture(scope="session")
def client():
    s = requests.Session()
    s.headers.update({"Accept-Encoding": "gzip"})
    return s


@pytest.fixture(scope="session")
def zones(client):
    r = client.get(f"{BASE_URL}/api/poe/zones", timeout=120)
    assert r.status_code == 200, r.text[:300]
    return r.json()


# --- Module: EEZ referential listing -----------------------------------------
class TestZones:
    def test_zones_count_and_summary(self, zones):
        assert zones["count"] == 285, f"expected 285 EEZ, got {zones['count']}"
        assert len(zones["items"]) == 285
        summary = zones["summary"]
        assert isinstance(summary["by_status"], dict) and summary["by_status"]
        assert summary["total_ports"] >= 30, summary
        assert "attribution" in zones

    def test_zone_item_shape_and_sort(self, zones):
        items = zones["items"]
        names = [(i.get("name") or "").lower() for i in items]
        assert names == sorted(names), "items not sorted by name"
        for it in items:
            assert isinstance(it["mrgid"], int)
            assert "name" in it and "iso2" in it and "status" in it
            assert "poe_count" in it and "bbox" in it and "anchor" in it
            assert "_id" not in it, "MongoDB _id leaked"

    def test_fiji_zone_generated(self, zones):
        fiji = [z for z in zones["items"] if z["mrgid"] == 8325]
        assert fiji, "Fiji mrgid=8325 missing"
        assert fiji[0]["status"] == "ia", fiji[0]
        assert fiji[0]["poe_count"] > 0, fiji[0]

    def test_zones_geojson(self, client):
        r = client.get(f"{BASE_URL}/api/poe/zones/geojson", timeout=300, stream=True)
        assert r.status_code == 200, r.text[:300]
        assert "geo+json" in r.headers.get("content-type", "") or "json" in r.headers.get("content-type", "")
        data = r.json()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 285, len(data["features"])
        f0 = data["features"][0]
        assert "mrgid" in f0["properties"]
        assert f0["geometry"]["type"] in ("Polygon", "MultiPolygon")


# --- Module: Ports of Entry --------------------------------------------------
class TestPorts:
    def test_ports_geojson(self, client):
        r = client.get(f"{BASE_URL}/api/poe/ports", timeout=120)
        assert r.status_code == 200, r.text[:300]
        gj = r.json()
        assert gj["type"] == "FeatureCollection"
        assert len(gj["features"]) >= 30, len(gj["features"])
        p = gj["features"][0]["properties"]
        for k in ("name", "zone_name", "country_iso2", "validated", "source_urls"):
            assert k in p, f"missing property {k}: {p}"
        assert gj["features"][0]["geometry"]["type"] == "Point"

    def test_ports_filter_by_mrgid(self, client):
        r = client.get(f"{BASE_URL}/api/poe/ports", params={"mrgid": 8325}, timeout=60)
        assert r.status_code == 200
        feats = r.json()["features"]
        assert len(feats) > 0
        assert all(f["properties"].get("zone_name", "").lower().startswith("fiji")
                   or f["properties"].get("country_iso2") == "FJ" for f in feats), \
            [f["properties"] for f in feats][:3]

    def test_ports_filter_unknown_mrgid_empty(self, client):
        r = client.get(f"{BASE_URL}/api/poe/ports", params={"mrgid": 999999}, timeout=60)
        assert r.status_code == 200
        assert r.json()["features"] == []

    def test_export_poe_geojson(self, client):
        r = client.get(f"{BASE_URL}/api/export/poe.geojson", timeout=120)
        assert r.status_code == 200
        assert "attachment" in r.headers.get("content-disposition", "")
        assert r.json()["type"] == "FeatureCollection"


# --- Module: task status endpoints ------------------------------------------
class TestTaskStatus:
    def test_referential_status(self, client):
        r = client.get(f"{BASE_URL}/api/poe/referential/status", timeout=60)
        assert r.status_code == 200
        d = r.json()
        for k in ("running", "progress", "total", "summary"):
            assert k in d, d

    def test_batch_status(self, client):
        r = client.get(f"{BASE_URL}/api/poe/generate-batch/status", timeout=60)
        assert r.status_code == 200
        assert "running" in r.json()

    def test_batch_cancel_when_idle(self, client):
        r = client.post(f"{BASE_URL}/api/poe/generate-batch/cancel", timeout=60)
        assert r.status_code == 409, r.status_code

    def test_generate_status_unknown_zone_idle(self, client):
        r = client.get(f"{BASE_URL}/api/poe/zones/999999/generate/status", timeout=60)
        assert r.status_code == 200
        assert r.json()["state"] == "idle"

    def test_generate_unknown_zone_404(self, client):
        r = client.post(f"{BASE_URL}/api/poe/zones/999999/generate", timeout=60)
        assert r.status_code == 404, r.status_code


# --- Module: legacy endpoints removed ---------------------------------------
class TestLegacyRemoved:
    @pytest.mark.parametrize("path", ["/api/formalities", "/api/territories"])
    def test_get_legacy_404(self, client, path):
        r = client.get(f"{BASE_URL}{path}", timeout=60)
        assert r.status_code == 404, f"{path} -> {r.status_code}"

    def test_post_zee_trigger_formalities_gone(self, client):
        r = client.post(f"{BASE_URL}/api/zee/trigger-formalities", timeout=60)
        assert r.status_code in (404, 405), r.status_code


# --- Module: stats ----------------------------------------------------------
class TestStats:
    def test_stats_formalities(self, client):
        r = client.get(f"{BASE_URL}/api/stats", params={"mode": "formalities"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d.get("items_mapped", 0) >= 30, d

    @pytest.mark.parametrize("mode", ["projects", "marinas"])
    def test_stats_other_modes(self, client, mode):
        r = client.get(f"{BASE_URL}/api/stats", params={"mode": mode}, timeout=60)
        assert r.status_code == 200, r.text[:300]
