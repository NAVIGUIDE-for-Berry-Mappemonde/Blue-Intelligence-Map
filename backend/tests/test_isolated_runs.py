"""Runs isolés Marinas / Capitaineries / AMP : pas d’écriture live, historique conservé."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "bi_test_isolated_runs")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.tasks import BuildState, TaskState
from app.services import isolated_runs
from app.services.isolated_runs import DATASETS
from app.services import marina_world as mw
from app.services import capitainerie_world as cw
from app.services import amp_visit
from app.services import review_queue


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

    def limit(self, n):
        return _FakeCursor(self._docs[:int(n)])


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.update_calls = 0

    def _match_one(self, doc, q):
        if not q:
            return True
        for k, v in q.items():
            if k == "$or":
                if not any(self._match_one(doc, clause) for clause in v):
                    return False
                continue
            if k == "$and":
                if not all(self._match_one(doc, clause) for clause in v):
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
                if "$nin" in v and doc.get(k) in v["$nin"]:
                    return False
                    continue
                if "$regex" in v:
                    import re
                    flags = re.I if "i" in str(v.get("$options") or "") else 0
                    if not re.search(str(v["$regex"]), str(doc.get(k) or ""), flags):
                        return False
                    continue
                continue
            if doc.get(k) != v:
                return False
        return True

    def _match(self, q):
        return [d for d in self.docs if self._match_one(d, q or {})]

    def find(self, q=None, proj=None):
        from copy import deepcopy
        return _FakeCursor([deepcopy(d) for d in self._match(q or {})])

    async def find_one(self, q=None, proj=None):
        from copy import deepcopy
        docs = self._match(q or {})
        return deepcopy(docs[0]) if docs else None

    async def count_documents(self, q=None, **k):
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

    async def replace_one(self, q, payload, upsert=False):
        doc = await self.find_one(q)
        if not doc:
            if upsert:
                self.docs.append(payload)
            return None
        idx = self.docs.index(doc)
        self.docs[idx] = payload
        return None

    async def update_one(self, q, upd, upsert=False):
        self.update_calls += 1
        docs = self._match(q)
        if not docs:
            if not upsert:
                return None
            doc = {}
            if "$setOnInsert" in upd:
                doc.update(upd["$setOnInsert"])
            if "$set" in upd:
                doc.update(upd["$set"])
            for k, v in (q or {}).items():
                if not isinstance(v, dict):
                    doc.setdefault(k, v)
            self.docs.append(doc)
            return None
        doc = docs[0]
        if "$set" in upd:
            doc.update(upd["$set"])
        if "$unset" in upd:
            for k in upd["$unset"]:
                doc.pop(k, None)
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


def test_datasets_cover_three_modes():
    assert set(DATASETS) == {"marinas", "capitaineries", "amp"}
    assert isolated_runs.spec_for("marinas").items_coll == "marina_run_marinas"
    assert isolated_runs.spec_for("capitaineries").items_coll == "capitainerie_run_sites"
    assert isolated_runs.spec_for("amp").items_coll == "amp_run_sites"
    assert isolated_runs.spec_for("marinas").meta_coll == "marina_runs"


def test_open_run_does_not_write_live_collections():
    db = _FakeDB()

    async def _go():
        opened = await isolated_runs.open_run(
            db, "marinas", kind="world_leisure_marina", to_file=False,
            run_id="marina-iso-open",
        )
        isolated_runs.reset_run(opened["token"])
        return opened

    opened = asyncio.run(_go())
    assert opened["run_id"] == "marina-iso-open"
    assert opened["wrote_marinas"] is False
    assert db.marinas.docs == []
    assert db.marina_run_marinas.docs == []
    meta = db.marina_runs.docs[0]
    assert meta["_id"] == "marina-iso-open"
    assert meta["wrote_marinas"] is False
    assert meta["kind"] == "world_leisure_marina"


def test_open_run_preserves_historical_live_dump():
    db = _FakeDB(marina_runs=[{
        "_id": "marina-keep",
        "created_at": "2026-01-01T00:00:00+00:00",
        "wrote_marinas": True,
        "kind": "dump_world",
        "state": "done",
        "label": "historique live",
        "summary": {"inserted": 12, "updated": 0},
    }])
    async def _go():
        opened = await isolated_runs.open_run(
            db, "marinas", kind="world_leisure_marina", to_file=False,
            run_id="marina-keep",
        )
        isolated_runs.reset_run(opened["token"])
        return opened

    opened = asyncio.run(_go())
    hist = next(d for d in db.marina_runs.docs if d["_id"] == "marina-keep")
    assert hist["wrote_marinas"] is True
    assert hist["state"] == "done"
    assert hist["kind"] == "dump_world"
    assert opened["run_id"] != "marina-keep"
    new = next(d for d in db.marina_runs.docs if d["_id"] == opened["run_id"])
    assert new["wrote_marinas"] is False


def test_write_item_goes_to_run_collection():
    db = _FakeDB()
    asyncio.run(isolated_runs.write_item(
        db, "marinas", "r1", {"osm_id": 9, "name": "A", "lat": 1.0, "lng": 2.0},
        source_id=9,
    ))
    asyncio.run(isolated_runs.write_extra_item(
        db, "marinas", "r1", {"dedup_key": "k1", "name": "M"},
        source_id="k1",
    ))
    assert db.marinas.docs == []
    assert db.anchorages.docs == []
    assert db.marina_run_marinas.docs[0]["_id"] == "r1:9"
    assert db.marina_run_marinas.docs[0]["run_id"] == "r1"
    assert db.marina_run_anchorages.docs[0]["_id"] == "r1:k1"


def test_dump_world_marinas_with_run_id_does_not_touch_live():
    live = _FakeColl([{
        "_id": "keep", "osm_id": "node/1", "name": "Live",
        "lat": 0.0, "lon": 0.0, "source": "curated",
    }])
    run_coll = _FakeColl()
    cursor = _FakeColl()
    tile = (43.0, 5.0, 44.0, 6.0)

    async def fetch(_client, _tile):
        return [{
            "type": "node", "id": 42, "lat": 43.1, "lon": 5.9,
            "tags": {"leisure": "marina", "name": "Run marina"},
        }]

    state = BuildState()
    out = asyncio.run(mw.build_world_marinas(
        marinas_coll=run_coll,
        cursor_coll=cursor,
        state=state,
        resume=False,
        tiles=(tile,),
        throttle_s=0,
        fetch_tile=fetch,
        run_id="marina-iso",
    ))
    assert out["ok"] is True if "ok" in out else out["inserted"] == 1
    assert live.docs[0]["name"] == "Live"
    assert len(live.docs) == 1
    assert any(d.get("osm_id") == "node/42" for d in run_coll.docs)
    assert all(d.get("run_id") == "marina-iso" for d in run_coll.docs)
    assert run_coll.docs[0]["_id"] == "marina-iso:node/42"
    assert any(d.get("run_id") == "marina-iso" or d.get("_id") == "marina-iso" for d in cursor.docs)


def test_dump_world_capitaineries_with_run_id_does_not_touch_live():
    live = _FakeColl([{
        "_id": "live", "source": "osm", "osm_id": "node/1",
        "name": "Live", "lat": 0.0, "lon": 0.0,
    }])
    run_coll = _FakeColl()
    cursor = _FakeColl()
    tile = (43.0, 5.0, 44.0, 6.0)

    async def fetch(_client, _tile):
        return [{
            "type": "node", "id": 88, "lat": 43.2, "lon": 5.4,
            "tags": {
                "name": "Cap run",
                "office": "harbour_master",
            },
        }]

    state = BuildState()
    out = asyncio.run(cw.build_world_capitaineries(
        coll=run_coll,
        cursor_coll=cursor,
        state=state,
        resume=False,
        tiles=(tile,),
        throttle_s=0,
        fetch_tile=fetch,
        skip_shom=True,
        skip_noaa=True,
        run_id="cap-iso",
    ))
    assert out["inserted"] == 1
    assert live.docs[0]["name"] == "Live"
    assert any(d.get("osm_id") == "node/88" for d in run_coll.docs)
    assert all(d.get("run_id") == "cap-iso" for d in run_coll.docs)
    assert live.docs[0].get("run_id") is None


def test_amp_discover_with_run_id_does_not_touch_live_sites():
    db = _FakeDB(amp_sites=[{
        "_id": "PS-1",
        "site_id": "wdpa-1",
        "name": "Live AMP",
        "lat": 43.0,
        "lng": 5.0,
        "manager_url": "https://parc.example",
        "other_helpful_links": "https://parc.example/visite",
        "visit_url": None,
        "visit_url_status": None,
    }])
    state = TaskState()
    out = asyncio.run(amp_visit.discover_visit_urls(
        db, state=state, limit=10, skip_search=True, tf_key="",
        refresh_attrs=False, use_llm_judge=False, run_id="amp-iso",
    ))
    assert out["ok"] is True if "ok" in out else out["from_links"] == 1
    live = db.amp_sites.docs[0]
    assert live["visit_url"] is None
    assert db.amp_sites.update_calls == 0
    run_docs = db.amp_run_sites.docs
    assert len(run_docs) == 1
    assert run_docs[0]["visit_url"] == "https://parc.example/visite"
    assert run_docs[0]["run_id"] == "amp-iso"


def test_review_lists_published_plus_isolated_and_historical_runs():
    db = _FakeDB(
        marinas=[{"_id": "m1", "name": "Live"}],
        marina_runs=[
            {
                "_id": "marina-old-live",
                "created_at": "2026-03-01T00:00:00Z",
                "kind": "dump_world",
                "state": "done",
                "label": "historique live",
                "wrote_marinas": True,
                "summary": {"inserted": 12, "updated": 0},
            },
            {
                "_id": "marina-iso",
                "created_at": "2026-09-01T00:00:00Z",
                "kind": "world_leisure_marina",
                "state": "done",
                "label": "isolé",
                "wrote_marinas": False,
                "summary": {"inserted": 3, "updated": 0},
            },
            {
                "_id": "test-dump",
                "created_at": "2026-09-02T00:00:00Z",
                "kind": "world_leisure_marina",
                "state": "done",
                "label": "test-dump",
                "wrote_marinas": False,
            },
        ],
        marina_run_marinas=[
            {"_id": "marina-iso:1", "run_id": "marina-iso", "osm_id": 1, "source_id": "1"},
            {"_id": "marina-iso:2", "run_id": "marina-iso", "osm_id": 2, "source_id": "2"},
            {"_id": "marina-iso:3", "run_id": "marina-iso", "osm_id": 3, "source_id": "3"},
        ],
        capitainerie_runs=[{
            "_id": "cap-1",
            "created_at": "2026-09-01T00:00:00Z",
            "kind": "world_harbour_master",
            "state": "done",
            "label": "cap isolé",
            "wrote_capitaineries": False,
        }],
        amp_runs=[{
            "_id": "amp-1",
            "created_at": "2026-09-01T00:00:00Z",
            "kind": "discover_visit",
            "state": "done",
            "label": "amp isolé",
            "wrote_amp_sites": False,
        }],
        amp_sites=[{"_id": "a1", "name": "AMP live"}],
        capitaineries=[{"_id": "c1", "name": "Cap live"}],
    )
    marina_runs = asyncio.run(review_queue.list_runs(db, "marina"))
    ids = [r["id"] for r in marina_runs["items"]]
    assert ids[0] == "published"
    assert "marina-old-live" in ids
    assert "marina-iso" in ids
    assert "test-dump" not in ids
    old = next(r for r in marina_runs["items"] if r["id"] == "marina-old-live")
    assert old["wrote_live"] is True
    iso = next(r for r in marina_runs["items"] if r["id"] == "marina-iso")
    assert iso["wrote_live"] is False
    assert iso["count"] == 3

    cap_runs = asyncio.run(review_queue.list_runs(db, "capitainerie"))
    assert [r["id"] for r in cap_runs["items"]] == ["published", "cap-1"]

    amp_runs = asyncio.run(review_queue.list_runs(db, "amp"))
    assert [r["id"] for r in amp_runs["items"]] == ["published", "amp-1"]


def test_review_queue_reads_isolated_marina_items():
    db = _FakeDB(
        marina_run_marinas=[{
            "_id": "marina-iso:node/1",
            "run_id": "marina-iso",
            "source_id": "node/1",
            "osm_id": "node/1",
            "name": "Run marina",
            "source": "openstreetmap",
        }],
        review_comments=[],
        review_gold=[],
    )
    queue = asyncio.run(review_queue.list_queue(db, "marina", "marina-iso"))
    assert queue["total"] == 1
    assert queue["items"][0]["id"] == "node/1"
    assert queue["items"][0]["title"] == "Run marina"


def test_routers_expose_runs_endpoints():
    from app.routers import marinas as marinas_router
    from app.routers import capitaineries as cap_router
    from app.routers import amp as amp_router
    marina_paths = {getattr(r, "path", "") for r in marinas_router.router.routes}
    cap_paths = {getattr(r, "path", "") for r in cap_router.router.routes}
    amp_paths = {getattr(r, "path", "") for r in amp_router.router.routes}
    assert "/api/marinas/runs" in marina_paths
    assert "/api/capitaineries/runs" in cap_paths
    assert "/api/amp/runs" in amp_paths
