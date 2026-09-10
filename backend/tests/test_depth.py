"""Profondeur d'approche EMODnet — parseur + cache (aucun réseau)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import depth_sample as ds


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

    async def update_one(self, q, upd, upsert=False):
        doc = await self.find_one(q)
        if not doc:
            if upsert:
                merged = dict(q or {})
                merged.update(upd.get("$set") or {})
                self.docs.append(merged)
            return None
        doc.update(upd.get("$set") or {})
        return None


def test_depth_from_emodnet_positive_is_depth():
    parsed = ds.depth_from_emodnet({"avg": 56.099})
    assert parsed["depth_m"] == 56.1
    assert parsed["on_land"] is False


def test_depth_from_emodnet_negative_is_elevation():
    parsed = ds.depth_from_emodnet({"avg": -12.4})
    assert parsed["depth_m"] == 12.4
    assert parsed["on_land"] is False


def test_depth_from_emodnet_near_zero_is_dry():
    parsed = ds.depth_from_emodnet({"avg": -0.23})
    assert parsed["depth_m"] == 0.2
    parsed2 = ds.depth_from_emodnet({"avg": 0.1})
    assert parsed2["on_land"] is True


def test_depth_from_emodnet_empty():
    assert ds.depth_from_emodnet(None)["depth_m"] is None
    assert ds.depth_from_emodnet({})["depth_m"] is None


def test_cache_key_rounds_to_4_decimals():
    assert ds.cache_key(48.09812, -4.41849) == "-4.4185:48.0981"


def test_sample_depth_caches_and_skips_second_fetch():
    async def run():
        coll = _FakeColl()
        calls = {"n": 0}

        async def fake_fetch(lat, lon):
            calls["n"] += 1
            return {"avg": 12.0}

        first = await ds.sample_depth(coll, 48.1, -4.5, fetch=fake_fetch)
        second = await ds.sample_depth(coll, 48.1, -4.5, fetch=fake_fetch)
        assert first["depth_m"] == 12.0 and first["cached"] is False
        assert second["cached"] is True
        assert calls["n"] == 1
        assert len(coll.docs) == 1

        async def boom(lat, lon):
            raise RuntimeError("réseau")

        failed = await ds.sample_depth(_FakeColl(), 47.0, -3.0, fetch=boom)
        assert failed["depth_m"] is None
        assert "RuntimeError" in (failed.get("error") or "")
    asyncio.run(run())
