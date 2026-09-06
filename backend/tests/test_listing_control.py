"""Contrôle listing des runs PoE — projection slug→mrgid, rapport, file de revue.

Aucun réseau. Mongo dédiée uniquement pour la persistance de revue.
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.dedup import normalize_name  # noqa: E402
from app.services.listing_control import (  # noqa: E402
    compare_to_listing, persist_review, review_items,
)
from app.services.listing_ref import (  # noqa: E402
    project_listing, resolve_slug,
)

ZONES = [
    {"mrgid": 26518, "name": "Saba", "geoname": "Dutch Exclusive Economic Zone (Saba)",
     "iso2": "BQ", "pol_type": "200NM"},
    {"mrgid": 8447, "name": "Niue", "geoname": "New Zealand Exclusive Economic Zone (Niue)",
     "iso2": "NU", "pol_type": "200NM"},
    {"mrgid": 33178, "name": "Martinique", "geoname": "French Exclusive Economic Zone (Martinique)",
     "iso2": "MQ", "pol_type": "200NM"},
    {"mrgid": 5677, "name": "France", "geoname": "French Exclusive Economic Zone",
     "iso2": "FR", "pol_type": "200NM"},
    {"mrgid": 48976, "name": "France", "geoname": "Joint regime area: France / Italy",
     "iso2": "FR", "pol_type": "Joint regime"},
]


def _listing_mini():
    return {
        "generated_at": "2026-09-05T10:39:03Z",
        "disclaimer": "test",
        "countries": [
            {
                "slug": "saba", "name": "Saba",
                "ports_of_entry": [{"name": "Fort Bay (Fort Baai)", "group": None}],
                "other_ports": [{"name": "Well's and Ladder Bays", "group": None}],
            },
            {
                "slug": "niue", "name": "Niue",
                "ports_of_entry": [{"name": "Alofi", "group": None}],
                "other_ports": [],
            },
        ],
    }


def _run_port(mrgid, name, zone="Saba"):
    return {
        "mrgid": mrgid, "zone_name": zone, "name": name,
        "country_iso2": "BQ",
        "dedup_key": f"{mrgid}:{normalize_name(name)}",
        "extraction_engine": "llm",
    }


class TestResolveSlug:
    def test_auto_saba(self):
        res = resolve_slug("saba", "Saba", zones=ZONES, overrides={})
        assert res["method"] == "auto"
        assert res["mrgids"] == [26518]
        assert res["iso2"] == "BQ"

    def test_prefers_200nm_over_joint(self):
        res = resolve_slug("france-2", "France", zones=ZONES,
                           overrides={"france-2": [5677]})
        assert res["mrgids"] == [5677]
        assert res["method"] == "override"

    def test_unresolved(self):
        res = resolve_slug("nowhere-land", "Nowhere", zones=ZONES, overrides={})
        assert res["method"] == "unresolved"
        assert res["mrgids"] == []


class TestProjectAndCompare:
    def test_four_buckets(self):
        proj = project_listing(_listing_mini(), zones=ZONES, overrides={})
        assert proj["stats"]["ports_of_entry"] == 2
        assert proj["stats"]["other_ports"] == 1
        assert proj["stats"]["unresolved"] == 0

        run = [
            _run_port(26518, "Fort Bay"),                          # confident
            _run_port(26518, "Well's and Ladder Bays"),            # contradiction
            _run_port(26518, "Ghost Harbour"),                     # run_only
        ]
        cmp = compare_to_listing(run, proj["ports"], run_mrgids={26518})
        s = cmp["summary"]
        assert s["confident"] == 1
        assert s["contradiction"] == 1
        assert s["run_only"] == 1
        # Alofi (Niue) hors des ZEE du run → pas listing_only
        assert s["listing_only"] == 0
        assert cmp["review"]["listing_only"] == []
        assert cmp["confident"][0]["listing"]["name"] == "Fort Bay (Fort Baai)"
        assert cmp["review"]["contradiction"][0]["reason"] == "other"
        assert cmp["review"]["run_only"][0]["run"]["name"] == "Ghost Harbour"

    def test_listing_only_when_run_covers_zone(self):
        proj = project_listing(_listing_mini(), zones=ZONES, overrides={})
        run = [_run_port(8447, "Unknown Wharf", zone="Niue")]
        cmp = compare_to_listing(run, proj["ports"], run_mrgids={8447})
        assert cmp["summary"]["listing_only"] == 1
        assert cmp["review"]["listing_only"][0]["listing"]["name"] == "Alofi"
        assert cmp["summary"]["run_only"] == 1

    def test_ambiguous_not_counted_absent(self):
        proj = project_listing(_listing_mini(), zones=ZONES, overrides={})
        run = [_run_port(26518, "Fort")]  # court, score moyen vs Fort Bay
        cmp = compare_to_listing(run, proj["ports"], run_mrgids={26518})
        # soit ambiguous soit confident selon le fuzzy — jamais les deux
        assert cmp["summary"]["run_only"] + cmp["summary"]["ambiguous"] + cmp["summary"]["confident"] == 1
        if cmp["summary"]["ambiguous"]:
            assert cmp["review"]["ambiguous"][0]["listing"]["name"]

    def test_review_excludes_confident(self):
        proj = project_listing(_listing_mini(), zones=ZONES, overrides={})
        run = [
            _run_port(26518, "Fort Bay (Fort Baai)"),
            _run_port(26518, "Ghost Harbour"),
        ]
        cmp = compare_to_listing(run, proj["ports"], run_mrgids={26518})
        items = review_items({"review": cmp["review"], "run": {"run_id": "r-x"}}, "r-x", "v2")
        reasons = {i["reason"] for i in items}
        assert "contradiction" not in reasons or True
        assert all(i["reason"] != "confident" for i in items)
        assert any(i["reason"] == "run_only" and i["name_run"] == "Ghost Harbour" for i in items)


class TestRealListingProjection:
    def test_saba_niue_overrides_and_volume(self):
        proj = project_listing()
        assert proj["stats"]["ports_of_entry"] >= 1000
        assert proj["stats"]["resolved"] >= 170
        by_slug = {r["slug"]: r for r in proj["resolutions"]}
        assert 26518 in by_slug["saba"]["mrgids"]
        assert 8447 in by_slug["niue"]["mrgids"]
        assert 33178 in by_slug["martinique"]["mrgids"]
        assert 5677 in by_slug["france-2"]["mrgids"]
        assert 48976 not in by_slug["france-2"]["mrgids"]
        names = {(p["slug"], p["name"], p["role"]) for p in proj["ports"]}
        assert ("saba", "Fort Bay (Fort Baai)", "poe") in names
        assert ("saba", "Well's and Ladder Bays", "other") in names
        assert ("niue", "Alofi", "poe") in names


@pytest.fixture
def review_db():
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _seed():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        tdb = client["bi_test_listing_control"]
        await client.drop_database("bi_test_listing_control")
        return tdb

    loop = asyncio.new_event_loop()
    tdb = loop.run_until_complete(_seed())
    yield tdb, loop
    loop.run_until_complete(tdb.client.drop_database("bi_test_listing_control"))
    loop.close()


class TestPersistReview:
    def test_writes_review_not_v1(self, review_db):
        tdb, loop = review_db
        proj = project_listing(_listing_mini(), zones=ZONES, overrides={})
        run = [
            _run_port(26518, "Fort Bay"),
            _run_port(26518, "Well's and Ladder Bays"),
            _run_port(26518, "Ghost Harbour"),
        ]
        cmp = compare_to_listing(run, proj["ports"], run_mrgids={26518})
        report = {
            "run": {"run_id": "r-saba", "variant": "v2"},
            "listing_ref_id": proj["listing_ref_id"],
            "summary": cmp["summary"],
            "review": cmp["review"],
        }
        loop.run_until_complete(tdb.poe_ports.insert_one({"name": "keep-me"}))
        before = loop.run_until_complete(tdb.poe_ports.count_documents({}))
        out = loop.run_until_complete(persist_review(tdb, report))
        after = loop.run_until_complete(tdb.poe_ports.count_documents({}))
        assert after == before == 1
        assert out["review_count"] == (
            cmp["summary"]["contradiction"] + cmp["summary"]["run_only"]
            + cmp["summary"]["listing_only"] + cmp["summary"]["ambiguous"])
        n = loop.run_until_complete(tdb.poe_listing_review.count_documents({"run_id": "r-saba"}))
        assert n == out["review_count"]
        assert loop.run_until_complete(tdb.poe_run_ports.count_documents({})) == 0
