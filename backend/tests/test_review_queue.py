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
            "source": "osm", "osm_id": "node/1", "priority": 1, "enriched": True,
            "canal_vhf": "9", "tags": {"name": "Port Vauban"},
            "maps_place_url": "https://maps.google.com/maps/place/Port+Vauban",
        }, {
            "_id": "m-curated", "name": "Curated haven", "lat": 43.1, "lon": 5.9,
            "source": "curated", "priority": 1,
        }],
        review_comments=[],
        review_gold=[],
        review_choices=[],
        amp_sites=[{
            "_id": "PS-1", "site_id": "PS-1", "name": "Parc marin du cap",
            "country": "France", "lfp": 3,
            "manager_url": "https://parc-marin.fr",
            "visit_url": "https://parc-marin.fr/visite",
            "visit_url_status": "found",
            "other_helpful_links": "https://parc-marin.fr/mouillage https://parc-marin.fr",
        }],
        capitaineries=[{
            "_id": "c1", "name": "Capitainerie Vauban",
            "lat": 43.58, "lon": 7.13, "source": "osm",
            "osm_id": "node/1", "shom_id": "SHOM-1",
            "telephone": "+33493900000",
            "canal_vhf": "9",
            "sources": ["osm", "shom"],
        }],
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
    n_amp = len(db.amp_sites.docs)
    saved = asyncio.run(review_queue.save_comment(
        db, "eez", "published", "5677", "TD OK, Mayotte à part"))
    assert saved["wrote_poe_ports"] is False
    assert saved["wrote_amp_sites"] is False
    assert saved["comment"] == "TD OK, Mayotte à part"
    assert len(db.poe_ports.docs) == n_ports
    assert len(db.projects.docs) == n_projects
    assert len(db.marinas.docs) == n_marinas
    assert len(db.amp_sites.docs) == n_amp
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
    assert marina["fiche"]["osm_id"] == "node/1"
    assert "/maps/place/" in (marina["fiche"].get("maps_place_url") or "")
    assert marina["gold_on"] is False
    assert marina["gold_ready"] is False
    proj = asyncio.run(review_queue.get_fiche(db, "project", "published", "p1"))
    assert proj["fiche"]["title"] == "Hope Spot Azores"
    assert proj["fiche"]["url"] == "https://example.org/hope"
    amp = asyncio.run(review_queue.get_fiche(db, "amp", "published", "PS-1"))
    assert amp["fiche"]["name"] == "Parc marin du cap"
    assert amp["fiche"]["manager_url"] == "https://parc-marin.fr"
    assert amp["fiche"]["visit_url"] == "https://parc-marin.fr/visite"
    assert amp["fiche"]["manager_url"] != amp["fiche"]["visit_url"]
    cand = {c["url"] for c in amp["fiche"]["visit_candidates"]}
    assert "https://parc-marin.fr/visite" in cand
    assert "https://parc-marin.fr/mouillage" in cand
    assert amp["gold_on"] is False
    cap = asyncio.run(review_queue.get_fiche(db, "capitainerie", "published", "c1"))
    assert cap["gold_on"] is False
    assert cap["fiche"]["shom_id"] == "SHOM-1"
    assert cap["wrote_capitaineries"] is False
    assert amp["wrote_amp_sites"] is False
    q = asyncio.run(review_queue.list_queue(db, "amp", "published"))
    assert q["kind"] == "amp"
    assert q["wrote_amp_sites"] is False
    assert [i["id"] for i in q["items"]] == ["PS-1"]
    assert q["items"][0]["manager_url"] != q["items"][0]["visit_url"]


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
    amp = asyncio.run(review_queue.list_runs(db, "amp"))
    assert [r["id"] for r in amp["items"]] == ["published"]
    assert amp["items"][0]["count"] == 1


def test_frontend_review_tab_exists():
    root = Path(__file__).resolve().parents[2] / "frontend" / "src"
    header = (root / "components" / "Header.js").read_text(encoding="utf-8")
    app = (root / "App.js").read_text(encoding="utf-8")
    review = (root / "components" / "ReviewView.js").read_text(encoding="utf-8")
    assert "view-toggle-map" in header
    assert "view-toggle-audit" in header
    assert "view-toggle-review" in header
    assert "mode-toggle-amp" in header
    assert 'setView("review")' in header
    assert "ReviewView" in app
    assert "mapEpoch" in app
    assert "AmpFiche" in review
    assert "review-pregold-filter" in review
    assert "review-kind-switch" not in review
    assert "review-kind-${k.id}" not in review
    assert "reviewKindPoe" not in review
    assert "PoeFiche" not in review
    assert "review-gold" in review
    assert "/review/choice" in review
    assert "gold_ready" in review
    assert "reviewGoldIncomplete" in review
    assert "poe-fiche-td-keep" in (root / "components" / "ZoneFiche.js").read_text(encoding="utf-8")
    assert "review-pregold-filter" in review
    assert "review-stable-filter" in review
    assert "content_run_id" in review
    assert "runsReady" in review
    assert 'kind === "eez" && (' in review
    assert "review-run-select" not in review
    assert "setQueue([])" in review
    assert "map-show-review" in (root / "components" / "MapView.js").read_text(encoding="utf-8")
    assert "onChoice={applyChoice}" in review
    formalities_layer = (root / "components" / "map" / "useFormalitiesLayers.js").read_text(encoding="utf-8")
    assert "showReview" in formalities_layer
    assert "visible: 1" in formalities_layer
    assert "params: { visible: 1 }" not in formalities_layer
    choice_ui = (root / "components" / "review" / "choiceUi.js").read_text(encoding="utf-8")
    assert "export function KeepDrop" in choice_ui
    assert "export function FicheShell" in choice_ui
    for name in ("ProjectFiche.js", "MarinaFiche.js", "CapitainerieFiche.js", "AmpFiche.js"):
        src = (root / "components" / "review" / name).read_text(encoding="utf-8")
        assert "FicheShell" in src
        assert "KeepDrop" in src or "UrlKeepRow" in src
    i18n = (root / "i18n.js").read_text(encoding="utf-8")
    assert "reviewStable" in i18n
    assert "reviewRecommended" in i18n
    assert "reviewKeep" in i18n
    assert "reviewDrop" in i18n
    assert "reviewGoldIncomplete" in i18n
    assert "reviewShowReview" in i18n
    assert "reviewNoVisit" in i18n
    app = (root / "App.js").read_text(encoding="utf-8")
    assert "useState(false)" in app
    assert "showReview ? { visible: 1 }" in app or 'showReview ? { visible: 1 }' in app
    assert "review-comment" in review
    assert "review-next" in review
    assert "reviewHint" in review
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
    assert review_gold.GOLD_KINDS == ("project", "eez", "marina", "capitainerie", "amp")
    assert review_gold.is_pre_gold_marina({
        "source": "openstreetmap", "osm_id": "1", "lat": 43.5, "lon": 7.1,
    }) is True
    assert review_gold.gold_is_on(None) is False
    assert review_gold.gold_pressed(True, None) is False
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
    assert next(i for i in all_p["items"] if i["id"] == "p1")["gold_on"] is False
    assert next(i for i in all_p["items"] if i["id"] == "p-snap")["gold_on"] is False
    all_m = asyncio.run(review_queue.list_queue(db, "marina", "published"))
    pre_m = asyncio.run(review_queue.list_queue(db, "marina", "published", pre_gold=True))
    assert {i["id"] for i in all_m["items"]} == {"m1", "m-curated"}
    assert [i["id"] for i in pre_m["items"]] == ["m1"]
    assert next(i for i in all_m["items"] if i["id"] == "m1")["gold_on"] is False
    cap = asyncio.run(review_queue.list_queue(db, "capitainerie", "published"))
    assert next(i for i in cap["items"] if i["id"] == "c1")["gold_on"] is False
    assert next(i for i in cap["items"] if i["id"] == "c1")["pre_gold"] is True


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
    assert by["5677"]["gold_on"] is False
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
    from app.services.review_choices import save_choice
    from app.services.review_gold import filter_visible, reset_eez_pre_gold_cache, toggle_gold
    reset_eez_pre_gold_cache()
    db = _db()
    n_projects = len(db.projects.docs)
    n_ports = len(db.poe_ports.docs)
    n_zones = len(db.eez_zones.docs)
    n_marinas = len(db.marinas.docs)
    packed = asyncio.run(review_queue.get_fiche(db, "project", "published", "p1"))
    assert packed["gold_on"] is False
    assert packed["gold_ready"] is False
    live_name = (asyncio.run(db.projects.find_one({"_id": "p1"})))["title"]
    try:
        asyncio.run(toggle_gold(db, "project", "p1"))
        raise AssertionError("Gold without URL + site_ok must fail")
    except review_gold.GoldNotReady:
        pass
    for url in packed["fiche"]["urls"]:
        asyncio.run(save_choice(db, "project", "p1", "url", "keep", url=url))
    for site in packed["fiche"]["sites"]:
        asyncio.run(save_choice(
            db, "project", "p1", "site", "keep", site_id=site["site_id"]))
    on = asyncio.run(toggle_gold(db, "project", "p1"))
    assert on["gold_on"] is True
    assert on["wrote_projects"] is False
    assert on["snapshot"]["url"] == "https://example.org/hope"
    assert len(db.projects.docs) == n_projects
    assert (asyncio.run(db.projects.find_one({"_id": "p1"})))["title"] == live_name
    visible = asyncio.run(filter_visible(
        db, "project", db.projects.docs, lambda p: p.get("_id")))
    assert [p["_id"] for p in visible] == ["p1"]
    snap_q = asyncio.run(review_queue.get_fiche(db, "project", "published", "p-snap"))
    for url in snap_q["fiche"]["urls"]:
        asyncio.run(save_choice(db, "project", "p-snap", "url", "keep", url=url))
    for site in snap_q["fiche"]["sites"]:
        asyncio.run(save_choice(
            db, "project", "p-snap", "site", "keep", site_id=site["site_id"]))
    try:
        asyncio.run(toggle_gold(db, "project", "p-snap"))
        raise AssertionError("Gold of snapped site must fail until GPS is accepted")
    except review_gold.GoldNotReady:
        pass
    try:
        asyncio.run(toggle_gold(db, "eez", "5677"))
        raise AssertionError("Gold EEZ without choices must fail")
    except review_gold.GoldNotReady:
        pass
    vis_eez = asyncio.run(filter_visible(
        db, "eez", db.eez_zones.docs, lambda z: str(z["mrgid"])))
    assert vis_eez == []
    assert len(db.poe_ports.docs) == n_ports
    assert len(db.eez_zones.docs) == n_zones
    assert len(db.marinas.docs) == n_marinas


def test_comment_key_is_kind_entity_not_run():
    db = _db()
    n_zones = len(db.eez_zones.docs)
    saved = asyncio.run(review_queue.save_comment(
        db, "eez", "r-union", "5677", "union note"))
    assert saved["wrote_poe_ports"] is False
    row = asyncio.run(db.review_comments.find_one({"_id": "eez:5677"}))
    assert row["comment"] == "union note"
    asyncio.run(review_queue.save_comment(
        db, "eez", "other-run", "5677", "still union"))
    row2 = asyncio.run(db.review_comments.find_one({"_id": "eez:5677"}))
    assert row2["comment"] == "still union"
    assert asyncio.run(db.review_comments.find_one({"_id": "eez:r-union:5677"})) is None
    zone = asyncio.run(db.eez_zones.find_one({"mrgid": 5677}))
    assert zone["name"] == "France"
    assert len(db.eez_zones.docs) == n_zones


def test_amp_visit_candidates_and_gold_refuses_manager_url():
    from app.services.review_choices import save_choice
    from app.services.review_gold import filter_visible, toggle_gold

    db = _db()
    n_amp = len(db.amp_sites.docs)
    packed = asyncio.run(review_queue.get_fiche(db, "amp", "published", "PS-1"))
    urls = {c["url"] for c in packed["fiche"]["visit_candidates"]}
    assert "https://parc-marin.fr/visite" in urls
    assert "https://parc-marin.fr/mouillage" in urls
    assert "https://parc-marin.fr" in urls
    same = [c for c in packed["fiche"]["visit_candidates"] if c.get("same_as_manager")]
    assert same
    live_visit = (asyncio.run(db.amp_sites.find_one({"_id": "PS-1"})))["visit_url"]
    asyncio.run(save_choice(
        db, "amp", "PS-1", "visit", "keep", url="https://parc-marin.fr"))
    try:
        asyncio.run(toggle_gold(db, "amp", "PS-1"))
        raise AssertionError("Gold must refuse visit_url == manager_url")
    except review_gold.GoldNotReady:
        pass
    asyncio.run(save_choice(
        db, "amp", "PS-1", "visit", "keep", url="https://parc-marin.fr/visite"))
    golded = asyncio.run(toggle_gold(db, "amp", "PS-1"))
    assert golded["gold_on"] is True
    assert golded["wrote_amp_sites"] is False
    assert golded["snapshot"]["visit_url"] == "https://parc-marin.fr/visite"
    live = asyncio.run(db.amp_sites.find_one({"_id": "PS-1"}))
    assert live["visit_url"] == live_visit
    assert len(db.amp_sites.docs) == n_amp
    overlay = asyncio.run(filter_visible(
        db, "amp", db.amp_sites.docs, lambda d: d.get("site_id") or d.get("_id")))
    assert overlay[0]["visit_url"] == "https://parc-marin.fr/visite"


def test_map_overlay_shows_certified_run_only_after_gold():
    from app.services.review_choices import save_choice
    from app.services.review_gold import filter_visible, toggle_gold

    db = _db()
    before = asyncio.run(filter_visible(
        db, "project", db.projects.docs, lambda p: p.get("_id")))
    assert before == []
    packed = asyncio.run(review_queue.get_fiche(db, "project", "published", "p1"))
    for url in packed["fiche"]["urls"]:
        asyncio.run(save_choice(db, "project", "p1", "url", "keep", url=url))
    for site in packed["fiche"]["sites"]:
        asyncio.run(save_choice(
            db, "project", "p1", "site", "keep", site_id=site["site_id"]))
    asyncio.run(toggle_gold(db, "project", "p1"))
    overlay = asyncio.run(filter_visible(
        db, "project", db.projects.docs, lambda p: p.get("_id")))
    assert [p["_id"] for p in overlay] == ["p1"]
    live = asyncio.run(db.projects.find_one({"_id": "p1"}))
    assert live["title"] == "Hope Spot Azores"
    assert len(db.projects.docs) == 2


def test_marina_and_capitainerie_gold_after_identity_gps():
    from app.services.review_choices import save_choice
    from app.services.review_gold import filter_visible, toggle_gold

    db = _db()
    n_m = len(db.marinas.docs)
    n_c = len(db.capitaineries.docs)
    try:
        asyncio.run(toggle_gold(db, "marina", "m1"))
        raise AssertionError("marina Gold without identity+GPS must fail")
    except review_gold.GoldNotReady:
        pass
    asyncio.run(save_choice(db, "marina", "m1", "identity", "keep"))
    asyncio.run(save_choice(db, "marina", "m1", "gps", "keep"))
    gold_m = asyncio.run(toggle_gold(db, "marina", "m1"))
    assert gold_m["gold_on"] is True
    assert gold_m["wrote_marinas"] is False
    live_m = asyncio.run(db.marinas.find_one({"_id": "m1"}))
    assert live_m["name"] == "Port Vauban"
    overlay_m = asyncio.run(filter_visible(
        db, "marina", db.marinas.docs, lambda m: m.get("_id")))
    assert [m["_id"] for m in overlay_m] == ["m1"]
    try:
        asyncio.run(toggle_gold(db, "capitainerie", "c1"))
        raise AssertionError("capitainerie Gold without identity+GPS must fail")
    except review_gold.GoldNotReady:
        pass
    asyncio.run(save_choice(db, "capitainerie", "c1", "identity", "keep"))
    asyncio.run(save_choice(db, "capitainerie", "c1", "gps", "keep"))
    try:
        asyncio.run(toggle_gold(db, "capitainerie", "c1"))
        raise AssertionError("displayed phone/VHF must be decided before Gold")
    except review_gold.GoldNotReady:
        pass
    asyncio.run(save_choice(db, "capitainerie", "c1", "field", "keep", field="telephone"))
    asyncio.run(save_choice(db, "capitainerie", "c1", "field", "keep", field="canal_vhf"))
    gold_c = asyncio.run(toggle_gold(db, "capitainerie", "c1"))
    assert gold_c["gold_on"] is True
    assert gold_c["wrote_capitaineries"] is False
    assert gold_c["snapshot"]["fields"]["telephone"] == "+33493900000"
    live_c = asyncio.run(db.capitaineries.find_one({"_id": "c1"}))
    assert live_c["name"] == "Capitainerie Vauban"
    assert len(db.marinas.docs) == n_m
    assert len(db.capitaineries.docs) == n_c


def _prepare_france_gold(db, *, drop_cambridge=True):
    from app.services.review_choices import save_choice

    fiche = asyncio.run(review_queue.get_fiche(db, "eez", "published", "5677"))
    body = fiche["fiche"]
    assert body["sources_td"], "France Review fiche must have TD URLs"
    td0 = body["sources_td"][0]["url"]
    asyncio.run(save_choice(db, "eez", "5677", "td", "keep", url=td0))
    for p in body["ports"]:
        name = (p.get("name") or "").lower()
        action = "drop" if drop_cambridge and "cambridge" in name else "keep"
        asyncio.run(save_choice(
            db, "eez", "5677", "port", action, port_id=p["port_id"]))
        if action != "keep":
            continue
        for rec in p.get("urls_bu") or []:
            if rec.get("url"):
                asyncio.run(save_choice(
                    db, "eez", "5677", "bu", "keep",
                    port_id=p["port_id"], url=rec["url"]))
    return fiche


def test_choice_persists_without_writing_v1():
    from app.services.review_choices import get_choices, save_choice

    db = _db()
    n_ports = len(db.poe_ports.docs)
    out = asyncio.run(save_choice(
        db, "eez", "5677", "td", "keep",
        url="https://douane.gouv.fr/hexagone.pdf"))
    assert out["wrote_poe_ports"] is False
    ch = asyncio.run(get_choices(db, "eez", "5677"))
    assert ch["td"]["https://douane.gouv.fr/hexagone.pdf"] == "keep"
    packed = asyncio.run(review_queue.get_fiche(db, "eez", "published", "5677"))
    assert packed["choices"]["td"]["https://douane.gouv.fr/hexagone.pdf"] == "keep"
    assert packed["gold_ready"] is False
    assert packed["gold_on"] is False
    assert len(db.poe_ports.docs) == n_ports


def test_gold_eez_incomplete_does_not_write_snapshot():
    from app.services.review_gold import reset_eez_pre_gold_cache, toggle_gold

    reset_eez_pre_gold_cache()
    db = _db()
    n_ports = len(db.poe_ports.docs)
    try:
        asyncio.run(toggle_gold(db, "eez", "5677"))
        raise AssertionError("expected GoldNotReady")
    except review_gold.GoldNotReady as e:
        assert "gold incomplete" in str(e)
    assert db.review_gold.docs == []
    assert len(db.poe_ports.docs) == n_ports


def test_gold_france_publishes_snapshot_not_v1():
    from app.services.poe_zone_fiche import build_map_zone_fiche
    from app.services.review_gold import (
        reset_eez_pre_gold_cache,
        toggle_gold,
        visible_eez_mrgids,
        visible_poe_port_docs,
    )

    reset_eez_pre_gold_cache()
    db = _db()
    db.poe_seed_ports.docs.append({
        "mrgid": 5677, "name": "Cambridge",
        "lat": 52.2, "lon": 0.12,
        "judge_sources": ["https://gov.uk/cambridge-port"],
    })
    n_ports = len(db.poe_ports.docs)
    n_v1_ids = {d["_id"] for d in db.poe_ports.docs}
    union = asyncio.run(review_queue.get_fiche(db, "eez", "published", "5677"))
    names = [p["name"] for p in union["fiche"]["ports"]]
    assert "Cambridge" in names
    assert "Marseille" in names
    assert "Sète" in names
    assert union["gold_ready"] is False
    assert asyncio.run(visible_eez_mrgids(db)) == set()
    assert asyncio.run(visible_poe_port_docs(db, mrgid=5677)) == []
    assert asyncio.run(build_map_zone_fiche(db, 5677)) is None
    _prepare_france_gold(db)
    ready = asyncio.run(review_queue.get_fiche(db, "eez", "published", "5677"))
    assert ready["gold_ready"] is True
    on = asyncio.run(toggle_gold(
        db, "eez", "5677",
        fiche=ready["fiche"],
        comment=ready.get("comment") or "",
        choices=ready["choices"],
    ))
    assert on["gold_on"] is True
    assert on["wrote_poe_ports"] is False
    assert on["gold_ready"] is True
    assert len(db.poe_ports.docs) == n_ports
    assert {d["_id"] for d in db.poe_ports.docs} == n_v1_ids
    ov = db.review_gold.docs[0]
    assert ov["on"] is True
    snap_names = [p["name"] for p in ov["snapshot"]["ports"]]
    assert snap_names == ["Marseille", "Sète"]
    assert "Cambridge" not in snap_names
    vis = asyncio.run(visible_eez_mrgids(db))
    assert vis == {5677}
    ports = asyncio.run(visible_poe_port_docs(db, mrgid=5677))
    assert {d["name"] for d in ports} == {"Marseille", "Sète"}
    assert all(str(d["_id"]).startswith("gold:5677:") for d in ports)
    map_fiche = asyncio.run(build_map_zone_fiche(db, 5677))
    assert map_fiche["fiche_scope"] == "gold"
    assert [p["name"] for p in map_fiche["ports"]] == ["Marseille", "Sète"]
    union_after = asyncio.run(review_queue.get_fiche(db, "eez", "published", "5677"))
    assert "Cambridge" in [p["name"] for p in union_after["fiche"]["ports"]]
    assert union_after["fiche"]["fiche_scope"] == "union"
    td_kept = [s["url"] for s in map_fiche["sources_td"]]
    assert ready["fiche"]["sources_td"][0]["url"] in td_kept
    listed = asyncio.run(review_queue.list_queue(db, "eez", "published"))
    fr = next(i for i in listed["items"] if i["id"] == "5677")
    assert fr["gold_on"] is True
    off = asyncio.run(toggle_gold(db, "eez", "5677"))
    assert off["gold_on"] is False
    assert off["wrote_poe_ports"] is False
    assert len(db.poe_ports.docs) == n_ports
    after = asyncio.run(build_map_zone_fiche(db, 5677))
    assert after is None
    hidden = asyncio.run(visible_poe_port_docs(db, mrgid=5677))
    assert hidden == []
    vis_after = asyncio.run(visible_eez_mrgids(db))
    assert 5677 not in vis_after
    still = asyncio.run(review_queue.get_fiche(db, "eez", "published", "5677"))
    assert still["gold_on"] is False
    assert still["gold_ready"] is True
    assert "Marseille" in [p["name"] for p in still["fiche"]["ports"]]


def test_gold_ready_none_and_zero_ports():
    from app.services.review_choices import empty_choices, gold_ready

    none_fiche = {
        "kind": "none", "sources_td": [], "ports": [],
        "unclos": {"code": "article_121"},
    }
    assert gold_ready(none_fiche, empty_choices()) is True
    listed = {
        "kind": "general_list",
        "sources_td": [{"url": "https://gov.example/list.pdf"}],
        "ports": [{"port_id": "5677:x", "name": "X"}],
    }
    assert gold_ready(listed, empty_choices()) is False
    half = {"td": {"https://gov.example/list.pdf": "keep"}, "ports": {}, "bu": {}}
    assert gold_ready(listed, half) is False
    done = {
        "td": {"https://gov.example/list.pdf": "keep"},
        "ports": {"5677:x": "drop"},
        "bu": {},
    }
    assert gold_ready(listed, done) is True

