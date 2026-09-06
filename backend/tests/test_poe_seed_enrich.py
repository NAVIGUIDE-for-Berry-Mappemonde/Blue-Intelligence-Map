"""Enrichissement bottom-up des graines — aucun réseau, aucun Mongo réel."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.tasks import TaskState  # noqa: E402
from app.services import poe_seed_enrich as enr  # noqa: E402
from app.services.poe_seeds import SEED_LEGEND  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class TestJudgePrompt:
    def test_one_seed_line_not_a_zone_list(self):
        doc = {
            "name": "Fort Bay", "lat": 17.62, "lon": -63.25,
            "seed_sources": ["listing", "v1"], "listing_role": "poe",
            "osm_customs": True, "has_coords": True,
            "verify_verdict": "unverified",
        }
        prompt = enr._judge_prompt(doc, {"name": "Saba", "iso2": "BQ"}, "extrait")
        assert "CANDIDAT (une ligne) :" in prompt
        assert "Fort Bay" in prompt
        assert "listing:poe" in prompt
        assert "osm:customs" in prompt
        assert "Juge uniquement CE lieu" in prompt
        assert "Uturoa" not in prompt
        assert SEED_LEGEND[:20] in enr.JUDGE_SYSTEM


class TestParseAndVerdict:
    def test_parse_judge_flags(self):
        assert enr.parse_judge({"is_poe": True, "confidence": 90})["judge_status"] == "accepted"
        assert enr.parse_judge({"is_poe": False})["judge_status"] == "rejected"
        assert enr.parse_judge({"is_poe": None})["judge_status"] == "inconclusive"
        assert enr.parse_judge({})["judge_status"] == "inconclusive"

    def test_apply_keeps_confirmed(self):
        seed = {"verify_verdict": "confirmed", "seed_sources": ["listing", "v1"],
                "has_coords": True}
        assert enr.apply_judge_verdict(seed, {"judge_status": "rejected"}) == "confirmed"

    def test_listing_accepted_becomes_confirmed(self):
        seed = {"verify_verdict": "unverified", "seed_sources": ["listing"],
                "has_coords": True}
        assert enr.apply_judge_verdict(seed, {"judge_status": "accepted"}) == "confirmed"

    def test_accepted_without_listing_is_probable(self):
        seed = {"verify_verdict": "unverified", "seed_sources": ["v1"],
                "has_coords": True}
        assert enr.apply_judge_verdict(seed, {"judge_status": "accepted"}) == "probable"


class TestJudgeLlmEscalate:
    def test_listing_calls_sonnet(self, monkeypatch):
        models = []

        async def fake_complete(system, user, settings=None, *, model=None, **k):
            models.append(model)
            if "sonnet" in (model or ""):
                return {"is_poe": True, "confidence": 91, "reason": "sonnet"}
            return {"is_poe": True, "confidence": 40, "reason": "haiku"}

        async def boom(*a, **k):
            raise AssertionError("OpenRouter should not run after Sonnet decided")

        from app.core import claude
        monkeypatch.setattr(claude, "claude_enabled", lambda s=None: True)
        monkeypatch.setattr(claude, "budget_allows_call", lambda s=None: True)
        monkeypatch.setattr(claude, "complete_json_claude", fake_complete)
        monkeypatch.setattr(enr, "ask_json", boom)

        out = _run(enr._judge_llm(
            {"name": "Nouméa", "seed_sources": ["listing"]},
            {"name": "NC"}, "extrait officiel", {}, lambda m: None))
        assert any(m and "haiku" in m for m in models)
        assert any(m and "sonnet" in m for m in models)
        assert out["judge_engine"] == "claude-sonnet"
        assert out["judge_status"] == "accepted"


class TestEscalate:
    def test_inconclusive_escalates(self):
        assert enr.should_escalate_sonnet({"judge_status": "inconclusive"}, {}) is True

    def test_listing_escalates_even_if_haiku_decided(self):
        doc = {"seed_sources": ["listing"]}
        assert enr.should_escalate_sonnet({"judge_status": "accepted"}, doc) is True

    def test_v1_accepted_stays_on_haiku(self):
        doc = {"seed_sources": ["v1"]}
        assert enr.should_escalate_sonnet({"judge_status": "accepted"}, doc) is False


class TestSelectFetchUrls:
    def test_all_whitelist_up_to_cap(self, monkeypatch):
        monkeypatch.setattr(enr, "url_allowed", lambda u, wl: "gouv.fr" in u)
        hits = [{"url": f"https://douane.gouv.fr/{i}"} for i in range(12)]
        hits.append({"url": "https://blog.com/x"})
        urls = enr.select_fetch_urls(hits, ["gouv.fr"], cap=10)
        assert len(urls) == 10
        assert all("gouv.fr" in u for u in urls)
        assert "https://blog.com/x" not in urls

    def test_empty_without_whitelist_hit(self, monkeypatch):
        monkeypatch.setattr(enr, "url_allowed", lambda u, wl: False)
        urls = enr.select_fetch_urls(
            [{"url": "https://example.com"}], ["gouv.fr"], cap=10)
        assert urls == []


class TestJudgeAgentOnlyIfBlocked:
    def test_no_agent_when_fetch_ok(self, monkeypatch):
        agent_calls = []

        async def fake_search(*a, **k):
            return [{"url": "https://douane.gouv.fr/list", "title": "t", "snippet": "s"}]

        async def fake_fetch(urls, key, **k):
            return {urls[0]: {"text": "Port de Nouméa désigné.", "blocked": False}}

        async def fake_agent(*a, **k):
            agent_calls.append(1)
            return {"is_poe": True, "confidence": 99, "reason": "nope"}

        async def fake_llm(*a, **k):
            return {**enr.parse_judge({"is_poe": True, "confidence": 70, "reason": "ok"}),
                    "judge_engine": "claude-haiku"}

        monkeypatch.setattr(enr, "load_exceptions", lambda: {})
        monkeypatch.setattr(enr, "build_whitelist", lambda *a, **k: ["gouv.fr"])
        monkeypatch.setattr(enr, "url_allowed", lambda u, wl: "gouv.fr" in u)
        monkeypatch.setattr(enr, "tf_api_key", lambda s=None: "k")
        monkeypatch.setattr(enr, "tf_search_pages", fake_search)
        monkeypatch.setattr(enr, "tf_fetch", fake_fetch)
        monkeypatch.setattr(enr, "tf_poe_agent", fake_agent)
        monkeypatch.setattr(enr, "_judge_llm", fake_llm)

        out = _run(enr.judge_one(
            {"name": "Nouméa", "seed_sources": ["listing"]},
            {"name": "NC", "iso2": "NC", "sov_iso2": "FR"},
            {}, lambda m: None))
        assert agent_calls == []
        assert out["judge_agent"] is False
        assert out["judge_status"] == "accepted"
        assert len(out["judge_sources"]) == 1

    def test_agent_when_bot_blocked(self, monkeypatch):
        agent_calls = []

        async def fake_search(*a, **k):
            return [{"url": "https://douane.gouv.fr/list"}]

        async def fake_fetch(urls, key, **k):
            return {urls[0]: {"text": "", "blocked": True, "error": "bot_blocked"}}

        async def fake_agent(url, name, zone, key, **k):
            agent_calls.append(url)
            return {"is_poe": True, "confidence": 88, "reason": "décret",
                    "_agent_profile": "stealth"}

        monkeypatch.setattr(enr, "load_exceptions", lambda: {})
        monkeypatch.setattr(enr, "build_whitelist", lambda *a, **k: ["gouv.fr"])
        monkeypatch.setattr(enr, "url_allowed", lambda u, wl: "gouv.fr" in u)
        monkeypatch.setattr(enr, "tf_api_key", lambda s=None: "k")
        monkeypatch.setattr(enr, "tf_search_pages", fake_search)
        monkeypatch.setattr(enr, "tf_fetch", fake_fetch)
        monkeypatch.setattr(enr, "tf_poe_agent", fake_agent)

        out = _run(enr.judge_one(
            {"name": "Nouméa", "seed_sources": ["listing"]},
            {"name": "NC", "iso2": "NC"},
            {}, lambda m: None, use_agent=True))
        assert agent_calls == ["https://douane.gouv.fr/list"]
        assert out["judge_engine"] == "tinyfish-agent"
        assert out["judge_status"] == "accepted"

    def test_no_agent_flag_skips(self, monkeypatch):
        agent_calls = []

        async def fake_search(*a, **k):
            return [{"url": "https://douane.gouv.fr/list"}]

        async def fake_fetch(urls, key, **k):
            return {urls[0]: {"text": "", "blocked": True, "error": "bot_blocked"}}

        async def fake_agent(*a, **k):
            agent_calls.append(1)
            return {}

        monkeypatch.setattr(enr, "load_exceptions", lambda: {})
        monkeypatch.setattr(enr, "build_whitelist", lambda *a, **k: ["gouv.fr"])
        monkeypatch.setattr(enr, "url_allowed", lambda u, wl: True)
        monkeypatch.setattr(enr, "tf_api_key", lambda s=None: "k")
        monkeypatch.setattr(enr, "tf_search_pages", fake_search)
        monkeypatch.setattr(enr, "tf_fetch", fake_fetch)
        monkeypatch.setattr(enr, "tf_poe_agent", fake_agent)

        out = _run(enr.judge_one(
            {"name": "Nouméa"}, {"name": "NC", "iso2": "NC"},
            {}, lambda m: None, use_agent=False))
        assert agent_calls == []
        assert out["judge_status"] == "inconclusive"


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, n):
        return list(self._docs)


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.updates = []

    def find(self, q, proj=None):
        out = []
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items() if k != "$in" and not isinstance(v, dict)):
                out.append(d)
            elif not q:
                out.append(d)
            elif "run_id" in q and d.get("run_id") == q["run_id"]:
                out.append(d)
            elif "mrgid" in q and isinstance(q["mrgid"], dict) and "$in" in q["mrgid"]:
                if d.get("mrgid") in q["mrgid"]["$in"]:
                    out.append(d)
        return _FakeCursor(out)

    async def update_one(self, q, upd):
        self.updates.append((q, upd))
        return None


class _FakeDB:
    def __init__(self):
        self.poe_run_ports = _FakeColl([{
            "_id": "p1", "run_id": "r1", "name": "Nouméa", "mrgid": 1,
            "verify_verdict": "name_only", "seed_sources": ["listing"],
        }])
        self.poe_runs = _FakeColl([{"_id": "r1"}])
        self.eez_zones = _FakeColl([{
            "mrgid": 1, "name": "NC", "iso2": "NC", "sov_iso2": "FR",
        }])

    async def __getattr_update(self):
        return None


class TestGeocodeAlias:
    def test_geocode_uses_listing_alias(self, monkeypatch):
        seen = []

        async def fake_dual(port, zone, log=None):
            seen.append(port["name"])
            return {"nominatim": [-22.27, 166.44], "geonames": None,
                    "nominatim_meta": {}, "agree": None}

        monkeypatch.setattr(enr, "geocode_port_dual", fake_dual)
        out = _run(enr.geocode_one(
            {"name": "Port autonome de Nouméa", "seed_sources": ["listing"]},
            {"name": "NC", "_geom": None, "_prep": None},
            lambda m: None))
        assert seen == ["Nouméa"]
        assert out["has_coords"] is True
        assert out["geocode_query"] == "Nouméa"
        assert out["lat"] == -22.27


class TestExecuteEnrich:
    def test_does_not_write_poe_ports(self, monkeypatch):
        db = _FakeDB()
        db.poe_ports = _FakeColl([{"_id": "v1", "name": "keep"}])

        async def fake_geo(doc, zone, log):
            return {"lat": -22.27, "lon": 166.44, "has_coords": True,
                    "geocoded_at": "t", "validated": True}

        async def fake_judge(*a, **k):
            return {**enr.parse_judge({"is_poe": True, "confidence": 80, "reason": "ok"}),
                    "judge_engine": "claude-haiku", "judge_at": "t"}

        async def fake_settings():
            return {}

        monkeypatch.setattr(enr, "geocode_one", fake_geo)
        monkeypatch.setattr(enr, "judge_one", fake_judge)
        import app.db as app_db
        monkeypatch.setattr(app_db, "get_settings", fake_settings)

        state = TaskState()
        summary = _run(enr.execute_enrich(
            db, state, run_id="r1", limit=200, verdicts=["name_only"],
            use_agent=False))
        assert summary["wrote_poe_ports"] is False
        assert db.poe_ports.updates == []
        assert db.poe_run_ports.updates
        assert summary["counts"].get("geo_ok") == 1
