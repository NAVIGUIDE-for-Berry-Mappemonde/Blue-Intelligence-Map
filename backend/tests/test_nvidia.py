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
        model, engine = nvidia.second_extract_choice(
            "Fort Bay Harbour is the official port of entry for visiting yachts. " * 4)
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


class TestJudgeNvidia:
    def test_laguna_then_muse_on_listing(self, monkeypatch):
        models = []

        async def fake_complete(system, user, settings=None, *, model=None, **k):
            models.append(model)
            if model == nvidia.SECONDARY_MODEL:
                return {"is_poe": True, "confidence": 90, "kind": "pleasure",
                        "reason": "muse"}
            return {"is_poe": True, "confidence": 40, "kind": "pleasure",
                    "reason": "laguna"}

        monkeypatch.setattr(nvidia, "nvidia_enabled", lambda s=None: True)
        monkeypatch.setattr(nvidia, "complete_json_nvidia", fake_complete)

        out = _run(enr._judge_llm(
            {"name": "Nouméa", "seed_sources": ["listing"]},
            {"name": "NC"}, "extrait officiel", {}, lambda m: None))
        assert models[0] == nvidia.PRIMARY_MODEL
        assert nvidia.SECONDARY_MODEL in models
        assert out["judge_engine"] == "nvidia-muse"
        assert out["judge_status"] == "accepted"

    def test_cargo_stays_on_laguna(self, monkeypatch):
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
        assert out["judge_engine"] == "nvidia-laguna"


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
