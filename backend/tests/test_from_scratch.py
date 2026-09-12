"""Full from scratch : ne pas sauter le déjà-posé sur la carte."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "bi_test_from_scratch")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.from_scratch import resolve_from_scratch
from app.services import amp as amp_svc
from app.services import amp_visit


def test_resolve_from_scratch_full_default():
    assert resolve_from_scratch(None, scope="full") is True
    assert resolve_from_scratch(None, mode="full") is True
    assert resolve_from_scratch(None, scope="test") is False
    assert resolve_from_scratch(True, scope="test") is True
    assert resolve_from_scratch(False, scope="full") is False


def test_world_amp_bboxes_cover_first_world_tile():
    tiles = list(amp_svc.iter_world_bboxes(step=8.0))
    assert len(tiles) > 16
    minx, miny, maxx, maxy = tiles[0]
    assert minx < maxx and miny < maxy
    assert all(max(b[2] - b[0], b[3] - b[1]) <= 8.0 + 1e-9 for b in tiles[:20])


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, n=None):
        if n is None:
            return list(self._docs)
        return list(self._docs[:n] if n else self._docs)


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def _match_one(self, doc, q):
        if not q:
            return True
        if "$or" in q:
            return any(self._match_one(doc, branch) for branch in q["$or"])
        for k, v in q.items():
            if isinstance(v, dict) and "$in" in v:
                if doc.get(k) not in v["$in"]:
                    return False
            elif doc.get(k) != v:
                return False
        return True

    def find(self, q=None, proj=None):
        return _FakeCursor([d for d in self.docs if self._match_one(d, q or {})])

    async def update_one(self, q, upd, upsert=False):
        docs = [d for d in self.docs if self._match_one(d, q or {})]
        if not docs:
            return None
        docs[0].update(upd.get("$set") or {})
        return None


class _FakeDB:
    def __init__(self, sites, run_sites=None):
        self.amp_sites = _FakeColl(sites)
        self.amp_run_sites = _FakeColl(run_sites or [])


def test_pending_sites_from_scratch_includes_already_found():
    db = _FakeDB([
        {
            "_id": "A", "site_id": "A", "name": "Parc A",
            "visit_url": "https://parc-a.fr/visite",
            "visit_url_status": "found",
            "visit_url_source": "tinyfish_search",
            "manager_url": "https://parc-a.fr",
        },
        {
            "_id": "M", "site_id": "M", "name": "Manuel",
            "visit_url": "https://keep.fr/visite",
            "visit_url_status": "found",
            "visit_url_source": "manual",
            "manager_url": "https://keep.fr",
        },
        {
            "_id": "B", "site_id": "B", "name": "Parc B",
            "visit_url": None, "visit_url_status": "none",
        },
    ])

    incremental = asyncio.run(amp_visit.pending_sites(db, 50))
    ids = {d.get("site_id") for d in incremental}
    assert "A" not in ids
    assert "B" in ids
    assert "M" not in ids

    scratch = asyncio.run(amp_visit.pending_sites(db, 50, from_scratch=True))
    ids = {d.get("site_id") for d in scratch}
    assert ids == {"A", "B"}
    found_a = next(d for d in scratch if d["site_id"] == "A")
    assert found_a.get("visit_url") in (None, "")


def test_copy_visit_to_live_skips_empty():
    db = _FakeDB(
        sites=[{
            "_id": "A", "site_id": "A",
            "visit_url": "https://old.fr/visite",
        }],
        run_sites=[
            {"run_id": "r1", "site_id": "A", "visit_url": "https://new.fr/entrer",
             "visit_url_status": "found", "visit_url_source": "tinyfish_fetch"},
            {"run_id": "r1", "site_id": "B", "visit_url": None},
        ],
    )
    n = asyncio.run(amp_visit.copy_visit_to_live(db, "r1"))
    assert n == 1
    assert db.amp_sites.docs[0]["visit_url"] == "https://new.fr/entrer"
