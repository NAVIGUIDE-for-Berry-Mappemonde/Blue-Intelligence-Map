"""
E2E PoE generation (zone 8397 - Sao Tome and Principe) SANS force :
verifie le monitoring (MD5 / semantique) ou une re-extraction avec upsert
non-destructif, et que poe_count ne descend jamais sous 4.
Test long (60-120s) — ne regenerer aucune autre zone.
"""
import os
import time

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

frontend_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")
backend_env = dotenv_values("/app/backend/.env")
MRGID = 8397


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


def test_generate_zone_8397_non_destructive(api, mongo):
    ports_before = list(mongo.poe_ports.find({"mrgid": MRGID}, {"_id": 1, "name": 1, "lat": 1, "lon": 1}))
    global_poe_before = mongo.poe_ports.count_documents({})
    projects_before = mongo.projects.count_documents({})
    assert len(ports_before) >= 4, len(ports_before)

    r = api.post(f"{BASE_URL}/api/poe/zones/{MRGID}/generate", json={}, timeout=60)
    assert r.status_code in (200, 202), r.text[:300]

    deadline = time.time() + 240
    st = {}
    while time.time() < deadline:
        s = api.get(f"{BASE_URL}/api/poe/zones/{MRGID}/generate/status", timeout=60)
        assert s.status_code == 200, s.text[:200]
        st = s.json()
        if st.get("state") in ("done", "error") and not st.get("running"):
            break
        time.sleep(5)
    assert st.get("state") == "done", st
    logs = "\n".join(st.get("logs_tail") or st.get("logs") or [])
    print(logs[-3000:])
    assert "purge" not in logs.lower() or "aucune purge" in logs.lower()
    assert ("MD5 inchangés" in logs or "monitoring sémantique" in logs
            or "fusionné" in logs or "préservés" in logs), logs[-1500:]

    # non destructivite
    ports_after = list(mongo.poe_ports.find({"mrgid": MRGID}, {"_id": 1, "name": 1, "lat": 1, "lon": 1}))
    assert len(ports_after) >= len(ports_before) >= 4
    ids_before = {str(p["_id"]) for p in ports_before}
    ids_after = {str(p["_id"]) for p in ports_after}
    assert ids_before <= ids_after, f"ports supprimes: {ids_before - ids_after}"
    assert mongo.poe_ports.count_documents({}) >= global_poe_before
    assert mongo.projects.count_documents({}) >= projects_before

    zone = mongo.eez_zones.find_one({"mrgid": MRGID})
    assert zone.get("poe_count", 0) >= 4, zone.get("poe_count")
    assert zone.get("status") in ("ia", "ia_sans_source"), zone.get("status")

    fc = api.get(f"{BASE_URL}/api/poe/ports?mrgid={MRGID}", timeout=60).json()
    assert len(fc["features"]) >= 4
