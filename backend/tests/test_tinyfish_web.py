"""Client TinyFish Search / Fetch — httpx mocké, aucun réseau."""
import asyncio
import json
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import tinyfish as tf  # noqa: E402


class _FakeResp:
    def __init__(self, status, payload=None, content=b"{}"):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        raw = json.dumps(self._payload).encode() if payload is not None else content
        self.content = raw
        self.request = httpx.Request("GET", "https://api.search.tinyfish.ai")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=self.request, response=self)


class _FakeClient:
    queue: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kwargs):
        return _FakeClient.queue.pop(0)

    async def post(self, url, **kwargs):
        return _FakeClient.queue.pop(0)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    tf.reset_rate_limits()
    monkeypatch.setattr(tf, "SEARCH_RETRY_SLEEP_S", 0)
    monkeypatch.setattr(tf.httpx, "AsyncClient", _FakeClient)
    _FakeClient.queue = []
    yield
    _FakeClient.queue = []


def _run(coro):
    return asyncio.run(coro)


class TestTfApiKey:
    def test_empty_without_env(self, monkeypatch):
        monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
        assert tf.tf_api_key() == ""
        assert tf.tf_api_key({"tinyfish_api_key": "  abc  "}) == "abc"


class TestTfSearch:
    def test_noop_without_key(self):
        assert _run(tf.tf_search("ports", "")) == []

    def test_maps_results(self):
        _FakeClient.queue = [_FakeResp(200, {
            "results": [
                {"url": "https://www.douane.gouv.fr/ports", "title": "Ports",
                 "snippet": "liste officielle"},
                {"url": "not-a-url", "title": "x"},
            ]
        })]
        hits = _run(tf.tf_search("ports", "k", location="fr", language="en"))
        assert len(hits) == 1
        assert hits[0]["engine"] == "tinyfish"
        assert hits[0]["domain"] == "douane.gouv.fr"
        assert hits[0]["title"] == "Ports"

    def test_exclude_domains_param(self, monkeypatch):
        seen = []

        class _Client(_FakeClient):
            async def get(self, url, **kwargs):
                seen.append(kwargs.get("params") or {})
                return _FakeClient.queue.pop(0)

        monkeypatch.setattr(tf.httpx, "AsyncClient", _Client)
        _FakeClient.queue = [_FakeResp(200, {"results": []})]
        _run(tf.tf_search(
            "Fort Bay", "k", exclude_domains=["noonsite.com"]))
        assert seen[0]["exclude_domains"] == "noonsite.com"
        assert seen[0]["query"] == "Fort Bay"

    def test_402_returns_empty(self):
        _FakeClient.queue = [_FakeResp(402, {"error": "payment"})]
        assert _run(tf.tf_search("ports", "k")) == []

    def test_429_retry_then_empty(self):
        _FakeClient.queue = [_FakeResp(429, {}), _FakeResp(429, {})]
        assert _run(tf.tf_search("ports", "k")) == []

    def test_429_retry_then_ok(self):
        _FakeClient.queue = [
            _FakeResp(429, {}),
            _FakeResp(200, {"results": [{"url": "https://customs.gov.fj/list"}]}),
        ]
        hits = _run(tf.tf_search("ports", "k"))
        assert hits[0]["url"] == "https://customs.gov.fj/list"


class TestTfFetch:
    def test_noop_without_key(self):
        assert _run(tf.tf_fetch(["https://example.gov"], "")) == {}

    def test_bot_blocked(self):
        url = "https://aduana.gob.mx/list"
        _FakeClient.queue = [_FakeResp(200, {
            "results": [],
            "errors": [{"url": url, "error": "bot_blocked"}],
        })]
        rec = _run(tf.tf_fetch([url], "k"))[url]
        assert rec["blocked"] is True
        assert rec["text"] == ""
        assert rec["level"] == "N3-mirror-tinyfish"

    def test_success_markdown(self):
        url = "https://www.gob.mx/decreto"
        _FakeClient.queue = [_FakeResp(200, {
            "results": [{
                "url": url, "title": "DOF",
                "text": "# Decreto\n\n1.- Ensenada",
                "links": ["https://www.gob.mx/file.pdf"],
            }],
            "errors": [],
        })]
        rec = _run(tf.tf_fetch([url], "k"))[url]
        assert rec["blocked"] is False
        assert "Ensenada" in rec["text"]
        assert rec["links"] == ["https://www.gob.mx/file.pdf"]


class TestPaygQuotas:
    def test_buckets_match_payg_docs(self):
        tf.reset_rate_limits()
        assert tf.SEARCH_RPM == 30
        assert tf.FETCH_RPM == 150
        assert tf.AGENT_CONCURRENCY == 2
        assert tf.AGENT_CREDIT_CAP == 40
        assert tf.FETCH_URL_CAP == 10
        assert tf._search_bucket.cap == 30
        assert tf._fetch_bucket.cap == 150


class TestTfSearchPages:
    def test_page_param_on_later_pages(self, monkeypatch):
        seen = []

        class _Client(_FakeClient):
            async def get(self, url, **kwargs):
                seen.append((kwargs.get("params") or {}).get("page"))
                return _FakeClient.queue.pop(0)

        monkeypatch.setattr(tf.httpx, "AsyncClient", _Client)
        _FakeClient.queue = [
            _FakeResp(200, {"results": [
                {"url": "https://douane.gouv.fr/a"},
                {"url": "https://douane.gouv.fr/b"},
            ]}),
            _FakeResp(200, {"results": []}),
        ]
        hits = _run(tf.tf_search_pages("ports", "k", max_pages=2))
        assert [h["url"] for h in hits] == [
            "https://douane.gouv.fr/a", "https://douane.gouv.fr/b"]
        assert seen[0] is None
        assert seen[1] == 1


class TestTfPoeAgent:
    def test_lite_then_stealth(self, monkeypatch):
        calls = []

        async def fake_sse(url, goal, schema, key, **kw):
            calls.append((kw.get("browser_profile"), (kw.get("agent_config") or {}).get("max_steps")))
            if kw.get("browser_profile") == "lite":
                raise ValueError("blocked")
            return {"is_poe": True, "confidence": 80, "reason": "liste"}

        monkeypatch.setattr(tf, "tf_run_sse", fake_sse)
        out = _run(tf.tf_poe_agent("https://gov.nc/ports", "Nouméa", "NC", "k"))
        assert calls == [("lite", 40), ("stealth", 40)]
        assert out["is_poe"] is True
        assert out["_agent_profile"] == "stealth"
        assert tf.POE_JUDGE_SCHEMA["required"] == ["is_poe", "confidence", "reason"]
        assert "kind" in tf.POE_JUDGE_SCHEMA["properties"]
        assert "kind" not in tf.POE_JUDGE_SCHEMA["required"]

    def test_goal_and_purpose_pleasure_or_mixed_not_cargo(self):
        goal = tf.poe_agent_goal("Nouméa", "New Caledonia", "NC").lower()
        assert "pleasure" in goal
        assert "mixed" in goal
        assert "cargo-only" in goal
        assert "marina is not automatically false" in goal
        assert "foreign vessels" not in goal
        purpose = tf.POE_PURPOSE.lower()
        assert "pleasure" in purpose
        assert "mixed" in purpose
        assert "cargo-only" in purpose
        assert "yacht" in purpose
        assert "excise" in purpose or "kartelë" in purpose


class TestProjectsAgents:
    def test_listing_and_fiche_goals_are_distinct(self):
        listing = tf.listing_goal("Save Our Seas")
        fiche = tf.discovery_goal("Save Our Seas")
        assert listing != fiche
        assert "listing agent" in listing.lower()
        assert "do not collect individual" in listing.lower()
        assert "one individual" in fiche.lower()
        assert "listing_url" in tf.LISTING_SCHEMA["required"]
        assert "projects" in tf.DISCOVERY_SCHEMA["required"]
        assert tf.PROJECTS_LISTING_PURPOSE != tf.PROJECTS_DISCOVERY_PURPOSE
        assert "index page" in tf.PROJECTS_LISTING_PURPOSE.lower()
        assert "not an individual" in tf.PROJECTS_LISTING_PURPOSE.lower()
        assert 60 <= tf.LISTING_AGENT_DURATION_S <= 90
        assert 60 <= tf.FICHE_AGENT_DURATION_S <= 90
        assert tf.LISTING_AGENT_DURATION_S <= tf.FICHE_AGENT_DURATION_S
