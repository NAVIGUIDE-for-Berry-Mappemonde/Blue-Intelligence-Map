"""Découverte visit_url AMP — Fetch / Search, jamais la homepage gestionnaire."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.tasks import TaskState
from app.services import amp as amp_svc
from app.services import amp_visit


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, n=None):
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

    async def find_one(self, q=None, proj=None):
        docs = [d for d in self.docs if self._match_one(d, q or {})]
        return docs[0] if docs else None

    async def update_one(self, q, upd, upsert=False):
        docs = [d for d in self.docs if self._match_one(d, q or {})]
        if not docs:
            if upsert:
                doc = dict(upd.get("$set") or {})
                self.docs.append(doc)
            return None
        docs[0].update(upd.get("$set") or {})
        return None


class _FakeDB:
    def __init__(self, docs):
        self.amp_sites = _FakeColl(docs)


def test_score_rejects_manager_homepage():
    assert amp_visit.score_visit_candidate(
        "https://www.parc-marin.fr/", "https://parc-marin.fr") == 0
    assert amp_visit.score_visit_candidate(
        "https://parc-marin.fr/equipe", "https://parc-marin.fr") == 0


def test_search_query_is_open_web():
    q, host = amp_visit.search_query({
        "name": "Cap de Creus",
        "country": "Spain",
        "manager_url": "https://parcsnaturals.gencat.cat/ca/xarxa-de-parcs/cap-creus/inici",
    })
    assert host == "parcsnaturals.gencat.cat"
    assert "site:" not in q
    assert "Cap de Creus" in q
    assert "visit" in q


def test_search_queries_prefer_same_host_then_open_web():
    scoped, open_q = amp_visit.search_queries({
        "name": "Cap de Creus",
        "country": "Spain",
        "manager_url": "https://parcsnaturals.gencat.cat/ca/xarxa-de-parcs/cap-creus/inici",
    })
    assert scoped[1] == "parcsnaturals.gencat.cat"
    assert scoped[0].startswith("site:parcsnaturals.gencat.cat")
    assert open_q[1] is None
    assert "site:" not in open_q[0]
    assert "Cap de Creus" in open_q[0]


def test_score_prefers_same_domain_procedure_page():
    home = "https://parc-marin.fr"
    visite = amp_visit.score_visit_candidate(
        "https://parc-marin.fr/reglementation-plaisance", home)
    other = amp_visit.score_visit_candidate(
        "https://ofb.gouv.fr/visite-amp", home)
    assert visite > other > 0


def test_search_score_rejects_unrelated_offhost_even_with_visit_hint():
    home = "https://parcsnaturals.gencat.cat/ca/xarxa-de-parcs/cap-creus/inici"
    assert amp_visit.score_visit_candidate(
        "https://www.mom.gov.sg", home,
        title="Visit Singapore", name="Cap de Creus", require_name=True) == 0
    assert amp_visit.score_visit_candidate(
        "https://atraques.es/en/guides/free-anchoring-spain-permitted-bays/",
        home, title="Free anchoring Spain", name="Aiguamolls de l'Alt Empordà",
        require_name=True) == 0
    assert amp_visit.score_visit_candidate(
        "https://ofb.gouv.fr/aires/cap-de-creus/visite",
        home, title="Visite Cap de Creus", name="Cap de Creus",
        require_name=True) > 0


def test_pick_from_fetch_links_never_returns_homepage():
    manager = "https://parc-marin.fr"
    picked = amp_visit.pick_visit_from_urls(manager, [
        "https://parc-marin.fr",
        "https://parc-marin.fr/contact",
        "https://parc-marin.fr/autorisation-mouillage",
    ])
    assert picked == "https://parc-marin.fr/autorisation-mouillage"
    assert not amp_svc.urls_equivalent(picked, manager)


def test_urls_from_fetch_record_reads_links_and_markdown():
    rec = {
        "links": ["https://parc-marin.fr/visite", {"href": "https://parc-marin.fr/contact"}],
        "text": "See also https://parc-marin.fr/plaisance",
    }
    urls = amp_visit.urls_from_fetch_record(rec)
    assert "https://parc-marin.fr/visite" in urls
    assert "https://parc-marin.fr/plaisance" in urls


def test_discover_fetch_then_search_and_keeps_urls_apart():
    docs = [
        {
            "_id": "A", "site_id": "A", "name": "Parc A",
            "manager_url": "https://parc-a.fr",
            "other_helpful_links": "https://parc-a.fr/entrer",
            "visit_url": None, "visit_url_status": "none",
        },
        {
            "_id": "B", "site_id": "B", "name": "Parc B",
            "manager_url": "https://parc-b.fr",
            "other_helpful_links": "",
            "visit_url": None, "visit_url_status": "none",
        },
        {
            "_id": "C", "site_id": "C", "name": "Parc C",
            "manager_url": "https://parc-c.fr",
            "other_helpful_links": "https://parc-c.fr",
            "visit_url": None, "visit_url_status": "none",
        },
        {
            "_id": "D", "site_id": "D", "name": "Parc D",
            "manager_url": "https://parc-d.fr",
            "other_helpful_links": "",
            "visit_url": "https://manual.example/visite",
            "visit_url_status": "found",
            "visit_url_source": "manual",
        },
    ]
    db = _FakeDB(docs)
    state = TaskState()

    async def fetch_many(urls):
        return {
            "https://parc-b.fr": {
                "links": ["https://parc-b.fr/visite-plaisance"],
                "text": "",
            },
            "https://parc-c.fr": {
                "links": ["https://parc-c.fr/"],
                "text": "homepage only",
            },
        }

    async def search(query, include_domains=None):
        if "Parc C" in query:
            return [{"url": "https://parc-c.fr/mouillage", "title": "Mouillage plaisance"}]
        return [{"url": "https://parc-c.fr", "title": "Home"}]

    out = asyncio.run(amp_visit.discover_visit_urls(
        db, state=state, limit=20, skip_search=False,
        fetch_many_fn=fetch_many, search_fn=search, tf_key="test",
        refresh_attrs=False, use_llm_judge=False,
    ))
    by = {d["_id"]: d for d in db.amp_sites.docs}
    assert by["A"]["visit_url"] == "https://parc-a.fr/entrer"
    assert by["A"]["visit_url_source"] == "other_helpful_links"
    assert by["B"]["visit_url"] == "https://parc-b.fr/visite-plaisance"
    assert by["B"]["visit_url_source"] == "tinyfish_fetch"
    assert by["C"]["visit_url"] == "https://parc-c.fr/mouillage"
    assert by["C"]["visit_url_source"] == "tinyfish_search"
    assert by["D"]["visit_url"] == "https://manual.example/visite"
    assert by["D"]["visit_url_source"] == "manual"
    for sid in ("A", "B", "C"):
        assert not amp_svc.urls_equivalent(by[sid]["visit_url"], by[sid]["manager_url"])
    assert out["from_links"] == 1
    assert out["from_fetch"] == 1
    assert out["from_search"] == 1
    assert out["found"] == 3


def test_discover_search_accepts_named_offhost_visit_page():
    docs = [{
        "_id": "F", "site_id": "F", "name": "Cerbère-Banyuls",
        "manager_url": "https://parc-f.fr",
        "other_helpful_links": "",
        "visit_url": None, "visit_url_status": "none",
    }]
    db = _FakeDB(docs)
    state = TaskState()

    async def fetch_many(urls):
        return {u: {"links": [], "text": ""} for u in urls}

    async def search(query, include_domains=None):
        if include_domains:
            return [{"url": "https://www.mom.gov.sg", "title": "Visit Singapore"}]
        return [
            {"url": "https://www.mom.gov.sg", "title": "Visit Singapore"},
            {"url": "https://ofb.gouv.fr/visite-cerbere-banyuls",
             "title": "Visite Cerbère-Banyuls"},
        ]

    out = asyncio.run(amp_visit.discover_visit_urls(
        db, state=state, limit=10, skip_search=False,
        fetch_many_fn=fetch_many, search_fn=search, tf_key="test",
        refresh_attrs=False, use_llm_judge=False,
    ))
    assert db.amp_sites.docs[0]["visit_url"] == "https://ofb.gouv.fr/visite-cerbere-banyuls"
    assert db.amp_sites.docs[0]["visit_url_source"] == "tinyfish_search"
    assert not amp_svc.is_manager_suburl(
        db.amp_sites.docs[0]["visit_url"], "https://parc-f.fr")
    assert out["from_search"] == 1


def test_discover_without_tinyfish_key_keeps_heuristic_only():
    docs = [{
        "_id": "E", "site_id": "E", "name": "Parc E",
        "manager_url": "https://parc-e.fr",
        "other_helpful_links": "",
        "visit_url": None, "visit_url_status": "none",
    }]
    db = _FakeDB(docs)
    state = TaskState()
    out = asyncio.run(amp_visit.discover_visit_urls(
        db, state=state, limit=10, tf_key="",
        fetch_many_fn=lambda urls: (_ for _ in ()).throw(AssertionError("no fetch")),
        refresh_attrs=False, use_llm_judge=False,
    ))
    assert out["no_tinyfish_key"] is True
    assert out["from_fetch"] == 0
    assert db.amp_sites.docs[0]["visit_url"] is None or not db.amp_sites.docs[0].get("visit_url")


def test_parse_visit_judge_only_accepts_listed_url():
    cands = [{"url": "https://ofb.gouv.fr/visite-cerbere", "title": "Visite"}]
    assert amp_visit.parse_visit_judge(
        {"accept": True, "url": "https://ofb.gouv.fr/visite-cerbere"},
        cands, "https://parc.fr") == "https://ofb.gouv.fr/visite-cerbere"
    assert amp_visit.parse_visit_judge(
        {"accept": True, "url": "https://evil.example/invented"},
        cands, "https://parc.fr") is None
    assert amp_visit.parse_visit_judge(
        {"accept": False, "url": "https://ofb.gouv.fr/visite-cerbere"},
        cands, "https://parc.fr") is None
    assert amp_visit.parse_visit_judge(
        {"accept": True, "url": "https://parc.fr"},
        [{"url": "https://parc.fr", "title": "Home"}],
        "https://www.parc.fr/") is None


def test_discover_refresh_then_links_without_tinyfish():
    docs = [{
        "_id": "G", "site_id": "G", "name": "Cerbère-Banyuls",
        "manager_url": "https://reserve website|https://www.reserves-naturelles.org/cerbere-banyuls",
        "other_helpful_links": "",
        "visit_url": None, "visit_url_status": "none",
    }]
    db = _FakeDB(docs)
    state = TaskState()

    async def fetch_attrs(ids):
        return {"G": {
            "url": (
                "Reserve website|https://www.reserves-naturelles.org/cerbere-banyuls; "
                "OFB website|http://www.amp.afbiodiversite.fr/accueil_fr/fiche"
            ),
            "other_helpful_links": "",
        }}

    out = asyncio.run(amp_visit.discover_visit_urls(
        db, state=state, limit=10, tf_key="",
        refresh_attrs=True, attrs_fetch_fn=fetch_attrs, use_llm_judge=False,
    ))
    assert out["attrs_refreshed"] == 1
    assert out["from_links"] == 1
    assert "afbiodiversite.fr" in db.amp_sites.docs[0]["visit_url"]
    assert db.amp_sites.docs[0]["manager_url"] == "https://reserves-naturelles.org/cerbere-banyuls"
    assert not amp_svc.urls_equivalent(
        db.amp_sites.docs[0]["visit_url"], db.amp_sites.docs[0]["manager_url"])


def test_discover_search_uses_injected_judge():
    docs = [{
        "_id": "H", "site_id": "H", "name": "Cerbère-Banyuls",
        "manager_url": "https://parc-h.fr",
        "other_helpful_links": "",
        "visit_url": None, "visit_url_status": "none",
    }]
    db = _FakeDB(docs)
    state = TaskState()

    async def fetch_many(urls):
        return {u: {"links": [], "text": ""} for u in urls}

    async def search(query, include_domains=None):
        return [
            {"url": "https://yachtmate.fr/blog/en/anchoring-regulations-france.html",
             "title": "Anchoring France"},
            {"url": "https://ofb.gouv.fr/visite-cerbere-banyuls",
             "title": "Visite Cerbère-Banyuls"},
        ]

    async def judge(doc, cands):
        for cand in cands:
            if "ofb.gouv.fr" in cand["url"]:
                doc["visit_url_judge"] = "nvidia-muse"
                return cand["url"]
        return None

    out = asyncio.run(amp_visit.discover_visit_urls(
        db, state=state, limit=10, skip_search=False,
        fetch_many_fn=fetch_many, search_fn=search, tf_key="test",
        refresh_attrs=False, use_llm_judge=True, judge_fn=judge,
    ))
    assert db.amp_sites.docs[0]["visit_url"] == "https://ofb.gouv.fr/visite-cerbere-banyuls"
    assert db.amp_sites.docs[0]["visit_url_judge"] == "nvidia-muse"
    assert out["from_search"] == 1


def test_discover_judge_can_reject_every_hit():
    docs = [{
        "_id": "I", "site_id": "I", "name": "Cap de Creus",
        "manager_url": "https://parc-i.fr",
        "other_helpful_links": "",
        "visit_url": None, "visit_url_status": "none",
    }]
    db = _FakeDB(docs)
    state = TaskState()

    async def fetch_many(urls):
        return {u: {"links": [], "text": ""} for u in urls}

    async def search(query, include_domains=None):
        return [{"url": "https://www.mom.gov.sg", "title": "Visit Singapore"}]

    async def judge(doc, cands):
        return None

    out = asyncio.run(amp_visit.discover_visit_urls(
        db, state=state, limit=10, skip_search=False,
        fetch_many_fn=fetch_many, search_fn=search, tf_key="test",
        refresh_attrs=False, use_llm_judge=True, judge_fn=judge,
    ))
    assert not db.amp_sites.docs[0].get("visit_url")
    assert out["from_search"] == 0
