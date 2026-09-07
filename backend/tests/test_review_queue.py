"""Onglet Review — file de fiches par run + commentaire en base, 0 écriture v1."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import review_gold, review_queue
from app.services.poe_zone_fiche import build_zone_fiche


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, n=None):
        if n is None:
            return list(self._docs)
        return list(self._docs[:n])

    def sort(self, key, direction=1):
        rev = direction == -1
        docs = sorted(
            self._docs,
            key=lambda d: str(d.get(key) or "").casefold(),
            reverse=rev,
        )
        return _FakeCursor(docs)

    def skip(self, n):
        return _FakeCursor(self._docs[int(n):])

    def limit(self, n):
        return _FakeCursor(self._docs[:int(n)])


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def _match_one(self, doc, q):
        if not q:
            return True
        for k, v in q.items():
            if isinstance(v, dict) and "$in" in v:
                if doc.get(k) not in v["$in"]:
                    return False
            elif isinstance(v, dict) and "$regex" in v:
                import re
                flags = re.I if "i" in str(v.get("$options") or "") else 0
                if not re.search(str(v["$regex"]), str(doc.get(k) or ""), flags):
                    return False
            elif doc.get(k) != v:
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

    async def delete_one(self, q):
        docs = self._match(q)
        if docs:
            self.docs.remove(docs[0])
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


# Sources de zone : placeholders. Pour mrgid 5677, assemble_zone_fiche
# préfère la liste plaisance curée (territories.json), pas ces URL.
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
        }, {
            "_id": "p-snap", "title": "Snapped HQ", "url": "https://example.org/snap",
            "funders": ["Pew"], "lat": 38.9, "lon": -77.0, "snapped": True,
            "geo_source": "snap_to_ocean",
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
        poe_runs=[
            {"_id": "poe-run-1", "label": "tinyfish-world", "state": "done",
             "created_at": "2026-09-07T12:00:00Z"},
            {"_id": "poe-run-2", "label": "bestof3-v1", "state": "done",
             "created_at": "2026-09-07T13:00:00Z"},
            {"_id": "canary-1", "label": "canary-claude", "state": "done",
             "created_at": "2026-09-07T14:00:00Z"},
        ],
        poe_run_zones=[
            {**_HEX, "run_id": "poe-run-1", "sources": [
                {"url": "https://run.gouv.fr/liste.pdf", "domain": "run.gouv.fr", "official": True},
            ]},
            {**_HEX, "run_id": "poe-run-2", "sources": [
                {"url": "https://douane.gouv.fr/hexagone.pdf", "domain": "douane.gouv.fr",
                 "official": True},
            ]},
            {**_HEX, "run_id": "canary-1", "sources": [
                {"url": "https://canary.test/fr", "domain": "canary.test", "official": True},
            ]},
        ],
        poe_run_ports=[{
            "_id": "runp1", "run_id": "poe-run-1", "dedup_key": "5677:sete",
            "name": "Sète", "mrgid": 5677, "zone_name": "France",
            "lat": 43.4, "lon": 3.7, "judge_sources": ["https://run.gouv.fr/sete"],
        }, {
            "_id": "runp2", "run_id": "poe-run-2", "dedup_key": "5677:marseille",
            "name": "Marseille", "mrgid": 5677, "zone_name": "France",
            "lat": 43.3, "lon": 5.3,
        }, {
            "_id": "runc", "run_id": "canary-1", "dedup_key": "5677:canary",
            "name": "Canary Port", "mrgid": 5677, "zone_name": "France",
        }],
        poe_seed_ports=[{
            "mrgid": 5677, "name": "Marseille",
            "judge_sources": ["https://douane.gouv.fr/marseille-bu"],
        }],
        marinas=[{
            "_id": "m1", "name": "Port Vauban", "lat": 43.58, "lon": 7.13,
            "source": "osm", "priority": 1, "enriched": True,
            "canal_vhf": "9", "tags": {"name": "Port Vauban"},
        }, {
            "_id": "m-curated", "name": "Curated haven", "lat": 43.1, "lon": 5.9,
            "source": "curated", "priority": 1,
        }],
        review_comments=[],
        review_gold=[],
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
    assert [i["title"] for i in pub["items"]] == ["Hope Spot Azores", "Snapped HQ"]


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
    # hexagone.pdf n'existe pas : la fiche prend la liste plaisance curée (mrgid 5677).
    td = (fiche["fiche"].get("url_td") or {}).get("url") or ""
    assert "plaisance" in td.lower() and "dispositif.pdf" in td
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
    # run.gouv.fr/liste.pdf est un placeholder : l'URL TD France reste la liste curée.
    td = (fiche.get("url_td") or {}).get("url") or ""
    assert "plaisance" in td.lower() and "dispositif.pdf" in td
    pub = asyncio.run(build_zone_fiche(db, 5677, run_id="published"))
    assert [p["name"] for p in pub["ports"]] == ["Marseille"]


def test_queue_pagination_does_not_drop_total():
    db = _db()
    page = asyncio.run(review_queue.list_queue(db, "eez", "published", offset=0, limit=1))
    assert page["total"] == 2
    assert len(page["items"]) == 1
    rest = asyncio.run(review_queue.list_queue(db, "eez", "published", offset=1, limit=1))
    assert {page["items"][0]["id"], rest["items"][0]["id"]} == {"5677", "48944"}


def test_list_runs_includes_published_and_isolated():
    db = _db()
    proj = asyncio.run(review_queue.list_runs(db, "project"))
    ids = [r["id"] for r in proj["items"]]
    assert ids[0] == "published"
    assert "pr-1" in ids
    poe = asyncio.run(review_queue.list_runs(db, "poe"))
    poe_ids = [r["id"] for r in poe["items"]]
    assert "poe-run-1" in poe_ids
    assert "poe-run-2" in poe_ids
    assert "canary-1" not in poe_ids
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
    assert "review-kind-switch" not in review
    assert "review-kind-${k.id}" not in review
    assert "reviewKindPoe" not in review
    assert "PoeFiche" not in review
    assert "review-gold" in review
    assert "review-pregold-filter" in review
    assert "review-comment" in review
    assert "review-next" in review
    assert "/generate" not in review


def test_test_run_labels_and_ocean_fallback():
    assert review_gold.is_test_run({"label": "canary-claude-v2"})
    assert review_gold.is_test_run({"label": "smoke-3-zones"})
    assert review_gold.is_test_run({"label": "seed-enrich"})
    assert review_gold.is_test_run({"_id": "seed-enrich", "label": ""})
    assert not review_gold.is_test_run({"label": "seed-verify-mondial"})
    assert not review_gold.is_test_run({"label": "bestof3-v1"})
    from app.core.geo import ocean_fallback_coords
    lat, lon = ocean_fallback_coords("Random dump")
    assert review_gold.is_pre_gold_project({
        "title": "Random dump", "lat": lat, "lon": lon,
    }) is False
    assert review_gold.is_pre_gold_project({
        "title": "Coastal AMP", "lat": 43.3, "lon": 5.4,
    }) is True


def test_pre_gold_filter_projects_and_marinas():
    db = _db()
    all_p = asyncio.run(review_queue.list_queue(db, "project", "published"))
    pre_p = asyncio.run(review_queue.list_queue(db, "project", "published", pre_gold=True))
    assert {i["id"] for i in all_p["items"]} == {"p1", "p-snap"}
    assert [i["id"] for i in pre_p["items"]] == ["p1"]
    assert next(i for i in all_p["items"] if i["id"] == "p1")["gold_on"] is True
    assert next(i for i in all_p["items"] if i["id"] == "p-snap")["gold_on"] is False
    all_m = asyncio.run(review_queue.list_queue(db, "marina", "published"))
    pre_m = asyncio.run(review_queue.list_queue(db, "marina", "published", pre_gold=True))
    assert {i["id"] for i in all_m["items"]} == {"m1", "m-curated"}
    assert [i["id"] for i in pre_m["items"]] == ["m1"]


def test_pre_gold_eez_is_consensus_across_prod_runs():
    from app.services.review_gold import reset_eez_pre_gold_cache
    reset_eez_pre_gold_cache()
    db = _db()
    pre = asyncio.run(review_queue.list_queue(db, "eez", "published", pre_gold=True))
    ids = {i["id"] for i in pre["items"]}
    assert ids == {"5677"}
    all_z = asyncio.run(review_queue.list_queue(db, "eez", "published"))
    by = {i["id"]: i for i in all_z["items"]}
    assert by["5677"]["pre_gold"] is True
    assert by["5677"]["gold_on"] is True
    assert by["48944"]["pre_gold"] is False
    assert by["48944"]["gold_on"] is False


def test_gold_toggle_does_not_write_v1():
    from app.services.review_gold import filter_visible, reset_eez_pre_gold_cache, toggle_gold
    reset_eez_pre_gold_cache()
    db = _db()
    n_projects = len(db.projects.docs)
    n_ports = len(db.poe_ports.docs)
    n_zones = len(db.eez_zones.docs)
    n_marinas = len(db.marinas.docs)
    fiche = asyncio.run(review_queue.get_fiche(db, "project", "published", "p1"))
    assert fiche["gold_on"] is True
    off = asyncio.run(toggle_gold(db, "project", "p1"))
    assert off["gold_on"] is False
    assert off["wrote_projects"] is False
    assert len(db.projects.docs) == n_projects
    visible = asyncio.run(filter_visible(
        db, "project", db.projects.docs, lambda p: p.get("_id")))
    assert [p["_id"] for p in visible] == []
    on = asyncio.run(toggle_gold(db, "project", "p1"))
    assert on["gold_on"] is True
    visible = asyncio.run(filter_visible(
        db, "project", db.projects.docs, lambda p: p.get("_id")))
    assert [p["_id"] for p in visible] == ["p1"]
    snapped = asyncio.run(toggle_gold(db, "project", "p-snap"))
    assert snapped["gold_on"] is True
    visible = asyncio.run(filter_visible(
        db, "project", db.projects.docs, lambda p: p.get("_id")))
    assert {p["_id"] for p in visible} == {"p1", "p-snap"}
    eez_off = asyncio.run(toggle_gold(db, "eez", "5677"))
    assert eez_off["gold_on"] is False
    vis_eez = asyncio.run(filter_visible(
        db, "eez", db.eez_zones.docs, lambda z: str(z["mrgid"])))
    assert vis_eez == []
    assert len(db.poe_ports.docs) == n_ports
    assert len(db.eez_zones.docs) == n_zones
    assert len(db.marinas.docs) == n_marinas
