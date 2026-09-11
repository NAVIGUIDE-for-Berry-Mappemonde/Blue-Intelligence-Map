"""Mode AMP — URL de visite ≠ site gestionnaire ProtectedSeas."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import amp as amp_svc


POLY = {
    "type": "Polygon",
    "coordinates": [[
        [3.0, 42.0], [3.4, 42.0], [3.4, 42.3], [3.0, 42.3], [3.0, 42.0],
    ]],
}


def _feat(**props):
    base = {
        "SITE_ID": "PS-1",
        "site_name": "Parc marin du cap",
        "url": "https://www.parc-marin.fr",
        "country": "France",
        "designation": "Parc naturel marin",
        "lfp": 3,
        "managing_authority": "OFB",
        "other_helpful_links": "",
    }
    base.update(props)
    return {"type": "Feature", "properties": base, "geometry": POLY}


def test_urls_equivalent_ignores_www_and_slash():
    assert amp_svc.urls_equivalent(
        "https://www.Parc-Marin.fr/visite/",
        "https://parc-marin.fr/visite",
    )
    assert not amp_svc.urls_equivalent(
        "https://parc-marin.fr",
        "https://parc-marin.fr/visite-plaisance",
    )


def test_pick_visit_rejects_manager_homepage():
    url, status = amp_svc.pick_visit_url(
        "https://parc-marin.fr",
        other_helpful_links="https://www.parc-marin.fr/",
    )
    assert url is None
    assert status == "rejected_same_as_manager"


def test_split_protectedseas_website_reads_labeled_urls():
    raw = (
        "Reserve website|https://www.reserves-naturelles.org/cerbere-banyuls; "
        "OFB website|http://www.amp.afbiodiversite.fr/accueil_fr/fiche"
    )
    manager, extras = amp_svc.split_protectedseas_website(raw)
    assert manager == "https://reserves-naturelles.org/cerbere-banyuls"
    assert extras
    assert any("afbiodiversite.fr" in u for u in extras)


def test_pick_visit_prefers_same_host_suburl_from_website_blob():
    url, status = amp_svc.pick_visit_url(
        "https://parcsnaturals.gencat.cat",
        extra_blobs=[
            "https://parcsnaturals.gencat.cat/ca/xarxa-de-parcs/cap-creus/inici/"
        ],
    )
    assert status == "found"
    assert url.endswith("/cap-creus/inici") or "cap-creus/inici" in url
    assert amp_svc.is_manager_suburl(url, "https://parcsnaturals.gencat.cat")
    assert not amp_svc.urls_equivalent(url, "https://parcsnaturals.gencat.cat")


def test_name_matches_requires_distinctive_token():
    assert amp_svc.name_matches(
        "Cap de Creus", "https://parcsnaturals.gencat.cat/cap-creus/normativa")
    assert not amp_svc.name_matches(
        "Cap de Creus", "https://www.mom.gov.sg Visit Singapore")
    assert amp_svc.name_matches(
        "Cerbère-Banyuls", "http://www.amp.afbiodiversite.fr/visite-cerbere")
    assert not amp_svc.name_matches(
        "Aiguamolls de l'Alt Empordà",
        "https://atraques.es/en/guides/free-anchoring-spain-permitted-bays/")


def test_pick_visit_accepts_offhost_extra_when_it_is_not_the_manager():
    url, status = amp_svc.pick_visit_url(
        "https://reserves-naturelles.org/cerbere-banyuls",
        extra_blobs=[
            "Reserve website|https://www.reserves-naturelles.org/cerbere-banyuls; "
            "OFB website|http://www.amp.afbiodiversite.fr/accueil_fr/fiche"
        ],
    )
    assert status == "found"
    assert url == "https://www.amp.afbiodiversite.fr/accueil_fr/fiche" or (
        url and "afbiodiversite.fr" in url)
    assert not amp_svc.urls_equivalent(url, "https://reserves-naturelles.org/cerbere-banyuls")
    assert not amp_svc.is_manager_suburl(url, "https://reserves-naturelles.org/cerbere-banyuls")


def test_attrs_parses_dirty_website_and_keeps_suburl_visit():
    feat = _feat(
        url="MPA Website|https://www.parc-marin.fr",
        other_helpful_links="https://parc-marin.fr/reglementation-plaisance",
    )
    doc = amp_svc.attrs_from_feature(feat)
    assert doc["manager_url"] == "https://parc-marin.fr"
    assert doc["visit_url"] == "https://parc-marin.fr/reglementation-plaisance"
    assert amp_svc.is_manager_suburl(doc["visit_url"], doc["manager_url"])


def test_pick_visit_keeps_distinct_procedure_page():
    url, status = amp_svc.pick_visit_url(
        "https://parc-marin.fr",
        other_helpful_links="See https://parc-marin.fr/reglementation-plaisance",
    )
    assert url == "https://parc-marin.fr/reglementation-plaisance"
    assert status == "found"


def test_discovered_manager_copy_is_rejected():
    url, status = amp_svc.pick_visit_url(
        "https://sanctuary.noaa.gov/channelislands",
        discovered="https://www.sanctuary.noaa.gov/channelislands/",
    )
    assert url is None
    assert status == "rejected_same_as_manager"


def test_attrs_split_manager_and_visit():
    feat = _feat(other_helpful_links="https://parc-marin.fr/entrer")
    doc = amp_svc.attrs_from_feature(feat)
    assert doc["manager_url"] == "https://parc-marin.fr"
    assert doc["visit_url"] == "https://parc-marin.fr/entrer"
    assert doc["visit_url_status"] == "found"
    props = amp_svc.public_properties(doc)
    assert props["manager_url"] != props["visit_url"]


def test_public_properties_never_echo_manager_as_visit():
    doc = amp_svc.attrs_from_feature(_feat())
    doc["visit_url"] = "https://parc-marin.fr"
    doc["visit_url_status"] = "found"
    props = amp_svc.public_properties(doc)
    assert props["manager_url"] == "https://parc-marin.fr"
    assert props["visit_url"] is None
    assert props["visit_url_status"] == "none"


def test_merge_cached_preserves_validated_visit_url():
    incoming = amp_svc.attrs_from_feature(_feat())
    existing = {
        "visit_url": "https://ofb.gouv.fr/amp/cap/visite",
        "visit_url_status": "found",
        "visit_url_source": "manual",
        "enriched_at": "2026-01-01T00:00:00+00:00",
    }
    merged = amp_svc.merge_cached(existing, incoming)
    assert merged["visit_url"] == "https://ofb.gouv.fr/amp/cap/visite"
    assert merged["manager_url"] == "https://parc-marin.fr"
    assert not amp_svc.urls_equivalent(merged["visit_url"], merged["manager_url"])


def test_merge_cached_drops_stale_visit_equal_to_new_manager():
    incoming = amp_svc.attrs_from_feature(_feat(url="https://new-manager.org"))
    existing = {
        "visit_url": "https://new-manager.org",
        "visit_url_status": "found",
        "visit_url_source": "tinyfish",
    }
    merged = amp_svc.merge_cached(existing, incoming)
    assert merged["manager_url"] == "https://new-manager.org"
    assert not amp_svc.urls_equivalent(merged.get("visit_url"), merged["manager_url"])


def test_sanitize_drops_degenerate_arcgis_hole():
    geom = {
        "type": "Polygon",
        "coordinates": [
            [[3.324, 42.325], [3.322, 42.322], [3.318, 42.328], [3.324, 42.325]],
            [[3.324, 42.322], [3.324, 42.322], [3.323, 42.322], [3.324, 42.322]],
        ],
    }
    clean = amp_svc.sanitize_geometry(geom)
    assert clean["type"] == "Polygon"
    assert len(clean["coordinates"]) == 1
    assert amp_svc._ring_ok(clean["coordinates"][0])
    feat = _feat()
    feat["geometry"] = geom
    feat["properties"]["SITE_ID"] = "AIESP236"
    doc = amp_svc.attrs_from_feature(feat)
    assert doc["geometry"]["type"] == "Polygon"
    assert len(doc["geometry"]["coordinates"]) == 1
    assert doc["manager_url"] == "https://parc-marin.fr"


def test_centroid_uses_exterior_not_inland_hole():
    geom = {
        "type": "Polygon",
        "coordinates": [
            [[0.0, 0.0], [4.0, 0.0], [4.0, 1.0], [0.0, 1.0], [0.0, 0.0]],
            [[10.0, 20.0], [10.1, 20.0], [10.1, 20.1], [10.0, 20.1], [10.0, 20.0]],
        ],
    }
    lat, lon = amp_svc._centroid(geom)
    assert lat is not None and lon is not None
    assert 0.0 <= lat <= 1.2
    assert 0.0 <= lon <= 4.2


def test_sanitize_falls_back_to_centroid_point():
    geom = {
        "type": "Polygon",
        "coordinates": [[[3.0, 42.0], [3.0, 42.0], [3.0, 42.0], [3.0, 42.0]]],
    }
    assert amp_svc.sanitize_geometry(geom) is None
    feat = _feat()
    feat["geometry"] = geom
    doc = amp_svc.attrs_from_feature(feat)
    assert doc["geometry"]["type"] == "Point"
    assert doc["lat"] is not None and doc["lon"] is not None


def test_cache_covers_tile_rejects_orphan_sites():
    sites = [{"site_id": "PS-1", "fetched_at": amp_svc.now_iso()}]
    assert amp_svc.cache_covers_tile(sites, None, 30, force=False) is False
    assert amp_svc.cache_covers_tile([], {"fetched_at": amp_svc.now_iso()}, 30, force=False) is False
    assert amp_svc.cache_covers_tile(
        sites, {"fetched_at": amp_svc.now_iso()}, 30, force=True) is False
    assert amp_svc.cache_covers_tile(
        sites, {"fetched_at": amp_svc.now_iso()}, 30, force=False) is True
    assert amp_svc.tile_key((3.1234, 42.1, 3.5, 42.5)) == "3.123,42.100,3.500,42.500"


def test_parse_bbox_and_span():
    box = amp_svc.parse_bbox("3,42,4,43")
    assert box == (3.0, 42.0, 4.0, 43.0)
    assert amp_svc.bbox_span_deg(box) == 1.0


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    async def find_one(self, q, proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return d
        return None

    async def update_one(self, q, upd, upsert=False):
        doc = await self.find_one(q)
        payload = dict(upd.get("$set") or {})
        if not doc:
            if upsert:
                payload.setdefault("_id", q.get("_id") or q.get("site_id"))
                self.docs.append(payload)
            return None
        doc.update(payload)
        return None

    def find(self, q=None, proj=None):
        return self

    def limit(self, n):
        return self

    async def to_list(self, n=None):
        return list(self.docs[:n] if n else self.docs)

    async def count_documents(self, q=None):
        if not q:
            return len(self.docs)
        if "manager_url" in q:
            return sum(1 for d in self.docs if d.get("manager_url"))
        if "visit_url" in q:
            return sum(1 for d in self.docs if d.get("visit_url"))
        return len(self.docs)

    async def create_index(self, *a, **k):
        return None


class _FakeDB:
    def __init__(self):
        self.amp_sites = _FakeColl()


def test_set_visit_url_rejects_manager_copy():
    db = _FakeDB()
    doc = amp_svc.attrs_from_feature(_feat())
    asyncio.run(db.amp_sites.update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True))
    out = asyncio.run(amp_svc.set_visit_url(db, "PS-1", "https://www.parc-marin.fr/"))
    assert out["visit_url"] is None
    assert out["visit_url_status"] == "rejected_same_as_manager"
    assert out["manager_url"] == "https://parc-marin.fr"


def test_set_visit_url_accepts_procedure_page():
    db = _FakeDB()
    doc = amp_svc.attrs_from_feature(_feat())
    asyncio.run(db.amp_sites.update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True))
    out = asyncio.run(amp_svc.set_visit_url(
        db, "PS-1", "https://parc-marin.fr/autorisation-mouillage"))
    assert out["visit_url"] == "https://parc-marin.fr/autorisation-mouillage"
    assert out["visit_url_status"] == "found"
    assert not amp_svc.urls_equivalent(out["visit_url"], out["manager_url"])


def test_to_feature_exposes_two_url_fields():
    doc = amp_svc.attrs_from_feature(_feat(
        other_helpful_links="https://parc-marin.fr/visite"))
    feat = amp_svc.to_feature(doc)
    p = feat["properties"]
    assert p["manager_url"] == "https://parc-marin.fr"
    assert p["visit_url"] == "https://parc-marin.fr/visite"
    assert p["manager_url"] != p["visit_url"]


def test_amp_router_and_legacy_mpa_stay_apart():
    from app.routers import amp as amp_router
    from app.routers import projects as projects_router
    amp_paths = {getattr(r, "path", "") for r in amp_router.router.routes}
    mpa_paths = {getattr(r, "path", "") for r in projects_router.router.routes}
    assert "/api/amp" in amp_paths
    assert "/api/amp/sites/{site_id}/visit-url" in amp_paths
    assert "/api/amp/discover-visit-urls" in amp_paths
    assert "/api/amp/runs" in amp_paths
    assert "/api/export/amp.geojson" in amp_paths
    assert "/api/mpa" in mpa_paths
    gone = [r for r in projects_router.router.routes if getattr(r, "path", "") == "/api/mpa"]
    assert gone and all(getattr(r, "status_code", None) == 410 for r in gone)


def test_apply_protectedseas_attrs_cleans_manager_and_keeps_extras():
    doc = {
        "_id": "PS-1",
        "site_id": "PS-1",
        "manager_url": "https://reserve website|https://www.reserves-naturelles.org/cerbere-banyuls",
        "other_helpful_links": "",
    }
    amp_svc.apply_protectedseas_attrs(doc, {
        "url": (
            "Reserve website|https://www.reserves-naturelles.org/cerbere-banyuls; "
            "OFB website|http://www.amp.afbiodiversite.fr/accueil_fr/fiche"
        ),
        "other_helpful_links": "https://parc.fr/visite",
        "purpose": "Protect seabed.",
    })
    assert doc["manager_url"] == "https://reserves-naturelles.org/cerbere-banyuls"
    assert "afbiodiversite.fr" in doc["ps_website_raw"]
    assert doc["other_helpful_links"] == "https://parc.fr/visite"
    assert doc["purpose"].startswith("Protect")


def test_refresh_protectedseas_attrs_writes_cache():
    docs = [{
        "_id": "PS-1", "site_id": "PS-1", "name": "Cerbère",
        "manager_url": "https://reserve website|https://old.example",
        "other_helpful_links": "",
    }]

    class _Coll:
        def __init__(self):
            self.docs = list(docs)

        async def update_one(self, q, upd, upsert=False):
            self.docs[0].update(upd.get("$set") or {})

    class _DB:
        def __init__(self):
            self.amp_sites = _Coll()

    async def fetch(ids):
        assert ids == ["PS-1"]
        return {"PS-1": {
            "SITE_ID": "PS-1",
            "url": "Reserve website|https://www.reserves-naturelles.org/cerbere-banyuls",
            "other_helpful_links": "https://ofb.gouv.fr/visite-cerbere",
        }}

    db = _DB()
    n = asyncio.run(amp_svc.refresh_protectedseas_attrs(db, docs, fetch_fn=fetch))
    assert n == 1
    assert docs[0]["manager_url"] == "https://reserves-naturelles.org/cerbere-banyuls"
    assert docs[0]["other_helpful_links"] == "https://ofb.gouv.fr/visite-cerbere"
    assert db.amp_sites.docs[0]["other_helpful_links"] == "https://ofb.gouv.fr/visite-cerbere"


def test_refresh_clears_visit_url_that_becomes_the_manager():
    docs = [{
        "_id": "PS-2", "site_id": "PS-2",
        "manager_url": "https://natura 2000|https://natura2000.eea.europa.eu/Natura2000/SDF.aspx",
        "visit_url": "https://natura2000.eea.europa.eu/Natura2000/SDF.aspx",
        "visit_url_status": "found",
        "visit_url_source": "other_helpful_links",
    }]

    class _Coll:
        def __init__(self):
            self.docs = list(docs)

        async def update_one(self, q, upd, upsert=False):
            self.docs[0].update(upd.get("$set") or {})

    class _DB:
        def __init__(self):
            self.amp_sites = _Coll()

    async def fetch(ids):
        return {"PS-2": {
            "url": "Natura 2000|https://natura2000.eea.europa.eu/Natura2000/SDF.aspx",
            "other_helpful_links": "",
        }}

    asyncio.run(amp_svc.refresh_protectedseas_attrs(_DB(), docs, fetch_fn=fetch))
    assert docs[0]["manager_url"] == "https://natura2000.eea.europa.eu/Natura2000/SDF.aspx"
    assert docs[0]["visit_url"] is None
    assert docs[0]["visit_url_status"] == "not_found"
