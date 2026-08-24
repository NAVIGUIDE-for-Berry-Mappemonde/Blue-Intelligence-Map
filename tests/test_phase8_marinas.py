"""Phase 8 — Marinas scan verification (read-only)."""
import os
import time

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


# --- Module: marinas count ---
class TestMarinasCount:
    def test_count_shape_and_growth(self, client):
        r1 = client.get(f"{BASE_URL}/api/marinas/count", timeout=60)
        assert r1.status_code == 200, r1.text[:300]
        d1 = r1.json()
        assert isinstance(d1["total"], int)
        assert d1["total"] > 500, f"total={d1['total']}"
        assert d1["by_source"]["openstreetmap"] > 0
        assert set(["by_priority", "by_source", "enriched"]).issubset(d1.keys())

        time.sleep(75)
        r2 = client.get(f"{BASE_URL}/api/marinas/count", timeout=60)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["total"] >= d1["total"], f"total DECREASED {d1['total']} -> {d2['total']}"
        print(f"marinas total: {d1['total']} -> {d2['total']}")


# --- Module: marinas build status ---
class TestMarinasBuildStatus:
    def test_build_status(self, client):
        r = client.get(f"{BASE_URL}/api/marinas/build/status", timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d.get("error") is None, f"build error: {d.get('error')}"
        assert isinstance(d["running"], bool)
        if d["running"]:
            assert d["total"] == 159, d["total"]
            assert 0 <= d["progress"] <= d["total"]
            logs = " ".join(d.get("logs_tail") or [])
            assert "Corridor bbox" in logs, logs[-500:]
            print(f"running, progress {d['progress']}/{d['total']}")
        else:
            s = d.get("summary")
            assert s is not None, "finished but summary null"
            assert s.get("unique_after_dedup", 0) > 500, s
            assert s.get("corridor_band_nm") == 50, s
            print(f"finished, summary={s}")

    def test_build_post_conflict_while_running(self, client):
        status = client.get(f"{BASE_URL}/api/marinas/build/status", timeout=60).json()
        if not status.get("running"):
            pytest.skip("build not running; cannot verify 409")
        r = client.post(f"{BASE_URL}/api/marinas/build", timeout=60)
        assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text[:200]}"


# --- Module: marinas GeoJSON ---
class TestMarinasGeoJSON:
    def test_feature_collection(self, client):
        cnt = client.get(f"{BASE_URL}/api/marinas/count", timeout=60).json()["total"]
        r = client.get(f"{BASE_URL}/api/marinas", timeout=120)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["type"] == "FeatureCollection"
        feats = d["features"]
        assert len(feats) >= cnt * 0.9, f"features={len(feats)} vs count={cnt}"
        assert not any("_id" in f or "_id" in f.get("properties", {}) for f in feats), "MongoDB _id leaked"
        missing_nw = 0
        for f in feats:
            p = f["properties"]
            assert p.get("name")
            assert p.get("source")
            assert p.get("priority") is not None
            assert f["geometry"]["type"] == "Point"
            nw = p.get("nearest_waypoint")
            if not nw or "name" not in nw or "distance_nm" not in nw:
                missing_nw += 1
        assert missing_nw == 0, f"{missing_nw}/{len(feats)} features missing nearest_waypoint"
        print(f"geojson features: {len(feats)}")


# --- Module: regression (anchorages / zee) ---
class TestRegression:
    def test_anchorages_count(self, client):
        r = client.get(f"{BASE_URL}/api/anchorages/count", timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["total"] > 700, f"total={d['total']}"
        print(f"anchorages total: {d['total']}")

    def test_zee_crossings(self, client):
        r = client.get(f"{BASE_URL}/api/zee/crossings", timeout=90)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        crossings = d.get("crossings", d if isinstance(d, list) else [])
        assert len(crossings) == 116, f"crossings={len(crossings)}"
