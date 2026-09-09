"""searx_instances — URL locale toujours en tête, sans doublon."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.poe_pipeline import (  # noqa: E402
    LOCAL_SEARXNG_URL,
    SEARX_PUBLIC_INSTANCES,
    configured_searxng_url,
    searx_instances,
)


class TestSearxInstances:
    def test_defaults_to_loopback_when_env_empty(self, monkeypatch):
        monkeypatch.setenv("SEARXNG_URL", "")
        assert configured_searxng_url() == LOCAL_SEARXNG_URL
        inst = searx_instances()
        assert inst[0] == LOCAL_SEARXNG_URL
        assert inst.count(LOCAL_SEARXNG_URL) == 1
        for pub in SEARX_PUBLIC_INSTANCES:
            assert pub.rstrip("/") in inst

    def test_defaults_to_loopback_when_env_absent(self, monkeypatch):
        monkeypatch.delenv("SEARXNG_URL", raising=False)
        assert configured_searxng_url() == LOCAL_SEARXNG_URL
        assert searx_instances()[0] == LOCAL_SEARXNG_URL

    def test_env_url_wins_without_duplicate(self, monkeypatch):
        monkeypatch.setenv("SEARXNG_URL", "http://127.0.0.1:8888/")
        inst = searx_instances()
        assert inst[0] == "http://127.0.0.1:8888"
        assert inst.count("http://127.0.0.1:8888") == 1

    def test_custom_url_prefixed(self, monkeypatch):
        monkeypatch.setenv("SEARXNG_URL", "http://searx.internal:8080")
        inst = searx_instances()
        assert inst[0] == "http://searx.internal:8080"
        assert inst.count("http://searx.internal:8080") == 1
        assert LOCAL_SEARXNG_URL not in inst
