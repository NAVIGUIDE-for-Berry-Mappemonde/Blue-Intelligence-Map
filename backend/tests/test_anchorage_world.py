"""Dump mondial mouillages — tuiles, reprise, upsert dedup_key, pas de purge."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ROUTE_FILE
from app.core.tasks import BuildState
from app.services import anchorage_build as ab


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def _match_one(self, doc, q):
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

    async def replace_one(self, q, payload, upsert=False):
        doc = await self.find_one(q)
        if not doc:
            if upsert:
                self.docs.append(payload)
            return None
        self.docs[self.docs.index(doc)] = payload
        return None

    async def create_index(self, *a, **k):
        return None


TILE_A = (-60.0, -180.0, -15.0, -90.0)
TILE_B = (-60.0, -90.0, -15.0, 0.0)


def _elements_for(tile):
    if tile == TILE_A:
        return [{
            "type": "node", "id": 20, "lat": -17.53, "lon": -149.57,
            "tags": {"seamark:type": "anchorage", "seamark:name": "Baie de Papeete"},
        }]
    return [
        {
            "type": "node", "id": 21, "lat": -22.9, "lon": -43.1,
            "tags": {"natural": "bay", "name": "Baía de Guanabara"},
        },
        # Baie anonyme = bruit, elle doit être écartée.
        {"type": "node", "id": 22, "lat": -23.0, "lon": -43.2, "tags": {"natural": "bay"}},
    ]


def test_world_anchorages_resumable_and_no_purge():
    live = {
        "_id": "old-1",
        "name": "Mouillage historique",
        "lat": 43.0,
        "lon": 5.0,
        "dedup_key": "old-key",
    }
    coll = _FakeColl([live])
    cursor = _FakeColl()
    calls = {"n": 0}

    async def fetch(_client, tile):
        calls["n"] += 1
        return _elements_for(tile)

    state = BuildState()
    summary1 = asyncio.run(ab.build_world_anchorages(
        anchorages_coll=coll,
        cursor_coll=cursor,
        state=state,
        route_path=ROUTE_FILE,
        resume=True,
        tiles=(TILE_A, TILE_B),
        throttle_s=0,
        fetch_tile=fetch,
    ))
    assert summary1["world"] is True
    assert summary1["inserted"] == 2          # la baie anonyme est écartée
    assert summary1["tiles_skipped"] == 0
    assert any(d.get("dedup_key") == "old-key" for d in coll.docs)  # pas de purge
    named = [d for d in coll.docs if d.get("name") == "Baie de Papeete"]
    assert named and named[0]["anchorage_type"] == "anchorage"
    assert named[0]["priority"] in (1, 2, 3)   # priorité route conservée
    first_calls = calls["n"]

    # Reprise : les tuiles faites sont sautées, rien n'est re-fetché.
    state2 = BuildState()
    summary2 = asyncio.run(ab.build_world_anchorages(
        anchorages_coll=coll,
        cursor_coll=cursor,
        state=state2,
        route_path=ROUTE_FILE,
        resume=True,
        tiles=(TILE_A, TILE_B),
        throttle_s=0,
        fetch_tile=fetch,
    ))
    assert summary2["tiles_skipped"] == 2
    assert calls["n"] == first_calls


def test_world_anchorages_upsert_by_dedup_key_no_duplicates():
    coll = _FakeColl()
    cursor = _FakeColl()

    async def fetch(_client, tile):
        return _elements_for(tile)

    for resume in (False, False):
        state = BuildState()
        asyncio.run(ab.build_world_anchorages(
            anchorages_coll=coll,
            cursor_coll=cursor,
            state=state,
            route_path=ROUTE_FILE,
            resume=resume,
            tiles=(TILE_A,),
            throttle_s=0,
            fetch_tile=fetch,
        ))
    keys = [d["dedup_key"] for d in coll.docs]
    assert len(keys) == len(set(keys)) == 1


def test_world_anchorages_cancel_stops_the_loop():
    coll = _FakeColl()
    cursor = _FakeColl()
    calls = {"n": 0}

    async def fetch(_client, tile):
        calls["n"] += 1
        return _elements_for(tile)

    state = BuildState()

    async def run_with_cancel():
        task = asyncio.create_task(ab.build_world_anchorages(
            anchorages_coll=coll,
            cursor_coll=cursor,
            state=state,
            route_path=ROUTE_FILE,
            resume=False,
            tiles=(TILE_A, TILE_B),
            throttle_s=0.3,
            fetch_tile=fetch,
        ))
        while calls["n"] == 0:
            await asyncio.sleep(0.01)
        state.cancel = True
        return await task

    summary = asyncio.run(run_with_cancel())
    assert calls["n"] == 1
    assert summary["tiles_total"] == 2
