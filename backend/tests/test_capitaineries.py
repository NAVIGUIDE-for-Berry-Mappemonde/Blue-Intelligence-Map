"""Dump mondial capitaineries — OSM harbour_master + overlay SHOM CATSCF=6."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.tasks import BuildState
from app.services import capitainerie_world as cw
from app.services.capitainerie_enrich import (
    allow_web_lookup,
    contact_search_query,
    enrich_capitainerie,
    merge_contact_payload,
    needs_website_enrich,
    rank_enrich_candidates,
)
from app.services import capitainerie_enrich as ce


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.indexes = []
        self.dropped = []

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
        if "$unset" in upd:
            for k in upd["$unset"]:
                doc.pop(k, None)
        return None

    async def update_many(self, q, upd):
        for d in self.docs:
            if self._match_one(d, q or {}):
                if "$set" in upd:
                    d.update(upd["$set"])
                if "$unset" in upd:
                    for k in upd["$unset"]:
                        d.pop(k, None)
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
        self.indexes.append((a, k))
        return None

    async def drop_index(self, name):
        self.dropped.append(name)
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
    assert cand["shom_id"] == "shom:smcfac:smc.1"
    assert cand["source"] == "shom"
    assert cand["canal_vhf"] == "9"
    assert cw.capitainerie_from_shom(feat_marina) is None


def test_shom_buisgl_functn_2():
    feat = {
        "id": "buis.9",
        "geometry": {"type": "Point", "coordinates": [-1.16, 46.15]},
        "properties": {"functn": "2,3", "inform": "Commercial harbour master's office"},
    }
    cand = cw.capitainerie_from_shom(feat, layer="buisgl")
    assert cand is not None
    assert cand["shom_id"] == "shom:buisgl:buis.9"
    assert cand["tags"]["shom:layer"] == "buisgl"
    customs = {
        "id": "buis.3",
        "geometry": {"type": "Point", "coordinates": [-1.16, 46.15]},
        "properties": {"functn": "3"},
    }
    assert cw.capitainerie_from_shom(customs, layer="buisgl") is None
    assert cw.is_buisgl_harbour_master("2")
    assert cw.is_buisgl_harbour_master("2,28")
    assert not cw.is_buisgl_harbour_master("33")


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
    assert "NOAA" in fc["attribution"]


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
    orphan = next(d for d in coll.docs if d.get("_id") == "shom:b")
    assert "osm_id" not in orphan
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
        skip_noaa=True,
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
        skip_noaa=True,
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


def test_rank_enrich_prefers_official_website():
    anon = {"_id": "a", "name": "", "lat": 1, "lon": 1}
    named = {"_id": "b", "name": "Bureau du port", "lat": 1, "lon": 1}
    site = {"_id": "c", "name": "Capitainerie", "website": "https://port.example/", "lat": 1, "lon": 1}
    generic = {"_id": "d", "name": "Capitainerie", "lat": 1, "lon": 1}
    ordered = rank_enrich_candidates([anon, named, site, generic])
    assert [d["_id"] for d in ordered] == ["c", "b", "a", "d"]
    assert allow_web_lookup(site) is True
    assert allow_web_lookup(named) is True
    assert allow_web_lookup(anon) is True
    assert allow_web_lookup(generic) is True
    assert allow_web_lookup({"name": "Capitainerie"}) is False


def test_contact_search_query_uses_gps_for_generic_name():
    q = contact_search_query({"name": "Capitainerie", "lat": 46.1592, "lon": -1.1517})
    assert "46.1592" in q
    assert "-1.1517" in q
    assert "capitainerie" in q.lower()
    named = contact_search_query({
        "name": "Capitainerie des Minimes", "lat": 46.15, "lon": -1.16,
    })
    assert "Minimes" in named


def test_enrich_generic_with_gps_skips_paid_without_pages(monkeypatch):
    async def no_urls(*a, **k):
        return []

    monkeypatch.setattr(ce, "discover_contact_urls", no_urls)
    doc = {"_id": "shom:x", "name": "Capitainerie", "lat": 46.15, "lon": -1.16, "tags": {}}
    assert allow_web_lookup(doc) is True
    result = asyncio.run(enrich_capitainerie(
        doc, openrouter_key="sk-or-fake", tinyfish_key="tf-fake",
    ))
    assert result["_tinyfish_attempted"] is False
    assert result["enrichment_source"] is None


def test_enrich_unnamed_without_coords_skips_web():
    doc = {"_id": "node/9", "name": "", "tags": {}}
    result = asyncio.run(enrich_capitainerie(
        doc, openrouter_key="sk-or-fake", tinyfish_key="tf-fake",
    ))
    assert result["_tinyfish_attempted"] is False
    assert result["enrichment_source"] is None
    assert result["enriched"] is False


def test_clean_phone_prefers_tel_link_and_skips_fax():
    phone, _ = cw.contact_from_text(
        "Fax 05 46 00 00 01 — accueil tel:+33-5-46-41-44-20"
    )
    assert phone and phone.startswith("+33")
    fax_only, _ = cw.contact_from_text("Fax 05 46 00 00 01")
    assert fax_only is None


def test_clean_vhf_accepts_us_and_uk_channels():
    _, vhf = cw.contact_from_text("Harbour master VHF 09 / 68 / 80")
    assert vhf == "9/68/80"
    _, dropped = cw.contact_from_text("channel 99")
    assert dropped is None


def test_noaa_buisgl_area_centroid():
    feat = {
        "id": 77,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-76.48, 38.97], [-76.47, 38.97],
                [-76.47, 38.98], [-76.48, 38.97],
            ]],
        },
        "properties": {
            "FUNCTN": "2,3", "OBJNAM": "Harbor Master",
            "OBJECTID": 77, "INFORM": "VHF 16 / 09 tel 410-263-7973",
        },
    }
    cand = cw.capitainerie_from_noaa(
        feat, service="enc_harbour", layer_id=143, kind="area",
    )
    assert cand is not None
    assert cand["noaa_id"] == "noaa:enc_harbour:area:143:77"
    assert cand["source"] == "noaa"
    assert "Harbor Master" in cand["name"]
    assert cand["canal_vhf"] == "16/9"
    assert cand["telephone"]
    covered = {
        "id": 8,
        "geometry": {"type": "Point", "coordinates": [-76.48, 38.97]},
        "properties": {"FUNCTN": "2", "OBJECTID": 8, "INFORM": "Covered slips"},
    }
    covered_cand = cw.capitainerie_from_noaa(
        covered, service="enc_harbour", layer_id=22, kind="point",
    )
    assert covered_cand["name"] == "Harbour master's office"
    customs = {
        "id": 1,
        "geometry": {"type": "Point", "coordinates": [-76.48, 38.97]},
        "properties": {"FUNCTN": "3", "OBJECTID": 1},
    }
    assert cw.capitainerie_from_noaa(
        customs, service="enc_harbour", layer_id=22, kind="point",
    ) is None


def test_noaa_merges_nearby_and_inserts_orphan():
    osm = {
        "_id": "node/1", "osm_id": "node/1", "name": "Annapolis HM",
        "lat": 38.9780, "lon": -76.4900, "source": "openstreetmap",
        "sources": ["openstreetmap"], "tags": {},
    }
    coll = _FakeColl([osm])
    near = {
        "noaa_id": "noaa:enc_harbour:area:143:1", "name": "Harbor Master",
        "lat": 38.9781, "lon": -76.4901, "tags": {"noaa:functn": "2"},
        "telephone": "410-263-7973", "canal_vhf": "9", "sources": ["noaa"],
    }
    far = {
        "noaa_id": "noaa:enc_harbour:area:143:2", "name": "Baltimore HM",
        "lat": 39.28, "lon": -76.58, "tags": {"noaa:functn": "2"},
        "telephone": None, "canal_vhf": "16", "sources": ["noaa"],
    }
    now = "2026-09-08T00:00:00Z"
    pts = list(coll.docs)
    assert asyncio.run(cw.upsert_noaa(coll, near, now, pts)) == "merged"
    assert "noaa" in coll.docs[0]["source"]
    assert coll.docs[0]["telephone"] == "410-263-7973"
    assert asyncio.run(cw.upsert_noaa(coll, far, now, pts)) == "inserted"
    orphan = next(d for d in coll.docs if d.get("_id") == "noaa:enc_harbour:area:143:2")
    assert "osm_id" not in orphan
    assert orphan["source"] == "noaa"


def test_build_noaa_overlay(monkeypatch):
    coll = _FakeColl([{
        "_id": "node/11", "osm_id": "node/11", "name": "La Rochelle",
        "lat": 46.15, "lon": -1.16, "source": "openstreetmap",
        "sources": ["openstreetmap"], "tags": {},
    }])
    cursor = _FakeColl([{"_id": cw.CURSOR_ID, "done_tiles": ["t"]}])

    async def fetch(_client, tile):
        return []

    async def fetch_shom(_client, bbox):
        return []

    async def fetch_noaa(_client):
        return [{
            "noaa_id": "noaa:enc_harbour:area:143:9",
            "name": "Harbor Master Annapolis",
            "lat": 38.9784, "lon": -76.4845,
            "tags": {"noaa:functn": "2"},
            "telephone": None, "canal_vhf": "9", "sources": ["noaa"],
        }]

    state = BuildState()
    summary = asyncio.run(cw.build_world_capitaineries(
        coll=coll, cursor_coll=cursor, state=state, resume=True,
        tiles=(), throttle_s=0,
        fetch_tile=fetch, fetch_shom=fetch_shom, fetch_noaa=fetch_noaa,
        skip_shom=True,
    ))
    assert summary["noaa"]["inserted"] == 1
    assert any(d.get("noaa_id") == "noaa:enc_harbour:area:143:9" for d in coll.docs)


def test_enrich_regex_from_fetch_skips_llm(monkeypatch):
    async def urls(*a, **k):
        return ["https://port.example/capitainerie"]

    async def pages(u, tinyfish_key=None, logger=None):
        return [{
            "url": u[0], "title": "Port",
            "text": "Capitainerie tél. 05 46 41 44 20 — VHF 9 / 16",
        }]

    async def must_not_muse(*a, **k):
        raise AssertionError("Muse should not run when regex is complete")

    async def must_not_or(*a, **k):
        raise AssertionError("OpenRouter should not run when regex is complete")

    monkeypatch.setattr(ce, "discover_contact_urls", urls)
    monkeypatch.setattr(ce, "fetch_contact_pages", pages)
    monkeypatch.setattr(ce, "enrich_via_nvidia", must_not_muse)
    monkeypatch.setattr(ce, "enrich_via_openrouter", must_not_or)
    doc = {
        "_id": "node/1", "name": "Capitainerie des Minimes",
        "lat": 46.15, "lon": -1.16, "tags": {},
    }
    result = asyncio.run(enrich_capitainerie(
        doc, tinyfish_key="tf", openrouter_key="or",
        settings={"nvidia_api_key": "nv"},
    ))
    assert result["enrichment_source"] == "fetch"
    assert result["telephone"]
    assert result["canal_vhf"] == "9/16"
    assert result["_tinyfish_attempted"] is False


def test_enrich_nvidia_before_openrouter(monkeypatch):
    order = []

    async def urls(*a, **k):
        return ["https://port.example/hm"]

    async def pages(u, tinyfish_key=None, logger=None):
        return [{"url": u[0], "title": "HM", "text": "The harbour office is open daily."}]

    async def nvidia(*a, **k):
        order.append("nvidia")
        return {"telephone": "+33 5 46 00 00 00", "canal_vhf": "9",
                "_engine": "nvidia-deepseek"}

    async def openrouter(*a, **k):
        order.append("openrouter")
        return {"telephone": "should-not-win", "canal_vhf": "16"}

    monkeypatch.setattr(ce, "discover_contact_urls", urls)
    monkeypatch.setattr(ce, "fetch_contact_pages", pages)
    monkeypatch.setattr(ce, "enrich_via_nvidia", nvidia)
    monkeypatch.setattr(ce, "enrich_via_openrouter", openrouter)
    doc = {
        "_id": "node/1", "name": "Bureau du port",
        "lat": 46.15, "lon": -1.16, "tags": {},
        "website": "https://port.example/hm",
    }
    result = asyncio.run(enrich_capitainerie(
        doc, tinyfish_key="tf", openrouter_key="or",
        settings={"nvidia_api_key": "nv"},
    ))
    assert order == ["nvidia"]
    assert result["enrichment_source"] == "nvidia-deepseek"
    assert result["telephone"].startswith("+33")
    assert result["canal_vhf"] == "9"
    assert "_engine" not in result


def test_enrich_nvidia_page_chain_not_muse_pin(monkeypatch):
    from app.core import nvidia as nv

    called = {}

    async def urls(*a, **k):
        return ["https://port.example/hm"]

    async def pages(u, tinyfish_key=None, logger=None):
        return [{"url": u[0], "title": "HM", "text": "The harbour office is open daily."}]

    async def tracked(system, prompt, settings=None, *, model=None, role="json", **k):
        called["model"] = model
        called["role"] = role
        return {"telephone": "05 46 41 44 20", "canal_vhf": "9"}, nv.PRIMARY_MODEL

    monkeypatch.setattr(ce, "discover_contact_urls", urls)
    monkeypatch.setattr(ce, "fetch_contact_pages", pages)
    monkeypatch.setattr(nv, "nvidia_enabled", lambda s=None: True)
    monkeypatch.setattr(nv, "complete_json_nvidia_tracked", tracked)
    doc = {
        "_id": "node/1", "name": "Bureau du port",
        "lat": 46.15, "lon": -1.16, "tags": {},
        "website": "https://port.example/hm",
    }
    result = asyncio.run(enrich_capitainerie(
        doc, tinyfish_key=None, openrouter_key=None,
        settings={"nvidia_api_key": "nv"},
    ))
    assert called["role"] == "page"
    assert called["model"] is None
    assert result["enrichment_source"] == "nvidia-deepseek"
    assert result["canal_vhf"] == "9"


def test_enrich_openrouter_after_empty_nvidia(monkeypatch):
    order = []

    async def urls(*a, **k):
        return ["https://port.example/hm"]

    async def pages(u, tinyfish_key=None, logger=None):
        return [{"url": u[0], "title": "HM", "text": "Call the harbour master on channel sixteen."}]

    async def nvidia(*a, **k):
        order.append("nvidia")
        return None

    async def openrouter(*a, **k):
        order.append("openrouter")
        return {"telephone": None, "canal_vhf": "16"}

    monkeypatch.setattr(ce, "discover_contact_urls", urls)
    monkeypatch.setattr(ce, "fetch_contact_pages", pages)
    monkeypatch.setattr(ce, "enrich_via_nvidia", nvidia)
    monkeypatch.setattr(ce, "enrich_via_openrouter", openrouter)
    doc = {
        "_id": "node/1", "name": "Bureau du port",
        "lat": 46.15, "lon": -1.16, "tags": {},
        "website": "https://port.example/hm",
    }
    result = asyncio.run(enrich_capitainerie(
        doc, tinyfish_key="tf", openrouter_key="or",
    ))
    assert order == ["nvidia", "openrouter"]
    assert result["enrichment_source"] == "openrouter"
    assert result["canal_vhf"] == "16"


def test_isolated_unique_indexes_are_partial_not_sparse():
    """Plusieurs OSM sans shom_id dans le même run : pas d'E11000 sur null."""
    coll = _FakeColl()
    asyncio.run(cw.ensure_indexes(coll, isolated=True))
    by_name = {kw.get("name"): kw for _args, kw in coll.indexes if kw.get("name")}
    for field in ("osm_id", "shom_id", "noaa_id"):
        name = f"run_id_1_{field}_1"
        assert name in coll.dropped
        kw = by_name[name]
        assert kw["unique"] is True
        assert "sparse" not in kw
        assert kw["partialFilterExpression"] == {field: {"$type": "string"}}


