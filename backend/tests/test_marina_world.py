"""Dump mondial marinas — palier 1 (identité osm_id, slim GeoJSON, pas de purge)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.tasks import BuildState
from app.services import marina_world as mw
from app.core.run_rules import catalog_default, reload_catalog


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def _match_one(self, doc, q):
        if not q:
            return True
        for k, v in (q or {}).items():
            if doc.get(k) != v:
                return False
        return True

    async def find_one(self, q=None, proj=None):
        for d in self.docs:
            if self._match_one(d, q or {}):
                return d
        return None

    async def insert_one(self, doc):
        self.docs.append(doc)

    async def update_one(self, q, upd, upsert=False):
        doc = await self.find_one(q)
        if not doc:
            if not upsert:
                return None
            doc = dict(q or {})
            if "$set" in upd:
                doc.update(upd["$set"])
            self.docs.append(doc)
            return None
        if "$set" in upd:
            doc.update(upd["$set"])
        return None

    async def replace_one(self, q, payload, upsert=False):
        doc = await self.find_one(q)
        if not doc:
            if upsert:
                self.docs.append(payload)
            return None
        idx = self.docs.index(doc)
        self.docs[idx] = payload
        return None

    async def create_index(self, *a, **k):
        return None


def test_google_maps_url_named():
    url = mw.google_maps_url("Port des Minimes", 46.14639, -1.16278)
    assert url.startswith("https://www.google.com/maps/search/?api=1&query=")
    assert "46.14639" in url
    assert "-1.16278" in url
    assert "Minimes" in url


def test_google_maps_url_unnamed_is_coords_only():
    url = mw.google_maps_url("", 43.3, 5.4)
    assert "43.30000" in url
    assert "5.40000" in url


def test_leisure_query_is_marina_only():
    ql = mw.leisure_marina_bbox_ql(40.0, -6.0, 52.0, 10.0)
    assert 'nwr["leisure"="marina"]' in ql
    assert "harbour" not in ql
    assert "seamark" not in ql


def test_element_name_does_not_invent():
    assert mw.element_name({}) == ""
    assert mw.element_name({"leisure": "marina"}) == ""
    assert mw.element_name({"name": "  Marina Rubicon "}) == "Marina Rubicon"


def test_marina_from_overpass_requires_leisure_marina():
    elem = {
        "type": "node", "id": 1, "lat": 46.15, "lon": -1.16,
        "tags": {"name": "Minimes", "leisure": "marina", "website": "https://portlarochelle.com"},
    }
    cand = mw.marina_from_overpass(elem)
    assert cand["osm_id"] == "node/1"
    assert cand["website"] == "https://portlarochelle.com"
    assert cand["name"] == "Minimes"

    harbour = {
        "type": "node", "id": 2, "lat": 46.15, "lon": -1.16,
        "tags": {"name": "Commerce", "harbour": "yes"},
    }
    assert mw.marina_from_overpass(harbour) is None


def test_marina_from_overpass_keeps_unnamed():
    elem = {
        "type": "way", "id": 99, "center": {"lat": 12.0, "lon": -61.0},
        "tags": {"leisure": "marina"},
    }
    cand = mw.marina_from_overpass(elem)
    assert cand["osm_id"] == "way/99"
    assert cand["name"] == ""


def test_slim_geojson_has_maps_url_not_route_fields():
    docs = [{
        "_id": "node/1",
        "osm_id": "node/1",
        "name": "Minimes",
        "lat": 46.14639,
        "lon": -1.16278,
        "source": "openstreetmap",
        "website": "https://portlarochelle.com",
        "website_status": "unchecked",
        "nearest_waypoint": {"name": "should-not-leak"},
        "priority": 1,
        "tags": {"website": "https://portlarochelle.com"},
    }]
    fc = mw.marinas_to_slim_geojson(docs)
    assert fc["type"] == "FeatureCollection"
    assert "ODbL" in fc["attribution"]
    p = fc["features"][0]["properties"]
    assert p["maps_url"].startswith("https://www.google.com/maps/search/")
    assert p["website"] == "https://portlarochelle.com"
    assert "priority" not in p
    assert "nearest_waypoint" not in p
    assert "tags" not in p
    assert "canal_vhf" not in p


def test_website_fallback_from_tags():
    doc = {
        "_id": "n/2", "lat": 1.0, "lon": 2.0, "name": "X",
        "tags": {"contact:website": "https://example.org"},
    }
    feat = mw.slim_feature(doc)
    assert feat["properties"]["website"] == "https://example.org"


def test_upsert_preserves_enrichment_and_locked_website():
    coll = _FakeColl([{
        "_id": "old-uuid",
        "osm_id": "node/1",
        "name": "Old",
        "lat": 46.0,
        "lon": -1.0,
        "canal_vhf": "9",
        "enriched": True,
        "website": "https://official.example",
        "website_status": "osm_ok",
        "website_source": "osm_tag",
    }])
    cand = {
        "osm_id": "node/1",
        "name": "Port des Minimes",
        "lat": 46.14639,
        "lon": -1.16278,
        "tags": {"website": "https://stale.example"},
        "website": "https://stale.example",
    }
    result = asyncio.run(mw.upsert_world_marina(coll, cand, "2026-09-07T00:00:00Z"))
    assert result == "updated"
    doc = coll.docs[0]
    assert doc["_id"] == "old-uuid"
    assert doc["name"] == "Port des Minimes"
    assert doc["canal_vhf"] == "9"
    assert doc["enriched"] is True
    assert doc["website"] == "https://official.example"
    assert doc["website_status"] == "osm_ok"


def test_upsert_inserts_with_osm_id_as_id():
    coll = _FakeColl()
    cand = {
        "osm_id": "way/7",
        "name": "Rodney Bay",
        "lat": 14.075,
        "lon": -60.947,
        "tags": {},
        "website": None,
    }
    result = asyncio.run(mw.upsert_world_marina(coll, cand, "2026-09-07T00:00:00Z"))
    assert result == "inserted"
    assert coll.docs[0]["_id"] == "way/7"
    assert coll.docs[0]["website_status"] is None
    assert "priority" not in coll.docs[0]
    assert "nearest_waypoint" not in coll.docs[0]


def test_build_world_is_resumable_and_does_not_purge():
    curated = {
        "_id": "curated-1",
        "name": "Seed",
        "lat": 16.0,
        "lon": -61.0,
        "source": "curated",
        "osm_id": None,
    }
    marinas = _FakeColl([curated])
    cursor = _FakeColl()
    tile_a = (-60.0, -180.0, -15.0, -90.0)
    tile_b = (-60.0, -90.0, -15.0, 0.0)
    calls = {"n": 0}

    async def fetch(_client, tile):
        calls["n"] += 1
        if tile == tile_a:
            return [{
                "type": "node", "id": 10, "lat": -20.0, "lon": -150.0,
                "tags": {"leisure": "marina", "name": "Papeete"},
            }]
        return [{
            "type": "node", "id": 11, "lat": -22.0, "lon": -45.0,
            "tags": {"leisure": "marina", "name": "Rio"},
        }]

    state = BuildState()
    summary1 = asyncio.run(mw.build_world_marinas(
        marinas_coll=marinas,
        cursor_coll=cursor,
        state=state,
        resume=True,
        tiles=(tile_a, tile_b),
        throttle_s=0,
        fetch_tile=fetch,
    ))
    assert summary1["inserted"] == 2
    assert summary1["tiles_skipped"] == 0
    assert any(d.get("source") == "curated" for d in marinas.docs)
    first_calls = calls["n"]

    state2 = BuildState()
    summary2 = asyncio.run(mw.build_world_marinas(
        marinas_coll=marinas,
        cursor_coll=cursor,
        state=state2,
        resume=True,
        tiles=(tile_a, tile_b),
        throttle_s=0,
        fetch_tile=fetch,
    ))
    assert summary2["tiles_skipped"] == 2
    assert calls["n"] == first_calls
    assert any(d.get("source") == "curated" for d in marinas.docs)


def test_overpass_throttle_is_catalogued():
    reload_catalog()
    assert catalog_default("marinas.overpass_throttle_s") == mw.OVERPASS_THROTTLE_S
