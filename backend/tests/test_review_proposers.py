"""Proposer Review hors Formalités : AMP, Projets, marinas, capitaineries."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.tasks import TaskState
from app.services.review_amp_picker import local_pick_amp, merge_amp
from app.services.review_field_picker import local_pick_fields
from app.services.review_lessons import (
    get_proposal,
    lesson_key,
    load_lessons,
    proposal_key,
)
from app.services.review_project_picker import local_pick_project, merge_project
from app.services.review_suggest import run_suggest_batch, suggest_one
from app.services import review_gold, review_queue
from test_review_queue import _db


def _no_llm_amp(monkeypatch):
    async def _none(*_a, **_k):
        return None
    monkeypatch.setattr(
        "app.services.review_amp_picker._llm_pick_amp", _none)


def _no_llm_project(monkeypatch):
    async def _none(*_a, **_k):
        return None
    monkeypatch.setattr(
        "app.services.review_project_picker._llm_pick_project", _none)


def test_amp_local_keeps_visit_drops_manager():
    manager = "https://parc-marin.fr"
    visit = "https://parc-marin.fr/visite"
    picked = local_pick_amp({
        "name": "Parc marin du cap",
        "site_id": "PS-1",
        "manager_url": manager,
        "visit_candidates": [
            {"url": manager, "same_as_manager": True},
            {"url": visit, "title": "Visite et mouillage"},
            {"url": "https://parc-marin.fr/a-propos"},
        ],
    })
    assert visit in picked["keep"]
    assert manager in picked["drop"]
    assert visit not in picked["drop"]
    assert picked["no_visit"] is False
    assert picked["engine"] == "local"


def test_amp_local_no_visit_when_only_manager():
    manager = "https://authority.example"
    picked = local_pick_amp({
        "name": "Empty reserve",
        "site_id": "PS-empty",
        "manager_url": manager,
        "visit_candidates": [
            {"url": manager, "same_as_manager": True},
        ],
    })
    assert picked["keep"] == []
    assert picked["no_visit"] is True
    assert manager in picked["drop"]


def test_amp_merge_rejects_invented_url():
    local = {
        "keep": ["https://parc-marin.fr/visite"],
        "drop": ["https://parc-marin.fr"],
        "no_visit": False,
        "comment": "local",
    }
    llm = {
        "keep": ["https://invented.example/permit", "https://parc-marin.fr/visite"],
        "drop": ["https://parc-marin.fr"],
        "no_visit": False,
        "comment": "LLM",
        "engine": "nvidia-deepseek",
    }
    allowed = {"https://parc-marin.fr/visite", "https://parc-marin.fr"}
    merged = merge_amp(local, llm, allowed, "https://parc-marin.fr")
    assert merged["keep"] == ["https://parc-marin.fr/visite"]
    assert "https://invented.example/permit" not in merged["keep"]
    assert merged["engine"] == "nvidia-deepseek"


def test_suggest_amp_does_not_gold_or_write_live(monkeypatch):
    _no_llm_amp(monkeypatch)
    db = _db()
    n_amp = len(db.amp_sites.docs)
    live = asyncio.run(db.amp_sites.find_one({"_id": "PS-1"}))
    out = asyncio.run(suggest_one(db, "amp", "PS-1", settings={}))
    assert out["kind"] == "amp"
    assert out["gold_on"] is False
    assert out["wrote_amp_sites"] is False
    assert out["wrote_poe_ports"] is False
    assert "https://parc-marin.fr" in (out["choices"].get("visit") or {})
    assert out["choices"]["visit"]["https://parc-marin.fr"] == "drop"
    visit = out["choices"]["visit"]
    assert visit.get("https://parc-marin.fr/visite") == "keep"
    prop = asyncio.run(get_proposal(db, "PS-1", "amp"))
    assert prop is not None
    assert prop["_id"] == proposal_key("PS-1", "amp")
    assert prop["kind"] == "amp"
    after = asyncio.run(db.amp_sites.find_one({"_id": "PS-1"}))
    assert after == live
    assert len(db.amp_sites.docs) == n_amp
    assert not db.review_gold.docs


def test_amp_gold_records_lesson_and_report_miss(monkeypatch):
    from app.services.review_choices import save_choice
    from app.services.review_report import build_report, report_markdown

    _no_llm_amp(monkeypatch)
    db = _db()
    asyncio.run(suggest_one(db, "amp", "PS-1", settings={}))
    asyncio.run(save_choice(db, "amp", "PS-1", "no_visit", "keep"))
    packed = asyncio.run(review_queue.get_fiche(db, "amp", "published", "PS-1"))
    golded = asyncio.run(review_gold.toggle_gold(
        db, "amp", "PS-1",
        fiche=packed["fiche"],
        comment=packed.get("comment") or "",
        choices=packed["choices"],
    ))
    assert golded["gold_on"] is True
    assert golded["wrote_amp_sites"] is False
    lessons = asyncio.run(load_lessons(db, kind="amp"))
    assert lessons
    assert lessons[0]["_id"] == lesson_key("PS-1", "amp")
    assert lessons[0]["kind"] == "amp"
    assert lessons[0]["had_proposal"] is True
    urls = {e["url"] for e in lessons[0]["errors"]}
    assert "https://parc-marin.fr/visite" in urls
    assert any(
        e["proposer"] == "keep" and e["human"] == "drop"
        for e in lessons[0]["errors"]
        if e["url"] == "https://parc-marin.fr/visite")

    only_eez = asyncio.run(load_lessons(db, kind="eez"))
    assert all((les.get("kind") or "eez") == "eez" for les in only_eez)

    rep = asyncio.run(build_report(db, "all"))
    misses = rep["pipeline_actions"]["proposer_errors"]
    assert any(m["kind"] == "amp" and m["url"] == "https://parc-marin.fr/visite"
               for m in misses)
    assert rep["summary"]["amp"]["proposer_errors"] >= 1
    md = report_markdown(rep)
    assert "Proposer s'est trompé ici" in md
    assert "AMP" in md
    assert "parc-marin.fr/visite" in md


def test_project_local_drops_donate_and_snapped():
    picked = local_pick_project({
        "title": "Reef restore",
        "urls": [
            "https://ngo.example/",
            "https://ngo.example/donate",
            "https://ngo.example/projects/reef-restore",
        ],
        "sites": [
            {"site_id": "ok", "name": "Azores reef",
             "lat": 38.5, "lon": -28.0},
            {"site_id": "snap", "name": "HQ", "lat": 38.9, "lon": -77.0,
             "snapped": True, "geo_source": "snap_to_ocean"},
        ],
    })
    assert "https://ngo.example/donate" in picked["drop_urls"]
    assert "https://ngo.example/" in picked["drop_urls"]
    assert "https://ngo.example/projects/reef-restore" in picked["keep_urls"]
    assert "ok" in picked["keep_sites"]
    assert "snap" in picked["drop_sites"]
    assert "site:snap" in picked["drop"]
    assert "site:ok" in picked["keep"]


def test_project_merge_rejects_invented_url_and_site():
    local = {
        "keep_urls": ["https://ngo.example/projects/reef-restore"],
        "drop_urls": ["https://ngo.example/donate"],
        "keep_sites": ["ok"],
        "drop_sites": ["snap"],
        "comment": "local",
    }
    llm = {
        "keep_urls": [
            "https://invented.example/secret",
            "https://ngo.example/projects/reef-restore",
        ],
        "drop_urls": ["https://ngo.example/donate"],
        "keep_sites": ["ok", "invented-site"],
        "drop_sites": ["snap"],
        "comment": "LLM",
        "engine": "nvidia-deepseek",
    }
    merged = merge_project(
        local, llm,
        {"https://ngo.example/projects/reef-restore",
         "https://ngo.example/donate"},
        {"ok", "snap"},
    )
    assert "https://invented.example/secret" not in merged["keep_urls"]
    assert "invented-site" not in merged["keep_sites"]
    assert merged["keep_urls"] == ["https://ngo.example/projects/reef-restore"]
    assert merged["keep_sites"] == ["ok"]


def test_suggest_project_does_not_write_live(monkeypatch):
    _no_llm_project(monkeypatch)
    db = _db()
    db.projects.docs.append({
        "_id": "p-donate",
        "title": "Reef restore",
        "url": "https://ngo.example/projects/reef-restore",
        "urls": [
            "https://ngo.example/donate",
            "https://ngo.example/projects/reef-restore",
        ],
        "sites": [
            {"site_id": "ok", "name": "Azores reef",
             "lat": 38.5, "lon": -28.0},
            {"site_id": "snap", "name": "HQ", "lat": 38.9, "lon": -77.0,
             "snapped": True},
        ],
    })
    n_proj = len(db.projects.docs)
    out = asyncio.run(suggest_one(db, "project", "p-donate", settings={}))
    assert out["gold_on"] is False
    assert out["wrote_projects"] is False
    assert out["choices"]["urls"].get("https://ngo.example/donate") == "drop"
    assert out["choices"]["urls"].get(
        "https://ngo.example/projects/reef-restore") == "keep"
    assert out["choices"]["sites"].get("snap") == "drop"
    assert out["choices"]["sites"].get("ok") == "keep"
    prop = asyncio.run(get_proposal(db, "p-donate", "project"))
    assert prop["_id"] == "project:p-donate"
    assert len(db.projects.docs) == n_proj
    assert not db.review_gold.docs


def test_marina_local_drops_ota_and_unsourced_vhf():
    picked = local_pick_fields({
        "name": "Port Fake",
        "osm_id": "node/99",
        "lat": 43.0,
        "lon": 6.0,
        "website": "https://www.tripadvisor.com/Hotel_Review-foo",
        "canal_vhf": "16",
        "places_visiteurs": 40,
        "tags": {"berths": "40"},
        "field_sources": {"places_visiteurs": "osm"},
    }, "marina")
    assert picked["identity"] == "keep"
    assert picked["gps"] == "keep"
    assert "https://www.tripadvisor.com/Hotel_Review-foo" in picked["url_drop"]
    assert picked["fields"].get("canal_vhf") == "drop"
    assert picked["fields"].get("places_visiteurs") == "keep"
    assert "field:canal_vhf" in picked["drop"]
    assert "field:places_visiteurs" in picked["keep"]


def test_capitainerie_local_overlay_and_unsourced_phone():
    picked = local_pick_fields({
        "name": "Capitainerie Fake",
        "osm_id": "node/2",
        "lat": 43.58,
        "lon": 7.13,
        "shom_id": "SHOM-1",
        "telephone": "+33490000000",
        "canal_vhf": "9",
        "tags": {},
    }, "capitainerie")
    assert picked["identity"] == "keep"
    assert picked["gps"] == "keep"
    assert picked["overlay"] == "keep"
    assert picked["fields"].get("telephone") == "drop"
    assert picked["fields"].get("canal_vhf") == "drop"


def test_suggest_marina_one_fiche_not_gold(monkeypatch):
    db = _db()
    db.marinas.docs.append({
        "_id": "m-ota",
        "name": "Fake haven",
        "lat": 43.0,
        "lon": 6.0,
        "osm_id": "node/99",
        "website": "https://www.tripadvisor.com/Hotel_Review-foo",
        "canal_vhf": "16",
        "tags": {"name": "Fake haven"},
    })
    n_m = len(db.marinas.docs)
    live = asyncio.run(db.marinas.find_one({"_id": "m-ota"}))
    out = asyncio.run(suggest_one(db, "marina", "m-ota"))
    assert out["kind"] == "marina"
    assert out["gold_on"] is False
    assert out["wrote_marinas"] is False
    assert out["choices"]["identity"] == "keep"
    assert out["choices"]["gps"] == "keep"
    assert out["choices"]["urls"].get(
        "https://www.tripadvisor.com/Hotel_Review-foo") == "drop"
    assert out["choices"]["fields"].get("canal_vhf") == "drop"
    prop = asyncio.run(get_proposal(db, "m-ota", "marina"))
    assert prop["_id"] == "marina:m-ota"
    after = asyncio.run(db.marinas.find_one({"_id": "m-ota"}))
    assert after == live
    assert len(db.marinas.docs) == n_m
    assert not db.review_gold.docs


def test_batch_rejected_for_marina_and_runs_amp(monkeypatch):
    _no_llm_amp(monkeypatch)
    db = _db()
    state = TaskState()
    with pytest.raises(ValueError, match="batch Proposer"):
        asyncio.run(run_suggest_batch(db, "marina", state))

    called = []

    async def fake_amp(db, eid, **_k):
        called.append(str(eid))
        return {"id": eid, "engine": "local", "choices": {"visit": {}}}

    monkeypatch.setattr(
        "app.services.review_amp_picker.suggest_amp_documents", fake_amp)
    out = asyncio.run(run_suggest_batch(db, "amp", TaskState(), settings={}))
    assert "PS-1" in called
    assert out["ok"] == len(called)
    assert out["kind"] == "amp"


def test_legacy_eez_proposal_key_still_readable():
    db = _db()
    asyncio.run(db.review_suggest.update_one(
        {"_id": "5677"},
        {"$set": {
            "_id": "5677", "kind": "eez", "entity_id": "5677",
            "keep": ["https://a.example/list"], "drop": [],
            "engine": "local",
        }},
        upsert=True,
    ))
    got = asyncio.run(get_proposal(db, "5677", "eez"))
    assert got is not None
    assert got["keep"] == ["https://a.example/list"]
