"""Enrichissement bottom-up des graines — aucun réseau, aucun Mongo réel."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.tasks import TaskState  # noqa: E402
from app.services import poe_seed_enrich as enr  # noqa: E402
from app.services.poe_seeds import SEARCH_EXCLUDE_DOMAINS, seed_search_query  # noqa: E402


@pytest.fixture(autouse=True)
def _keep_unit_tests_off_nvidia(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")


def _run(coro):
    return asyncio.run(coro)


class TestJudgePrompt:
    def test_name_and_extracts_not_seed_tokens(self):
        doc = {
            "name": "Fort Bay", "lat": 17.62, "lon": -63.25,
            "seed_sources": ["listing", "v1"], "listing_role": "poe",
            "osm_customs": True, "has_coords": True,
            "verify_verdict": "unverified",
            "wpi_commercial": True,
            "seed_line": "Fort Bay | listing:poe · osm:customs · wpi_commercial",
        }
        prompt = enr._judge_prompt(doc, {"name": "Saba", "iso2": "BQ"}, "extrait officiel")
        assert "Candidat : Fort Bay" in prompt
        assert "listing:poe" not in prompt
        assert "osm:customs" not in prompt
        assert "wpi_commercial" not in prompt
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

    def test_catalog_named_does_not_confirm(self):
        named = {"verify_verdict": "unverified", "seed_sources": ["listing"],
                 "has_coords": True}
        assert enr.apply_judge_verdict(named, {"judge_status": "catalog"}) == "unverified"
        name_only = {"verify_verdict": "name_only", "has_coords": True}
        assert enr.apply_judge_verdict(name_only, {"judge_status": "catalog"}) == "unverified"
        no_gps = {"verify_verdict": "name_only"}
        assert enr.apply_judge_verdict(no_gps, {"judge_status": "catalog"}) == "name_only"
        probable = {"verify_verdict": "probable", "has_coords": True}
        assert enr.apply_judge_verdict(probable, {"judge_status": "catalog"}) == "probable"


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


_MX_SCT = """
### **Puertos habilitados**
#### 4.- Ensenada
**Entidad federativa:**Baja California
**Latitud:**31.8522146
**Longitud:**-116.625788
#### 5.- Guaymas
**Entidad federativa:**Sonora
**Latitud:**27.9
**Longitud:**-110.9
#### 34.- Manzanillo
**Entidad federativa:**Colima
**Latitud:**19.057546
**Longitud:**-104.313762
"""
_MX_URL = "https://www.gob.mx/sct/puertos-habilitados"
_ALOFI = (
    "No plant material may be imported into Niue except through "
    "the port of Alofi, the Hanan International Airport, or the Post Office."
)


def _mx_zone():
    return {"mrgid": 8429, "name": "Mexico", "iso2": "MX", "sov_iso2": "MX"}


def _patch_judge_net(monkeypatch, fetch_text=_MX_SCT, hits=None):
    searches = []

    async def fake_search(*a, **k):
        searches.append(1)
        return hits or [{"url": _MX_URL, "title": "SCT", "snippet": "puertos"}]

    async def fake_fetch(urls, key, **k):
        return {u: {"text": fetch_text, "blocked": False} for u in urls}

    monkeypatch.setattr(enr, "load_exceptions", lambda: {})
    monkeypatch.setattr(enr, "build_whitelist", lambda *a, **k: ["gob.mx"])
    monkeypatch.setattr(enr, "url_allowed", lambda u, wl: "gob.mx" in u)
    monkeypatch.setattr(enr, "tf_api_key", lambda s=None: "k")
    monkeypatch.setattr(enr, "tf_search_pages", fake_search)
    monkeypatch.setattr(enr, "tf_fetch", fake_fetch)
    return searches


class TestBuCatalog:
    def test_harvest_detects_sct_and_rejects_alofi_phrase(self):
        found = enr.harvest_bu_catalog(
            {_MX_URL: {"text": _MX_SCT, "blocked": False}}, [_MX_URL])
        names = {p.get("name") for p in found["ports"]}
        assert found["sufficient"] is True
        assert {"Ensenada", "Guaymas", "Manzanillo"} <= names
        assert _MX_URL in found["urls"]
        stripped = enr.harvest_bu_catalog(
            {_MX_URL: {"text": _MX_SCT.strip(), "blocked": False}}, [_MX_URL])
        assert stripped["sufficient"] is True
        assert {"Ensenada", "Guaymas", "Manzanillo"} <= {
            p.get("name") for p in stripped["ports"]}
        lone = enr.harvest_bu_catalog(
            {"https://gov.nu/act": {"text": _ALOFI, "blocked": False}},
            ["https://gov.nu/act"])
        assert lone["sufficient"] is False
        assert any(p.get("name") == "Alofi" for p in lone["ports"])

    def test_named_on_list_skips_llm_and_remembers(self, monkeypatch):
        searches = _patch_judge_net(monkeypatch)
        llm_calls = []
        remembered = []

        async def boom(*a, **k):
            llm_calls.append(1)
            raise AssertionError("juge oui/non interdit si le nom est sur la liste")

        def fake_remember(zone, urls, persist=True, **k):
            remembered.append({"iso2": zone.get("iso2"), "urls": list(urls),
                               "persist": persist})
            return list(urls)

        monkeypatch.setattr(enr, "_judge_llm", boom)
        monkeypatch.setattr(enr, "remember_seed_urls", fake_remember)

        out = _run(enr.judge_one(
            {"name": "Ensenada", "mrgid": 8429, "seed_sources": ["listing"]},
            _mx_zone(), {}, lambda m: None, persist_memory=False))
        assert searches == [1]
        assert llm_calls == []
        assert out["judge_status"] == "catalog"
        assert out["judge_engine"] == "catalog-bu"
        assert out["catalog_named"] is True
        assert out["official_name"] == "Ensenada"
        assert remembered and remembered[0]["iso2"] == "MX"
        assert _MX_URL in remembered[0]["urls"]
        assert remembered[0]["persist"] is False

    def test_residue_calls_llm_and_attaches_sources_bu(self, monkeypatch):
        _patch_judge_net(monkeypatch)
        llm_calls = []

        async def fake_llm(*a, **k):
            llm_calls.append(1)
            return {**enr.parse_judge({"is_poe": None, "reason": "hors liste"}),
                    "judge_engine": "claude-haiku"}

        monkeypatch.setattr(enr, "_judge_llm", fake_llm)
        monkeypatch.setattr(enr, "remember_seed_urls", lambda *a, **k: [])

        out = _run(enr.judge_one(
            {"name": "Puerto Fantasma", "mrgid": 8429, "seed_sources": ["v1"]},
            _mx_zone(), {}, lambda m: None, persist_memory=False))
        assert llm_calls == [1]
        assert out["judge_status"] == "inconclusive"
        assert out["catalog_named"] is False
        assert out["sources_bu"] == [_MX_URL]
        assert out["catalog_bu_n"] >= 3

    def test_second_seed_same_zone_skips_search(self, monkeypatch):
        searches = _patch_judge_net(monkeypatch)
        cache = {}
        monkeypatch.setattr(enr, "remember_seed_urls", lambda *a, **k: [])

        async def boom(*a, **k):
            raise AssertionError("2e graine déjà sur la liste : pas de LLM")

        monkeypatch.setattr(enr, "_judge_llm", boom)
        zone = _mx_zone()
        first = _run(enr.judge_one(
            {"name": "Ensenada", "mrgid": 8429},
            zone, {}, lambda m: None, catalog_cache=cache, persist_memory=False))
        assert first["judge_status"] == "catalog"
        assert searches == [1]
        assert cache.get("sufficient") is True
        second = _run(enr.judge_one(
            {"name": "Guaymas", "mrgid": 8429},
            zone, {}, lambda m: None, catalog_cache=cache, persist_memory=False))
        assert second["judge_status"] == "catalog"
        assert second["judge_engine"] == "catalog-bu"
        assert searches == [1]

    def test_persist_writes_eez_zones_not_poe_ports(self):
        db = _FakeDB()
        db.poe_ports = _FakeColl([{"_id": "v1", "name": "keep"}])
        cache = {
            "sufficient": True,
            "urls": [_MX_URL],
            "ports": [{"name": "Ensenada", "lat": 31.8522146, "lon": -116.625788}],
        }
        _run(enr.persist_bu_catalog(db, {"mrgid": 1, "iso2": "MX"}, cache))
        assert db.poe_ports.updates == []
        assert db.eez_zones.updates
        q, upd, _upsert = db.eez_zones.updates[0]
        assert q == {"mrgid": 1}
        assert upd["$addToSet"]["sources_bu"]["$each"] == [_MX_URL]
        assert upd["$set"]["catalog_bu"][0]["name"] == "Ensenada"
        assert "catalog_bu_at" in upd["$set"]

    def test_execute_enrich_shares_cache_and_counts_catalog(self, monkeypatch):
        db = _FakeDB()
        db.poe_ports = _FakeColl([{"_id": "v1", "name": "keep"}])
        db.poe_seed_ports = _FakeColl([
            {"_id": "e1", "name": "Ensenada", "mrgid": 8429, "lat": 31.85,
             "lon": -116.62, "has_coords": True, "verify_verdict": "unverified",
             "seed_sources": ["listing"]},
            {"_id": "g1", "name": "Guaymas", "mrgid": 8429, "lat": 27.9,
             "lon": -110.9, "has_coords": True, "verify_verdict": "unverified",
             "seed_sources": ["v1"]},
        ])
        db.eez_zones = _FakeColl([{
            "mrgid": 8429, "name": "Mexico", "iso2": "MX", "sov_iso2": "MX",
        }])
        searches = _patch_judge_net(monkeypatch)
        monkeypatch.setattr(enr, "remember_seed_urls", lambda *a, **k: [_MX_URL])

        async def boom(*a, **k):
            raise AssertionError("noms SCT : pas de juge oui/non")

        async def fake_settings():
            return {}

        monkeypatch.setattr(enr, "_judge_llm", boom)
        import app.db as app_db
        monkeypatch.setattr(app_db, "get_settings", fake_settings)

        state = TaskState()
        summary = _run(enr.execute_enrich(
            db, state, source="seeds", limit=0, do_geocode=False,
            verdicts=["unverified"], use_agent=False, concurrency=1,
            persist_memory=False))
        assert summary["wrote_poe_ports"] is False
        assert db.poe_ports.updates == []
        assert summary["counts"].get("judge_catalog") == 2
        assert searches == [1]
        assert db.eez_zones.updates
        assert "sources_bu" in db.eez_zones.updates[0][1]["$addToSet"]
        verdicts = [
            u[1]["$set"].get("judge_status")
            for u in db.poe_seed_ports.updates
            if u[1].get("$set", {}).get("judge_status")
        ]
        assert verdicts == ["catalog", "catalog"]


class TestMinePaidSources:
    def test_select_list_url_drops_noonsite_and_embassy(self):
        items = enr.collect_paid_source_urls([
            {"name": "A", "mrgid": 8429, "judge_sources": [
                "https://www.noonsite.com/country/mx/ensenada",
                "https://www.gob.mx/sct/puertos-habilitados",
                "https://www.mfa.government.bg/en/embassyinfo/india",
            ]},
            {"name": "B", "mrgid": 8429, "judge_sources": [
                "https://www.gob.mx/sct/puertos-habilitados",
            ]},
        ])
        picked = enr.select_mine_urls(items, cap=10)
        urls = [it["url"] for it in picked]
        assert urls == [_MX_URL] or any("habilitados" in u for u in urls)
        assert not any("noonsite" in u for u in urls)
        assert not any("embassyinfo" in u for u in urls)
        assert enr.select_mine_urls(items, cap=1)[0]["url"] == _MX_URL

    def test_mine_fetch_without_search_marks_named(self, monkeypatch):
        db = _FakeDB()
        db.poe_ports = _FakeColl([{"_id": "v1", "name": "keep"}])
        db.poe_seed_ports = _FakeColl([
            {"_id": "e1", "name": "Ensenada", "mrgid": 8429,
             "verify_verdict": "unverified", "has_coords": True,
             "judge_sources": [_MX_URL]},
            {"_id": "f1", "name": "Puerto Fantasma", "mrgid": 8429,
             "verify_verdict": "unverified", "has_coords": True,
             "judge_sources": [_MX_URL]},
            {"_id": "m1", "name": "Manzanillo", "mrgid": 8429,
             "verify_verdict": "probable", "judge_status": "accepted",
             "has_coords": True, "judge_sources": [_MX_URL]},
        ])
        db.eez_zones = _FakeColl([{
            "mrgid": 8429, "name": "Mexico", "iso2": "MX", "sov_iso2": "MX",
        }])
        db.poe_run_ports = _FakeColl([])

        async def boom_search(*a, **k):
            raise AssertionError("mine = 0 Search")

        async def fake_fetch(urls, key, **k):
            return {u: {"text": _MX_SCT, "blocked": False} for u in urls}

        async def fake_settings():
            return {}

        monkeypatch.setattr(enr, "tf_search_pages", boom_search)
        monkeypatch.setattr(enr, "tf_fetch", fake_fetch)
        monkeypatch.setattr(enr, "tf_api_key", lambda s=None: "k")
        monkeypatch.setattr(enr, "remember_seed_urls", lambda *a, **k: [_MX_URL])
        import app.db as app_db
        monkeypatch.setattr(app_db, "get_settings", fake_settings)

        state = TaskState()
        summary = _run(enr.mine_paid_sources(
            db, state, fetch_cap=20, persist_memory=False,
            mark_named=True, judge_residue=False, include_runs=False))
        assert summary["search"] is False
        assert summary["wrote_poe_ports"] is False
        assert db.poe_ports.updates == []
        assert 8429 in summary["eez_catalog"]
        assert _MX_URL in summary["urls_catalog"]
        assert summary["counts"]["named_catalog"] == 1
        assert summary["counts"]["named_kept"] == 1
        assert db.eez_zones.updates
        named = [
            u[1]["$set"]
            for u in db.poe_seed_ports.updates
            if u[1].get("$set", {}).get("judge_status") == "catalog"
        ]
        assert named and named[0].get("official_name") == "Ensenada"

    def test_mine_residue_restricted_to_catalog_eez(self, monkeypatch):
        db = _FakeDB()
        db.poe_seed_ports = _FakeColl([
            {"_id": "e1", "name": "Ensenada", "mrgid": 8429,
             "verify_verdict": "unverified",
             "judge_sources": [_MX_URL]},
        ])
        db.eez_zones = _FakeColl([
            {"mrgid": 8429, "name": "Mexico", "iso2": "MX"},
        ])
        db.poe_run_ports = _FakeColl([])
        seen = {}

        async def fake_fetch(urls, key, **k):
            return {u: {"text": _MX_SCT, "blocked": False} for u in urls}

        async def fake_enrich(*a, **k):
            seen.update(k)
            return {"judge_todo": 1, "counts": {"judge_inconclusive": 1},
                    "run_id": "seed-enrich"}

        async def fake_settings():
            return {}

        monkeypatch.setattr(enr, "tf_fetch", fake_fetch)
        monkeypatch.setattr(enr, "tf_api_key", lambda s=None: "k")
        monkeypatch.setattr(enr, "remember_seed_urls", lambda *a, **k: [])
        monkeypatch.setattr(enr, "execute_enrich", fake_enrich)
        import app.db as app_db
        monkeypatch.setattr(app_db, "get_settings", fake_settings)

        state = TaskState()
        _run(enr.mine_paid_sources(
            db, state, persist_memory=False, mark_named=False,
            judge_residue=True, include_runs=False))
        assert seen.get("residue_only") is True
        assert seen.get("do_geocode") is False
        assert 8429 in set(seen.get("only_mrgids") or [])

    def test_execute_enrich_residue_skips_named(self, monkeypatch):
        db = _FakeDB()
        db.poe_seed_ports = _FakeColl([
            {"_id": "e1", "name": "Ensenada", "mrgid": 8429, "lat": 31.85,
             "lon": -116.62, "has_coords": True, "verify_verdict": "unverified"},
            {"_id": "f1", "name": "Puerto Fantasma", "mrgid": 8429, "lat": 1,
             "lon": 1, "has_coords": True, "verify_verdict": "unverified"},
        ])
        db.eez_zones = _FakeColl([{
            "mrgid": 8429, "name": "Mexico", "iso2": "MX",
            "sources_bu": [_MX_URL],
            "catalog_bu": [
                {"name": "Ensenada", "lat": 31.85, "lon": -116.62},
                {"name": "Guaymas", "lat": 27.9, "lon": -110.9},
                {"name": "Manzanillo", "lat": 19.05, "lon": -104.31},
            ],
        }])
        judged = []

        async def fake_judge(doc, *a, **k):
            judged.append(doc["name"])
            return {**enr.parse_judge({"is_poe": None, "reason": "hors liste"}),
                    "judge_engine": "claude-haiku", "judge_at": "t"}

        async def fake_settings():
            return {}

        monkeypatch.setattr(enr, "judge_one", fake_judge)
        import app.db as app_db
        monkeypatch.setattr(app_db, "get_settings", fake_settings)

        state = TaskState()
        _run(enr.execute_enrich(
            db, state, source="seeds", limit=0, do_geocode=False,
            verdicts=["unverified"], use_agent=False, concurrency=1,
            persist_memory=False, only_mrgids={8429}, residue_only=True))
        assert judged == ["Puerto Fantasma"]
