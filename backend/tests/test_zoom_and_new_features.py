"""Backend tests for iter4: /api/categories, /api/reports, /api/report-project, saturation, settings."""
import os
import asyncio
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def s():
    return requests.Session()


# ---------- /api/categories ----------
def test_categories_shape_and_totals(s):
    r = s.get(f"{API}/categories")
    assert r.status_code == 200
    d = r.json()
    assert "groups" in d
    groups = d["groups"]
    assert len(groups) == 9
    names = {g["name"] for g in groups}
    for expected in ("MPA", "Conservation", "Research", "Fisheries", "Policy & Advocacy",
                     "Pollution", "Coastal & Habitat", "Education", "Other"):
        assert expected in names
    for g in groups:
        assert "color" in g and g["color"].startswith("#")
        assert "count" in g and isinstance(g["count"], int)
    total = sum(g["count"] for g in groups)
    # DB is ~4425 projects
    assert total >= 4000, f"Total category counts too low: {total}"


def test_projects_have_category_group(s):
    r = s.get(f"{API}/projects")
    assert r.status_code == 200
    feats = r.json()["features"]
    assert len(feats) >= 1
    # sample first 20 features
    for f in feats[:20]:
        assert "category_group" in f["properties"]
        assert f["properties"]["category_group"] in {
            "MPA", "Conservation", "Research", "Fisheries", "Policy & Advocacy",
            "Pollution", "Coastal & Habitat", "Education", "Other"
        }


# ---------- /api/report-project ----------
def test_report_project_invalid_url(s):
    r = s.post(f"{API}/report-project", json={"name": "TEST_x", "url": "not-a-url", "description": "d"})
    assert r.status_code == 400


def test_report_project_empty_name(s):
    r = s.post(f"{API}/report-project", json={"name": "", "url": "https://example.com", "description": ""})
    assert r.status_code == 400


def test_report_project_valid_then_lists(s):
    payload = {
        "name": "TEST_Reef Project Iter4",
        "url": "https://example.org/reef-test-iter4",
        "description": "Automated test entry from iteration 4",
    }
    r = s.post(f"{API}/report-project", json=payload)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] in ("queued_now", "queued_next_run")
    assert "email_status" in d
    rid = d["id"]

    # GET /api/reports contains entry
    lst = s.get(f"{API}/reports").json()
    assert any(e["id"] == rid and e["name"] == payload["name"] for e in lst)


# ---------- /api/settings saturation_limit ----------
def test_settings_saturation_limit_default_and_persist(s):
    orig = s.get(f"{API}/settings").json()
    assert "saturation_limit" in orig
    # default is 50 if not previously changed; either way should be int
    assert isinstance(orig["saturation_limit"], int)

    r = s.put(f"{API}/settings", json={"saturation_limit": 30})
    assert r.status_code == 200
    assert r.json()["saturation_limit"] == 30
    assert s.get(f"{API}/settings").json()["saturation_limit"] == 30

    # restore
    s.put(f"{API}/settings", json={"saturation_limit": orig["saturation_limit"]})


# ---------- Auto-Stop saturation (in-process pipeline test) ----------
class _FakeDB:
    pass


def test_saturation_bump_triggers_stop_and_reset():
    # Import in-process pipeline
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from pipeline import Swarm

    async def run():
        sw = Swarm(_FakeDB())
        sw.settings = {"saturation_limit": 3}
        sw.running = True
        # stub stop() to just flip flag (avoid touching queue/main_task)
        stop_called = {"n": 0}

        async def fake_stop():
            stop_called["n"] += 1
            sw.running = False
        sw.stop = fake_stop

        sw._bump_saturation(False)
        assert sw.no_new_streak == 1
        assert sw.saturated is False
        sw._bump_saturation(False)
        sw._bump_saturation(False)  # 3rd → should schedule stop
        # give the create_task a tick
        await asyncio.sleep(0.05)
        assert sw.saturated is True
        assert stop_called["n"] == 1

        # Reset via new_project=True
        sw.no_new_streak = 7
        sw._bump_saturation(True)
        assert sw.no_new_streak == 0

    asyncio.run(run())
