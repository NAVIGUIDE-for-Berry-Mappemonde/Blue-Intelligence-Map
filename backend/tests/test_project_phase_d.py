"""Phase D — file de revue, Gold (v1 − snapped − fallback), promote, ML."""
import asyncio
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "bi_test_project_phase_d")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import ml as ml_core
from app.services import project_review as review
from app.services import project_runs


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)
        self._i = 0

    async def to_list(self, n=None):
        if n is None:
            return list(self._docs)
        return list(self._docs[:n])

    def sort(self, *a, **k):
        return self

    def skip(self, n):
        return _FakeCursor(self._docs[n:])

    def limit(self, n):
        return _FakeCursor(self._docs[:n])

    def __aiter__(self):
        self._i = 0
        return self

    async def __anext__(self):
        if self._i >= len(self._docs):
            raise StopAsyncIteration
        doc = self._docs[self._i]
        self._i += 1
        return doc


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
                if "$ne" in v and doc.get(k) == v["$ne"]:
                    return False
                    continue
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

    async def insert_many(self, docs):
        self.docs.extend(docs)

    async def delete_one(self, q):
        matched = self._match(q)
        if matched:
            self.docs.remove(matched[0])

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


def _clean(**kw):
    base = {
        "_id": "v1-clean",
        "title": "Hope Spot Azores marine restoration visitable site",
        "url": "https://example.org/hope-azores",
        "description": "A boat-accessible marine Hope Spot in the Azores.",
        "location": "Azores",
        "lat": 38.6,
        "lon": -28.0,
        "funders": ["Mission Blue"],
        "snapped": False,
        "geo_source": "extracted",
    }
    base.update(kw)
    return base


def _snapped(**kw):
    base = {
        "_id": "v1-snap",
        "title": "Snapped junk headquarters Paris office",
        "url": "https://example.org/snapped-paris",
        "description": "Snapped to ocean from a city HQ.",
        "location": "Paris",
        "lat": 45.5,
        "lon": -5.0,
        "funders": ["Pew"],
        "snapped": True,
        "geo_source": "snap_to_ocean",
    }
    base.update(kw)
    return base


def _fallback(**kw):
    base = {
        "_id": "v1-fb",
        "title": "Fallback Pacific centroid not a real site",
        "url": "https://example.org/fallback-pacific",
        "description": "Ocean region fallback coordinates.",
        "location": "Pacific",
        "lat": 0.1,
        "lon": -150.0,
        "funders": ["Unknown"],
        "snapped": False,
        "geo_source": "ocean-region-fallback",
    }
    base.update(kw)
    return base


def test_gold_excludes_snapped_and_fallback():
    async def run():
        db = _FakeDB(projects=[_clean(), _snapped(), _fallback()])
        items = await review.collect_gold_items(db)
        urls = {i["url"] for i in items}
        assert "https://example.org/hope-azores" in urls
        assert "https://example.org/snapped-paris" not in urls
        assert "https://example.org/fallback-pacific" not in urls
        stats = await review.gold_stats(db)
        assert stats["excluded_snapped"] == 1
        assert stats["excluded_fallback"] == 1
        assert stats["gold_count"] == 1

    asyncio.run(run())


def test_rebuild_queues_dirty_v1_and_run_leftovers():
    async def run():
        db = _FakeDB(
            projects=[_clean(), _snapped(), _fallback()],
            project_runs=[{"_id": "r1", "created_at": "2026-09-07"}],
            project_run_projects=[
                {
                    "_id": "rp-hq",
                    "run_id": "r1",
                    "url": "https://example.org/pew-hq",
                    "title": "Pew Charitable Trusts",
                    "verdict": "unlocated",
                    "reason": "unlocated:hq",
                    "geo_kind": "hq",
                    "location": "Washington, D.C.",
                    "lat": 38.9,
                    "lon": -77.0,
                },
                {
                    "_id": "rp-new",
                    "run_id": "r1",
                    "url": "https://example.org/new-reef",
                    "title": "Golfe reef restoration visitable",
                    "verdict": "site",
                    "lat": 45.5,
                    "lon": -5.0,
                    "location": "Golfe de Gascogne",
                },
            ],
        )
        out = await review.rebuild_queue(db, run_id="r1")
        assert out["by_status"]["pending"] >= 4
        listed = await review.list_review(db, status="pending", limit=50)
        sources = {i["source"] for i in listed["items"]}
        assert "v1_snapped" in sources
        assert "v1_fallback" in sources
        assert "run_hq" in sources
        assert "run_diff" in sources
        assert await db.projects.count_documents({}) == 3

    asyncio.run(run())


def test_accept_snapped_writes_projects_and_enters_gold():
    async def run():
        db = _FakeDB(projects=[_snapped(), _clean()])
        await review.rebuild_queue(db)
        pending = await review.list_review(db, status="pending", source="v1_snapped")
        assert pending["total"] == 1
        item_id = pending["items"][0]["id"]
        before = await db.projects.count_documents({})
        out = await review.accept_item(
            db, item_id,
            lat=38.6, lon=-28.0, site_name="Azores Hope Spot",
            settings={"max_inland_km": 15},
        )
        assert out["wrote_projects"] is True
        assert out["item"]["status"] == "accepted"
        assert await db.projects.count_documents({}) == before
        updated = await db.projects.find_one({"url": "https://example.org/snapped-paris"})
        assert updated["snapped"] is False
        assert updated["lat"] == 38.6
        assert updated["geo_source"] == "review"
        gold = await review.collect_gold_items(db)
        assert any(g["url"] == "https://example.org/snapped-paris" for g in gold)

    asyncio.run(run())


def test_reject_keeps_treasure_out_of_gold():
    async def run():
        db = _FakeDB(projects=[_snapped(), _clean()])
        await review.rebuild_queue(db)
        pending = await review.list_review(db, status="pending", source="v1_snapped")
        item_id = pending["items"][0]["id"]
        await review.reject_item(db, item_id, note="siège")
        assert await db.projects.find_one({"_id": "v1-snap"}) is not None
        gold = await review.collect_gold_items(db)
        assert all(g["url"] != "https://example.org/snapped-paris" for g in gold)
        texts = await review.rejected_negative_texts(db)
        assert any("Snapped" in t or "snapped" in t.lower() for t in texts)

    asyncio.run(run())


def test_accept_inland_without_force_fails():
    async def run():
        db = _FakeDB(projects=[_snapped(lat=48.8566, lon=2.3522, geo_source="extracted")])
        await review.rebuild_queue(db)
        item_id = (await review.list_review(db, status="pending"))["items"][0]["id"]
        try:
            await review.accept_item(
                db, item_id, lat=48.8566, lon=2.3522,
                settings={"max_inland_km": 15})
            raise AssertionError("inland accept should fail")
        except ValueError as e:
            assert "non publiable" in str(e)

    asyncio.run(run())


def test_edit_gps_then_accept():
    async def run():
        db = _FakeDB(projects=[], project_review=[{
            "_id": "run_unlocated:https://example.org/hq",
            "source": "run_hq",
            "status": "pending",
            "url": "https://example.org/hq",
            "title": "Pew offices Washington",
            "location": "Washington",
            "funders": ["Pew"],
            "lat": 38.9,
            "lon": -77.0,
            "reason": "hq",
        }])
        edited = await review.edit_item(
            db, "run_unlocated:https://example.org/hq",
            lat=38.6, lon=-28.0, site_name="Azores action site")
        assert edited["lat"] == 38.6
        out = await review.accept_item(
            db, "run_unlocated:https://example.org/hq",
            settings={"max_inland_km": 15})
        assert out["projects"]["action"] == "inserted"
        live = await db.projects.find_one({"url": "https://example.org/hq"})
        assert live["lat"] == 38.6
        assert live["snapped"] is False

    asyncio.run(run())


def test_promote_writes_projects_only_on_manual_action():
    async def run():
        db = _FakeDB(projects=[_clean()])
        opened = await project_runs.open_run(
            db, mode="test", settings={}, to_file=False)
        rid = opened["run_id"]
        await project_runs.write_run_project(db, rid, {
            "url": "https://example.org/new-reef",
            "title": "Raja Ampat reef restoration visitable",
            "verdict": "site",
            "lat": 45.5,
            "lon": -5.0,
            "location": "Golfe de Gascogne",
            "funders": ["Coral Triangle"],
            "sites": [{
                "name": "Banc d'essai", "lat": 45.5, "lon": -5.0,
                "verdict": "site_ok",
            }],
        })
        before = await db.projects.count_documents({})
        assert before == 1
        assert (await db.project_runs.find_one({"_id": rid}))["wrote_projects"] is False
        out = await review.promote_run(db, rid, settings={"max_inland_km": 15})
        assert out["wrote_projects"] is True
        assert out["inserted"] == 1
        assert await db.projects.count_documents({}) == 2
        assert await db.projects.find_one({"url": "https://example.org/hope-azores"}) is not None
        run = await db.project_runs.find_one({"_id": rid})
        assert run["wrote_projects"] is True
        rep = await project_runs.build_run_report(db, rid)
        assert rep["wrote_projects"] is True

    asyncio.run(run())


def test_rebuild_preserves_accepted():
    async def run():
        db = _FakeDB(projects=[_snapped()])
        await review.rebuild_queue(db)
        item_id = (await review.list_review(db, status="pending"))["items"][0]["id"]
        await review.accept_item(
            db, item_id, lat=38.6, lon=-28.0,
            settings={"max_inland_km": 15})
        again = await review.rebuild_queue(db)
        assert again["preserved"] >= 1
        acc = await review.list_review(db, status="accepted")
        assert acc["total"] == 1

    asyncio.run(run())


def test_export_gold_file(tmp_path, monkeypatch):
    dest = tmp_path / "project_gold.json"
    monkeypatch.setattr(review, "GOLD_FILE", dest)

    async def run():
        db = _FakeDB(projects=[_clean(), _snapped(), _fallback()])
        stats = await review.export_gold(db)
        assert stats["exported"] == 1
        payload = json.loads(dest.read_text())
        assert payload["count"] == 1
        assert payload["items"][0]["url"] == "https://example.org/hope-azores"

    asyncio.run(run())


def test_gatekeeper_dataset_uses_gold_not_raw_projects():
    async def run():
        projects = [_clean(), _snapped(), _fallback()]
        for i in range(5):
            projects.append(_clean(
                _id=f"v1-extra-{i}",
                url=f"https://example.org/clean-{i}",
                title=f"Coastal mangrove restoration visitable site {i} ocean",
            ))
        db = _FakeDB(
            projects=projects,
            failed=[{
                "stage": "gatekeeper",
                "url": "https://land.example/forest",
                "reason": "terrestrial forestry inland",
            }],
            project_review=[{
                "_id": "rej",
                "status": "rejected",
                "source": "run_hq",
                "title": "Pew headquarters Washington office",
                "reason": "hq",
                "url": "https://example.org/pew-hq",
            }],
        )
        pos, neg, n_real = await ml_core.build_gatekeeper_dataset(db)
        blob = " | ".join(pos)
        assert "Hope Spot Azores" in blob
        assert "Snapped junk" not in blob
        assert "Fallback Pacific" not in blob
        assert n_real >= 1
        assert any("headquarters" in n.lower() or "terrestrial" in n.lower() for n in neg)

    asyncio.run(run())


def test_train_gatekeeper_skips_snapped(monkeypatch):
    captured = {}

    def fake_train(pos, neg):
        captured["pos"] = pos
        captured["neg"] = neg
        return {"trained_at": "t", "n_pos": len(pos), "n_neg": len(neg),
                "accuracy": 1.0, "f1": 1.0}

    monkeypatch.setattr(ml_core, "_train_sync", fake_train)

    async def run():
        projects = []
        for i in range(110):
            projects.append(_clean(
                _id=f"g{i}",
                url=f"https://example.org/gold-{i}",
                title=f"Marine coastal restoration visitable reef site number {i}",
            ))
        projects.append(_snapped())
        db = _FakeDB(projects=projects, failed=[], project_review=[])
        metrics = await ml_core.train_gatekeeper(db)
        assert metrics["n_pos"] == 110
        assert all("Snapped junk" not in t for t in captured["pos"])

    asyncio.run(run())


def test_review_router_mounted_before_projects():
    main = Path(__file__).resolve().parents[1] / "app" / "main.py"
    text = main.read_text()
    assert "project_review" in text
    assert text.index("project_review") < text.index("projects,")
    review_r = Path(__file__).resolve().parents[1] / "app" / "routers" / "project_review.py"
    assert "/projects/review" in review_r.read_text()
    assert "/projects/gold" in review_r.read_text()


def test_ui_review_card_exists():
    card = Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "audit" / "ReviewCard.js"
    text = card.read_text()
    assert "project-review-card" in text
    assert "/projects/review" in text
    assert "/projects/gold/export" in text
    assert "/ml/train/gatekeeper" in text
    hub = Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "BatchHub.js"
    assert "ReviewCard" in hub.read_text()
