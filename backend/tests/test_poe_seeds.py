"""Union bottom-up des seeds PoE — sans réseau, sans Mongo."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.listing_ref import project_listing  # noqa: E402
from app.services.poe_seeds import (  # noqa: E402
    attach_listing_other, attach_listing_seeds, attach_osm_priors,
    attach_osm_seeds, build_seed_report, build_seeds_offline,
    format_seed_line, listing_name_seeds, persist_seed_database,
    seed_db_doc, union_extracted, verdict_for_seed,
)

ZONES = [
    {"mrgid": 26518, "name": "Saba", "geoname": "Dutch Exclusive Economic Zone (Saba)",
     "iso2": "BQ", "pol_type": "200NM"},
    {"mrgid": 8447, "name": "Niue", "geoname": "New Zealand Exclusive Economic Zone (Niue)",
     "iso2": "NU", "pol_type": "200NM"},
]


def _listing():
    return {
        "generated_at": "2026-09-06T00:00:00Z",
        "disclaimer": "test",
        "countries": [
            {
                "slug": "saba", "name": "Saba",
                "ports_of_entry": [{"name": "Fort Bay"}],
                "other_ports": [],
            },
            {
                "slug": "niue", "name": "Niue",
                "ports_of_entry": [{"name": "Alofi"}],
                "other_ports": [],
            },
        ],
    }


def _port(mrgid, name, **kw):
    d = {"mrgid": mrgid, "zone_name": kw.pop("zone", "Saba"), "name": name,
         "lat": kw.pop("lat", None), "lon": kw.pop("lon", None)}
    d.update(kw)
    return d


class TestUnionExtracted:
    def test_dedup_keeps_v1_coords_and_unions_sources(self):
        v1 = [_port(26518, "Fort Bay", lat=17.62, lon=-63.25, osm_confidence=0.7)]
        run = [_port(26518, "Fort Bay (Fort Baai)", source_urls=["https://gov.bq/poe"])]
        out = union_extracted([("v1", v1), ("run:x", run)])
        assert len(out) == 1
        p = out[0]
        assert p["lat"] == 17.62
        assert p["osm_confidence"] == 0.7
        assert p["source_urls"] == ["https://gov.bq/poe"]
        assert p["seed_sources"] == ["v1", "run:x"]

    def test_drops_legal_fragments(self):
        junk = [_port(26518, "l'uniforme", note="tournure légale")]
        good = [_port(26518, "Fort Bay")]
        out = union_extracted([("run:x", junk + good)])
        assert [p["name"] for p in out] == ["Fort Bay"]

    def test_second_zone_stays(self):
        a = [_port(26518, "Fort Bay")]
        b = [_port(8447, "Alofi", zone="Niue")]
        out = union_extracted([("v1", a), ("run:y", b)])
        assert {p["name"] for p in out} == {"Fort Bay", "Alofi"}

    def test_same_name_other_zone_is_kept(self):
        a = [_port(26518, "Harbor", zone="Saba")]
        b = [_port(8447, "Harbor", zone="Niue")]
        out = union_extracted([("v1", a + b)])
        assert len(out) == 2
        assert {p["mrgid"] for p in out} == {26518, 8447}


class TestListingSeeds:
    def test_listing_fills_hole_and_attaches_known(self):
        proj = project_listing(_listing(), zones=ZONES, overrides={})
        extracted = union_extracted([("v1", [_port(26518, "Fort Bay", lat=1, lon=2)])])
        packed = attach_listing_seeds(extracted, proj["ports"])
        assert packed["listing_attached"] == 1
        assert len(packed["listing_novel"]) == 1
        assert packed["listing_novel"][0]["name"] == "Alofi"
        assert "listing" in extracted[0]["seed_sources"]

    def test_report_residual_is_geocode_queue(self):
        proj = project_listing(_listing(), zones=ZONES, overrides={})
        extracted = union_extracted([("v1", [_port(26518, "Fort Bay", lat=1, lon=2)])])
        rep = build_seed_report(extracted, proj["ports"])
        assert rep["summary"]["confident"] == 1
        assert rep["summary"]["residual"] == 1
        assert rep["residual"][0]["name"] == "Alofi"
        assert rep["residual"][0]["action"] == "geocode_then_osm"
        assert rep["summary"]["extracted_geocoded"] == 1
        assert rep["summary"]["by_verdict"]["confirmed"] == 1
        assert rep["summary"]["by_verdict"]["name_only"] == 1

    def test_listing_name_seeds_skip_other_ports(self):
        ports = [
            {"name": "Fort Bay", "role": "poe", "mrgid": 26518, "mrgids": [26518]},
            {"name": "Well's", "role": "other", "mrgid": 26518, "mrgids": [26518]},
        ]
        seeds = listing_name_seeds(ports)
        assert [s["name"] for s in seeds] == ["Fort Bay"]


class TestVerdicts:
    def test_listing_and_v1_with_coords_is_confirmed(self):
        seed = _port(26518, "Fort Bay", lat=17.6, lon=-63.2)
        seed["seed_sources"] = ["v1", "listing"]
        seed["has_coords"] = True
        assert verdict_for_seed(seed) == "confirmed"

    def test_listing_only_is_name_only(self):
        seed = listing_name_seeds([
            {"name": "Alofi", "role": "poe", "mrgid": 8447, "mrgids": [8447]},
        ])[0]
        assert verdict_for_seed(seed) == "name_only"

    def test_v1_with_osm_is_probable(self):
        seed = _port(26518, "Fort Bay", lat=17.6, lon=-63.2, osm_confidence=0.7)
        seed["seed_sources"] = ["v1"]
        seed["has_coords"] = True
        assert verdict_for_seed(seed) == "probable"

    def test_v1_alone_is_unverified(self):
        seed = _port(26518, "Fort Bay", lat=17.6, lon=-63.2)
        seed["seed_sources"] = ["v1"]
        seed["has_coords"] = True
        assert verdict_for_seed(seed) == "unverified"

    def test_two_runs_are_probable(self):
        seed = _port(26518, "Fort Bay", lat=17.6, lon=-63.2)
        seed["seed_sources"] = ["run:a", "run:b"]
        seed["has_coords"] = True
        assert verdict_for_seed(seed) == "probable"

    def test_listing_and_osm_with_coords_is_confirmed(self):
        seed = _port(26518, "Fort Bay", lat=17.6, lon=-63.2)
        seed["seed_sources"] = ["osm", "listing"]
        seed["has_coords"] = True
        seed["osm_confidence"] = 0.7
        assert verdict_for_seed(seed) == "confirmed"

    def test_osm_only_high_confidence_is_probable(self):
        seed = _port(26518, "Fort Bay", lat=17.6, lon=-63.2)
        seed["seed_sources"] = ["osm"]
        seed["has_coords"] = True
        seed["osm_confidence"] = 0.7
        assert verdict_for_seed(seed) == "probable"

    def test_osm_only_low_confidence_is_unverified(self):
        seed = _port(26518, "Fort Bay", lat=17.6, lon=-63.2)
        seed["seed_sources"] = ["osm"]
        seed["has_coords"] = True
        seed["osm_confidence"] = 0.35
        assert verdict_for_seed(seed) == "unverified"


class TestOsmUnion:
    def _osm(self, mrgid, name, lat, lon, osm_id, **kw):
        return {
            "osm_id": osm_id,
            "name": name,
            "lat": lat,
            "lon": lon,
            "tags": {"harbour": "yes"},
            "mrgid": mrgid,
            "iso": "BQ",
            "zone_name": "Saba",
            "in_eez": kw.get("in_eez", True),
            "osm_confidence": 0.7,
        }

    def test_osm_merges_by_name_and_creates_orphan(self):
        extracted = union_extracted([
            ("v1", [_port(26518, "Fort Bay", lat=17.62, lon=-63.25)]),
        ])
        stats = attach_osm_seeds(extracted, [
            self._osm(26518, "Fort Bay", 17.621, -63.249, "node/1"),
            self._osm(26518, "Ladder Bay", 17.65, -63.26, "way/2"),
        ])
        assert stats["osm_merged_by_name"] == 1
        assert stats["osm_created"] == 1
        names = {p["name"] for p in extracted}
        assert names == {"Fort Bay", "Ladder Bay"}
        fort = next(p for p in extracted if p["name"] == "Fort Bay")
        assert "osm" in fort["seed_sources"]
        assert "node/1" in fort["osm_ids"]

    def test_osm_merges_by_proximity_without_name_match(self):
        extracted = union_extracted([
            ("v1", [_port(26518, "Fort Bay", lat=17.620, lon=-63.250)]),
        ])
        stats = attach_osm_seeds(extracted, [
            self._osm(26518, "West Quay", 17.6202, -63.2501, "node/9"),
        ])
        assert stats["osm_merged_by_proximity"] == 1
        assert stats["osm_created"] == 0
        assert len(extracted) == 1
        assert "osm" in extracted[0]["seed_sources"]

    def test_unnamed_osm_does_not_create_seed(self):
        extracted = union_extracted([
            ("v1", [_port(26518, "Fort Bay", lat=17.62, lon=-63.25)]),
        ])
        stats = attach_osm_seeds(extracted, [
            self._osm(26518, "", 17.80, -63.10, "node/3"),
        ])
        assert stats["osm_created"] == 0
        assert stats["osm_skipped_unnamed_in_eez"] == 1
        assert len(extracted) == 1

    def test_marina_only_is_not_a_seed(self):
        extracted = union_extracted([
            ("v1", [_port(26518, "Fort Bay", lat=17.62, lon=-63.25)]),
        ])
        marina = self._osm(26518, "Yacht Club", 17.80, -63.10, "node/8")
        marina["tags"] = {
            "leisure": "marina",
            "seamark:type": "harbour",
            "seamark:harbour:category": "marina",
        }
        stats = attach_osm_seeds(extracted, [marina])
        assert stats["osm_created"] == 0
        assert stats["osm_skipped_not_candidate"] == 1
        assert len(extracted) == 1

    def test_listing_intersects_new_osm_seed(self):
        extracted = union_extracted([("v1", [])])
        attach_osm_seeds(extracted, [
            self._osm(26518, "Fort Bay", 17.62, -63.25, "node/1"),
        ])
        proj = project_listing(_listing(), zones=ZONES, overrides={})
        packed = attach_listing_seeds(extracted, proj["ports"])
        assert packed["listing_attached"] == 1
        assert "listing" in extracted[0]["seed_sources"]
        extracted[0]["has_coords"] = True
        assert verdict_for_seed(extracted[0]) == "confirmed"


class TestSeedLineAndListingOther:
    def test_line_keeps_present_tokens_only(self):
        seed = _port(26518, "Fort Bay", lat=17.62, lon=-63.25)
        seed.update({
            "seed_sources": ["v1", "listing"],
            "listing_role": "poe",
            "osm_customs": True,
            "osm_kinds": ["port"],
            "has_coords": True,
            "verify_verdict": "confirmed",
        })
        line = format_seed_line(seed)
        assert line.startswith("Fort Bay | 17.620,-63.250 | ")
        assert "listing:poe" in line
        assert "osm:customs" in line
        assert "osm:port" in line
        assert "runs:1" in line
        assert "listing:other" not in line
        assert "osm:border" not in line

    def test_listing_other_does_not_confirm(self):
        seed = _port(26518, "Well's", lat=17.63, lon=-63.23)
        seed["seed_sources"] = ["v1", "listing"]
        seed["listing_role"] = "other"
        seed["has_coords"] = True
        assert verdict_for_seed(seed) == "unverified"
        assert "listing:other" in format_seed_line(seed)

    def test_listing_other_attaches_to_existing_only(self):
        extracted = union_extracted([
            ("v1", [_port(26518, "Well's Bay", lat=17.63, lon=-63.23)]),
        ])
        ports = [
            {"name": "Fort Bay", "role": "poe", "mrgid": 26518, "mrgids": [26518]},
            {"name": "Well's Bay", "role": "other", "mrgid": 26518, "mrgids": [26518]},
        ]
        n = attach_listing_other(extracted, ports)
        assert n == 1
        assert extracted[0]["listing_role"] == "other"
        assert len(extracted) == 1


class TestOsmPriors:
    def test_marina_near_customs_is_a_seed(self):
        extracted = union_extracted([("v1", [])])
        priors = {
            "ports": [{
                "id": "way/1",
                "name": "Yacht Basin",
                "lat": 17.80,
                "lon": -63.10,
                "kinds": ["marina"],
                "customs": True,
                "border_control": False,
                "port_of_entry": None,
                "eez": [{"mrgid": 26518, "name": "Saba", "iso2": "BQ",
                         "relation": "in_eez"}],
            }],
        }
        stats = attach_osm_priors(extracted, priors)
        assert stats["osm_created"] == 1
        seed = extracted[0]
        assert seed["osm_customs"] is True
        assert "marina" in seed["osm_kinds"]
        assert seed["observations"][0]["origin"] == "osm"
        assert "osm:customs" in format_seed_line(seed)
        assert "osm:marina" in format_seed_line(seed)

    def test_prior_merges_on_v1_name(self):
        extracted = union_extracted([
            ("v1", [_port(26518, "Fort Bay", lat=17.62, lon=-63.25)]),
        ])
        attach_osm_priors(extracted, {
            "ports": [{
                "id": "node/9",
                "name": "Fort Bay",
                "lat": 17.621,
                "lon": -63.249,
                "kinds": ["port"],
                "customs": True,
                "border_control": True,
                "port_of_entry": "yes",
                "eez": [{"mrgid": 26518, "name": "Saba", "iso2": "BQ",
                         "relation": "in_eez"}],
            }],
        })
        assert len(extracted) == 1
        assert extracted[0]["osm_customs"] is True
        assert extracted[0]["osm_border"] is True
        assert extracted[0]["osm_port_of_entry"] == "yes"
        assert "osm" in extracted[0]["seed_sources"]
        assert len(extracted[0]["observations"]) >= 2


class TestSeedDatabase:
    def test_doc_keeps_observations_and_line(self):
        seed = _port(26518, "Fort Bay", lat=17.62, lon=-63.25)
        seed.update({
            "seed_sources": ["v1", "listing", "osm"],
            "listing_role": "poe",
            "has_coords": True,
            "osm_customs": True,
            "observations": [{"source": "run", "origin": "v1", "name": "Fort Bay"}],
            "verify_verdict": "confirmed",
            "dedup_key": "26518:fortbay",
        })
        doc = seed_db_doc(seed, "t")
        assert doc["seed_line"].startswith("Fort Bay")
        assert doc["observations"]
        assert doc["osm_customs"] is True
        assert doc["verify_verdict"] == "confirmed"

    def test_persist_replaces_seed_collection_not_poe_ports(self):
        import asyncio

        class _Coll:
            def __init__(self, docs=None):
                self.docs = list(docs or [])
                self.deleted = 0

            async def create_index(self, *a, **k):
                return None

            async def delete_many(self, q):
                self.deleted += 1
                self.docs = []

            async def insert_many(self, docs):
                self.docs.extend(docs)

        class _DB:
            def __init__(self):
                self.poe_seed_ports = _Coll()
                self.poe_ports = _Coll([{"_id": "v1", "name": "keep"}])

        extracted = union_extracted([
            ("v1", [_port(26518, "Fort Bay", lat=17.62, lon=-63.25)]),
        ])
        proj = project_listing(_listing(), zones=ZONES, overrides={})
        report = build_seed_report(extracted, proj["ports"])
        db = _DB()
        out = asyncio.run(persist_seed_database(db, report))
        assert out["wrote_poe_ports"] is False
        assert out["collection"] == "poe_seed_ports"
        assert out["ports"] == len(report["seeds"])
        assert db.poe_ports.docs == [{"_id": "v1", "name": "keep"}]
        assert db.poe_ports.deleted == 0
        assert db.poe_seed_ports.deleted == 1
        stored = db.poe_seed_ports.docs[0]
        assert stored["seed_line"]
        assert stored["observations"]

    def test_offline_listing_and_priors_union(self):
        proj = project_listing(_listing(), zones=ZONES, overrides={})
        priors = {
            "ports": [{
                "id": "node/1",
                "name": "Fort Bay",
                "lat": 17.62,
                "lon": -63.25,
                "kinds": ["port"],
                "customs": True,
                "border_control": False,
                "port_of_entry": None,
                "eez": [{"mrgid": 26518, "name": "Saba", "iso2": "BQ",
                         "relation": "in_eez"}],
            }],
        }
        report = build_seeds_offline(
            extracted=[], listing_ports=proj["ports"], priors_doc=priors)
        assert report["summary"]["by_verdict"]["confirmed"] == 1
        assert report["summary"]["by_verdict"]["name_only"] == 1
        fort = next(s for s in report["seeds"] if s["name"] == "Fort Bay")
        assert fort["osm_customs"] is True
        assert any(o["origin"] == "listing" for o in fort["observations"])
        assert any(o["origin"] == "osm" for o in fort["observations"])
        assert "listing:poe" in fort["seed_line"]
        assert "osm:customs" in fort["seed_line"]


class TestRealFiles:
    def test_listing_and_osm_priors_build(self):
        report = build_seeds_offline()
        summary = report["summary"]
        assert summary["seed_ports"] > 1500
        assert summary["by_verdict"]["confirmed"] >= 1
        assert summary["by_verdict"]["name_only"] >= 1
        multi = [s for s in report["seeds"] if len(s.get("observations") or []) >= 2]
        assert multi
        sample = multi[0]
        assert sample.get("seed_line")
        assert "is_poe" not in sample
        assert {o.get("source") for o in sample["observations"]} <= {
            "listing", "osm", "run"}
