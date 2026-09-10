"""Mode Science — moisson catalogues (Sextant/ODATIS/EDMED) + flotteurs Argo."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.run_rules import resolve_rules, snapshot_for_run
from app.core.tasks import BuildState
from app.services import science_build as sb


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def _match_one(self, doc, q):
        for k, v in (q or {}).items():
            if isinstance(v, dict) and "$in" in v:
                if doc.get(k) not in v["$in"]:
                    return False
            elif doc.get(k) != v:
                return False
        return True

    async def find_one(self, q=None, proj=None):
        for d in self.docs:
            if self._match_one(d, q or {}):
                return d
        return None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def update_one(self, q, upd, upsert=False):
        doc = await self.find_one(q)
        if not doc:
            if upsert:
                merged = dict(q or {})
                merged.update(upd.get("$set") or {})
                self.docs.append(merged)
            return None
        doc.update(upd.get("$set") or {})
        return None

    async def create_index(self, *a, **k):
        return None


# ---------------------------------------------------------------------------
# Emprises
# ---------------------------------------------------------------------------

def test_bbox_from_geom_polygon():
    geom = [{"type": "Polygon", "coordinates": [[[3.08, 38.01], [20.11, 38.01],
                                                 [20.11, 45.61], [3.08, 45.61], [3.08, 38.01]]]}]
    assert sb.bbox_from_geom(geom) == (3.08, 38.01, 20.11, 45.61)


def test_bbox_from_geom_antimeridian():
    geom = {"type": "Polygon", "coordinates": [[[170.0, -10.0], [-170.0, -10.0],
                                                [-170.0, 10.0], [170.0, 10.0], [170.0, -10.0]]]}
    w, s, e, n = sb.bbox_from_geom(geom)
    assert (s, n) == (-10.0, 10.0)
    assert e - w == 20.0  # 20° de large, pas 340°


def test_bbox_from_geom_invalid():
    assert sb.bbox_from_geom(None) is None
    assert sb.bbox_from_geom({"type": "Polygon", "coordinates": []}) is None
    assert sb.bbox_from_geom({"type": "Point", "coordinates": [999.0, 12.0]}) is None


def test_bbox_from_wkt_edmed():
    wkt = "POLYGON((-6.78333 49.26667, -4.64649 49.26667, -4.64649 47.30483, -6.78333 47.30483, -6.78333 49.26667))"
    assert sb.bbox_from_wkt(wkt) == (-6.78333, 47.30483, -4.64649, 49.26667)
    assert sb.bbox_from_wkt("POINT(2.5 47.0)") == (2.5, 47.0, 2.5, 47.0)
    assert sb.bbox_from_wkt("") is None
    assert sb.bbox_from_wkt("n/a") is None


def test_global_bbox_not_located():
    assert sb.is_global_bbox((-180.0, -85.0, 180.0, 85.0)) is True
    assert sb.is_global_bbox((-6.8, 47.3, -4.6, 49.3)) is False
    lat, lon = sb.bbox_center((170.0, -10.0, 190.0, 10.0))
    assert lat == 0.0
    assert lon in (180.0, -180.0)


# ---------------------------------------------------------------------------
# GeoNetwork (Sextant / ODATIS)
# ---------------------------------------------------------------------------

def _gn_hit(**over):
    src = {
        "uuid": "abc-123",
        "resourceTitleObject": {"default": "Température de surface Manche"},
        "resourceAbstractObject": {"default": "Jeu de données test."},
        "geom": [{"type": "Polygon", "coordinates": [[[-6.0, 47.0], [-4.0, 47.0],
                                                      [-4.0, 49.0], [-6.0, 49.0], [-6.0, 47.0]]]}],
        "OrgForResource": ["Ifremer"],
        "resourceDate": [{"type": "publication", "date": "2021-05-12T00:00:00Z"}],
        "link": [
            {"protocol": "WWW:LINK", "url": "https://example.org/data.nc"},
            {"protocol": "DOI", "url": "https://doi.org/10.17882/62440"},
        ],
    }
    src.update(over)
    return {"_id": "abc-123", "_source": src}


def test_dataset_from_gn_hit():
    doc = sb.dataset_from_gn_hit(_gn_hit(), "sextant")
    assert doc["_id"] == "sextant:abc-123"
    assert doc["kind"] == "dataset"
    assert doc["name"].startswith("Température")
    assert doc["provider"] == "Ifremer"
    assert doc["doi"] == "https://doi.org/10.17882/62440"
    assert doc["date"] == "2021-05-12"
    assert doc["lat"] == 48.0 and doc["lon"] == -5.0
    assert doc["bbox"] == [-6.0, 47.0, -4.0, 49.0]
    assert "sextant.ifremer.fr" in doc["url"] and "abc-123" in doc["url"]


def test_dataset_from_gn_hit_odatis_portal_url():
    doc = sb.dataset_from_gn_hit(_gn_hit(), "odatis")
    assert doc["_id"] == "odatis:abc-123"
    assert "/geonetwork/ODATIS/" in doc["url"]


def test_dataset_from_gn_hit_requires_title():
    assert sb.dataset_from_gn_hit(_gn_hit(resourceTitleObject={}), "sextant") is None


def test_dataset_from_gn_hit_global_stays_unlocated():
    world = [{"type": "Polygon", "coordinates": [[[-180.0, -85.0], [180.0, -85.0],
                                                  [180.0, 85.0], [-180.0, 85.0], [-180.0, -85.0]]]}]
    doc = sb.dataset_from_gn_hit(_gn_hit(geom=world), "sextant")
    assert doc["lat"] is None and doc["lon"] is None
    assert doc["global"] is True


# ---------------------------------------------------------------------------
# EDMED (SeaDataNet)
# ---------------------------------------------------------------------------

def _edmed_binding(geom=True):
    b = {
        "s": {"type": "uri", "value": "https://edmed.seadatanet.org/report/6944/"},
        "title": {"type": "literal", "value": "HFR surface currents in the Iroise Sea"},
        "desc": {"type": "literal", "value": "Sea surface currents recorded by HF radar."},
    }
    if geom:
        b["geom"] = {"type": "literal", "value": (
            "POLYGON((-6.78333 49.26667, -4.64649 49.26667, -4.64649 47.30483, "
            "-6.78333 47.30483, -6.78333 49.26667))")}
    return b


def test_dataset_from_edmed_binding():
    doc = sb.dataset_from_edmed_binding(_edmed_binding())
    assert doc["_id"] == "edmed:6944"
    assert doc["source"] == "edmed"
    assert doc["url"] == "https://edmed.seadatanet.org/report/6944/"
    assert doc["lat"] is not None and doc["lon"] is not None
    assert doc["abstract"].startswith("Sea surface currents")


def test_dataset_from_edmed_binding_without_geometry():
    doc = sb.dataset_from_edmed_binding(_edmed_binding(geom=False))
    assert doc["lat"] is None and doc["bbox"] is None


# ---------------------------------------------------------------------------
# Argo (index ERDDAP)
# ---------------------------------------------------------------------------

def _argo_table():
    return {
        "columnNames": ["file", "date", "latitude", "longitude", "ocean",
                        "profiler_type", "institution", "date_update"],
        "rows": [
            ["aoml/1901514/profiles/R1901514_538.nc", "2026-08-11T13:23:13Z", 1.626, 44.637, "I", 846, "AO", "2026-08-12T08:00:28Z"],
            ["aoml/1901514/profiles/R1901514_539.nc", "2026-08-21T13:31:00Z", 1.7, 44.9, "I", 846, "AO", "2026-08-22T08:00:00Z"],
            ["coriolis/6904240/profiles/R6904240_101.nc", "2026-09-01T02:00:00Z", 47.5, -8.2, "A", 844, "IF", "2026-09-01T09:00:00Z"],
            ["bad-row", "2026-09-01T02:00:00Z", 91.0, 0.0, "A", 844, "IF", "x"],
        ],
    }


def test_wmo_from_file():
    assert sb.wmo_from_file("aoml/1901514/profiles/R1901514_538.nc") == ("1901514", "aoml", 538)
    assert sb.wmo_from_file("coriolis/6904240/profiles/D6904240_101D.nc") == ("6904240", "coriolis", 101)
    assert sb.wmo_from_file("garbage") == (None, None, None)


def test_argo_docs_latest_position_per_float():
    docs = sb.argo_docs_from_index(_argo_table())
    assert len(docs) == 2
    by_wmo = {d["wmo"]: d for d in docs}
    assert by_wmo["1901514"]["cycle"] == 539            # dernier profil gagne
    assert by_wmo["1901514"]["lat"] == 1.7
    assert by_wmo["1901514"]["provider"] == "AOML (USA)"
    assert by_wmo["1901514"]["ocean"] == "Indian"
    assert by_wmo["6904240"]["url"].endswith("/float/6904240")
    assert all(d["kind"] == "argo_float" for d in docs)


# ---------------------------------------------------------------------------
# CSR (campagnes)
# ---------------------------------------------------------------------------

def _csr_binding(track=True, label="NODSSUM 2026"):
    b = {
        "r": {"value": "https://csr.seadatanet.org/report/21042655"},
        "label": {"value": label},
        "desc": {"value": "Survey in the North Sea."},
        "ship": {"value": "https://vocab.nerc.ac.uk/collection/C17/current/35PK/"},
        "start": {"value": "2026-05-27"},
        "end": {"value": "2026-06-28"},
        "bbox": {"value": "POLYGON((-2 50, 3 50, 3 55, -2 55, -2 50))"},
    }
    if track:
        b["track"] = {"value": "LINESTRING((-1.5 51.2, 0.4 52.1, 1.8 53.0))"}
    return b


def test_subsample_line_keeps_ends():
    pairs = [(float(i), 48.0) for i in range(1000)]
    out = sb.subsample_line(pairs, max_points=160)
    assert len(out) == 160
    assert out[0] == [0.0, 48.0]
    assert out[-1] == [999.0, 48.0]


def test_cruise_from_csr_binding():
    doc = sb.cruise_from_csr_binding(_csr_binding())
    assert doc["_id"] == "csr:21042655"
    assert doc["kind"] == "cruise"
    assert doc["ship"] == "35PK"
    assert doc["start"] == "2026-05-27"
    assert doc["track"][0] == [-1.5, 51.2]
    assert "csr.seadatanet.org/report/21042655" in doc["url"]
    assert doc["lat"] is not None and doc["lon"] is not None


def test_cruise_skips_placeholder_label():
    assert sb.cruise_from_csr_binding(_csr_binding(label="-")) is None


def test_slim_feature_cruise_is_linestring():
    doc = sb.cruise_from_csr_binding(_csr_binding())
    feat = sb.slim_feature(doc)
    assert feat["geometry"]["type"] == "LineString"
    assert feat["properties"]["kind"] == "cruise"
    assert feat["properties"]["ship"] == "35PK"


# ---------------------------------------------------------------------------
# Persistance + GeoJSON
# ---------------------------------------------------------------------------

def test_upsert_science_non_destructive():
    async def run():
        coll = _FakeColl()
        doc = sb.dataset_from_gn_hit(_gn_hit(), "sextant")
        assert await sb.upsert_science(coll, doc, "2026-09-10T00:00:00Z") == "inserted"
        assert await sb.upsert_science(coll, {**doc, "name": "Titre révisé"},
                                       "2026-09-10T01:00:00Z") == "updated"
        assert len(coll.docs) == 1
        assert coll.docs[0]["name"] == "Titre révisé"
        assert coll.docs[0]["fetched_at"] == "2026-09-10T01:00:00Z"
        assert coll.docs[0]["schema"] == sb.SCHEMA
    asyncio.run(run())


def test_upsert_merges_sextant_odatis_twins():
    """Même uuid GeoNetwork via Sextant puis ODATIS → une seule fiche.

    ODATIS est un sous-portail de Sextant : la fiche commune garde l'identité
    (_id, source, url) du portail moissonné en premier, mais son contenu est
    bien rafraîchi.
    """
    async def run():
        coll = _FakeColl()
        sx = sb.dataset_from_gn_hit(_gn_hit(), "sextant")
        od = sb.dataset_from_gn_hit(_gn_hit(), "odatis")
        assert sx["native_id"] == od["native_id"]

        assert await sb.upsert_science(coll, sx, "2026-09-10T00:00:00Z") == "inserted"
        assert await sb.upsert_science(coll, {**od, "name": "Titre ODATIS"},
                                       "2026-09-10T01:00:00Z") == "updated"
        assert len(coll.docs) == 1
        kept = coll.docs[0]
        assert kept["_id"] == "sextant:abc-123"
        assert kept["source"] == "sextant"
        assert kept["url"] == sx["url"]           # lien portail d'origine conservé
        assert kept["name"] == "Titre ODATIS"     # contenu rafraîchi
        assert kept["fetched_at"] == "2026-09-10T01:00:00Z"

        # L'ordre inverse fonctionne aussi (base vide, ODATIS seul coché).
        coll2 = _FakeColl()
        assert await sb.upsert_science(coll2, od, "2026-09-10T00:00:00Z") == "inserted"
        assert await sb.upsert_science(coll2, sx, "2026-09-10T01:00:00Z") == "updated"
        assert len(coll2.docs) == 1
        assert coll2.docs[0]["_id"] == "odatis:abc-123"
    asyncio.run(run())


def test_to_slim_geojson_filters_unlocated():
    located = sb.dataset_from_gn_hit(_gn_hit(), "sextant")
    unlocated = sb.dataset_from_edmed_binding(_edmed_binding(geom=False))
    fc = sb.to_slim_geojson([located, unlocated])
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 1
    props = fc["features"][0]["properties"]
    assert props["id"] == "sextant:abc-123"
    assert props["url"] and props["kind"] == "dataset"
    assert "Sextant" in fc["attribution"]


# ---------------------------------------------------------------------------
# Orchestrateur (fetchers injectés — aucun réseau)
# ---------------------------------------------------------------------------

def test_build_science_all_sources():
    async def run():
        coll = _FakeColl()
        state = BuildState()

        async def fake_gn(client, es_url, frm, size):
            if frm > 0:
                return []
            uuid = "odatis-1" if "ODATIS" in es_url else "sextant-1"
            return [_gn_hit(uuid=uuid)]

        async def fake_edmed(client, limit, offset):
            return [_edmed_binding()] if offset == 0 else []

        async def fake_argo(client, days):
            assert days == 30
            return _argo_table()

        async def fake_csr(client, limit, offset):
            return [_csr_binding()] if offset == 0 else []

        summary = await sb.build_science(
            coll=coll, state=state,
            sources=("sextant", "odatis", "edmed", "argo", "csr"),
            fetch_gn=fake_gn, fetch_edmed=fake_edmed, fetch_argo=fake_argo,
            fetch_csr=fake_csr,
            run_id="test-run",
        )
        assert summary["inserted"] == 6   # 1+1+1+2 argo + 1 csr
        assert summary["updated"] == 0
        assert not state.running and state.progress == 5
        ids = {d["_id"] for d in coll.docs}
        assert {"sextant:sextant-1", "odatis:odatis-1", "edmed:6944",
                "argo:1901514", "argo:6904240", "csr:21042655"} <= ids

        # Relance : tout passe en update, pas de doublon (no purge / upsert).
        state2 = BuildState()
        summary2 = await sb.build_science(
            coll=coll, state=state2,
            sources=("sextant", "odatis", "edmed", "argo", "csr"),
            fetch_gn=fake_gn, fetch_edmed=fake_edmed, fetch_argo=fake_argo,
            fetch_csr=fake_csr,
        )
        assert summary2["inserted"] == 0
        assert summary2["updated"] == 6
        assert len(coll.docs) == 6
    asyncio.run(run())


def test_build_science_source_error_does_not_stop_others():
    async def run():
        coll = _FakeColl()
        state = BuildState()

        async def fake_gn(client, es_url, frm, size):
            raise RuntimeError("catalogue indisponible")

        async def fake_edmed(client, limit, offset):
            return [_edmed_binding()] if offset == 0 else []

        async def fake_argo(client, days):
            return _argo_table()

        summary = await sb.build_science(
            coll=coll, state=state, sources=("sextant", "edmed", "argo"),
            fetch_gn=fake_gn, fetch_edmed=fake_edmed, fetch_argo=fake_argo,
        )
        assert "RuntimeError" in summary["sources"]["sextant"]["error"]
        assert summary["sources"]["edmed"]["inserted"] == 1
        assert summary["sources"]["argo"]["inserted"] == 2
    asyncio.run(run())


# ---------------------------------------------------------------------------
# Règles — mode science enregistré au catalogue
# ---------------------------------------------------------------------------

def test_science_rules_registered():
    resolved = resolve_rules(mode="science")
    chosen = resolved["chosen"]
    assert chosen["science.catalog_max_records"]["value"] == 2000
    assert chosen["science.argo_window_days"]["value"] == 30
    assert chosen["science.csr_max_records"]["value"] == 500
    snap = snapshot_for_run(mode="science", overrides={"science.catalog_max_records": 500})
    assert snap["chosen"]["science.catalog_max_records"]["value"] == 500
    assert snap["hash"]
