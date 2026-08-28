"""
Tests des jobs longs non-destructifs :
- POST /api/ml/anomalies/scan  (flags spatial_anomaly uniquement)
- POST /api/poe/validate-osm   (flags osm_* uniquement)
Verifie qu'AUCUN champ name/lat/lon des poe_ports n'est modifie et que les
comptes globaux (projects / poe_ports) ne diminuent jamais.
"""
from pathlib import Path
import os
import time

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

frontend_env = dotenv_values(Path(__file__).resolve().parent.parent.parent / "frontend" / ".env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")
backend_env = dotenv_values(Path(__file__).resolve().parent.parent / ".env")


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(backend_env.get("MONGO_URL"))
    yield client[backend_env.get("DB_NAME")]
    client.close()


def snapshot(db):
    docs = list(db.poe_ports.find({}, {"_id": 1, "name": 1, "lat": 1, "lon": 1}))
    return {str(d["_id"]): (d.get("name"), d.get("lat"), d.get("lon")) for d in docs}


def wait_done(api, url, timeout=180, interval=3):
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        r = api.get(url, timeout=60)
        assert r.status_code == 200, r.text[:300]
        last = r.json()
        if not last.get("running") and (last.get("finished_at") or last.get("state") in ("done", "error")):
            return last
        time.sleep(interval)
    pytest.fail(f"timeout waiting {url}: {last}")


class TestAnomalyScan:
    def test_scan_non_destructive(self, api, mongo):
        before = snapshot(mongo)
        projects_before = mongo.projects.count_documents({})
        poe_before = len(before)

        r = api.post(f"{BASE_URL}/api/ml/anomalies/scan", json={}, timeout=60)
        assert r.status_code == 202, r.text[:300]

        st = wait_done(api, f"{BASE_URL}/api/ml/anomalies/status", timeout=240)
        assert not st.get("error"), st.get("error")
        summary = st.get("summary") or {}
        assert summary.get("ports_checked", 0) >= 1100, summary
        assert summary.get("anomalies_flagged", 0) > 0, summary

        after = snapshot(mongo)
        assert len(after) >= poe_before, "poe_ports count decreased!"
        assert mongo.projects.count_documents({}) >= projects_before
        changed = {k: (before[k], after[k]) for k in before if k in after and before[k] != after[k]}
        assert not changed, f"name/lat/lon modified for {len(changed)} ports: {list(changed.items())[:3]}"
        # les flags ont bien ete ajoutes
        assert mongo.poe_ports.count_documents({"anomaly_checked_at": {"$exists": True}}) >= 1100
        assert mongo.poe_ports.count_documents({"spatial_anomaly": True}) > 0

    def test_anomaly_report(self, api):
        r = api.get(f"{BASE_URL}/api/ml/anomalies/report", timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert d["summary"]["ports_checked"] >= 1100, d["summary"]
        assert d["summary"]["anomalies_flagged"] > 0
        assert isinstance(d["anomalies"], list) and len(d["anomalies"]) > 0
        first = d["anomalies"][0]
        for k in ("id", "name", "lat", "lon"):
            assert k in first, first
        assert "_id" not in first

    def test_scan_conflict_409(self, api):
        # relance immediate : soit 202 (precedent termine), soit 409 si running
        r = api.post(f"{BASE_URL}/api/ml/anomalies/scan", json={}, timeout=60)
        assert r.status_code in (202, 409), r.status_code
        if r.status_code == 202:
            r2 = api.post(f"{BASE_URL}/api/ml/anomalies/scan", json={}, timeout=60)
            assert r2.status_code == 409
            wait_done(api, f"{BASE_URL}/api/ml/anomalies/status", timeout=240)


class TestOsmValidate:
    def test_validate_osm_non_destructive(self, api, mongo):
        before = snapshot(mongo)
        r = api.post(f"{BASE_URL}/api/poe/validate-osm",
                     json={"limit": 3, "only_unchecked": True}, timeout=60)
        assert r.status_code == 202, r.text[:300]

        st = wait_done(api, f"{BASE_URL}/api/poe/validate-osm/status", timeout=180)
        assert not st.get("error"), st.get("error")
        summary = st.get("summary") or {}
        assert summary.get("checked") == 3, summary

        after = snapshot(mongo)
        assert len(after) >= len(before)
        changed = {k: (before[k], after[k]) for k in before if k in after and before[k] != after[k]}
        assert not changed, f"name/lat/lon modified for {len(changed)} ports: {list(changed.items())[:3]}"
        checked = list(mongo.poe_ports.find({"osm_checked_at": {"$exists": True}},
                                            {"_id": 0, "osm_confidence": 1, "osm_tags": 1,
                                             "osm_checked_at": 1}))
        assert len(checked) >= 3
        assert all("osm_confidence" in c for c in checked)
