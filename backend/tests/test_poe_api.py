"""Backend tests — Formalities refactor [EEZ -> Ports of Entry] pipeline endpoints."""
from pathlib import Path
import os

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values(Path(__file__).resolve().parent.parent.parent / "frontend" / ".env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")


@pytest.fixture(scope="session")
def client():
    s = requests.Session()
    s.headers.update({"Accept-Encoding": "gzip"})
    return s


@pytest.fixture(scope="session")
def zones(client):
    r = client.get(f"{BASE_URL}/api/poe/zones", timeout=120)
    assert r.status_code == 200, r.text[:300]
    return r.json()


# --- Module: EEZ referential listing -----------------------------------------
class TestZones:
    def test_zones_count_and_summary(self, zones):
        assert zones["count"] == 285, f"expected 285 EEZ, got {zones['count']}"
        assert len(zones["items"]) == 285
        summary = zones["summary"]
        assert isinstance(summary["by_status"], dict) and summary["by_status"]
        assert summary["total_ports"] >= 30, summary
        assert "attribution" in zones

    def test_zone_item_shape_and_sort(self, zones):
        items = zones["items"]

        def _sk(z):
            return (
                (z.get("sovereign") or z.get("name") or "").lower(),
                0 if z.get("qualifier_key") in ("hexagone", "metropole") else 1,
                (z.get("label") or z.get("name") or "").lower(),
            )

        assert [_sk(z) for z in items] == sorted(_sk(z) for z in items)
        for it in items:
            assert isinstance(it["mrgid"], int)
            assert "name" in it and "iso2" in it and "status" in it
            assert "label" in it
            assert "poe_count" in it and "bbox" in it and "anchor" in it
            assert "_id" not in it, "MongoDB _id leaked"

    def test_some_zone_generated(self, zones):
        """Au moins une zone générée avec des PoE (dynamique, robuste au seed)."""
        gen = [z for z in zones["items"] if z.get("status") == "ia" and (z.get("poe_count") or 0) > 0]
        assert gen, "aucune zone au statut ia avec des PoE"

    def test_zones_geojson(self, client):
        r = client.get(f"{BASE_URL}/api/poe/zones/geojson", timeout=300, stream=True)
        assert r.status_code == 200, r.text[:300]
        assert "geo+json" in r.headers.get("content-type", "") or "json" in r.headers.get("content-type", "")
        data = r.json()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 285, len(data["features"])
        f0 = data["features"][0]
        assert "mrgid" in f0["properties"]
        assert f0["geometry"]["type"] in ("Polygon", "MultiPolygon")


# --- Module: Ports of Entry --------------------------------------------------
class TestPorts:
    def test_ports_geojson(self, client):
        r = client.get(f"{BASE_URL}/api/poe/ports", timeout=120)
        assert r.status_code == 200, r.text[:300]
        gj = r.json()
        assert gj["type"] == "FeatureCollection"
        assert len(gj["features"]) >= 30, len(gj["features"])
        p = gj["features"][0]["properties"]
        for k in ("name", "zone_name", "country_iso2", "validated", "source_urls"):
            assert k in p, f"missing property {k}: {p}"
        assert gj["features"][0]["geometry"]["type"] == "Point"

    def test_ports_filter_by_mrgid(self, client):
        """Le filtre mrgid ne renvoie que les ports de la zone (zone générée dynamique)."""
        zones = client.get(f"{BASE_URL}/api/poe/zones", timeout=120).json()["items"]
        gen = [z for z in zones if z.get("status") == "ia" and (z.get("poe_count") or 0) > 0]
        assert gen, "aucune zone générée avec des PoE"
        mrgid = gen[0]["mrgid"]
        r = client.get(f"{BASE_URL}/api/poe/ports", params={"mrgid": mrgid}, timeout=60)
        assert r.status_code == 200
        feats = r.json()["features"]
        assert all(f["properties"]["mrgid"] == mrgid for f in feats), \
            [f["properties"] for f in feats][:3]

    def test_ports_filter_unknown_mrgid_empty(self, client):
        r = client.get(f"{BASE_URL}/api/poe/ports", params={"mrgid": 999999}, timeout=60)
        assert r.status_code == 200
        assert r.json()["features"] == []


# --- Module: fiche ZEE (revue) ----------------------------------------------
class TestZoneFiche:
    def test_fiche_has_ports_and_td_bu(self, client, zones):
        gen = [z for z in zones["items"] if (z.get("poe_count") or 0) > 0]
        assert gen, "aucune ZEE avec des PoE"
        mrgid = gen[0]["mrgid"]
        r = client.get(f"{BASE_URL}/api/poe/zones/{mrgid}", timeout=60)
        if r.status_code == 404:
            pytest.skip("carte Formalités = Gold seulement")
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["mrgid"] == mrgid
        assert d["wrote_poe_ports"] is False
        assert d.get("fiche_scope") == "gold"
        assert "sources_td" in d and "sources_bu" in d and "ports" in d
        assert isinstance(d["ports"], list)
        blob = " ".join(
            [s.get("url") or "" for s in (d.get("urls") or [])]
            + [u for p in d["ports"] for u in (p.get("source_urls") or [])]
        ).lower()
        assert "noonsite.com" not in blob
        assert all("name" in p for p in d["ports"])

    def test_fiche_unknown_zone_404(self, client):
        r = client.get(f"{BASE_URL}/api/poe/zones/999999", timeout=60)
        assert r.status_code == 404

    def test_generate_still_gone_on_same_zone(self, client, zones):
        mrgid = zones["items"][0]["mrgid"]
        r = client.post(f"{BASE_URL}/api/poe/zones/{mrgid}/generate", timeout=60)
        assert r.status_code == 410

    def test_export_poe_geojson(self, client):
        r = client.get(f"{BASE_URL}/api/export/poe.geojson", timeout=120)
        assert r.status_code == 200
        assert "attachment" in r.headers.get("content-disposition", "")
        assert r.json()["type"] == "FeatureCollection"

    def test_france_subzones_are_separate_fiches(self, client, zones):
        """France hexagone ≠ Mayotte : deux mrgid, deux libellés, pas d'agrégat."""
        by_id = {z["mrgid"]: z for z in zones["items"]}
        hexagon = by_id[5677]
        mayotte = by_id[48944]
        assert hexagon["qualifier_key"] == "hexagone"
        assert hexagon["label"] == "France (hexagone)"
        assert mayotte["label"] == "France (Mayotte)"
        fr_labels = [z["label"] for z in zones["items"] if z.get("sovereign") == "France"]
        assert len(fr_labels) == len(set(fr_labels))
        r = client.get(f"{BASE_URL}/api/poe/zones/5677", timeout=60)
        assert r.status_code in (200, 404)
        if r.status_code == 200:
            fiche = r.json()
            assert fiche["mrgid"] == 5677
            assert fiche["label"] == "France (hexagone)"
            assert fiche["wrote_poe_ports"] is False
            assert fiche.get("fiche_scope") == "gold"
            blob = " ".join(p.get("name") or "" for p in fiche["ports"]).lower()
            assert "mamoudzou" not in blob
            assert "dzaoudzi" not in blob
        r2 = client.get(f"{BASE_URL}/api/poe/zones/48944", timeout=60)
        assert r2.status_code in (200, 404)
        if r2.status_code == 200:
            f2 = r2.json()
            assert f2["mrgid"] == 48944
            assert f2["label"] == "France (Mayotte)"


# --- Module: task status endpoints ------------------------------------------
class TestTaskStatus:
    def test_referential_status(self, client):
        r = client.get(f"{BASE_URL}/api/poe/referential/status", timeout=60)
        assert r.status_code == 200
        d = r.json()
        for k in ("running", "progress", "total", "summary"):
            assert k in d, d

    def test_batch_status_gone(self, client):
        r = client.get(f"{BASE_URL}/api/poe/generate-batch/status", timeout=60)
        assert r.status_code == 410, r.status_code

    def test_batch_cancel_gone(self, client):
        r = client.post(f"{BASE_URL}/api/poe/generate-batch/cancel", timeout=60)
        assert r.status_code == 410, r.status_code

    def test_generate_status_gone(self, client):
        r = client.get(f"{BASE_URL}/api/poe/zones/999999/generate/status", timeout=60)
        assert r.status_code == 410, r.status_code

    def test_generate_zone_gone(self, client):
        r = client.post(f"{BASE_URL}/api/poe/zones/999999/generate", timeout=60)
        assert r.status_code == 410, r.status_code
        r2 = client.post(f"{BASE_URL}/api/poe/generate-batch", json={"limit": 5}, timeout=60)
        assert r2.status_code == 410, r2.status_code


# --- Module: legacy endpoints removed ---------------------------------------
class TestLegacyRemoved:
    @pytest.mark.parametrize("path", ["/api/formalities", "/api/territories"])
    def test_get_legacy_404(self, client, path):
        r = client.get(f"{BASE_URL}{path}", timeout=60)
        assert r.status_code == 404, f"{path} -> {r.status_code}"

    def test_post_zee_trigger_formalities_gone(self, client):
        r = client.post(f"{BASE_URL}/api/zee/trigger-formalities", timeout=60)
        assert r.status_code in (404, 405), r.status_code


# --- Module: stats ----------------------------------------------------------
class TestStats:
    def test_stats_formalities(self, client):
        r = client.get(f"{BASE_URL}/api/stats", params={"mode": "formalities"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d.get("items_mapped", 0) >= 30, d

    @pytest.mark.parametrize("mode", ["projects", "marinas"])
    def test_stats_other_modes(self, client, mode):
        r = client.get(f"{BASE_URL}/api/stats", params={"mode": mode}, timeout=60)
        assert r.status_code == 200, r.text[:300]
