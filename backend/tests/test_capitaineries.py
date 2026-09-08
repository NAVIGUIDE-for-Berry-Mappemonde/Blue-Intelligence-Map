"""Dump mondial capitaineries — OSM harbour_master + overlay SHOM CATSCF=6."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.tasks import BuildState
from app.services import capitainerie_world as cw
from app.services.capitainerie_enrich import (
    enrich_capitainerie,
    merge_contact_payload,
    needs_website_enrich,
)


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


def test_query_is_harbour_master_only():
    ql = cw.harbour_master_bbox_ql(40.0, -6.0, 52.0, 10.0)
    assert 'nwr["office"="harbour_master"]' in ql
    assert 'nwr["seamark:building:function"="harbour_master"]' in ql
    assert "leisure" not in ql
    assert "marina" not in ql


def test_is_harbour_master():
    assert cw.is_harbour_master({"office": "harbour_master"})
    assert cw.is_harbour_master({"seamark:building:function": "harbour_master"})
    assert cw.is_harbour_master({"harbour": "harbour_master"})
    assert not cw.is_harbour_master({"leisure": "marina"})
    assert not cw.is_harbour_master({"office": "customs"})


def test_from_overpass_requires_harbour_master():
    elem = {
        "type": "node", "id": 1, "lat": 46.15, "lon": -1.16,
        "tags": {
            "name": "Capitainerie des Minimes",
            "office": "harbour_master",
            "phone": "+33 5 46 00 00 00",
            "vhf": "9",
            "website": "https://portlarochelle.com",
        },
    }
    cand = cw.capitainerie_from_overpass(elem)
    assert cand["osm_id"] == "node/1"
    assert cand["telephone"] == "+33 5 46 00 00 00"
    assert cand["canal_vhf"] == "9"
    assert cand["website"] == "https://portlarochelle.com"

    marina = {
        "type": "node", "id": 2, "lat": 46.15, "lon": -1.16,
        "tags": {"name": "Minimes", "leisure": "marina", "phone": "+33 1 00 00 00 00"},
    }
    assert cw.capitainerie_from_overpass(marina) is None


def test_contact_from_inform_text():
    phone, vhf = cw.contact_from_tags({
        "shom:inform": "Contacter la capitainerie VHF 9 / 16 — tél 05 46 41 44 20",
    })
    assert vhf in ("9/16", "9")
    assert phone


def test_comcha_vhf():
    _, vhf = cw.contact_from_tags({"comcha": "09;16"})
    assert vhf == "9/16"


def test_shom_catscf_filter():
    feat_ok = {
        "id": "smc.1",
        "geometry": {"type": "Point", "coordinates": [-1.16, 46.15]},
        "properties": {"catscf": "6", "objnam": "Capitainerie SHOM", "comcha": "09"},
    }
    feat_marina = {
        "id": "smc.2",
        "geometry": {"type": "Point", "coordinates": [-1.16, 46.15]},
        "properties": {"catscf": "3", "objnam": "Marina"},
    }
    cand = cw.capitainerie_from_shom(feat_ok)
    assert cand["shom_id"] == "shom:smc.1"
    assert cand["source"] == "shom"
    assert cand["canal_vhf"] == "9"
    assert cw.capitainerie_from_shom(feat_marina) is None


def test_slim_geojson_exposes_phone_vhf_not_marina_fields():
    docs = [{
        "_id": "node/1", "osm_id": "node/1", "name": "Capitainerie",
        "lat": 46.15, "lon": -1.16, "source": "openstreetmap",
        "telephone": "+33 5 46 00 00 00", "canal_vhf": "9",
        "nearest_waypoint": {"name": "should-not-leak"},
    }]
    fc = cw.to_slim_geojson(docs)
    p = fc["features"][0]["properties"]
    assert p["kind"] == "capitainerie"
    assert p["telephone"].startswith("+33")
    assert p["canal_vhf"] == "9"
    assert "nearest_waypoint" not in p
    assert "ODbL" in fc["attribution"]
    assert "SHOM" in fc["attribution"]


def test_upsert_preserves_phone():
    coll = _FakeColl([{
        "_id": "node/1", "osm_id": "node/1", "name": "Old",
        "lat": 46.0, "lon": -1.0, "telephone": "+33 5 46 00 00 00",
        "enriched": True,
    }])
    cand = {
        "osm_id": "node/1", "name": "Capitainerie des Minimes",
        "lat": 46.15, "lon": -1.16, "tags": {}, "website": None,
        "telephone": None, "canal_vhf": None, "sources": ["openstreetmap"],
    }
    result = asyncio.run(cw.upsert_osm(coll, cand, "2026-09-08T00:00:00Z"))
    assert result == "updated"
    assert coll.docs[0]["telephone"] == "+33 5 46 00 00 00"
    assert coll.docs[0]["enriched"] is True
    assert coll.docs[0]["name"] == "Capitainerie des Minimes"


def test_shom_merges_nearby_osm_and_inserts_orphan():
    osm = {
        "_id": "node/1", "osm_id": "node/1", "name": "Capitainerie OSM",
        "lat": 46.1500, "lon": -1.1600, "source": "openstreetmap",
        "sources": ["openstreetmap"], "tags": {},
    }
    coll = _FakeColl([osm])
    near = {
        "shom_id": "shom:a", "name": "Capitainerie SHOM",
        "lat": 46.1501, "lon": -1.1601, "tags": {"shom:catscf": "6", "shom:comcha": "16"},
        "telephone": None, "canal_vhf": "16", "sources": ["shom"],
    }
    far = {
        "shom_id": "shom:b", "name": "Capitainerie lointaine",
        "lat": 47.2, "lon": -2.0, "tags": {"shom:catscf": "6"},
        "telephone": "02 97 00 00 00", "canal_vhf": None, "sources": ["shom"],
    }
    now = "2026-09-08T00:00:00Z"
    pts = list(coll.docs)
    assert asyncio.run(cw.upsert_shom(coll, near, now, pts)) == "merged"
    assert coll.docs[0]["source"] == "osm+shom"
    assert coll.docs[0]["canal_vhf"] == "16"
    assert coll.docs[0]["shom_id"] == "shom:a"
    assert asyncio.run(cw.upsert_shom(coll, far, now, pts)) == "inserted"
    assert any(d.get("_id") == "shom:b" for d in coll.docs)
    assert any(d.get("source") == "shom" for d in coll.docs)


def test_build_resumable_and_shom_overlay():
    coll = _FakeColl()
    cursor = _FakeColl()
    tile_a = (-60.0, -180.0, -15.0, -90.0)
    tile_b = (-60.0, -90.0, -15.0, 0.0)
    calls = {"n": 0}

    async def fetch(_client, tile):
        calls["n"] += 1
        if tile == tile_a:
            return [{
                "type": "node", "id": 10, "lat": -17.54, "lon": -149.57,
                "tags": {"office": "harbour_master", "name": "Papeete", "phone": "+689 404200"},
            }]
        return [{
            "type": "node", "id": 11, "lat": 46.15, "lon": -1.16,
            "tags": {"seamark:building:function": "harbour_master", "name": "La Rochelle"},
        }]

    async def fetch_shom(_client, bbox):
        return [{
            "shom_id": "shom:lr", "name": "Capitainerie SHOM LR",
            "lat": 46.1502, "lon": -1.1602,
            "tags": {"shom:catscf": "6"},
            "telephone": "05 46 00 00 00", "canal_vhf": "9",
            "sources": ["shom"],
        }]

    state = BuildState()
    summary1 = asyncio.run(cw.build_world_capitaineries(
        coll=coll, cursor_coll=cursor, state=state, resume=True,
        tiles=(tile_a, tile_b), throttle_s=0,
        fetch_tile=fetch, fetch_shom=fetch_shom,
        shom_bboxes=((46.0, -2.0, 47.0, 0.0),),
    ))
    assert summary1["inserted"] == 2
    assert summary1["shom"]["merged"] == 1
    roc = next(d for d in coll.docs if d.get("osm_id") == "node/11")
    assert roc["source"] == "osm+shom"
    assert roc["telephone"] == "05 46 00 00 00"
    first_calls = calls["n"]

    state2 = BuildState()
    summary2 = asyncio.run(cw.build_world_capitaineries(
        coll=coll, cursor_coll=cursor, state=state2, resume=True,
        tiles=(tile_a, tile_b), throttle_s=0,
        fetch_tile=fetch, fetch_shom=fetch_shom,
        shom_bboxes=((46.0, -2.0, 47.0, 0.0),),
    ))
    assert summary2["tiles_skipped"] == 2
    assert calls["n"] == first_calls


def test_all_docs_ignores_motor_subcollection():
    """Motor expose .docs comme sous-collection : ne pas faire list(coll.docs)."""

    class _Cursor:
        def __init__(self, docs):
            self._docs = docs

        async def to_list(self, n):
            return list(self._docs)

    class _MotorLike:
        def __init__(self, docs):
            self._store = docs
            self.docs = object()

        def find(self, q=None, proj=None):
            return _Cursor(self._store)

    coll = _MotorLike([
        {"_id": "node/1", "osm_id": "node/1", "lat": 46.15, "lon": -1.16, "name": "LR"},
    ])
    docs = asyncio.run(cw._all_docs(coll))
    assert len(docs) == 1
    assert docs[0]["osm_id"] == "node/1"


def test_enrich_tags_skip_website():
    doc = {
        "_id": "node/1", "name": "Capitainerie", "lat": 46.15, "lon": -1.16,
        "tags": {"phone": "+33 5 46 00 00 00", "vhf_channel": "9"},
    }
    assert needs_website_enrich(doc) is False
    merged = merge_contact_payload(doc, None)
    assert merged["telephone"]
    assert merged["canal_vhf"] == "9"
    result = asyncio.run(enrich_capitainerie(doc, openrouter_key=None, tinyfish_key=None))
    assert result["enrichment_source"] == "tags"
    assert result["enriched"] is True
    assert result["_tinyfish_attempted"] is False
