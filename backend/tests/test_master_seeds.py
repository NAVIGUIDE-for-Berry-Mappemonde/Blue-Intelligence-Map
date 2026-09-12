"""MasterSeeds élargis (CDC C5) + Follow the Money (plafond = nouveautés seulement)."""
import asyncio
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "bi_test_master_seeds")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import master_seeds as ms
from app.services.swarm_pipeline import Swarm
from app.static_data.seeds import CURATED_SEEDS, MASTER_SEEDS, TEST_SEED_COUNT
from tests.test_project_runs import _FakeDB


CURATED = [
    {"name": "Blue Marine Foundation", "url": "https://www.bluemarinefoundation.com/projects/",
     "country": "UK", "category": "Conservation", "aliases": []},
    {"name": "Rare Fish Forever", "url": "https://rare.org/program/fish-forever/",
     "country": "US", "category": "Fisheries", "aliases": ["Rare"]},
]


def test_unknown_funder_is_not_a_seed():
    projects = [
        {"url": "https://a.org/p", "funders": ["Unknown"]},
        {"url": "https://saveourseas.com/x", "funders": ["Save Our Seas Foundation"]},
        {"url": "https://saveourseas.com/y", "funder": "Save Our Seas Foundation"},
    ]
    seeds = ms.build_v1_seeds(projects)
    names = {s["name"] for s in seeds}
    assert "Unknown" not in names
    sos = next(s for s in seeds if s["name"] == "Save Our Seas Foundation")
    assert sos["url"] == "https://saveourseas.com/"
    assert sos["project_count"] == 2


def test_listing_url_prefers_funder_domain():
    urls = [
        "https://news.example.com/a",
        "https://news.example.com/b",
        "https://saveourseas.com/project/1",
    ]
    listing = ms.listing_url_from_project_urls(urls, "Save Our Seas Foundation")
    assert listing == "https://saveourseas.com/"


def test_merge_curated_alias_no_priority():
    v1 = [
        {"name": "Rare", "url": "https://rare.org/", "project_count": 12, "listing_kind": "homepage"},
        {"name": "Save Our Seas Foundation", "url": "https://saveourseas.com/",
         "project_count": 40, "listing_kind": "homepage"},
    ]
    merged = ms.merge_curated(v1, CURATED)
    by = {s["name"]: s for s in merged}
    assert "priority" not in by["Rare Fish Forever"]
    assert by["Rare Fish Forever"]["source"] == "curated"
    assert by["Rare Fish Forever"]["url"].startswith("https://rare.org/")
    assert by["Rare Fish Forever"]["project_count"] == 12
    assert "Rare" not in by
    assert "priority" not in by["Save Our Seas Foundation"]
    assert by["Save Our Seas Foundation"]["source"] == "v1"
    assert "priority" not in by["Blue Marine Foundation"]


def test_seeds_for_run_skips_empty_url_and_ignores_legacy_priority():
    seeds = [
        {"name": "P2-big", "url": "https://b.org/", "priority": 2, "project_count": 99},
        {"name": "P1", "url": "https://a.org/", "priority": 1, "project_count": 1},
        {"name": "NoURL", "url": None, "priority": 2, "project_count": 50},
        {"name": "Alpha", "url": "https://z.org/", "project_count": 0},
    ]
    queued = ms.seeds_for_run(seeds)
    assert [s["name"] for s in queued] == ["Alpha", "P1", "P2-big"]


def test_dump_and_load_strip_legacy_priority(tmp_path):
    path = tmp_path / "master_seeds.json"
    ms.dump_master_seeds(
        [{"name": "X", "url": "https://x.org/", "priority": 1, "project_count": 3}],
        path,
        source="test",
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "priority" not in data["seeds"][0]
    loaded = ms.load_master_seeds(path)
    assert "priority" not in loaded[0]
    assert loaded[0]["name"] == "X"


def test_build_master_seeds_from_geojson_style_funder_string():
    projects = [
        {"url": "https://oceanfdn.org/p1", "funder": "The Ocean Foundation"},
        {"url": "https://sos.org/p2", "funder": "Save Our Seas Foundation"},
    ]
    merged = ms.build_master_seeds(projects, CURATED_SEEDS)
    assert any(s["name"] == "The Ocean Foundation" and s["source"] == "curated" for s in merged)
    assert any(s["name"] == "Save Our Seas Foundation" for s in merged)


def test_loaded_catalog_has_v1_scale():
    assert TEST_SEED_COUNT == 3
    assert len(CURATED_SEEDS) == 21
    assert CURATED_SEEDS[0]["name"] == "The Ocean Foundation"
    # Sans JSON : repli 21. Avec JSON généré : ~861.
    assert len(MASTER_SEEDS) >= 700
    assert all("priority" not in s for s in MASTER_SEEDS)
    assert all("priority" not in s for s in CURATED_SEEDS)


def test_follow_the_money_caps_only_new_orgs():
    async def run():
        sw = Swarm(_FakeDB())
        sw.running = True
        sw.settings = {"follow_the_money": True, "max_partner_orgs": 1}
        sw.master_seeds = [
            {"name": "Rare Fish Forever", "url": "https://rare.org/program/fish-forever/",
             "aliases": ["Rare"]},
        ]
        sw.partner_domains = {"bluemarinefoundation.com"}
        sw.new_partner_count = 0
        sw.recursive_tasks = []
        discovered = []

        async def fake_discover(seed, max_urls, depth=0):
            discovered.append(seed["url"])

        sw._discover = fake_discover

        sw._queue_partner("Rare", "https://rare.org/our-work/")
        sw._queue_partner("Wild Oysters", "https://wild-oysters.org/")
        sw._queue_partner("Another New", "https://brand-new.example/")
        await asyncio.sleep(0)

        assert "https://rare.org/our-work/" in discovered
        assert "https://wild-oysters.org/" in discovered
        assert "https://brand-new.example/" not in discovered
        assert sw.new_partner_count == 1
        extras = sw.db.master_seeds.docs
        assert any(d.get("domain") == "wild-oysters.org" for d in extras)
        assert all("priority" not in d for d in extras)

    asyncio.run(run())


def test_follow_the_money_resolves_name_without_url():
    async def run():
        sw = Swarm(_FakeDB())
        sw.running = True
        sw.settings = {"follow_the_money": True, "max_partner_orgs": 0}
        sw.master_seeds = [
            {"name": "Rare Fish Forever", "url": "https://rare.org/program/fish-forever/",
             "aliases": ["Rare"]},
        ]
        sw.partner_domains = set()
        sw.recursive_tasks = []
        discovered = []

        async def fake_discover(seed, max_urls, depth=0):
            discovered.append((seed["name"], seed["url"]))

        sw._discover = fake_discover
        sw._follow_the_money({"partners": [{"name": "Rare", "url": None}]}, depth=0)
        await asyncio.sleep(0)
        assert discovered == [("Rare Fish Forever", "https://rare.org/program/fish-forever/")]
        assert sw.new_partner_count == 0

    asyncio.run(run())


def test_follow_the_money_skips_already_queued_domain():
    sw = Swarm(_FakeDB())
    sw.running = True
    sw.settings = {"follow_the_money": True, "max_partner_orgs": 5}
    sw.master_seeds = []
    sw.partner_domains = {"wild-oysters.org"}
    sw.recursive_tasks = []
    sw._queue_partner("Wild Oysters", "https://wild-oysters.org/tyne/")
    assert sw.recursive_tasks == []
