"""Home → catalogue : filtres, deux Agents TinyFish, pas de dump cache from scratch."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "bi_test_project_listing")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.core.tinyfish import LISTING_SCHEMA, PROJECTS_LISTING_PURPOSE
from app.services.project_listing import (
    apply_learned_listings, filter_listing_urls, infer_listing_from_project_urls,
    is_homepage_url, is_listing_path, is_listing_url, listing_search_query,
    listing_search_retry_query, needs_listing_hop, pick_listing_url,
)
from app.services.swarm_pipeline import Swarm
from app.static_data.seeds import CURATED_SEEDS
from tests.test_project_runs import _FakeDB

HOME = {"name": "Example Ocean", "url": "https://example.org/"}
LISTING = {
    "name": "Example Ocean",
    "url": "https://example.org/projects/",
    "listing_kind": "projects_index",
}


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _no_paid_env(monkeypatch):
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)


def _swarm(settings=None):
    sw = Swarm(_FakeDB())
    sw.running = True
    sw.force_rescan = True
    sw.queue = asyncio.Queue()
    sw.master_seeds = [dict(HOME)]
    sw.settings = {
        "tinyfish_api_key": "tf-test",
        "serper_api_key": "sp-test",
        "allow_tinyfish_agent": True,
        "follow_the_money": True,
        "max_partner_orgs": 5,
        **(settings or {}),
    }
    return sw


async def _queued(sw, seed=HOME, max_urls=6):
    await sw._discover(seed, max_urls)
    await asyncio.sleep(0)
    items = []
    while not sw.queue.empty():
        items.append(sw.queue.get_nowait())
        sw.queue.task_done()
    return items


def test_listing_path_accepts_curated_leaves_rejects_fiches():
    assert is_listing_path("/projects/")
    assert is_listing_path("/hope-spots/")
    assert is_listing_path("/en/where-we-work/")
    assert is_listing_path("/campaigns/")
    assert not is_listing_path("/projects/coral-restore")
    assert not is_listing_path("/")
    assert not is_listing_path("/about")
    assert not is_listing_path("/news/project-launch")
    assert not is_listing_path("/wp-content/uploads/")
    assert is_homepage_url("https://example.org/")
    assert is_homepage_url("https://example.org/en")
    assert not is_homepage_url("https://example.org/projects/")
    assert is_listing_url("https://missionblue.org/hope-spots/")
    assert not is_listing_url("https://example.org/projects/coral-restore")


def test_needs_listing_hop_skips_known_and_curated():
    assert needs_listing_hop(HOME) is True
    assert needs_listing_hop(LISTING) is False
    assert needs_listing_hop({"url": "https://example.org/projects/"}) is False
    rare = next(s for s in CURATED_SEEDS if "rare.org" in s["url"])
    assert needs_listing_hop(rare) is False
    mer = next(s for s in CURATED_SEEDS if "fondationdelamer" in s["url"])
    assert needs_listing_hop(mer) is False


def test_pick_listing_prefers_shortest_index():
    assert pick_listing_url([
        "https://example.org/en/where-we-work/",
        "https://example.org/projects/",
        "https://example.org/projects/coral-restore",
    ]) == "https://example.org/projects/"


def test_filter_listing_same_host_not_fiche_not_home():
    hits = [
        {"url": "https://example.org/"},
        {"url": "https://example.org/projects/coral-restore"},
        {"url": "https://example.org/news/projects"},
        {"url": "https://other.org/projects/"},
        {"url": "https://example.org/projects/"},
        {"url": "https://example.org/hope-spots/"},
    ]
    out = filter_listing_urls(hits, HOME, 5)
    assert out == [
        "https://example.org/projects/",
        "https://example.org/hope-spots/",
    ]
    dropped = filter_listing_urls(
        hits, HOME, 5, exclude_urls=["https://example.org/projects/"])
    assert dropped == ["https://example.org/hope-spots/"]


def test_infer_listing_sos_not_wp_content():
    sos = infer_listing_from_project_urls([
        "https://saveourseas.com/project/alpha",
        "https://saveourseas.com/project/beta",
    ], "Save Our Seas Foundation")
    assert sos == "https://saveourseas.com/project/"
    junk = infer_listing_from_project_urls([
        "https://blueactionfund.org/wp-content/uploads/a.pdf",
        "https://blueactionfund.org/wp-content/uploads/b.pdf",
    ], "Blue Action Fund")
    assert junk is None


def test_apply_learned_listings_overlays_v1_home():
    seeds = [
        {"name": "Example Ocean", "url": "https://example.org/", "listing_kind": "homepage"},
    ]
    extras = [{
        "name": "Example Ocean", "url": "https://example.org/projects/",
        "domain": "example.org", "listing_kind": "projects_index",
    }]
    out = apply_learned_listings(seeds, extras)
    assert out[0]["url"] == "https://example.org/projects/"
    assert out[0]["listing_kind"] == "projects_index"
    assert needs_listing_hop(out[0]) is False


def test_listing_search_query_is_single_shot_site():
    q = listing_search_query(HOME)
    assert q.startswith("site:example.org")
    assert "listing" in q
    retry = listing_search_retry_query(HOME)
    assert "inurl:projects" in retry
    assert retry != q


def test_known_listing_skips_listing_agent(monkeypatch):
    sw = _swarm()
    listing_agent = {"n": 0}

    async def fake_crawl(seed, max_urls):
        return ["https://example.org/projects/coral"]

    async def boom_listing(*a, **k):
        listing_agent["n"] += 1
        return None

    async def boom(*a, **k):
        raise AssertionError("search/fetch should not run")

    monkeypatch.setattr(sw, "_crawl_discover", fake_crawl)
    monkeypatch.setattr(sw, "_tinyfish_listing_discover", boom_listing)
    monkeypatch.setattr(sw, "_resolve_listing", boom)
    import app.services.swarm_pipeline as sp
    monkeypatch.setattr(sp, "tf_fetch", boom)
    monkeypatch.setattr(sp, "tf_search", boom)

    queued = _run(_queued(sw, LISTING))
    assert [i["url"] for i in queued] == ["https://example.org/projects/coral"]
    assert listing_agent["n"] == 0
    assert sw.db.projects.docs == []
    assert sw.wrote_projects is False


def test_home_n1_finds_listing_then_fiches(monkeypatch):
    sw = _swarm()
    seen = {"listing_agent": 0, "fiche_agent": 0, "search": 0}

    async def fake_listing_crawl(seed, max_urls=5):
        assert seed["url"] == "https://example.org/"
        return ["https://example.org/projects/"]

    async def fake_fiche_crawl(seed, max_urls):
        assert seed["url"] == "https://example.org/projects/"
        return ["https://example.org/projects/coral"]

    async def boom_listing(*a, **k):
        seen["listing_agent"] += 1
        return None

    async def boom_fiche(*a, **k):
        seen["fiche_agent"] += 1
        return []

    async def track_search(*a, **k):
        seen["search"] += 1
        return []

    monkeypatch.setattr(sw, "_crawl_listing", fake_listing_crawl)
    monkeypatch.setattr(sw, "_crawl_discover", fake_fiche_crawl)
    monkeypatch.setattr(sw, "_tinyfish_listing_discover", boom_listing)
    monkeypatch.setattr(sw, "_tinyfish_discover", boom_fiche)
    import app.services.swarm_pipeline as sp
    monkeypatch.setattr(sp, "tf_fetch", track_search)
    monkeypatch.setattr(sp, "tf_search", track_search)
    monkeypatch.setattr(sp, "serper_search", track_search)

    queued = _run(_queued(sw, HOME))
    assert [i["url"] for i in queued] == ["https://example.org/projects/coral"]
    assert seen == {"listing_agent": 0, "fiche_agent": 0, "search": 0}
    assert queued[0]["source"] == "https://example.org/projects/"
    remembered = sw.db.master_seeds.docs
    assert any(d.get("listing_kind") == "projects_index" for d in remembered)
    assert any(d.get("url") == "https://example.org/projects/" for d in remembered)
    assert sw.db.projects.docs == []


def test_listing_search_retry_blacklists_eliminated(monkeypatch):
    sw = _swarm()
    queries = []

    async def none(*a, **k):
        return None

    async def empty_list(*a, **k):
        return []

    async def fake_tf(query, key, **kw):
        queries.append(("tf", query, kw.get("purpose")))
        if "inurl:projects" in query:
            return [{"url": "https://example.org/projects/"}]
        return [
            {"url": "https://example.org/news/project-launch"},
            {"url": "https://example.org/about"},
        ]

    async def fake_sp(query, key, **kw):
        queries.append(("sp", query))
        return [{"url": "https://example.org/donate"}]

    async def fake_fiche_crawl(seed, max_urls):
        assert seed["url"] == "https://example.org/projects/"
        return ["https://example.org/projects/coral"]

    monkeypatch.setattr(sw, "_crawl_listing", empty_list)
    monkeypatch.setattr(sw, "_fetch_listing", empty_list)
    monkeypatch.setattr(sw, "_infer_listing_from_live", none)
    monkeypatch.setattr(sw, "_crawl_discover", fake_fiche_crawl)
    monkeypatch.setattr(sw, "_tinyfish_listing_discover", empty_list)
    monkeypatch.setattr(sw, "_tinyfish_discover", empty_list)
    import app.services.swarm_pipeline as sp
    monkeypatch.setattr(sp, "tf_search", fake_tf)
    monkeypatch.setattr(sp, "serper_search", fake_sp)

    queued = _run(_queued(sw, HOME))
    assert [i["url"] for i in queued] == ["https://example.org/projects/coral"]
    tf_calls = [x for x in queries if x[0] == "tf"]
    assert len(tf_calls) >= 2
    assert tf_calls[0][2] == PROJECTS_LISTING_PURPOSE
    assert "inurl:projects" in tf_calls[1][1]
    assert sw._serper_queries >= 2
    assert sw.db.projects.docs == []


def test_two_distinct_tinyfish_agents(monkeypatch):
    sw = _swarm()
    calls = []

    async def empty(*a, **k):
        if k.get("log") or True:
            return []
        return []

    async def empty_search(*a, **k):
        return [], 0, 0

    async def fake_sse(url, goal, schema, key, **kw):
        calls.append({
            "url": url,
            "goal": goal,
            "required": schema.get("required"),
            "cfg": kw.get("agent_config") or {},
        })
        if schema is LISTING_SCHEMA or schema.get("required") == ["listing_url"]:
            return {"listing_url": "https://example.org/projects/", "title": "Projects"}
        return {"projects": [
            {"url": "https://example.org/projects/coral", "title": "Coral"},
        ]}

    monkeypatch.setattr(sw, "_crawl_listing", empty)
    monkeypatch.setattr(sw, "_fetch_listing", empty)
    monkeypatch.setattr(sw, "_infer_listing_from_live", empty)
    monkeypatch.setattr(sw, "_search_listing", empty_search)
    monkeypatch.setattr(sw, "_crawl_discover", empty)
    monkeypatch.setattr(sw, "_fetch_discover", empty)
    monkeypatch.setattr(sw, "_search_discover", empty_search)
    import app.services.swarm_pipeline as sp
    monkeypatch.setattr(sp, "tf_run_sse", fake_sse)

    queued = _run(_queued(sw, HOME))
    assert [i["url"] for i in queued] == ["https://example.org/projects/coral"]
    assert len(calls) == 2
    assert calls[0]["required"] == ["listing_url"]
    assert "listing agent" in calls[0]["goal"].lower()
    assert "do not collect individual" in calls[0]["goal"].lower()
    assert calls[0]["url"] == "https://example.org/"
    assert calls[1]["required"] == ["projects"]
    assert "one individual" in calls[1]["goal"].lower()
    assert calls[1]["url"] == "https://example.org/projects/"
    assert calls[0]["cfg"].get("max_duration_seconds") == 180
    assert calls[1]["cfg"].get("max_duration_seconds") == 300
    assert LISTING_SCHEMA["required"] == ["listing_url"]
    assert sw.db.projects.docs == []
    assert sw.wrote_projects is False
    msgs = " ".join(e["msg"] for e in sw.logs)
    assert "TinyFish Agent listing" in msgs
    assert "TinyFish Agent fiches" in msgs
    assert "Search vide → TinyFish Agent" not in msgs


def test_filtered_search_log_is_not_empty_search(monkeypatch, tmp_path):
    from app.services import run_journal
    monkeypatch.setattr(run_journal, "RUNS_DIR", tmp_path)
    sw = _swarm()
    sw.run_id = "20260912-221000-lst01"

    async def empty(*a, **k):
        return []

    async def news_only(query, key, **kw):
        return [{"url": "https://example.org/news/project-launch"}]

    async def fake_agent(*a, **k):
        return ["https://example.org/projects/from-agent"]

    monkeypatch.setattr(sw, "_crawl_discover", empty)
    monkeypatch.setattr(sw, "_fetch_discover", empty)
    import app.services.swarm_pipeline as sp
    monkeypatch.setattr(sp, "tf_search", news_only)
    monkeypatch.setattr(sp, "serper_search", news_only)
    monkeypatch.setattr(sw, "_tinyfish_discover", fake_agent)

    queued = _run(_queued(sw, LISTING))
    assert [i["url"] for i in queued] == ["https://example.org/projects/from-agent"]
    packed = run_journal.read_journal_file(sw.run_id)
    text = " ".join(e["msg"] for e in packed["items"])
    assert "hits filtrés (0 fiches) → TinyFish Agent fiches" in text
    assert "Search vide → TinyFish Agent" not in text
    assert packed["wrote_projects"] is False


def _drain_worker(sw, processed=None):
    processed = processed if processed is not None else []

    async def worker(idx):
        while True:
            try:
                item = await asyncio.wait_for(sw.queue.get(), timeout=0.2)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                return
            try:
                processed.append(item.get("url"))
            finally:
                try:
                    sw.queue.task_done()
                except ValueError:
                    pass
    return worker


def test_full_from_scratch_does_not_dump_deeplink_cache(monkeypatch):
    import app.services.swarm_pipeline as sp
    monkeypatch.setattr(sp, "MASTER_SEEDS", [])
    monkeypatch.setattr(sp, "seeds_for_run", lambda seeds: [])
    sw = Swarm(_FakeDB())
    sw.running = True
    sw.mode = "full"
    sw.force_rescan = True
    sw.settings = {
        "discover_concurrency": 1,
        "extract_concurrency": 1,
        "full_max_urls_per_seed": 1,
        "tinyfish_agents": 1,
        "allow_tinyfish_agent": False,
    }
    sw.db.deeplink_pages.docs = [
        {"url": "https://cached.org/projects/old", "funder": "X", "source": "cache"},
    ]
    monkeypatch.setattr(sw, "_extract_worker", _drain_worker(sw))

    _run(sw._run())
    msgs = " ".join(e["msg"] for e in sw.logs)
    assert "DeepLinkCache non déversé" in msgs
    assert "not yet extracted → queued" not in msgs
    assert sw.wrote_projects is False
    assert sw.db.projects.docs == []


def test_full_incremental_still_dumps_fresh_cache(monkeypatch):
    import app.services.swarm_pipeline as sp
    monkeypatch.setattr(sp, "MASTER_SEEDS", [])
    monkeypatch.setattr(sp, "seeds_for_run", lambda seeds: [])
    processed = []
    sw = Swarm(_FakeDB())
    sw.running = True
    sw.mode = "full"
    sw.force_rescan = False
    sw.run_id = "20260912-221100-inc01"
    sw.settings = {
        "discover_concurrency": 1,
        "extract_concurrency": 1,
        "full_max_urls_per_seed": 1,
        "tinyfish_agents": 1,
        "allow_tinyfish_agent": False,
    }
    sw.db.deeplink_pages.docs = [
        {"url": "https://cached.org/projects/old", "funder": "X", "source": "cache"},
        {"url": "https://cached.org/projects/live", "funder": "X", "source": "cache"},
    ]
    sw.db.projects.docs = [{"url": "https://cached.org/projects/live"}]
    monkeypatch.setattr(sw, "_extract_worker", _drain_worker(sw, processed))

    _run(sw._run())
    assert processed == ["https://cached.org/projects/old"]
    msgs = " ".join(e["msg"] for e in sw.logs)
    assert "not yet extracted → queued" in msgs
    assert sw.db.projects.docs == [{"url": "https://cached.org/projects/live"}]
