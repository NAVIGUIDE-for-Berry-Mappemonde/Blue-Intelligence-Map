# Tests for /api/mpa adaptive-simplification fix (iteration 7)
from pathlib import Path
import os
import time

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values(Path(__file__).resolve().parent.parent.parent / "frontend" / ".env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

NC_BBOX = "158,-26,172,-14"
ARGUIN_BBOX = "-18,19,-15,21"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    return s


class TestMpaNewCaledonia:
    """CRITICAL: Coral Sea / New Caledonia bbox must return simplified geometry fast."""

    def test_nc_bbox_returns_expected_features(self, client):
        t0 = time.time()
        r = client.get(f"{BASE_URL}/api/mpa", params={"bbox": NC_BBOX}, timeout=120)
        elapsed = time.time() - t0
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert data["type"] == "FeatureCollection"
        feats = data["features"]
        print(f"NC first call: {elapsed:.1f}s, {len(feats)} features, raw bytes={len(r.content)}")
        assert len(feats) >= 50, f"only {len(feats)} features"
        names = [(f["properties"].get("site_name") or "") for f in feats]
        assert any("Coral Sea" in n for n in names), names[:20]
        assert any("Natural Park of the Coral Sea" in n for n in names), \
            [n for n in names if "Coral" in n]
        assert any("Coral Sea Australian Marine Park" in n for n in names), \
            [n for n in names if "Coral" in n]
        # geometry present and valid on every feature
        for f in feats:
            assert f["geometry"] is not None
            assert f["geometry"]["type"] in ("Polygon", "MultiPolygon")
        assert "CC BY 4.0" in data["attribution"]
        assert elapsed < 30, f"first call took {elapsed:.1f}s"

    def test_nc_bbox_cached_is_fast(self, client):
        t0 = time.time()
        r = client.get(f"{BASE_URL}/api/mpa", params={"bbox": NC_BBOX}, timeout=60)
        elapsed = time.time() - t0
        assert r.status_code == 200
        print(f"NC cached call: {elapsed:.2f}s")
        assert elapsed < 5, f"cached call took {elapsed:.1f}s"
        assert len(r.json()["features"]) >= 50

    def test_nc_gzip_wire_size_under_5mb(self, client):
        r = client.get(f"{BASE_URL}/api/mpa", params={"bbox": NC_BBOX},
                       headers={"Accept-Encoding": "gzip"}, timeout=60, stream=True)
        assert r.status_code == 200
        wire = len(r.raw.read())
        enc = r.headers.get("content-encoding")
        print(f"content-encoding={enc} wire={wire/1e6:.2f} MB")
        assert enc == "gzip", f"expected gzip, got {enc}"
        assert wire < 5_000_000, f"wire size {wire}"


class TestMpaArguinAndValidation:
    def test_arguin_bbox_has_lfp(self, client):
        r = client.get(f"{BASE_URL}/api/mpa", params={"bbox": ARGUIN_BBOX}, timeout=120)
        assert r.status_code == 200, r.text[:300]
        feats = r.json()["features"]
        assert len(feats) >= 1
        lfps = [f["properties"]["lfp"] for f in feats]
        print(f"Arguin features={len(feats)} lfps={set(lfps)}")
        assert all(isinstance(v, int) for v in lfps)
        assert any(v > 0 for v in lfps)
        # no mongo _id leakage
        assert "_id" not in r.json()

    @pytest.mark.parametrize("bad", ["abc", "1,2,3", "", "1,2,3,x"])
    def test_invalid_bbox_400(self, client, bad):
        r = client.get(f"{BASE_URL}/api/mpa", params={"bbox": bad}, timeout=30)
        assert r.status_code == 400, f"bbox={bad!r} -> {r.status_code} {r.text[:200]}"


class TestRegressionProjects:
    def test_projects_endpoint(self, client):
        r = client.get(f"{BASE_URL}/api/projects", timeout=60)
        assert r.status_code == 200
        body = r.json()
        assert body["type"] == "FeatureCollection"
        items = body["features"]
        assert isinstance(items, list) and len(items) > 0
        print(f"projects count={len(items)}")
        assert "_id" not in items[0]["properties"]
        assert items[0]["properties"].get("id")
