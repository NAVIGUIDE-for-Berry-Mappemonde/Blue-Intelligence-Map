"""Onglet Review — file de fiches par run + commentaire en base, 0 écriture v1."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import review_queue
from app.services.poe_zone_fiche import build_zone_fiche


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, n=None):
        if n is None:
            return list(self._docs)
        return list(self._docs[:n])

    def sort(self, *a, **k):
        return self


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def _match_one(self, doc, q):
        if not q:
            return True
        for k, v in q.items():
            if doc.get(k) != v:
                return False
        return True

    def _match(self, q):
        return [d for d in self.docs if self._match_one(d, q or {})]

    def find(self, q=None, proj=None):
        return _FakeCursor(self._match(q or {}))

    async def find_one(self, q=None, proj=None):
        docs = self._match(q or {})
        return docs[0] if docs else None

    async def count_documents(self, q=None):
        return len(self._match(q or {}))

    async def create_index(self, *a, **k):
        return None

    async def update_one(self, q, upd, upsert=False):
        docs = self._match(q)
        if not docs:
            if not upsert:
                return None
            doc = {}
            if "$set" in upd:
                doc.update(upd["$set"])
            for k, v in (q or {}).items():
                if not isinstance(v, dict):
                    doc.setdefault(k, v)
            self.docs.append(doc)
            return None
        if "$set" in upd:
            docs[0].update(upd["$set"])
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


_HEX = {
    "mrgid": 5677, "name": "France", "geoname": "French Exclusive Economic Zone",
    "iso2": "FR", "sov_iso2": "FR", "sovereign": "France", "pol_type": "200NM",
    "status": "ia", "poe_count": 1,
    "sources": [{"url": "https://douane.gouv.fr/hexagone.pdf", "domain": "douane.gouv.fr",
                 "official": True}],
}
_MAYOTTE = {
    "mrgid": 48944, "name": "Mayotte",
    "geoname": "Overlapping claim Mayotte: France / Comores",
    "iso2": "YT", "sov_iso2": "FR", "sovereign": "France",
    "pol_type": "Overlapping claim", "status": "ia", "poe_count": 1,
    "sources": [{"url": "https://douane.gouv.fr/mayotte.pdf", "domain": "douane.gouv.fr",
                 "official": True}],
}


def _db():
    return _FakeDB(
        projects=[{
            "_id": "p1", "title": "Hope Spot Azores", "url": "https://example.org/hope",
            "funders": ["Mission Blue"], "location": "Azores", "lat": 38.5, "lon": -28.0,
            "description": "marine protected area",
        }],
        project_runs=[{"_id": "pr-1", "label": "projects-test", "state": "done",
                       "created_at": "2026-09-07T00:00:00Z"}],
        project_run_projects=[{
            "_id": "rp1", "run_id": "pr-1", "title": "Run site only",
            "url": "https://example.org/run-site", "verdict": "site",
            "funders": ["Pew"], "lat": 45.0, "lon": -5.0,
        }],
        eez_zones=[_HEX, _MAYOTTE],
        poe_ports=[
            {"_id": "v1a", "dedup_key": "5677:marseille", "name": "Marseille",
             "mrgid": 5677, "zone_name": "France", "lat": 43.3, "lon": 5.3,
             "confidence": 80, "source_urls": ["https://douane.gouv.fr/hexagone.pdf"]},
            {"_id": "v1b", "dedup_key": "48944:mamoudzou", "name": "Mamoudzou",
             "mrgid": 48944, "zone_name": "Mayotte", "lat": -12.78, "lon": 45.23},
        ],
        poe_runs=[{"_id": "poe-run-1", "label": "tinyfish-world", "state": "done",
                   "created_at": "2026-09-07T12:00:00Z"}],
        poe_run_zones=[
            {**_HEX, "run_id": "poe-run-1", "sources": [
                {"url": "https://run.gouv.fr/liste.pdf", "domain": "run.gouv.fr", "official": True},
            ]},
        ],
        poe_run_ports=[{
            "_id": "runp1", "run_id": "poe-run-1", "dedup_key": "5677:sete",
            "name": "Sète", "mrgid": 5677, "zone_name": "France",
            "lat": 43.4, "lon": 3.7, "judge_sources": ["https://run.gouv.fr/sete"],
        }],
        poe_seed_ports=[{
            "mrgid": 5677, "name": "Marseille",
            "judge_sources": ["https://douane.gouv.fr/marseille-bu"],
        }],
        marinas=[{
            "_id": "m1", "name": "Port Vauban", "lat": 43.58, "lon": 7.13,
            "source": "osm", "priority": 1, "enriched": True,
            "canal_vhf": "9", "tags": {"name": "Port Vauban"},
        }],
        review_comments=[],
    )


def test_queue_separates_eez_polygons_from_poe():
    db = _db()
    eez = asyncio.run(review_queue.list_queue(db, "eez", "published"))
    poe = asyncio.run(review_queue.list_queue(db, "poe", "published"))
    eez_ids = {i["id"] for i in eez["items"]}
    poe_ids = {i["id"] for i in poe["items"]}
    assert eez_ids == {"5677", "48944"}
    assert "5677:marseille" in poe_ids
    assert "48944:mamoudzou" in poe_ids
    assert eez_ids.isdisjoint(poe_ids)
    hexagon = next(i for i in eez["items"] if i["id"] == "5677")
    mayotte = next(i for i in eez["items"] if i["id"] == "48944")
    assert hexagon["title"] == "France (hexagone)"
    assert mayotte["title"] == "France (Mayotte)"


def test_run_queue_only_contains_that_run():
    db = _db()
    eez = asyncio.run(review_queue.list_queue(db, "eez", "poe-run-1"))
    poe = asyncio.run(review_queue.list_queue(db, "poe", "poe-run-1"))
    proj = asyncio.run(review_queue.list_queue(db, "project", "pr-1"))
    pub = asyncio.run(review_queue.list_queue(db, "project", "published"))
    assert [i["id"] for i in eez["items"]] == ["5677"]
    assert [i["id"] for i in poe["items"]] == ["5677:sete"]
    assert [i["title"] for i in proj["items"]] == ["Run site only"]
    assert [i["title"] for i in pub["items"]] == ["Hope Spot Azores"]


def test_comment_persists_per_fiche_without_writing_v1():
    db = _db()
    n_ports = len(db.poe_ports.docs)
    n_projects = len(db.projects.docs)
    n_marinas = len(db.marinas.docs)
    saved = asyncio.run(review_queue.save_comment(
        db, "eez", "published", "5677", "TD OK, Mayotte à part"))
    assert saved["wrote_poe_ports"] is False
    assert saved["comment"] == "TD OK, Mayotte à part"
    assert len(db.poe_ports.docs) == n_ports
    assert len(db.projects.docs) == n_projects
    assert len(db.marinas.docs) == n_marinas
    q = asyncio.run(review_queue.list_queue(db, "eez", "published"))
    by = {i["id"]: i for i in q["items"]}
    assert by["5677"]["has_comment"] is True
    assert by["48944"]["has_comment"] is False
    fiche = asyncio.run(review_queue.get_fiche(db, "eez", "published", "5677"))
    assert fiche["comment"] == "TD OK, Mayotte à part"
    assert fiche["fiche"]["url_td"]["url"].endswith("hexagone.pdf")
    assert [p["name"] for p in fiche["fiche"]["ports"]] == ["Marseille"]
    assert fiche["wrote_poe_ports"] is False


def test_poe_and_marina_and_project_fiches():
    db = _db()
    poe = asyncio.run(review_queue.get_fiche(db, "poe", "published", "5677:marseille"))
    assert poe["fiche"]["name"] == "Marseille"
    assert poe["fiche"]["url_bu"]["url"] == "https://douane.gouv.fr/marseille-bu"
    marina = asyncio.run(review_queue.get_fiche(db, "marina", "published", "m1"))
    assert marina["fiche"]["name"] == "Port Vauban"
    assert marina["fiche"]["canal_vhf"] == "9"
    proj = asyncio.run(review_queue.get_fiche(db, "project", "published", "p1"))
    assert proj["fiche"]["title"] == "Hope Spot Azores"
    assert proj["fiche"]["url"] == "https://example.org/hope"


def test_run_fiche_uses_run_ports_not_v1():
    db = _db()
    fiche = asyncio.run(build_zone_fiche(db, 5677, run_id="poe-run-1"))
    assert [p["name"] for p in fiche["ports"]] == ["Sète"]
    assert fiche["url_td"]["url"] == "https://run.gouv.fr/liste.pdf"
    pub = asyncio.run(build_zone_fiche(db, 5677, run_id="published"))
    assert [p["name"] for p in pub["ports"]] == ["Marseille"]


def test_list_runs_includes_published_and_isolated():
    db = _db()
    proj = asyncio.run(review_queue.list_runs(db, "project"))
    ids = [r["id"] for r in proj["items"]]
    assert ids[0] == "published"
    assert "pr-1" in ids
    poe = asyncio.run(review_queue.list_runs(db, "poe"))
    assert "poe-run-1" in [r["id"] for r in poe["items"]]
    marina = asyncio.run(review_queue.list_runs(db, "marina"))
    assert [r["id"] for r in marina["items"]] == ["published"]


def test_frontend_review_tab_exists():
    root = Path(__file__).resolve().parents[2] / "frontend" / "src"
    header = (root / "components" / "Header.js").read_text(encoding="utf-8")
    app = (root / "App.js").read_text(encoding="utf-8")
    review = (root / "components" / "ReviewView.js").read_text(encoding="utf-8")
    assert "view-toggle-map" in header
    assert "view-toggle-audit" in header
    assert "view-toggle-review" in header
    assert 'setView("review")' in header
    assert "ReviewView" in app
    assert "review-kind-${k.id}" in review
    assert "review-kind-switch" in review
    assert "review-comment" in review
    assert "review-next" in review
    assert "/generate" not in review
