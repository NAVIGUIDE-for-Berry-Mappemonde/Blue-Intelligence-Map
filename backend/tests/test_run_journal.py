"""Journal structuré des dumps isolés (events + tiles HTTP + cancel marinas)."""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.events import HeartbeatWatch, RunRecorder, emit
from app.core.tasks import LOGS_TAIL_N, BuildState, TaskState
from app.services import isolated_runs
from app.services import marina_world as mw
from app.services import capitainerie_world as cw


class _MemRec:
    def __init__(self):
        self.events = []

    async def event(self, step, **payload):
        self.events.append((step, payload))


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def _match_one(self, doc, q):
        if not q:
            return True
        for k, v in (q or {}).items():
            if doc.get(k) != v:
                return False
        return True

    async def find_one(self, q=None, proj=None):
        for d in self.docs:
            if self._match_one(d, q or {}):
                return d
        return None

    async def insert_one(self, doc):
        self.docs.append(doc)

    async def update_one(self, q, upd, upsert=False):
        doc = await self.find_one(q)
        if not doc:
            if not upsert:
                return None
            doc = dict(q or {})
            if "$set" in upd:
                doc.update(upd["$set"])
            self.docs.append(doc)
            return None
        if "$set" in upd:
            doc.update(upd["$set"])
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

    async def create_index(self, *a, **k):
        return None


def test_logs_tail_is_at_least_200():
    assert LOGS_TAIL_N >= 200
    st = TaskState()
    for i in range(250):
        st.log(f"line {i}")
    tail = st.status()["logs_tail"]
    assert len(tail) == 200
    assert "line 249" in tail[-1]


def test_parse_osm_tiles_valid_and_rejects_bad():
    tiles = isolated_runs.parse_osm_tiles([[39.8, 3.78, 40.1, 4.32]])
    assert tiles == ((39.8, 3.78, 40.1, 4.32),)
    assert isolated_runs.parse_osm_tiles(None) is None
    try:
        isolated_runs.parse_osm_tiles([[1, 2, 3]])
        assert False, "expected ValueError"
    except ValueError:
        pass
    try:
        isolated_runs.parse_osm_tiles([[40.1, 3.78, 39.8, 4.32]])
        assert False, "expected south < north"
    except ValueError:
        pass


def test_recorder_warns_instead_of_swallowing(caplog):
    class _Boom:
        async def insert_one(self, doc):
            raise RuntimeError("mongo down")

    class _DB:
        def __getattr__(self, name):
            return _Boom()

    rec = RunRecorder("r-warn", db=_DB(), to_file=False, events_coll="x_events")
    with caplog.at_level(logging.WARNING, logger="app.core.events"):
        asyncio.run(rec.event("tile_start", tile="t"))
    assert any("Mongo insert failed" in r.message for r in caplog.records)


def test_heartbeat_emits_when_progress_stuck():
    rec = _MemRec()

    async def _go():
        hb = HeartbeatWatch(rec, interval_s=0.05).start(lambda: {"progress": 0, "last_item": "a"})
        await asyncio.sleep(0.16)
        await hb.aclose()

    asyncio.run(_go())
    steps = [s for s, _ in rec.events]
    assert steps.count("heartbeat") >= 1


def test_marinas_build_emits_tile_events_and_respects_cancel():
    rec = _MemRec()
    coll = _FakeColl()
    cursor = _FakeColl()
    tile = (43.0, 5.0, 44.0, 6.0)

    async def fetch(_client, _tile):
        return [
            {"type": "node", "id": i, "lat": 43.1, "lon": 5.1,
             "tags": {"leisure": "marina", "name": f"M{i}"}}
            for i in range(1, 16)
        ]

    state = BuildState()

    class RecCancel(_MemRec):
        async def event(self, step, **payload):
            await super().event(step, **payload)
            if step == "tile_start":
                state.cancel = True

    rec = RecCancel()
    out = asyncio.run(mw.build_world_marinas(
        marinas_coll=coll, cursor_coll=cursor, state=state,
        resume=False, tiles=(tile,), throttle_s=0, fetch_tile=fetch,
        run_id="marina-j", recorder=rec,
    ))
    steps = [s for s, _ in rec.events]
    assert "tile_start" in steps
    assert "overpass_query" in steps
    assert "overpass_result" in steps
    assert "tile_done" in steps
    assert out["cancelled"] is True
    assert out["inserted"] == 0


def test_marinas_build_tile_upsert_every_ten():
    rec = _MemRec()
    coll = _FakeColl()
    cursor = _FakeColl()
    tile = (43.0, 5.0, 44.0, 6.0)

    async def fetch(_client, _tile):
        return [
            {"type": "node", "id": i, "lat": 43.1, "lon": 5.1,
             "tags": {"leisure": "marina", "name": f"M{i}"}}
            for i in range(1, 25)
        ]

    state = BuildState()
    out = asyncio.run(mw.build_world_marinas(
        marinas_coll=coll, cursor_coll=cursor, state=state,
        resume=False, tiles=(tile,), throttle_s=0, fetch_tile=fetch,
        run_id="marina-u", recorder=rec,
    ))
    upserts = [p for s, p in rec.events if s == "tile_upsert"]
    assert len(upserts) >= 2
    assert upserts[0]["n"] == 10
    assert out["inserted"] == 24
    done = [p for s, p in rec.events if s == "tile_done"]
    assert done[0]["raw"] == 24
    assert done[0]["inserted"] == 24


def test_capitaineries_emits_skip_overlay():
    rec = _MemRec()
    coll = _FakeColl()
    cursor = _FakeColl()
    tile = (43.0, 5.0, 44.0, 6.0)

    async def fetch(_client, _tile):
        return [{
            "type": "node", "id": 7, "lat": 43.2, "lon": 5.4,
            "tags": {"name": "Cap", "office": "harbour_master"},
        }]

    state = BuildState()
    asyncio.run(cw.build_world_capitaineries(
        coll=coll, cursor_coll=cursor, state=state, resume=False,
        tiles=(tile,), throttle_s=0, fetch_tile=fetch,
        skip_shom=True, skip_noaa=True, run_id="cap-j", recorder=rec,
    ))
    steps = [s for s, p in rec.events]
    assert "skip_overlay" in steps
    overlay = next(p for s, p in rec.events if s == "skip_overlay")
    assert overlay["shom"] is True and overlay["noaa"] is True
    assert "tile_start" in steps and "tile_done" in steps


def test_routers_expose_events_and_marina_cancel():
    from app.routers import marinas as marinas_router
    from app.routers import capitaineries as cap_router
    from app.routers import amp as amp_router
    marina_paths = {getattr(r, "path", "") for r in marinas_router.router.routes}
    cap_paths = {getattr(r, "path", "") for r in cap_router.router.routes}
    amp_paths = {getattr(r, "path", "") for r in amp_router.router.routes}
    assert "/api/marinas/runs/{run_id}/events" in marina_paths
    assert "/api/marinas/build/cancel" in marina_paths
    assert "/api/capitaineries/runs/{run_id}/events" in cap_paths
    assert "/api/amp/runs/{run_id}/events" in amp_paths


def test_resume_seq_continues_after_max():
    stored = []

    class _Cur:
        def __init__(self, docs):
            self.docs = list(docs)

        def sort(self, *a, **k):
            self.docs.sort(key=lambda d: d.get("seq") or 0, reverse=True)
            return self

        async def to_list(self, n):
            return self.docs[:n]

    class _Coll:
        def find(self, q=None):
            return _Cur([{"seq": 8, "run_id": "r-seq"}, {"seq": 3, "run_id": "r-seq"}])

        async def insert_one(self, doc):
            stored.append(doc)

    class _DB:
        def __getattr__(self, name):
            return _Coll()

    rec = RunRecorder("r-seq", db=_DB(), to_file=False, events_coll="e")
    asyncio.run(rec.resume_seq())
    asyncio.run(rec.event("run_done"))
    assert rec._seq == 9
    assert stored and stored[-1]["seq"] == 9
    assert stored[-1]["step"] == "run_done"


def test_emit_noop_without_recorder():
    asyncio.run(emit(None, "tile_start", tile="x"))
