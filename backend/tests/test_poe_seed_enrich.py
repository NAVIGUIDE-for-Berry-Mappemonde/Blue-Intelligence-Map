"""Enrichissement bottom-up des graines — aucun réseau, aucun Mongo réel."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.tasks import TaskState  # noqa: E402
from app.services import poe_seed_enrich as enr  # noqa: E402
from app.services.poe_seeds import SEARCH_EXCLUDE_DOMAINS, seed_search_query  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class TestJudgePrompt:
    def test_name_and_extracts_not_seed_tokens(self):
        doc = {
            "name": "Fort Bay", "lat": 17.62, "lon": -63.25,
            "seed_sources": ["listing", "v1"], "listing_role": "poe",
            "osm_customs": True, "has_coords": True,
            "verify_verdict": "unverified",
            "seed_line": "Fort Bay | listing:poe · osm:customs",
        }
        prompt = enr._judge_prompt(doc, {"name": "Saba", "iso2": "BQ"}, "extrait officiel")
        assert "Candidat : Fort Bay" in prompt
        assert "listing:poe" not in prompt
        assert "osm:customs" not in prompt
        assert "extrait officiel" in prompt
        assert "Uturoa" not in prompt

    def test_system_requires_pleasure_or_mixed_not_cargo(self):
        sys = enr.JUDGE_SYSTEM.lower()
        assert "plaisance" in sys
        assert "mixte" in sys
        assert "cargo" in sys
        assert "kind" in sys
        assert "marina n'est pas false automatique" in sys
        assert "false si les sources parlent d'autre chose (marina" not in sys


class TestSearchFromSeed:
    def test_query_is_the_port_name(self):
        q = seed_search_query({
            "name": "Fort Bay", "zone_name": "Saba", "listing_role": "poe",
        })
        assert q.startswith("Fort Bay ")
        assert "port of entry" in q
        assert "Saba" in q
        assert "noonsite" not in q.lower()
        assert "listing:poe" not in q

    def test_drop_noonsite_hits(self):
        hits = [
            {"url": "https://www.noonsite.com/country/bq/fort-bay"},
            {"url": "https://douane.gouv.fr/ports"},
        ]
        kept = enr.drop_excluded_hits(hits)
        assert [h["url"] for h in kept] == ["https://douane.gouv.fr/ports"]
        assert SEARCH_EXCLUDE_DOMAINS == ("noonsite.com",)

    def test_select_fetch_skips_noonsite(self, monkeypatch):
        monkeypatch.setattr(enr, "url_allowed", lambda u, wl: True)
        urls = enr.select_fetch_urls([
            {"url": "https://www.noonsite.com/x"},
            {"url": "https://douane.gouv.fr/y"},
        ], ["gouv.fr"], cap=10)
        assert urls == ["https://douane.gouv.fr/y"]


class TestParseAndVerdict:
    def test_parse_judge_flags(self):
        assert enr.parse_judge({"is_poe": True, "confidence": 90})["judge_status"] == "accepted"
        assert enr.parse_judge({"is_poe": False})["judge_status"] == "rejected"
        assert enr.parse_judge({"is_poe": None})["judge_status"] == "inconclusive"
        assert enr.parse_judge({})["judge_status"] == "inconclusive"
        assert enr.parse_judge({"is_poe": True})["judge_kind"] == "unknown"

    def test_parse_judge_pleasure_or_mixed_accepted(self):
        pleasure = enr.parse_judge({
            "is_poe": True, "confidence": 90, "kind": "pleasure"})
        assert pleasure["judge_status"] == "accepted"
        assert pleasure["judge_kind"] == "pleasure"
        mixed = enr.parse_judge({
            "is_poe": True, "confidence": 80, "kind": "mixed"})
        assert mixed["judge_status"] == "accepted"
        assert mixed["judge_kind"] == "mixed"
        marina = enr.parse_judge({
            "is_poe": True, "kind": "pleasure",
            "reason": "clearance officielle à cette marina"})
        assert marina["judge_status"] == "accepted"

    def test_parse_judge_cargo_forced_rejected(self):
        out = enr.parse_judge({
            "is_poe": True, "confidence": 95, "kind": "cargo",
            "reason": "designated commercial port"})
        assert out["judge_status"] == "rejected"
        assert out["judge_kind"] == "cargo"
        for alias in ("commercial", "freight", "industrial"):
            forced = enr.parse_judge({"is_poe": True, "kind": alias})
            assert forced["judge_status"] == "rejected"
            assert forced["judge_kind"] == "cargo"

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

    def test_listing_cargo_rejected_stays_unverified(self):
        seed = {"verify_verdict": "unverified", "seed_sources": ["listing"],
                "has_coords": True}
        judge = enr.parse_judge({"is_poe": True, "kind": "cargo"})
        assert judge["judge_status"] == "rejected"
        assert enr.apply_judge_verdict(seed, judge) == "unverified"


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

    def test_cargo_kind_rejected_without_listing_escalation(self, monkeypatch):
        async def fake_complete(system, user, settings=None, *, model=None, **k):
            return {"is_poe": True, "confidence": 90, "kind": "cargo",
                    "reason": "terminal conteneur"}

        async def boom(*a, **k):
            raise AssertionError("OpenRouter should not run after cargo reject")

        from app.core import claude
        monkeypatch.setattr(claude, "claude_enabled", lambda s=None: True)
        monkeypatch.setattr(claude, "budget_allows_call", lambda s=None: True)
        monkeypatch.setattr(claude, "complete_json_claude", fake_complete)
        monkeypatch.setattr(enr, "ask_json", boom)

        out = _run(enr._judge_llm(
            {"name": "Port Commerce", "seed_sources": ["v1"]},
            {"name": "XX"}, "terminal conteneur", {}, lambda m: None))
        assert out["judge_status"] == "rejected"
        assert out["judge_kind"] == "cargo"
        assert out["judge_engine"] == "claude-haiku"
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
        seen_search = []

        async def fake_search(query, key, **k):
            seen_search.append({"query": query, **k})
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
            {"name": "Nouméa", "seed_sources": ["listing"],
             "search_query": "Nouméa official port of entry OR clearance NC"},
            {"name": "NC", "iso2": "NC", "sov_iso2": "FR"},
            {}, lambda m: None))
        assert agent_calls == []
        assert out["judge_agent"] is False
        assert out["judge_status"] == "accepted"
        assert len(out["judge_sources"]) == 1
        assert seen_search[0]["query"].startswith("Nouméa")
        assert seen_search[0]["exclude_domains"] == ("noonsite.com",)

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

    async def update_one(self, q, upd, upsert=False):
        self.updates.append((q, upd, upsert))
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
            db, state, run_id="r1", source="run", limit=200,
            verdicts=["name_only"], use_agent=False))
        assert summary["wrote_poe_ports"] is False
        assert db.poe_ports.updates == []
        assert db.poe_run_ports.updates
        assert summary["counts"].get("geo_ok") == 1

    def test_seeds_source_writes_seed_collection(self, monkeypatch):
        db = _FakeDB()
        db.poe_ports = _FakeColl([{"_id": "v1", "name": "keep"}])
        db.poe_seed_ports = _FakeColl([{
            "_id": "s1", "name": "Nouméa", "mrgid": 1,
            "verify_verdict": "name_only", "seed_sources": ["listing"],
            "search_query": "Nouméa official port of entry",
        }])

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
            db, state, source="seeds", limit=200,
            verdicts=["name_only"], use_agent=False))
        assert summary["source"] == "seeds"
        assert summary["wrote_poe_ports"] is False
        assert db.poe_ports.updates == []
        assert db.poe_run_ports.updates == []
        assert db.poe_seed_ports.updates

    def test_limit_zero_geocodes_before_judge_without_duplicate(self, monkeypatch):
        db = _FakeDB()
        db.poe_seed_ports = _FakeColl([
            {"_id": "n1", "name": "OnlyName", "mrgid": 1,
             "verify_verdict": "name_only", "seed_sources": ["listing"]},
            {"_id": "u1", "name": "AlreadyXY", "mrgid": 1, "lat": 1, "lon": 2,
             "has_coords": True, "verify_verdict": "unverified",
             "seed_sources": ["v1"]},
        ])
        judged = []

        async def fake_geo(doc, zone, log):
            return {"lat": -22.27, "lon": 166.44, "has_coords": True,
                    "geocoded_at": "t", "validated": True}

        async def fake_judge(doc, *a, **k):
            judged.append(doc["name"])
            return {**enr.parse_judge({"is_poe": False, "confidence": 10, "reason": "x"}),
                    "judge_engine": "claude-haiku", "judge_at": "t"}

        async def fake_settings():
            return {}

        monkeypatch.setattr(enr, "geocode_one", fake_geo)
        monkeypatch.setattr(enr, "judge_one", fake_judge)
        import app.db as app_db
        monkeypatch.setattr(app_db, "get_settings", fake_settings)

        state = TaskState()
        _run(enr.execute_enrich(
            db, state, source="seeds", limit=0,
            verdicts=["name_only", "unverified"], use_agent=False))
        assert judged.count("OnlyName") == 1
        assert judged.count("AlreadyXY") == 1
        assert set(judged) == {"OnlyName", "AlreadyXY"}


class TestPickGeocode:
    def test_agree_near_eez_keeps_point(self, monkeypatch):
        monkeypatch.setattr(enr, "classify_poe_point", lambda *a, **k: {
            "validated": False, "kind": "other_water", "dist_km": 3.4,
        })
        out = enr.pick_geocode(
            {"nominatim": [-38.147, 144.361],
             "geonames": [-38.149, 144.357],
             "agree": True},
            {"name": "Geelong"},
            {"iso2": "AU"},
            object(),
            None,
        )
        assert out["lat"] == -38.147
        assert out["has_coords"] is True
        assert out["geocode_arbitration"] == "agree_near_eez"
        assert out["validated"] is True

    def test_outside_persists_rejected_coords(self, monkeypatch):
        monkeypatch.setattr(enr, "classify_poe_point", lambda *a, **k: {
            "validated": False, "kind": "other_water", "dist_km": 2.3,
        })
        out = enr.pick_geocode(
            {"nominatim": [43.216, 5.537], "agree": False},
            {"name": "Cassis"},
            {"iso2": "FR"},
            object(),
            None,
        )
        assert out["lat"] is None
        assert out["has_coords"] is False
        assert out["geocode_arbitration"] == "spatial_rejected"
        assert out["geocode_rejected_lat"] == 43.216
        assert out["geocode_rejected_lon"] == 5.537
        assert out["geocode_rejected_source"] == "nominatim"
