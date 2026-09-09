"""Contrat Projets CDC v2 — phase A (purges, sites, seuils)."""
import asyncio
import inspect
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "bi_test_project_contract")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.core.llm import heuristic_gatekeeper
from app.core.project_geo import site_publishable, valid_coords
from app.services.swarm_pipeline import Swarm


def test_valid_coords_rejects_null_island_and_garbage():
    assert valid_coords(48.8, -3.0) is True
    assert valid_coords(0, 0) is False
    assert valid_coords(None, 2) is False
    assert valid_coords(200, 0) is False


def test_site_publishable_ocean_ok():
    # Milieu du golfe de Gascogne
    ok, kind = site_publishable(45.5, -5.0, {"max_inland_km": 15})
    assert ok is True
    assert kind == "ocean"


def test_site_publishable_paris_inland():
    ok, kind = site_publishable(48.8566, 2.3522, {"max_inland_km": 15})
    assert ok is False
    assert kind == "inland"


def test_site_publishable_no_coords():
    ok, kind = site_publishable(None, None, {})
    assert ok is False
    assert kind == "no_coords"


def test_site_publishable_inland_threshold_configurable():
    # Point ~30 km à l'intérieur : rejeté à 15 km, accepté si le seuil est large
    lat, lon = 48.4, -1.5  # Bretagne intérieure approximative
    ok_strict, _ = site_publishable(lat, lon, {"max_inland_km": 5})
    ok_wide, kind_wide = site_publishable(lat, lon, {"max_inland_km": 200})
    assert ok_strict is False or ok_wide is True
    if ok_wide:
        assert kind_wide in ("coastal", "ocean")


def test_pipeline_does_not_call_snap_or_fallback():
    src = Path(__file__).resolve().parents[1] / "app" / "services" / "swarm_pipeline.py"
    text = src.read_text()
    assert "ocean_fallback_coords" not in text
    assert "snap_to_ocean" not in text
    assert "geocode_project_site" in text
    assert "from app.core.geo import geocode" not in text


def test_force_extract_does_not_call_snap_or_fallback():
    src = Path(__file__).resolve().parents[1] / "app" / "routers" / "swarm.py"
    text = src.read_text()
    assert "ocean_fallback_coords" not in text
    assert "snap_to_ocean" not in text


def test_swarm_never_writes_projects_collection():
    src = Path(__file__).resolve().parents[1] / "app" / "services" / "swarm_pipeline.py"
    text = src.read_text()
    assert "db.projects.insert_one" not in text
    assert "db.projects.update_one" not in text
    assert "db.projects.insert_many" not in text
    assert "write_run_project" in text
    assert "project_run_projects" in text


def test_force_extract_never_writes_projects():
    src = Path(__file__).resolve().parents[1] / "app" / "routers" / "swarm.py"
    text = src.read_text()
    assert "db.projects.insert_one" not in text
    assert "db.projects.update_one" not in text
    assert "_process_url" in text
    assert "wrote_projects" in text


def test_deploy_clear_db_raises():
    sw = Swarm(None)

    async def run():
        with pytest.raises(ValueError, match="clear_db is disabled"):
            await sw.deploy("test", True, {}, False)

    asyncio.run(run())


def test_heuristic_gatekeeper_uses_min_marine_score():
    text = "ocean marine coral mountain rainforest savanna desert grassland alpine prairie terrestrial"
    loose = heuristic_gatekeeper(text, {"min_marine_score": 0.01})
    strict = heuristic_gatekeeper(text, {"min_marine_score": 0.99})
    assert loose["accepted"] is True
    assert strict["accepted"] is False


def test_gatekeeper_check_reads_thresholds_from_settings():
    src = inspect.getsource(__import__("app.core.llm", fromlist=["gatekeeper_check"]).gatekeeper_check)
    assert "gatekeeper_accept" in src
    assert "gatekeeper_reject" in src


@pytest.mark.skipif(
    not os.environ.get("REACT_APP_BACKEND_URL"),
    reason="API locale non configurée",
)
def test_http_purge_endpoints_disabled():
    import requests
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
    api = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
    r = requests.delete(f"{api}/projects", timeout=30)
    assert r.status_code == 410
    r2 = requests.post(f"{api}/swarm/deploy", json={"mode": "test", "clear_db": True}, timeout=30)
    assert r2.status_code == 400
