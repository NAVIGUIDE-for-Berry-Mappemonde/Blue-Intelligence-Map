"""Client Serper — httpx mocké, aucun réseau."""
import asyncio
import json
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import serper as sp  # noqa: E402


class _FakeResp:
    def __init__(self, status, payload=None, content=b"{}"):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        raw = json.dumps(self._payload).encode() if payload is not None else content
        self.content = raw
        self.request = httpx.Request("POST", sp.SEARCH_URL)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=self.request, response=self)


class _FakeClient:
    queue: list = []
    last_json: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kwargs):
        _FakeClient.last_json = kwargs.get("json") or {}
        return _FakeClient.queue.pop(0)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(sp, "SEARCH_RETRY_SLEEP_S", 0)
    monkeypatch.setattr(sp.httpx, "AsyncClient", _FakeClient)
    _FakeClient.queue = []
    _FakeClient.last_json = {}
    yield
    _FakeClient.queue = []


def _run(coro):
    return asyncio.run(coro)


class TestSerperKey:
    def test_empty_without_env(self, monkeypatch):
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
        assert sp.serper_api_key() == ""
        assert sp.serper_api_key({"serper_api_key": "  abc  "}) == "abc"


class TestSerperSearch:
    def test_noop_without_key(self):
        assert _run(sp.serper_search("ports", "")) == []

    def test_maps_organic_only(self):
        _FakeClient.queue = [_FakeResp(200, {
            "organic": [
                {"title": "Dogana", "link": "https://www.dogana.gov.al/x",
                 "snippet": "porteve"},
                {"title": "bad", "link": "not-a-url"},
            ],
            "answerBox": {"link": "https://noonsite.com/albania"},
            "knowledgeGraph": {"website": "https://en.wikipedia.org/wiki/Albania"},
            "peopleAlsoAsk": [{"link": "https://cruisersforum.com/x"}],
        })]
        hits = _run(sp.serper_search("Albania .al", "k", gl="AL", hl="en"))
        assert len(hits) == 1
        assert hits[0]["engine"] == "serper"
        assert hits[0]["domain"] == "dogana.gov.al"
        assert hits[0]["url"] == "https://www.dogana.gov.al/x"
        assert _FakeClient.last_json["num"] == 10
        assert _FakeClient.last_json["gl"] == "al"
        assert _FakeClient.last_json["hl"] == "en"

    def test_402_returns_empty(self):
        _FakeClient.queue = [_FakeResp(402, {"message": "credits"})]
        assert _run(sp.serper_search("ports", "k")) == []

    def test_429_retry_then_ok(self):
        _FakeClient.queue = [
            _FakeResp(429, {}),
            _FakeResp(200, {"organic": [{"link": "https://sis.gov.eg/yacht"}]}),
        ]
        hits = _run(sp.serper_search("Egypt .eg", "k"))
        assert hits[0]["url"] == "https://sis.gov.eg/yacht"
