"""Arrêt propre du swarm : tâches, file, Mongo project_runs. Pas `projects`."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "bi_test_swarm_stop")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import project_runs
from app.services.swarm_pipeline import Swarm
from tests.test_project_listing import HOME, _run, _swarm
from tests.test_project_runs import _FakeDB, _v1_treasure


def test_stop_cancels_recursive_tasks():
    async def hang():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise

    async def go():
        sw = Swarm(_FakeDB())
        sw.running = True
        sw.queue = asyncio.Queue()
        sw.queued_count = 2
        await sw.queue.put({"url": "https://example.org/a"})
        await sw.queue.put({"url": "https://example.org/b"})
        t = asyncio.create_task(hang())
        sw.recursive_tasks = [t]
        await sw.stop()
        assert t.done()
        assert sw.queue.empty()
        assert sw.queued_count == 0
        assert sw.running is False
        assert sw.stopping is False

    asyncio.run(go())


def test_stop_finalizes_mongo_cancelled_not_projects():
    async def go():
        db = _FakeDB(projects=[_v1_treasure()], project_runs=[{
            "_id": "r-stop-1",
            "state": "running",
            "wrote_projects": False,
            "counters": project_runs.empty_counters(),
        }])
        before = await db.projects.count_documents({})
        sw = Swarm(db)
        sw.run_id = "r-stop-1"
        sw.running = True
        await sw.stop()
        doc = await db.project_runs.find_one({"_id": "r-stop-1"})
        assert doc["state"] == "cancelled"
        assert doc["wrote_projects"] is False
        assert doc.get("finished_at")
        assert await db.projects.count_documents({}) == before
        assert sw._finalized is True

    asyncio.run(go())


def test_stop_is_idempotent_and_does_not_downgrade_cancelled():
    async def go():
        db = _FakeDB(project_runs=[{
            "_id": "r-stop-2",
            "state": "running",
            "wrote_projects": False,
            "counters": project_runs.empty_counters(),
        }])
        sw = Swarm(db)
        sw.run_id = "r-stop-2"
        sw.running = True
        await sw.stop()
        first = await db.project_runs.find_one({"_id": "r-stop-2"})
        await sw.stop()
        second = await db.project_runs.find_one({"_id": "r-stop-2"})
        assert first["state"] == "cancelled"
        assert second["state"] == "cancelled"
        assert second["finished_at"] == first["finished_at"]

    asyncio.run(go())


def test_discover_and_partner_noop_when_halted():
    sw = _swarm()
    sw.stopping = True
    sw.running = False

    async def boom(*a, **k):
        raise AssertionError("halted swarm must not discover")

    sw._resolve_official_home = boom
    sw._resolve_listing = boom
    sw._discover_fiches = boom
    items = _run(sw._discover(HOME, 6))
    assert items is None
    sw._queue_partner("New Org", "https://new-org.example/")
    assert sw.recursive_tasks == []


def test_discover_fiches_does_not_queue_after_stop():
    sw = _swarm()
    sw.main_task = object()  # _halted if not running
    sw.running = False
    sw.stopping = False

    async def fake_crawl(*a, **k):
        return ["https://example.org/project/one"]

    sw._crawl_discover = fake_crawl
    _run(sw._discover_fiches(HOME, 6))
    assert sw.queue.empty()
    assert sw.queued_count == 0


def test_request_cancel_finalizes_orphan_mongo_run():
    async def go():
        db = _FakeDB(projects=[_v1_treasure()], project_runs=[{
            "_id": "orphan-1",
            "state": "running",
            "wrote_projects": False,
            "counters": project_runs.empty_counters(),
        }])
        before = await db.projects.count_documents({})
        idle = Swarm(db)
        idle.run_id = None
        idle.running = False
        out = await project_runs.request_cancel(db, "orphan-1", idle)
        assert out["wrote_projects"] is False
        assert out["run_id"] == "orphan-1"
        doc = await db.project_runs.find_one({"_id": "orphan-1"})
        assert doc["state"] == "cancelled"
        assert await db.projects.count_documents({}) == before

    asyncio.run(go())


def test_request_cancel_same_run_even_if_memory_idle():
    """Après stop() trop tôt : Mongo encore running, mémoire déjà idle."""
    async def go():
        db = _FakeDB(project_runs=[{
            "_id": "ghost-1",
            "state": "running",
            "wrote_projects": False,
            "counters": project_runs.empty_counters(),
        }])
        sw = Swarm(db)
        sw.run_id = "ghost-1"
        sw.running = False
        sw.stopping = False
        await project_runs.request_cancel(db, "ghost-1", sw)
        doc = await db.project_runs.find_one({"_id": "ghost-1"})
        assert doc["state"] == "cancelled"

    asyncio.run(go())


def test_request_cancel_409_when_already_done():
    async def go():
        db = _FakeDB(project_runs=[{
            "_id": "done-1",
            "state": "done",
            "finished_at": "2026-09-13T00:00:00+00:00",
            "wrote_projects": False,
        }])
        sw = Swarm(db)
        sw.run_id = None
        try:
            await project_runs.request_cancel(db, "done-1", sw)
        except project_runs.RunNotRunning:
            return
        raise AssertionError("expected RunNotRunning")

    asyncio.run(go())


def test_request_cancel_unknown_run():
    async def go():
        try:
            await project_runs.request_cancel(_FakeDB(), "missing", Swarm(_FakeDB()))
        except KeyError:
            return
        raise AssertionError("expected KeyError")

    asyncio.run(go())


def test_status_exposes_stopping():
    sw = Swarm(_FakeDB())
    st = sw.status()
    assert "stopping" in st
    assert st["stopping"] is False
    assert st["wrote_projects"] is False
