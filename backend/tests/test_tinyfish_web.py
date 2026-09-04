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
