"""Union bottom-up des seeds PoE — sans réseau, sans Mongo."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.listing_ref import project_listing  # noqa: E402
from app.services.poe_seeds import (  # noqa: E402
    attach_listing_seeds, build_seed_report, listing_name_seeds,
    union_extracted, verdict_for_seed,
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
