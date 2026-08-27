"""Phase 8 backend tests — ZEE crossings, anchorages, marinas build status, formalities.

Read-only except POST /api/zee/trigger-formalities (idempotent: 13 skipped expected).
NO POST to /api/anchorages/build, /api/marinas/build, /api/zee/compute (real Overpass build running).
"""
import json
import os
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def territory_codes():
    p = Path("/app/backend/data/territories.json")
    if not p.exists():
        p = Path("/app/backend/territories.json")
    data = json.loads(p.read_text(encoding="utf-8"))
    terrs = data.get("territories", data)
    return {t["code"] for t in terrs}


# ---------------- ZEE crossings ----------------
class TestZeeCrossings:
    def test_crossings_payload(self, client):
        r = client.get(f"{BASE_URL}/api/zee/crossings", timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["detection_method"] == "shapely"
        s = d["summary"]
        assert s["total_crossings"] == 116, s
        assert s["unique_territories"] == 13, s
        cr = d["crossings"]
        assert len(cr) == 116
        # ordering + required fields
        orders = [c["order"] for c in cr]
        assert orders == sorted(orders), "crossings not ordered by order field"
        for c in cr:
            for k in ("order", "territory_code", "geoname", "entry_lat", "entry_lon",
                      "exit_lat", "exit_lon", "intersection_length_nm", "pol_type"):
                assert k in c, f"missing {k} in crossing {c.get('order')}"
            assert isinstance(c["intersection_length_nm"], (int, float))
            assert -90 <= c["entry_lat"] <= 90 and -180 <= c["entry_lon"] <= 180

    def test_french_only(self, client, territory_codes):
        r = client.get(f"{BASE_URL}/api/zee/crossings", params={"french_only": "true"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        cr = d["crossings"]
        assert all(c["territory_code"] for c in cr), "french_only returned null territory_code"
        assert len(cr) == 27, f"expected 27 french crossings, got {len(cr)}"
        codes = {c["territory_code"] for c in cr}
        assert len(codes) == 13, codes
        assert codes.issubset(territory_codes), codes - territory_codes

    def test_compute_status(self, client):
        r = client.get(f"{BASE_URL}/api/zee/compute/status", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert isinstance(d["running"], bool)
        assert d["running"] is False, "ZEE compute unexpectedly running"
        assert isinstance(d["logs_tail"], list)

    def test_trigger_formalities_idempotent(self, client):
        r = client.post(f"{BASE_URL}/api/zee/trigger-formalities", json={}, timeout=120)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert len(d["detected_territory_codes"]) == 13, d
        assert d["triggered"] == [], f"generation was relaunched: {d['triggered']}"
        assert d.get("skipped_uptodate") == 13 or len(d.get("skipped_uptodate", [])) == 13, d


# ---------------- Anchorages ----------------
class TestAnchorages:
    def test_anchorages_geojson(self, client):
        r = client.get(f"{BASE_URL}/api/anchorages", timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["type"] == "FeatureCollection"
        assert isinstance(d["features"], list)

    def test_count(self, client):
        r = client.get(f"{BASE_URL}/api/anchorages/count", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "total" in d and isinstance(d["total"], int)
        assert set(d["by_priority"].keys()) == {"1", "2", "3"}
        assert "anchorage" in d["by_type"]

    def test_build_status_running(self, client):
        r = client.get(f"{BASE_URL}/api/anchorages/build/status", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert isinstance(d["running"], bool)
        assert isinstance(d["progress"], int) and isinstance(d["total"], int)
        assert d["total"] >= 0
        assert isinstance(d["logs_tail"], list)

    @pytest.mark.skip(reason="read-only run: POST build would restart real Overpass build")
    def test_build_conflict_409(self, client):
        r = client.post(f"{BASE_URL}/api/anchorages/build", json={}, timeout=30)
        assert r.status_code in (409, 200), f"unexpected {r.status_code}"

    def test_export_geojson(self, client):
        r = client.get(f"{BASE_URL}/api/export/anchorages.geojson", timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert "attachment" in r.headers.get("Content-Disposition", "").lower()
        d = r.json()
        assert d["type"] == "FeatureCollection"


# ---------------- Marinas build status ----------------
def test_marinas_build_status_idle(client):
    r = client.get(f"{BASE_URL}/api/marinas/build/status", timeout=30)
    assert r.status_code == 200
    assert r.json()["running"] is False


# ---------------- Formalities ----------------
def test_formalities_13_ia(client):
    r = client.get(f"{BASE_URL}/api/formalities", timeout=60)
    assert r.status_code == 200
    d = r.json()
    items = d["items"]
    assert len(items) == 13, f"expected 13 formalities, got {len(items)}"
    for it in items:
        assert it["status"] == "ia", f"{it['territory_code']} status={it['status']}"
        assert it.get("sources"), f"{it['territory_code']} has empty sources"
        assert "_id" not in it, "MongoDB _id leaked in response"
