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


def test_listing_url_skips_shared_hubs():
    urls = [
        "https://oceandecade.org/actions/alpha",
        "https://oceandecade.org/actions/beta",
        "https://oceandecade.org/actions/gamma",
    ]
    assert ms.listing_url_from_project_urls(urls, "BMKG") is None
    mixed = urls + ["https://www.bmkg.go.id/project/1"]
    assert ms.listing_url_from_project_urls(mixed, "BMKG") == "https://bmkg.go.id/"


def test_shared_hub_home_not_for_owner():
    bmkg = {
        "name": "Agency for Meteorology Climatology and Geophysics (BMKG) – Indonesia",
        "url": "https://oceandecade.org/",
    }
    decade = {"name": "Ocean Decade", "url": "https://oceandecade.org/"}
    team = {"name": "Ocean Decade Team", "url": "https://oceandecade.org/"}
    aker = {"name": "Aker Biomarine", "url": "https://hubocean.earth/"}
    hub = {"name": "HUB Ocean, Microsoft, Accenture", "url": "https://hubocean.earth/"}
    own = {"name": "Example Ocean", "url": "https://example.org/"}
    assert ms.is_shared_hub_home(bmkg) is True
    assert ms.is_shared_hub_home(decade) is False
    assert ms.is_shared_hub_home(team) is False
    assert ms.is_shared_hub_home(aker) is True
    assert ms.is_shared_hub_home(hub) is True
    assert ms.is_shared_hub_home(own) is False
    ccc = {
        "name": "California Coastal Commission",
        "url": "https://surfrider.org/",
    }
    surfrider = {
        "name": "Surfrider Foundation",
        "url": "https://surfrider.org/",
    }
    bloom = {
        "name": "Bloomberg Philanthropies",
        "url": "https://archive.oceanx.org/",
    }
    assert ms.is_shared_hub("https://surfrider.org/") is True
    assert ms.is_shared_hub_home(ccc) is True
    assert ms.needs_official_home(ccc) is True
    assert ms.is_shared_hub_home(surfrider) is False
    assert ms.needs_official_home(surfrider) is False
    assert ms.is_shared_hub_home(bloom) is True
    assert "pew" in ms.official_name_tokens("The Pew Charitable Trusts")
    assert "wwf" in ms.official_name_tokens("WWF Oceans")
    assert "msc" in ms.official_name_tokens("MSC Ocean Stewardship Fund")
    assert ms.domain_matches_org("https://www.pew.org/", "The Pew Charitable Trusts")
    assert ms.domain_matches_org(
        "https://www.msc.org/", "MSC Ocean Stewardship Fund") is True
    assert ms.domain_matches_org(
        "https://bluenaturalcapital.org/", "Blue Carbon Accelerator Fund (BCAF)"
    ) is False
    assert ms.official_site_query(bmkg["name"]) == f'"{bmkg["name"]}" official site'
    assert ms.official_site_retry_query(bmkg["name"]) == '"BMKG" official website'
    assert ms.is_publisher_host("https://www.nature.com/articles/x") is True
    assert ms.is_publisher_host("https://www.bmkg.go.id/") is False
    assert "bmkg" in ms.official_name_tokens(bmkg["name"])
    assert ms.domain_matches_org("https://www.bmkg.go.id/", bmkg["name"]) is True
    assert ms.domain_matches_org("bmkg.go.id", bmkg["name"]) is True
    assert ms.domain_matches_org("saveourseas.com", "Save Our Seas Foundation") is True
    assert ms.domain_matches_org("oceans5.org", "Oceans 5") is True
    assert ms.domain_matches_org("oceandecade.org", "Ocean Decade Programme SMARTNET") is False
    assert ms.domain_matches_org("https://www.nature.com/", bmkg["name"]) is False
    assert "awi" in ms.official_name_tokens("Alfred Wegener Institute (AWI)")
    assert "awi" in ms.official_name_tokens("Alfred Wegener Institute")
    assert ms.is_known_funder(
        [decade], "BMKG", "https://oceandecade.org/actions/x") is False
    assert ms.is_known_funder(
        [decade], "Ocean Decade", "https://oceandecade.org/") is True


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


def test_seeds_for_run_only_crawl_ready():
    seeds = [
        {"name": "P2-big", "url": "https://b.org/", "home_status": "official",
         "queue": "crawl", "project_count": 99},
        {"name": "P1", "url": "https://a.org/", "home_status": "official",
         "queue": "crawl", "project_count": 1},
        {"name": "NoURL", "url": None, "home_status": "unknown", "queue": "resolve"},
        {"name": "", "url": None, "project_count": 1},
        {"name": "Alpha", "url": "https://z.org/", "home_status": "official",
         "queue": "crawl"},
        {"name": "BMKG", "url": "https://oceandecade.org/",
         "home_status": "borrowed_hub", "queue": "resolve"},
    ]
    queued = ms.seeds_for_run(seeds)
    assert [s["name"] for s in queued] == ["Alpha", "P1", "P2-big"]


def test_merge_curated_keeps_hosted_on_cordis():
    v1 = [
        {"name": "Horizon Europe", "url": None, "project_count": 24,
         "listing_kind": "unknown", "home_status": "borrowed_hub", "queue": "resolve"},
        {"name": "CORDIS Europe", "url": "https://cordis.europa.eu/", "project_count": 1},
    ]
    curated = [{
        "name": "CORDIS Europe", "url": "https://cordis.europa.eu/projects/en",
        "listing_kind": "projects_index", "aliases": [],
    }]
    merged = ms.merge_curated(v1, curated)
    names = {s["name"] for s in merged}
    assert "CORDIS Europe" in names
    assert "Horizon Europe" in names
    hor = next(s for s in merged if s["name"] == "Horizon Europe")
    assert hor.get("queue") == "resolve"


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
    assert len(MASTER_SEEDS) >= 800
    assert all("priority" not in s for s in MASTER_SEEDS)
    assert all("priority" not in s for s in CURATED_SEEDS)
    queues = {s.get("queue") for s in MASTER_SEEDS}
    assert "crawl" in queues and "resolve" in queues
    crawl = [s for s in MASTER_SEEDS if s.get("queue") == "crawl"]
    # Étape B : homes Search officielles — plus de plafond artificiel < 400.
    assert len(crawl) >= 500
    assert not any((s.get("home_status") or "") == "borrowed_hub" for s in crawl)
    assert sum(
        1 for s in MASTER_SEEDS
        if s.get("home_source") in {"search", "review"}
    ) >= 500


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

        assert "https://rare.org/program/fish-forever/" in discovered
        assert "https://rare.org/our-work/" not in discovered
        assert "https://wild-oysters.org/" in discovered
        assert "https://brand-new.example/" not in discovered
        assert sw.new_partner_count == 1
        extras = sw.db.master_seeds.docs
        assert any(
            d.get("domain") == "wild-oysters.org"
            and d.get("home_status") == "official"
            and d.get("queue") == "crawl"
            for d in extras
        )
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
        await sw._follow_the_money({"partners": [{"name": "Rare", "url": None}]}, depth=0)
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


def test_follow_the_money_skips_exclude_and_catalog_not_ready():
    async def run():
        sw = Swarm(_FakeDB())
        sw.running = True
        sw.settings = {"follow_the_money": True, "max_partner_orgs": 5}
        sw.master_seeds = [{
            "name": "Drake Enterprise Foundation",
            "url": "https://drakespm.com/",
            "home_status": "official",
            "queue": "skip",
            "review_action": "no_projects",
            "listing_kind": "home_only",
            "name_status": "ok",
        }]
        sw.partner_domains = set()
        sw.recursive_tasks = []
        discovered = []

        async def fake_discover(seed, max_urls, depth=0):
            discovered.append(seed["url"])

        sw._discover = fake_discover
        await sw._follow_the_money({
            "partners": [
                {"name": "Unknown", "url": None},
                {"name": "CEA and CNRS", "url": "https://www.cnrs.fr/"},
                {"name": "Drake Enterprise Foundation", "url": "https://drakespm.com/"},
            ],
        }, depth=0)
        await asyncio.sleep(0)
        assert discovered == []
        assert sw.recursive_tasks == []
        assert sw.new_partner_count == 0

    asyncio.run(run())


def test_follow_the_money_queue_rejects_hub_url():
    sw = Swarm(_FakeDB())
    sw.running = True
    sw.settings = {"follow_the_money": True, "max_partner_orgs": 5}
    sw.master_seeds = [
        {"name": "Rare Fish Forever", "url": "https://rare.org/program/fish-forever/",
         "aliases": ["Rare"], "home_status": "official", "queue": "crawl"},
    ]
    sw.partner_domains = set()
    sw.recursive_tasks = []
    sw._queue_partner("BMKG", "https://oceandecade.org/actions/")
    assert sw.recursive_tasks == []
    assert sw.new_partner_count == 0
