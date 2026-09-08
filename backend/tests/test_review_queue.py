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
            ], "sources_official": True},
            {**_HEX, "run_id": "poe-run-2", "sources": [
                {"url": "https://douane.gouv.fr/hexagone.pdf", "domain": "douane.gouv.fr",
                 "official": True},
            ], "sources_official": True},
            {
                "mrgid": 8447, "name": "Niue", "iso2": "NU", "sov_iso2": "NZ",
                "sovereign": "New Zealand", "pol_type": "200NM",
                "status": "erreur", "poe_count": 0, "run_id": "poe-run-2",
                "sources": [{"url": "http://www.paclii.org/nu/legis/niue_laws",
                             "official": True}],
                "sources_official": True,
            },
            {
                "mrgid": 9999, "name": "Elsewhere", "iso2": "XX",
                "sovereign": "Elsewhere", "pol_type": "200NM",
                "status": "ia", "poe_count": 3, "run_id": "poe-run-2",
                "sources": [{"url": "https://elsewhere.test/ports", "official": True}],
                "sources_official": True,
            },
            {**_HEX, "run_id": "canary-1", "sources": [
                {"url": "https://canary.test/fr", "domain": "canary.test", "official": True},
            ], "sources_official": True},
            {
                "mrgid": 8429, "name": "Mexico", "iso2": "MX", "sov_iso2": "MX",
                "sovereign": "Mexico", "pol_type": "200NM",
                "status": "ia", "poe_count": 12, "run_id": "canary-1",
                "sources": [{"url": "https://canary.test/mx", "official": True}],
                "sources_official": True,
            },
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
    assert [p["name"] for p in fiche["fiche"]["ports"]] == ["Marseille", "Sète"]
    td_urls = [s["url"] for s in fiche["fiche"]["sources_td"]]
    assert any("run.gouv.fr/liste.pdf" in u for u in td_urls)
    assert not any("canary.test" in u for u in td_urls)
    assert fiche["fiche"]["fiche_scope"] == "union"
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
    union = asyncio.run(build_zone_fiche(db, 5677, run_id="published", union=True))
    assert [p["name"] for p in union["ports"]] == ["Marseille", "Sète"]
    assert "Canary Port" not in [p["name"] for p in union["ports"]]


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
    eez_runs = asyncio.run(review_queue.list_runs(db, "eez"))
    assert eez_runs["recommended_id"] == "poe-run-2"
    rec = [r for r in eez_runs["items"] if r.get("recommended")]
    assert [r["id"] for r in rec] == ["poe-run-2"]
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
    assert "review-stable-filter" in review
    assert "content_run_id" in review
    assert 'kind === "eez" && (' in review
    i18n = (root / "i18n.js").read_text(encoding="utf-8")
    assert "reviewStable" in i18n
    assert "reviewRecommended" in i18n
    assert "review-comment" in review
    assert "review-next" in review
    assert 'kind === "project"' in review
    assert "reviewHintFormalities" in review
    assert "/generate" not in review


def test_stable_mrgids_match_probe_targets():
    from app.services.poe_stable import STABLE_REVIEW_MRGIDS
    src = (Path(__file__).resolve().parents[1] / "scripts" / "probe_example_sources.py")
    text = src.read_text(encoding="utf-8")
    assert "TARGET_MRGIDS = STABLE_REVIEW_MRGIDS" in text
    assert STABLE_REVIEW_MRGIDS == (
        5677, 8429, 8433, 8447, 8455, 8312, 21803, 48944, 5696, 8490, 5670,
    )


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


def test_pre_gold_eez_is_productive_prod_run():
    from app.services.review_gold import (
        eez_extraction_is_productive,
        pre_gold_eez_mrgids,
        reset_eez_pre_gold_cache,
    )
    reset_eez_pre_gold_cache()
    db = _db()
    pre_ids = asyncio.run(pre_gold_eez_mrgids(db))
    assert 5677 in pre_ids
    assert 9999 in pre_ids
    assert 48944 not in pre_ids
    assert 8447 not in pre_ids
    assert 8429 not in pre_ids
    assert eez_extraction_is_productive({"poe_count": 0, "sources_official": True}) is False
    assert eez_extraction_is_productive({"poe_count": 4, "sources_official": False}) is False
    assert eez_extraction_is_productive({
        "poe_count": 2, "sources": [{"kind": "official"}],
    }) is True
    pre = asyncio.run(review_queue.list_queue(db, "eez", "published", pre_gold=True))
    ids = {i["id"] for i in pre["items"]}
    assert ids == {"5677"}
    all_z = asyncio.run(review_queue.list_queue(db, "eez", "published"))
    by = {i["id"]: i for i in all_z["items"]}
    assert by["5677"]["pre_gold"] is True
    assert by["5677"]["gold_on"] is True
    assert by["5677"]["stable"] is True
    assert by["5677"]["subtitle"].endswith("1 port")
    assert by["48944"]["pre_gold"] is False
    assert by["48944"]["gold_on"] is False


def test_stable_eez_queue_is_the_eleven_in_order():
    from app.services.poe_stable import STABLE_REVIEW_MRGIDS
    from app.services.review_gold import reset_eez_pre_gold_cache
    reset_eez_pre_gold_cache()
    db = _db()
    stable = asyncio.run(review_queue.list_queue(
        db, "eez", "published", stable=True))
    assert stable["stable"] is True
    assert [i["id"] for i in stable["items"]] == [str(m) for m in STABLE_REVIEW_MRGIDS]
    assert all(i["stable"] for i in stable["items"])
    by = {i["id"]: i for i in stable["items"]}
    assert by["8447"]["title"] == "Niue"
    assert by["8447"]["pre_gold"] is False
    assert "0 port" in by["8447"]["subtitle"]
    both = asyncio.run(review_queue.list_queue(
        db, "eez", "published", pre_gold=True, stable=True))
    assert [i["id"] for i in both["items"]] == ["5677"]
    run = asyncio.run(review_queue.list_queue(
        db, "eez", "poe-run-2", stable=True))
    run_ids = [i["id"] for i in run["items"]]
    assert run_ids == [str(m) for m in STABLE_REVIEW_MRGIDS]
    assert "9999" not in run_ids
    run_by = {i["id"]: i for i in run["items"]}
    assert run_by["5677"]["poe_count"] == 1
    assert run_by["8447"]["poe_count"] == 0
    run_pre = asyncio.run(review_queue.list_queue(
        db, "eez", "poe-run-2", pre_gold=True, stable=False))
    assert {i["id"] for i in run_pre["items"]} == {"5677", "9999"}


def test_stable_queue_overlays_best_fr_ports():
    from app.services.review_gold import reset_eez_pre_gold_cache
    reset_eez_pre_gold_cache()
    db = _db()
    db.poe_runs.docs.extend([
        {"_id": "serper-11", "label": "serper-11-tinyfish", "state": "done",
         "created_at": "2026-09-08T00:30:00Z"},
        {"_id": "catalog-fr", "label": "catalog-skip-fr", "state": "done",
         "created_at": "2026-09-08T01:06:00Z"},
    ])
    db.poe_run_zones.docs.extend([
        {**_HEX, "run_id": "serper-11", "poe_count": 0, "status": "erreur",
         "sources_official": False, "sources": []},
        {**_HEX, "run_id": "catalog-fr", "poe_count": 50, "sources_official": True,
         "sources": [{"url": "https://douane.gouv.fr/liste.pdf", "official": True}]},
    ])
    db.poe_run_ports.docs.append({
        "_id": "fr50", "run_id": "catalog-fr", "dedup_key": "5677:brest",
        "name": "Brest", "mrgid": 5677, "zone_name": "France",
        "lat": 48.4, "lon": -4.5,
    })
    q = asyncio.run(review_queue.list_queue(
        db, "eez", "serper-11", stable=True))
    fr = next(i for i in q["items"] if i["id"] == "5677")
    assert fr["poe_count"] == 50
    assert fr["source_run_id"] == "catalog-fr"
    assert "50 ports" in fr["subtitle"]
    fiche = asyncio.run(review_queue.get_fiche(
        db, "eez", "serper-11", "5677", content_run_id="catalog-fr"))
    assert [p["name"] for p in fiche["fiche"]["ports"]] == ["Brest"]
    assert fiche["run_id"] == "serper-11"


def test_recommended_run_prefers_broader_stable_coverage():
    from app.services.review_gold import reset_eez_pre_gold_cache
    reset_eez_pre_gold_cache()
    db = _db()
    db.poe_runs.docs.append({
        "_id": "poe-run-0", "label": "serper-11-tinyfish", "state": "done",
        "created_at": "2026-09-07T10:00:00Z",
    })
    db.poe_run_zones.docs.extend([
        {**_HEX, "run_id": "poe-run-0", "sources_official": True, "sources": [
            {"url": "https://douane.gouv.fr/hexagone.pdf", "official": True},
        ]},
        {
            "mrgid": 8429, "name": "Mexico", "iso2": "MX", "poe_count": 8,
            "run_id": "poe-run-0", "sources_official": True,
            "sources": [{"url": "https://gob.mx/puertos", "official": True}],
        },
        {
            "mrgid": 8455, "name": "New Zealand", "iso2": "NZ", "poe_count": 26,
            "run_id": "poe-run-0", "sources_official": True,
            "sources": [{"url": "https://mpi.govt.nz/places", "official": True}],
        },
    ])
    runs = asyncio.run(review_queue.list_runs(db, "eez"))
    assert runs["recommended_id"] == "poe-run-0"


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
