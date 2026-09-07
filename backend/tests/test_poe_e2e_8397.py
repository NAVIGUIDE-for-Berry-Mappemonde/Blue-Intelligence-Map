"""
generate-batch / generate ZEE retirés : 410, poe_ports intact (Sao Tome 8397).
"""
from pathlib import Path
import os

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

frontend_env = dotenv_values(Path(__file__).resolve().parent.parent.parent / "frontend" / ".env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or frontend_env.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
backend_env = dotenv_values(Path(__file__).resolve().parent.parent / ".env")
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


@pytest.mark.skipif(not BASE_URL, reason="REACT_APP_BACKEND_URL missing")
def test_generate_zone_8397_gone_non_destructive(api, mongo):
    ports_before = list(mongo.poe_ports.find({"mrgid": MRGID}, {"_id": 1, "name": 1}))
    global_poe_before = mongo.poe_ports.count_documents({})
    projects_before = mongo.projects.count_documents({})
    assert len(ports_before) >= 4, len(ports_before)

    r = api.post(f"{BASE_URL}/api/poe/zones/{MRGID}/generate", json={}, timeout=60)
    assert r.status_code == 410, r.text[:300]
    st = api.get(f"{BASE_URL}/api/poe/zones/{MRGID}/generate/status", timeout=60)
    assert st.status_code == 410, st.text[:200]

    ports_after = list(mongo.poe_ports.find({"mrgid": MRGID}, {"_id": 1, "name": 1}))
    assert {str(p["_id"]) for p in ports_after} == {str(p["_id"]) for p in ports_before}
    assert mongo.poe_ports.count_documents({}) == global_poe_before
    assert mongo.projects.count_documents({}) == projects_before
    zone = mongo.eez_zones.find_one({"mrgid": MRGID})
    assert zone.get("poe_count", 0) >= 4, zone.get("poe_count")
