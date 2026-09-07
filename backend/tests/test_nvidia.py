"""Adaptateur NVIDIA NIM — aucun réseau."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import nvidia  # noqa: E402
from app.services import poe_pipeline as poe  # noqa: E402
from app.services import poe_seed_enrich as enr  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class TestParseAndLegal:
    def test_strict_json_accepts_object(self):
        assert nvidia.parse_json_strict('{"is_poe": false, "kind": "cargo"}')["kind"] == "cargo"

    def test_strict_json_rejects_thinking_dump(self):
        blob = (
            "Here's a thinking process:\n"
            '1. Output format: {"is_poe": true, "confidence": 0, "reason": "", '
            '"official_name": null, "kind": "pleasure"}\n'
        )
        assert nvidia.parse_json_strict(blob) is None

    def test_strict_json_rejects_prose_then_json(self):
        assert nvidia.parse_json_strict('Sure. {"is_poe": true}') is None

    def test_message_text_ignores_reasoning_only(self):
        assert nvidia._message_text({
            "content": None,
            "reasoning_content": '{"is_poe": true}',
        }) == ""
        assert nvidia._message_text({
            "content": '{"is_poe": false}',
        }) == '{"is_poe": false}'

    def test_legal_gazette_fr(self):
        text = (
            "Arrêté relatif aux points de passage frontaliers maritimes pour la "
            "plaisance. Sont habilités : Dunkerque, Calais, Saint-Malo, Brest. "
            "Les formalités de police aux frontières s'y accomplissent."
        )
        assert nvidia.looks_like_legal_text(text) is True
        model, engine = nvidia.second_extract_choice(text)
        assert engine == "nvidia-kimi"
        assert model == nvidia.LEGAL_MODEL

    def test_short_or_forum_is_not_legal(self):
        assert nvidia.looks_like_legal_text("Fort Bay is nice") is False
        # Muse est déjà le lecteur principal : pas de second appel identique.
        assert nvidia.second_extract_choice(
            "Fort Bay Harbour is the official port of entry for visiting yachts. " * 4) is None

    def test_engine_label(self):
        assert nvidia.engine_label() == "nvidia-muse"
        assert nvidia.engine_label("meta/muse-glimmer-30b") == "nvidia-muse"
        assert nvidia.engine_label("moonshotai/kimi-k3") == "nvidia-kimi"
        assert nvidia.engine_label("poolside/laguna-xs-2.1") == "nvidia-laguna"

    def test_second_extract_muse_if_primary_overridden(self, monkeypatch):
        monkeypatch.setenv("NVIDIA_MODEL", "other/reader")
        model, engine = nvidia.second_extract_choice(
            "Fort Bay Harbour is the official port of entry for visiting yachts. " * 4)
        assert model == nvidia.SECONDARY_MODEL
        assert engine == "nvidia-muse"


class TestProvider:
    def test_auto_uses_nvidia_when_key(self, monkeypatch):
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        assert nvidia.llm_provider({}) == "nvidia"
        assert nvidia.nvidia_enabled({}) is True

    def test_openrouter_forced(self, monkeypatch):
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
        monkeypatch.setenv("LLM_PROVIDER", "openrouter")
        assert nvidia.nvidia_enabled({}) is False

    def test_settings_key_beats_empty_env(self, monkeypatch):
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.setenv("LLM_PROVIDER", "auto")
        assert nvidia.nvidia_enabled({"nvidia_api_key": "nvapi-ui"}) is True

    def test_laguna_env_is_remapped_to_muse(self, monkeypatch):
        monkeypatch.setenv("NVIDIA_MODEL", "poolside/laguna-xs-2.1")
        monkeypatch.setenv("NVIDIA_MODEL_SECONDARY", "poolside/laguna-xs-2.1")
        assert nvidia.primary_model() == nvidia.PRIMARY_MODEL
        assert nvidia.secondary_model() == nvidia.PRIMARY_MODEL
        assert nvidia.engine_label(nvidia.primary_model()) == "nvidia-muse"

    def test_muse_payload_lowers_reasoning(self):
        extras = nvidia.muse_generation_extras("meta/muse-glimmer-30b")
        assert extras["reasoning_effort"] == "low"
        assert extras["chat_template_kwargs"]["reasoning_strength"] == "low"
        assert nvidia.muse_generation_extras("moonshotai/kimi-k3") == {}


class TestJudgeNvidia:
    def test_muse_only_when_secondary_is_same(self, monkeypatch):
        models = []

        async def fake_complete(system, user, settings=None, *, model=None, **k):
            models.append(model)
            return {"is_poe": True, "confidence": 40, "kind": "pleasure",
                    "reason": "muse"}

        monkeypatch.setattr(nvidia, "nvidia_enabled", lambda s=None: True)
        monkeypatch.setattr(nvidia, "complete_json_nvidia", fake_complete)

        out = _run(enr._judge_llm(
            {"name": "Nouméa", "seed_sources": ["listing"]},
            {"name": "NC"}, "extrait officiel", {}, lambda m: None))
        assert models == [nvidia.PRIMARY_MODEL]
        assert nvidia.PRIMARY_MODEL == nvidia.SECONDARY_MODEL
        assert out["judge_engine"] == "nvidia-muse"
        assert out["judge_status"] == "accepted"

    def test_escalates_only_if_secondary_differs(self, monkeypatch):
        models = []

        async def fake_complete(system, user, settings=None, *, model=None, **k):
            models.append(model)
            if model == "meta/muse-glimmer-30b":
                return {"is_poe": True, "confidence": 90, "kind": "pleasure",
                        "reason": "muse"}
            return {"is_poe": True, "confidence": 40, "kind": "pleasure",
                    "reason": "other"}

        monkeypatch.setattr(nvidia, "nvidia_enabled", lambda s=None: True)
        monkeypatch.setattr(nvidia, "primary_model", lambda: "other/reader")
        monkeypatch.setattr(nvidia, "secondary_model", lambda: "meta/muse-glimmer-30b")
        monkeypatch.setattr(nvidia, "complete_json_nvidia", fake_complete)

        out = _run(enr._judge_llm(
            {"name": "Nouméa", "seed_sources": ["listing"]},
            {"name": "NC"}, "extrait officiel", {}, lambda m: None))
        assert models == ["other/reader", "meta/muse-glimmer-30b"]
        assert out["judge_engine"] == "nvidia-muse"
        assert out["judge_status"] == "accepted"

    def test_cargo_stays_on_muse(self, monkeypatch):
        models = []

        async def fake_complete(system, user, settings=None, *, model=None, **k):
            models.append(model)
            return {"is_poe": True, "confidence": 90, "kind": "cargo",
                    "reason": "terminal"}

        async def boom(*a, **k):
            raise AssertionError("OpenRouter should not run")

        monkeypatch.setattr(nvidia, "nvidia_enabled", lambda s=None: True)
        monkeypatch.setattr(nvidia, "complete_json_nvidia", fake_complete)
        monkeypatch.setattr(enr, "ask_json", boom)

        out = _run(enr._judge_llm(
            {"name": "Port Commerce", "seed_sources": ["v1"]},
            {"name": "XX"}, "terminal conteneur", {}, lambda m: None))
        assert models == [nvidia.PRIMARY_MODEL]
        assert out["judge_status"] == "rejected"
        assert out["judge_engine"] == "nvidia-muse"


class TestExtractSecondReader:
    def test_muse_parallel_and_agreement(self, monkeypatch):
        async def fake_primary(context, zone, settings=None, log=None):
            return [{"name": "Fort Bay", "city": None, "note": None,
                     "extraction_engine": "nvidia-laguna"}]

        async def fake_muse(context, zone, settings=None, log=None,
                            model=None, engine="nvidia-muse"):
            assert engine == "nvidia-muse"
            return [{"name": "Fort Bay", "extraction_engine": engine},
                    {"name": "Cinta Oil Terminal", "extraction_engine": engine}]

        import app.core.ml as ml
        monkeypatch.setattr(nvidia, "nvidia_enabled", lambda s=None: True)
        monkeypatch.setattr(nvidia, "second_extract_choice",
                            lambda ctx: (nvidia.SECONDARY_MODEL, "nvidia-muse"))
        monkeypatch.setattr(poe, "extract_ports", fake_primary)
        monkeypatch.setattr(nvidia, "extract_ports_nvidia", fake_muse)
        monkeypatch.setattr(ml, "extract_entities", lambda text: [])

        ports = _run(poe.extract_ports_llm(
            "ctx", {"name": "Testland"}, lambda m: None, settings={"x": 1}))
        by = {p["name"]: p for p in ports}
        assert by["Fort Bay"]["extraction_engine"] == "nvidia-laguna"
        assert by["Fort Bay"]["claude_agreement"] is True
        assert by["Cinta Oil Terminal"]["extraction_engine"] == "nvidia-muse"
        assert "vu par nvidia-muse" in (by["Cinta Oil Terminal"].get("note") or "")
