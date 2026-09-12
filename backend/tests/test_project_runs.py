"""Runs isolés Projets (CDC v2, phase B) — n'écrit jamais `projects`."""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "bi_test_project_runs")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.services import project_runs
from app.services.swarm_pipeline import Swarm


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, n=None):
        if n is None:
            return list(self._docs)
        return list(self._docs[:n])

    def sort(self, *a, **k):
        return self

    def skip(self, n):
        return _FakeCursor(self._docs[n:])


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def _match_one(self, doc, q):
        if not q:
            return True
        for k, v in q.items():
            if k == "$or":
                if not any(self._match_one(doc, clause) for clause in v):
                    return False
                continue
            if isinstance(v, dict):
                if "$exists" in v:
                    exists = k in doc
                    if bool(v["$exists"]) != exists:
                        return False
                    continue
                if "$in" in v and doc.get(k) not in v["$in"]:
                    return False
                continue
            if doc.get(k) != v:
                return False
        return True

    def _match(self, q):
        return [d for d in self.docs if self._match_one(d, q)]

    def find(self, q=None, proj=None):
        return _FakeCursor(self._match(q or {}))

    async def find_one(self, q=None, proj=None):
        docs = self._match(q or {})
        return docs[0] if docs else None

    async def count_documents(self, q=None):
        return len(self._match(q or {}))

    async def insert_one(self, doc):
        self.docs.append(doc)
        return None

    async def delete_one(self, q):
        matched = self._match(q)
        if matched:
            self.docs.remove(matched[0])
        return None

    async def create_index(self, *a, **k):
        return None

    @staticmethod
    def _inc(doc, dotted, n):
        parts = dotted.split(".")
        cur = doc
        for p in parts[:-1]:
            nxt = cur.get(p)
            if not isinstance(nxt, dict):
                cur[p] = {}
            cur = cur[p]
        cur[parts[-1]] = cur.get(parts[-1], 0) + n

    async def update_one(self, q, upd, upsert=False):
        docs = self._match(q)
        if not docs:
            if not upsert:
                return None
            doc = {}
            if "$setOnInsert" in upd:
                doc.update(upd["$setOnInsert"])
            if "$set" in upd:
                doc.update(upd["$set"])
            for k, v in q.items():
                if not isinstance(v, dict):
                    doc.setdefault(k, v)
            if "$inc" in upd:
                for k, n in upd["$inc"].items():
                    self._inc(doc, k, n)
            self.docs.append(doc)
            return None
        doc = docs[0]
        if "$set" in upd:
            doc.update(upd["$set"])
        if "$inc" in upd:
            for k, n in upd["$inc"].items():
                self._inc(doc, k, n)
        return None


class _FakeDB:
    def __init__(self, **seed):
        self._cols = {name: _FakeColl(docs) for name, docs in seed.items()}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._cols:
            self._cols[name] = _FakeColl()
        return self._cols[name]


def _v1_treasure():
    return {
        "_id": "v1-keep",
        "title": "Existing Hope Spot",
        "url": "https://example.org/v1-keep",
        "lat": 38.5,
        "lon": -28.0,
        "funders": ["Mission Blue"],
        "location": "Azores",
    }


def _ocean_page(title="Hope Spot Azores"):
    return {
        "text": "marine ocean coastal conservation coral reef restoration boat-accessible site",
        "title": title,
        "meta_desc": "",
        "image": None,
        "ext_links": [],
        "level": "N1",
    }


def _ocean_proj(title="Hope Spot Azores", lat=45.5, lon=-5.0):
    return {
        "title": title,
        "description": "A visitable marine site.",
        "location": "Azores",
        "latitude": lat,
        "longitude": lon,
        "s_ocean": 0.91,
        "engine": "heuristic",
        "category": "MPA",
        "partners": [],
    }


def _patch_extract(monkeypatch, *, page=None, gk=None, proj=None):
    import app.services.swarm_pipeline as sp

    async def fake_cascade(url, min_chars=200, log=None):
        return page or _ocean_page()

    async def fake_gk(title, text, settings):
        return gk or {"accepted": True, "reason": "ok", "engine": "heuristic"}

    async def fake_extract(*a, **k):
        return proj or _ocean_proj()

    monkeypatch.setattr(sp, "extract_cascade", fake_cascade)
    monkeypatch.setattr(sp, "gatekeeper_check", fake_gk)
    monkeypatch.setattr(sp, "extract_project", fake_extract)
    # Geocode live (Nominatim) would turn inland HQ coords into a site; keep
    # the inland→unlocated path deterministic.
    from unittest.mock import AsyncMock
    monkeypatch.setattr(sp, "geocode_project_site", AsyncMock(return_value={}))


def test_open_run_never_writes_projects():
    async def run():
        db = _FakeDB(projects=[_v1_treasure()])
        before = await db.projects.count_documents({})
        opened = await project_runs.open_run(
            db, mode="test", label="canary", settings={}, to_file=False)
        assert opened["wrote_projects"] is False
        assert opened["run_id"]
        doc = await db.project_runs.find_one({"_id": opened["run_id"]})
        assert doc["wrote_projects"] is False
        assert doc["state"] == "running"
        assert doc["params"]["rules"]["hash"]
        assert doc["params"]["rules"]["chosen"]["shared.no_snap"]["value"] is True
        assert await db.projects.count_documents({}) == before

    asyncio.run(run())


def test_process_url_writes_run_not_v1(monkeypatch):
    _patch_extract(monkeypatch)

    async def run():
        db = _FakeDB(projects=[_v1_treasure()])
        before = await db.projects.count_documents({})
        opened = await project_runs.open_run(
            db, mode="test", settings={}, to_file=False)
        sw = Swarm(db)
        sw.run_id = opened["run_id"]
        sw.recorder = opened["recorder"]
        sw.settings = {}
        out = await sw._process_url({
            "url": "https://example.org/new-site",
            "funder": "Mission Blue",
            "source": "test",
        })
        assert out["status"] == "site"
        assert await db.projects.count_documents({}) == before
        assert await db.projects.find_one({"url": "https://example.org/new-site"}) is None
        row = await db.project_run_projects.find_one({
            "run_id": opened["run_id"], "url": "https://example.org/new-site",
        })
        assert row["verdict"] == "site"
        assert row["wrote_projects"] is False
        assert row["lat"] == 45.5
        run_doc = await db.project_runs.find_one({"_id": opened["run_id"]})
        assert run_doc["counters"]["sites"] == 1

    asyncio.run(run())


def test_seen_v1_skips_crawl_and_leaves_treasure(monkeypatch):
    called = {"cascade": 0}

    import app.services.swarm_pipeline as sp

    async def boom(*a, **k):
        called["cascade"] += 1
        raise AssertionError("cascade should not run for seen_v1")

    monkeypatch.setattr(sp, "extract_cascade", boom)

    async def run():
        db = _FakeDB(projects=[_v1_treasure()])
        before = await db.projects.count_documents({})
        opened = await project_runs.open_run(
            db, mode="test", settings={}, to_file=False)
        sw = Swarm(db)
        sw.run_id = opened["run_id"]
        sw.recorder = opened["recorder"]
        out = await sw._process_url({
            "url": "https://example.org/v1-keep",
            "funder": "Mission Blue",
            "source": "test",
        })
        assert out["status"] == "seen_v1"
        assert called["cascade"] == 0
        assert await db.projects.count_documents({}) == before
        v1 = await db.projects.find_one({"_id": "v1-keep"})
        assert v1["title"] == "Existing Hope Spot"
        row = await db.project_run_projects.find_one({
            "run_id": opened["run_id"], "url": "https://example.org/v1-keep",
        })
        assert row["verdict"] == "seen_v1"

    asyncio.run(run())


def test_force_rescan_reextracts_url_already_on_live_map(monkeypatch):
    _patch_extract(monkeypatch, proj=_ocean_proj(title="Reextracted Hope Spot"))

    async def run():
        db = _FakeDB(projects=[_v1_treasure()])
        before = await db.projects.count_documents({})
        opened = await project_runs.open_run(
            db, mode="full", settings={}, to_file=False, force_rescan=True)
        sw = Swarm(db)
        sw.run_id = opened["run_id"]
        sw.recorder = opened["recorder"]
        sw.force_rescan = True
        sw.settings = {}
        out = await sw._process_url({
            "url": "https://example.org/v1-keep",
            "funder": "Mission Blue",
            "source": "test",
            "force": True,
        })
        assert out["status"] == "site", out
        assert await db.projects.count_documents({}) == before
        v1 = await db.projects.find_one({"_id": "v1-keep"})
        assert v1["title"] == "Existing Hope Spot"
        row = await db.project_run_projects.find_one({
            "run_id": opened["run_id"], "url": "https://example.org/v1-keep",
        })
        assert row["verdict"] == "site"
        assert row["title"] == "Reextracted Hope Spot"

    asyncio.run(run())

    _patch_extract(monkeypatch, proj=_ocean_proj(title="Pew HQ", lat=48.8566, lon=2.3522))

    async def run():
        db = _FakeDB(projects=[_v1_treasure()])
        before = await db.projects.count_documents({})
        opened = await project_runs.open_run(
            db, mode="test", settings={"max_inland_km": 15}, to_file=False)
        sw = Swarm(db)
        sw.run_id = opened["run_id"]
        sw.recorder = opened["recorder"]
        sw.settings = {"max_inland_km": 15}
        out = await sw._process_url({
            "url": "https://example.org/pew-hq",
            "funder": "Pew",
            "source": "test",
        })
        assert out["status"] == "unlocated"
        assert await db.projects.count_documents({}) == before
        row = await db.project_run_projects.find_one({
            "run_id": opened["run_id"], "url": "https://example.org/pew-hq",
        })
        assert row["verdict"] == "unlocated"

    asyncio.run(run())


def test_rejected_writes_run_not_v1(monkeypatch):
    _patch_extract(monkeypatch, gk={"accepted": False, "reason": "terrestrial", "engine": "heuristic"})

    async def run():
        db = _FakeDB(projects=[_v1_treasure()])
        before = await db.projects.count_documents({})
        opened = await project_runs.open_run(
            db, mode="test", settings={}, to_file=False)
        sw = Swarm(db)
        sw.run_id = opened["run_id"]
        sw.recorder = opened["recorder"]
        sw.settings = {}
        out = await sw._process_url({
            "url": "https://example.org/forest",
            "funder": "X",
            "source": "test",
        })
        assert out["status"] == "rejected"
        assert await db.projects.count_documents({}) == before
        row = await db.project_run_projects.find_one({
            "run_id": opened["run_id"], "url": "https://example.org/forest",
        })
        assert row["verdict"] == "rejected"

    asyncio.run(run())


def test_process_url_requires_isolated_run():
    async def run():
        sw = Swarm(_FakeDB())
        with pytest.raises(RuntimeError, match="isolated run required"):
            await sw._process_url({
                "url": "https://example.org/x", "funder": "X", "source": "t",
            })

    asyncio.run(run())


def test_deploy_opens_run_and_leaves_projects(monkeypatch):
    import app.services.swarm_pipeline as sp
    monkeypatch.setattr(sp, "MASTER_SEEDS", [])
    monkeypatch.setattr(sp, "TEST_SEED_COUNT", 0)

    async def run():
        db = _FakeDB(projects=[_v1_treasure()])
        before = await db.projects.count_documents({})
        sw = Swarm(db)
        await sw.deploy("test", False, {"extract_concurrency": 1, "tinyfish_agents": 1}, False)
        assert sw.run_id
        assert sw.wrote_projects is False
        await sw.main_task
        assert sw.running is False
        assert await db.projects.count_documents({}) == before
        doc = await db.project_runs.find_one({"_id": sw.run_id})
        assert doc["wrote_projects"] is False
        assert doc["state"] == "done"
        assert await db.project_run_projects.count_documents({"run_id": sw.run_id}) == 0

    asyncio.run(run())


def test_merged_v1_does_not_update_treasure(monkeypatch):
    _patch_extract(monkeypatch, proj=_ocean_proj(title="Existing Hope Spot", lat=38.5, lon=-28.0))

    async def run():
        db = _FakeDB(projects=[_v1_treasure()])
        before = await db.projects.count_documents({})
        opened = await project_runs.open_run(
            db, mode="test", settings={}, to_file=False)
        sw = Swarm(db)
        sw.run_id = opened["run_id"]
        sw.recorder = opened["recorder"]
        sw.settings = {}
        out = await sw._process_url({
            "url": "https://example.org/dup",
            "funder": "Ocean Foundation",
            "source": "test",
        })
        assert out["status"] == "merged_v1"
        v1 = await db.projects.find_one({"_id": "v1-keep"})
        assert v1["funders"] == ["Mission Blue"]
        assert await db.projects.count_documents({}) == before
        row = await db.project_run_projects.find_one({
            "run_id": opened["run_id"], "url": "https://example.org/dup",
        })
        assert row["verdict"] == "merged_v1"

    asyncio.run(run())


def test_diff_and_report_wrote_projects_false():
    async def run():
        db = _FakeDB(projects=[_v1_treasure()])
        opened = await project_runs.open_run(
            db, mode="test", settings={}, to_file=False)
        rid = opened["run_id"]
        await project_runs.write_run_project(db, rid, {
            "url": "https://example.org/new",
            "title": "New Site",
            "verdict": "site",
            "lat": 36.1,
            "lon": -5.3,
        })
        await project_runs.write_run_project(db, rid, {
            "url": "https://example.org/v1-keep",
            "title": "Existing Hope Spot",
            "verdict": "seen_v1",
        })
        await project_runs.finalize_run(db, rid)
        diff = await project_runs.diff_run_vs_v1(db, rid)
        assert diff["wrote_projects"] is False
        assert diff["summary"]["added"] == 1
        assert diff["summary"]["already_in_v1"] == 1
        rep = await project_runs.build_run_report(db, rid)
        assert rep["wrote_projects"] is False
        md = project_runs.report_to_markdown(rep)
        assert "wrote_projects : false" in md
        assert "Promotion carte" in md

    asyncio.run(run())


def test_promote_is_phase_d():
    src = Path(__file__).resolve().parents[1] / "app" / "routers" / "project_runs.py"
    text = src.read_text()
    assert "501" in text
    assert "phase D" in text
    assert "/projects/runs/{run_id}/report" in text
    assert "/projects/runs/{run_id}/journal" in text
