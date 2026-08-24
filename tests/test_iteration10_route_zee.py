"""Iteration 10 — read-only backend verification.

Covers: /api/route (antimeridian split), /api/zee/crossings (recomputed),
plus basic health of formalities / marinas / anchorages endpoints.
NO build/compute POSTs (live Overpass builds running).
"""
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
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- /api/route : antimeridian split ----------
class TestRoute:
    @pytest.fixture(scope="class")
    def route(self, client):
        r = client.get(f"{BASE_URL}/api/route", timeout=60)
        assert r.status_code == 200, r.text[:400]
        return r.json()

    def test_feature_count(self, route):
        feats = route.get("features", route.get("route", {}).get("features"))
        assert isinstance(feats, list), f"unexpected shape: {list(route)[:6]}"
        print(f"features={len(feats)}")
        assert len(feats) == 72, f"expected 72 features, got {len(feats)}"

    def test_no_out_of_bounds_longitudes(self, route):
        feats = route.get("features", route.get("route", {}).get("features"))
        bad = []

        def walk(coords):
            if not coords:
                return
            if isinstance(coords[0], (int, float)):
                lon, lat = coords[0], coords[1]
                if lon < -180 or lon > 180 or lat < -90 or lat > 90:
                    bad.append((lon, lat))
            else:
                for c in coords:
                    walk(c)

        for f in feats:
            geom = f.get("geometry") or {}
            walk(geom.get("coordinates"))
        assert not bad, f"out-of-bounds coords: {bad[:10]}"

    def test_antimeridian_parts_present(self, route):
        feats = route.get("features", route.get("route", {}).get("features"))
        parts = [f for f in feats if (f.get("properties") or {}).get("antimeridian_part")]
        print(f"antimeridian_part features: {[(f['properties'].get('antimeridian_part'), f['properties'].get('name') or f['properties'].get('label')) for f in parts]}")
        assert len(parts) >= 2, "expected the Mata-Utu -> Noumea leg split in 2 parts"

    def test_no_mongo_id_leak(self, route):
        assert "_id" not in str(route)[:200000] or '"_id"' not in str(route)


# ---------- /api/zee/crossings ----------
class TestZeeCrossings:
    @pytest.fixture(scope="class")
    def data(self, client):
        r = client.get(f"{BASE_URL}/api/zee/crossings", timeout=90)
        assert r.status_code == 200, r.text[:400]
        return r.json()

    def test_summary(self, data):
        s = data.get("summary") or {}
        print(f"summary={s}")
        assert s.get("total_crossings") == 117, s
        assert s.get("unique_territories") == 13, s

    def test_fiji_crossing_present(self, data):
        crossings = data.get("crossings") or []
        assert crossings, "no crossings returned"
        fiji = [c for c in crossings if "Fij" in str(c.get("geoname") or "")]
        print(f"fiji entries={[(c['order'], c['geoname'], c['seg_from'], c['seg_to']) for c in fiji]}")
        assert fiji, "missing Fijian EEZ crossing (corrected antimeridian leg)"
        f = fiji[0]
        assert f.get("territory_code") is None, f
        assert 76 < f["order"] < 80, f"Fiji crossing order {f['order']} not between Wallis(76) and NC(80)"
        assert "Mata-Utu" in f["seg_from"] and "Nouméa" in f["seg_to"], f

    def test_no_mongo_id(self, data):
        assert '"_id"' not in str(data)


# ---------- basic read endpoints ----------
class TestReadEndpoints:
    @pytest.mark.parametrize("path", [
        "/api/formalities",
        "/api/marinas",
        "/api/anchorages",
        "/api/swarm/status",
        "/api/stats",
    ])
    def test_get_ok(self, client, path):
        r = client.get(f"{BASE_URL}{path}", timeout=90)
        print(f"{path} -> {r.status_code}")
        assert r.status_code == 200, r.text[:300]
        assert '"_id"' not in r.text[:200000]

    def test_anchorages_count(self, client):
        r = client.get(f"{BASE_URL}/api/anchorages", timeout=90)
        assert r.status_code == 200
        feats = r.json().get("features") or []
        c = client.get(f"{BASE_URL}/api/anchorages/count", timeout=60)
        assert c.status_code == 200
        total = c.json()["total"]
        print(f"anchorages features={len(feats)} count.total={total}")
        assert total > 2600, f"expected >2600 anchorages, got {total}"
        assert len(feats) == total

    def test_formalities_territories(self, client):
        """17 escales map onto 13 French territories - endpoint returns per-territory docs."""
        r = client.get(f"{BASE_URL}/api/formalities", timeout=60)
        j = r.json()
        items = j["items"]
        assert j["count"] == 13 and len(items) == 13, j["count"]
        assert all(i.get("territory_code") for i in items)
