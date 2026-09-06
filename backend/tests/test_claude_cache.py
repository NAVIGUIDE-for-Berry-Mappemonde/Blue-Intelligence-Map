"""Tests unitaires de l'adaptateur Claude PoE — aucun appel réseau."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import claude  # noqa: E402
from app.core.extract import (  # noqa: E402
    catalog_is_sufficient, catalog_ports_with_coords, extract_structured_ports,
    is_geocodeable_name,
)
from app.core.llm import coerce_ports, coords_appear_in_text  # noqa: E402


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
    def test_accepts_claude_api_key_alias(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("CLAUDE_API_KEY", "sk-ant-alias")
        assert claude.get_anthropic_key({}) == "sk-ant-alias"

    def test_disabled_without_key_or_budget(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_BUDGET_USD", raising=False)
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

    def test_eight_fragments_are_not_enough(self):
        text = " ".join(f"le port de Port{i}," for i in range(1, 9))
        ports = extract_structured_ports(text)
        assert len(ports) >= 8
        assert catalog_ports_with_coords(ports) == []
        assert catalog_is_sufficient(ports, text) is False


class TestGeocodeableName:
    def test_real_ports_pass(self):
        assert is_geocodeable_name("Nouméa") is True
        assert is_geocodeable_name("Saint-Laurent du Maroni") is True
        assert is_geocodeable_name("Bar") is True
        assert is_geocodeable_name("Port of Spain") is True

    def test_canary_junk_rejected(self):
        assert is_geocodeable_name("eerste binnenkomst") is False
        assert is_geocodeable_name("binnenkomst moet worden ingediend") is False
        assert is_geocodeable_name("l’uniforme") is False
        assert is_geocodeable_name("armes") is False
        assert is_geocodeable_name("Bar has continuously conducted") is False

    def test_llm_flag_false_wins(self):
        assert is_geocodeable_name("Marokko", geocodeable=False) is False


class TestSourceCoords:
    def test_coords_must_appear_in_excerpt(self):
        src = "Latitud: 31.8522146 Longitud: -116.625788"
        assert coords_appear_in_text(31.8522146, -116.625788, src) is True
        assert coords_appear_in_text(31.85, -116.63, src) is True
        assert coords_appear_in_text(46.48, 30.73, src) is False

    def test_coerce_drops_invented_gps(self):
        data = {"ports": [
            {"name": "Ensenada", "lat": 31.8522146, "lon": -116.625788,
             "geocodeable": True},
            {"name": "Odessa", "lat": 46.48, "lon": 30.73, "geocodeable": True},
        ]}
        src = "#### 4.- Ensenada\nLatitud: 31.8522146\nLongitud: -116.625788"
        ports = coerce_ports(data, context=src)
        by = {p["name"]: p for p in ports}
        assert by["Ensenada"]["lat"] == 31.8522146
        assert "lat" not in by["Odessa"]
        assert by["Ensenada"]["geocodeable"] is True

    def test_coerce_without_context_keeps_numbers(self):
        data = {"ports": [{"name": "X", "lat": 10.5, "lon": 20.5}]}
        ports = coerce_ports(data)
        assert ports[0]["lat"] == 10.5


class TestTiebreakParse:
    def test_maps_choices(self):
        items = [{"name": "Port Alpha", "nominatim": [1, 2], "geonames": [3, 4]}]
        parsed = {"picks": [
            {"name": "Port Alpha", "choice": "geonames"},
            {"name": "Unknown", "choice": "nominatim"},
            {"name": "Port Alpha", "choice": "invented"},
        ]}
        out = claude._parse_tiebreak(parsed, items)
        assert out["Port Alpha"] == "geonames"
        assert out["port alpha"] == "geonames"
        assert "Unknown" not in out
