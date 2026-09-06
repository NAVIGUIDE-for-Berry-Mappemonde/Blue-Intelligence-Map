"""Tests unitaires de l'adaptateur Claude PoE — aucun appel réseau."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import claude  # noqa: E402
from app.core.extract import catalog_is_sufficient, extract_structured_ports  # noqa: E402


@pytest.fixture
def usage_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(claude, "USAGE_FILE", tmp_path / "claude_usage.json")
    monkeypatch.setattr(claude, "USAGE_LOCK", tmp_path / "claude_usage.lock")
    return tmp_path


class TestPayloadCache:
    def test_static_prefix_meets_haiku_minimum(self):
        assert claude.estimate_tokens(claude.STATIC_PREFIX) >= claude.MIN_CACHE_TOKENS

    def test_breakpoint_on_system_not_user_or_toplevel(self):
        payload = claude.build_extract_payload(
            {"name": "Fiji", "sovereign": "Fiji"}, "Suva and Lautoka")
        assert "cache_control" not in payload
        assert payload["model"] == "claude-haiku-4-5"
        assert payload["temperature"] == 0
        sys_block = payload["system"][0]
        assert sys_block["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
        assert sys_block["text"] == claude.STATIC_PREFIX
        user_block = payload["messages"][0]["content"][0]
        assert "cache_control" not in user_block
        assert "Fiji" in user_block["text"]
        assert "Suva and Lautoka" in user_block["text"]

    def test_system_identical_across_zones(self):
        a = claude.build_extract_payload({"name": "Alpha", "sovereign": "A"}, "ports: One")
        b = claude.build_extract_payload({"name": "Beta", "sovereign": "B"}, "ports: Two")
        assert a["system"] == b["system"]
        assert a["messages"] != b["messages"]


class TestBudget:
    def test_disabled_without_key_or_budget(self):
        assert claude.claude_enabled({}) is False
        assert claude.claude_enabled({"anthropic_api_key": "sk-ant-x"}) is False
        assert claude.claude_enabled({"anthropic_api_key": "sk-ant-x",
                                     "claude_budget_usd": 0}) is False
        assert claude.claude_enabled({"anthropic_api_key": "sk-ant-x",
                                     "claude_budget_usd": 10}) is True

    def test_env_budget_when_settings_zero(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_BUDGET_USD", "12.5")
        assert claude.get_claude_budget_usd({"claude_budget_usd": 0}) == 12.5
        assert claude.get_claude_budget_usd({"claude_budget_usd": 3}) == 3.0

    def test_stop_at_90_percent(self, usage_dir):
        settings = {"anthropic_api_key": "sk-ant-x", "claude_budget_usd": 10}
        claude.record_usage({}, cost_usd=8.99)
        assert claude.budget_allows_call(settings) is True
        claude.record_usage({}, cost_usd=0.02)
        assert claude.load_usage()["spent_usd"] >= 9.0
        assert claude.budget_allows_call(settings) is False

    def test_cost_estimator_1h_write_and_read(self):
        write = claude.estimate_cost_usd({
            "cache_creation_input_tokens": 4096,
            "cache_read_input_tokens": 0,
            "input_tokens": 100,
            "output_tokens": 200,
        })
        # 4096 * 2.0 + 100 * 1.0 + 200 * 5.0 = 9292 / 1e6
        assert abs(write - 9292 / 1e6) < 1e-9
        read = claude.estimate_cost_usd({
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 4096,
            "input_tokens": 80,
            "output_tokens": 50,
        })
        assert abs(read - (409.6 + 80 + 250) / 1e6) < 1e-9

    def test_billing_error_detection(self):
        assert claude._is_billing_error(402, "") is True
        assert claude._is_billing_error(400, "insufficient credits") is True
        assert claude._is_billing_error(400, "invalid_request") is False


class TestCatalogSufficient:
    _MX = """
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

    def test_three_coord_ports_are_enough(self):
        ports = extract_structured_ports(self._MX)
        assert catalog_is_sufficient(ports, self._MX) is True

    def test_single_legal_phrase_is_not_enough(self):
        text = ("No plant material may be imported into Niue except through "
                "the port of Alofi, the Hanan International Airport, or the Post Office.")
        ports = extract_structured_ports(text)
        assert any(p["name"] == "Alofi" for p in ports)
        assert catalog_is_sufficient(ports, text) is False

    def test_empty_is_not_enough(self):
        assert catalog_is_sufficient([], "hello") is False
        assert catalog_is_sufficient(None, "") is False
