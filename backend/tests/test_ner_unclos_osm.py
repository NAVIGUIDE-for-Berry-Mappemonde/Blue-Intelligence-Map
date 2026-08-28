"""Iteration 13 — NER spaCy, qualification UNCLOS, badges OSM sur /poe/ports.
NON-DESTRUCTIF : aucune génération, aucun purge. Ne touche pas la tâche Overpass en cours.
"""
from pathlib import Path
import os
import sys
import time

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

frontend_env = dotenv_values(Path(__file__).resolve().parent.parent.parent / "frontend" / ".env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL manquant")
BASE_URL = base_url.rstrip("/")

backend_env = dotenv_values(Path(__file__).resolve().parent.parent / ".env")
MONGO_URL = backend_env.get("MONGO_URL")
DB_NAME = backend_env.get("DB_NAME")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


# ---------------------------------------------------------------- ML / NER
class TestMlNer:
    def test_ml_status_ner_model(self, api):
        r = api.get(f"{BASE_URL}/api/ml/status", timeout=60)
        assert r.status_code == 200, r.text[:400]
        models = r.json()["models"]
        assert "ner_model" in models, f"pas de ner_model: {list(models)}"
        ner = models["ner_model"]
        assert ner["ents_f"] >= 0.9, ner
        assert set(ner["labels"]) == {"LOCATION", "PORT_NAME", "PROJECT_NAME"}, ner["labels"]
        assert ner["n_train"] > 0 and ner["trained_at"]

    def test_ner_extract_port_name(self, api):
        payload = {"text": "Port de Papeete, Tahiti (French Polynesia). Clearance douanière au quai."}
        r = api.post(f"{BASE_URL}/api/ml/ner/extract", json=payload, timeout=120)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        ents = data.get("entities") or data.get("ents") or []
        assert ents, f"aucune entité: {data}"
        ports = [e for e in ents if e.get("label") == "PORT_NAME"]
        assert ports, f"aucun PORT_NAME dans {ents}"
        assert any("Papeete" in (e.get("text") or "") for e in ports), ports

    def test_ner_extract_empty_text(self, api):
        r = api.post(f"{BASE_URL}/api/ml/ner/extract", json={"text": ""}, timeout=60)
        assert r.status_code in (200, 400, 422), r.text[:300]

    def test_ner_train_status(self, api):
        r = api.get(f"{BASE_URL}/api/ml/train/ner/status", timeout=60)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        # Shape: {running, started_at, finished_at, progress, total, error, summary, cancelling}
        # NOTE: NER_STATE is an in-process global -> reset to a blank state on backend reload.
        assert d.get("running") is False, "training still running"
        assert not d.get("error"), d.get("error")
        summary = d.get("summary") or {}
        if summary:
            assert summary.get("ents_f", 0) >= 0.9, summary
        else:
            # fallback: the persisted model metadata must expose the metrics
            meta = api.get(f"{BASE_URL}/api/ml/status", timeout=60).json()["models"]["ner_model"]
            assert meta["ents_f"] >= 0.9, meta


# ---------------------------------------------------------------- UNCLOS unit
class TestUnclosUnit:
    def test_overlapping_claim(self):
        from app.services import poe_pipeline as poe
        out = poe.qualify_unclos({"poe_count": 0, "pol_type": "Overlapping claim",
                                  "anchor": [0, 10], "name": "x"})
        assert out and out["code"] == "overlapping_claim", out
        assert out.get("basis")

    def test_zone_with_poe_returns_none(self):
        from app.services import poe_pipeline as poe
        assert poe.qualify_unclos({"poe_count": 5, "pol_type": "200NM",
                                   "anchor": [0, 10], "name": "x"}) is None

    def test_joint_and_antarctic_and_uninhabited(self):
        from app.services import poe_pipeline as poe
        assert poe.qualify_unclos({"poe_count": 0, "pol_type": "Joint regime",
                                   "anchor": [0, 10], "name": "x"})["code"] == "joint_regime"
        assert poe.qualify_unclos({"poe_count": 0, "pol_type": "200NM",
                                   "anchor": [0, -70], "name": "x"})["code"] == "antarctic"
        assert poe.qualify_unclos({"poe_count": 0, "pol_type": "200NM",
                                   "anchor": [0, 10], "name": "Clipperton Island"})["code"] == "uninhabited"
        assert poe.qualify_unclos({"poe_count": 0, "pol_type": "200NM",
                                   "anchor": [0, 10], "name": "Cuba"})["code"] == "sovereign_entry"

    def test_localized_query_fr(self):
        from app.services import poe_pipeline as poe
        q = poe.localized_query({"sov_iso2": "FR", "name": "Martinique"})
        assert q and "Martinique" in q, q
        assert "ports d'entrée" in q, q

    def test_localized_query_multilang(self):
        from app.services import poe_pipeline as poe
        assert len(poe.QUERY_TEMPLATES) >= 16, len(poe.QUERY_TEMPLATES)
        assert "官方入境港口" in poe.localized_query({"sov_iso2": "CN", "name": "Hainan"})
        assert poe.localized_query({"sov_iso2": "XX", "name": "Nowhere"}) is None


# ---------------------------------------------------------------- UNCLOS API
class TestUnclosApi:
    def test_qualify_unclos_endpoint(self, api):
        r = api.post(f"{BASE_URL}/api/poe/qualify-unclos", json={}, timeout=180)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        assert d.get("zones_scanned") == 285, d
        assert 100 <= d.get("qualified", 0) <= 140, d
        by_code = d.get("by_code") or {}
        for code in ("sovereign_entry", "uninhabited", "overlapping_claim", "joint_regime"):
            assert code in by_code and by_code[code] > 0, by_code

    def test_zones_expose_unclos_only_when_no_poe(self, api):
        r = api.get(f"{BASE_URL}/api/poe/zones", timeout=120)
        assert r.status_code == 200, r.text[:400]
        items = r.json()["items"]
        assert len(items) == 285, len(items)
        empty = [z for z in items if (z.get("poe_count") or 0) == 0]
        filled = [z for z in items if (z.get("poe_count") or 0) > 0]
        assert empty and filled
        missing = [z["name"] for z in empty if not (z.get("unclos") or {}).get("code")]
        assert not missing, f"{len(missing)} zones sans PoE sans unclos: {missing[:5]}"
        leaked = [z["name"] for z in filled if z.get("unclos")]
        assert not leaked, f"zones avec PoE exposant unclos: {leaked[:5]}"
        for z in empty[:20]:
            assert z["unclos"]["code"] in ("sovereign_entry", "uninhabited", "overlapping_claim",
                                           "joint_regime", "antarctic"), z["unclos"]
            assert z["unclos"].get("basis")


# ---------------------------------------------------------------- OSM badges
class TestOsmBadges:
    def test_ports_expose_osm_properties(self, api):
        r = api.get(f"{BASE_URL}/api/poe/ports", timeout=180)
        assert r.status_code == 200, r.text[:400]
        gj = r.json()
        feats = gj["features"]
        assert len(feats) >= 1100, len(feats)
        assert "_id" not in feats[0]["properties"]
        with_conf = [f for f in feats if f["properties"].get("osm_confidence") is not None]
        assert len(with_conf) >= 300, f"seulement {len(with_conf)} ports avec osm_confidence"
        sample = with_conf[0]["properties"]
        assert isinstance(sample["osm_confidence"], (int, float))
        assert 0 <= sample["osm_confidence"] <= 1
        assert "osm_tags" in sample
        anomalies = [f for f in feats if f["properties"].get("spatial_anomaly")]
        assert len(anomalies) >= 1, "aucun port spatial_anomaly=true"

    def test_validate_osm_status_progressing(self, api):
        r1 = api.get(f"{BASE_URL}/api/poe/validate-osm/status", timeout=60)
        assert r1.status_code == 200, r1.text[:300]
        d1 = r1.json()
        if not d1.get("running"):
            pytest.skip(f"tâche Overpass non active (state={d1})")
        time.sleep(8)
        d2 = api.get(f"{BASE_URL}/api/poe/validate-osm/status", timeout=60).json()
        assert d2["progress"] >= d1["progress"], (d1["progress"], d2["progress"])
        assert d2["progress"] > d1["progress"], "progress n'avance pas en 8s"
        assert d2["total"] == d1["total"]

    def test_osm_checked_total_increasing(self, api, db):
        c1 = db.poe_ports.count_documents({"osm_confidence": {"$ne": None}})
        s = api.get(f"{BASE_URL}/api/ml/status", timeout=60).json()
        assert s["dataset"]["poe_osm_checked"] >= 300
        time.sleep(8)
        c2 = db.poe_ports.count_documents({"osm_confidence": {"$ne": None}})
        assert c2 >= c1


# ---------------------------------------------------------------- non-destructivité
class TestNonDestructive:
    def test_counts_unchanged(self, db):
        # Baselines = seed/ (les suites d'import nettoient leurs fixtures)
        assert db.projects.count_documents({}) >= 4463
        assert db.poe_ports.count_documents({}) >= 1169
        assert db.eez_zones.count_documents({}) == 285

    def test_projects_endpoint_intact(self, api):
        r = api.get(f"{BASE_URL}/api/projects", timeout=180)
        assert r.status_code == 200
        feats = r.json()["features"]
        assert len(feats) >= 4463, len(feats)
        assert all(f.get("geometry") for f in feats[:50])
