"""Porte unique ask_yes_no — aucun réseau."""
from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import judge as yn  # noqa: E402
from app.core import llm  # noqa: E402
from app.services import amp_visit  # noqa: E402
from app.services import poe_seed_enrich as enr  # noqa: E402
from app.services import project_listing as pl  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class TestAsBool:
    def test_python_bool_false_string_is_false(self):
        assert yn.as_bool("false") is False
        assert yn.as_bool("FALSE") is False
        assert yn.as_bool("non") is False
        assert yn.as_bool("true") is True
        assert yn.as_bool("oui") is True
        assert yn.as_bool(True) is True
        assert yn.as_bool(0) is False
        assert yn.as_bool(None) is None
        assert bool("false") is True  # le piège que l'adaptateur évite


class TestParseYesNo:
    def test_marine_is_poe_and_accept(self):
        assert yn.parse_yes_no({"marine": True, "reason": "reef"}).accepted is True
        assert yn.parse_yes_no({"is_poe": False, "reason": "cargo"}).accepted is False
        assert yn.parse_yes_no({"accept": True, "reason": "ok"}).accepted is True
        assert yn.parse_yes_no({"is_poe": None}).accepted is None
        assert yn.parse_yes_no({"marine": "false"}).accepted is False

    def test_url_must_be_in_candidates(self):
        cands = [{"url": "https://ofb.gouv.fr/visite-cerbere", "title": "Visite"}]
        ok = yn.parse_yes_no(
            {"accept": True, "url": "https://www.ofb.gouv.fr/visite-cerbere"},
            allowed_urls=cands)
        assert ok.accepted is True
        assert ok.url == "https://ofb.gouv.fr/visite-cerbere"

        invented = yn.parse_yes_no(
            {"accept": True, "url": "https://evil.example/invented",
             "reason": "sure"},
            allowed_urls=cands)
        assert invented.accepted is False
        assert invented.url is None

        null_url = yn.parse_yes_no(
            {"accept": True, "url": "null"},
            allowed_urls=cands)
        assert null_url.accepted is False
        assert null_url.url is None

    def test_forbidden_manager_url(self):
        cands = [{"url": "https://parc.fr/", "title": "Home"}]
        out = yn.parse_yes_no(
            {"accept": True, "url": "https://www.parc.fr/"},
            allowed_urls=cands,
            forbidden_urls=["https://parc.fr"],
        )
        assert out.accepted is False
        assert out.url is None


class TestAskYesNoCascade:
    def test_nvidia_then_openrouter_then_claude(self, monkeypatch):
        from app.core import claude, nvidia

        order = []

        async def nv_fail(*a, **k):
            order.append("nvidia")
            raise RuntimeError("nvidia down")

        async def or_fail(*a, **k):
            order.append("openrouter")
            raise RuntimeError("or down")

        async def claude_ok(*a, **k):
            order.append("claude")
            return {"accept": True, "reason": "ok", "url": None}

        monkeypatch.setattr(nvidia, "nvidia_enabled", lambda s=None: True)
        monkeypatch.setattr(nvidia, "complete_json_nvidia_tracked", nv_fail)
        monkeypatch.setattr(llm, "get_llm_key", lambda s=None: "sk-or")
        monkeypatch.setattr(llm, "_json_openrouter", or_fail)
        monkeypatch.setattr(claude, "claude_enabled", lambda s=None: True)
        monkeypatch.setattr(claude, "budget_allows_call", lambda s=None: True)
        monkeypatch.setattr(claude, "complete_json_claude", claude_ok)

        yes = _run(yn.ask_yes_no("sys", "user", role="json"))
        assert yes.accepted is True
        assert yes.engine == "claude-haiku"
        assert order == ["nvidia", "openrouter", "claude"]

    def test_nvidia_hit_skips_openrouter(self, monkeypatch):
        from app.core import nvidia

        async def nv_ok(*a, **k):
            return {"marine": True, "score": 0.9, "reason": "reef"}, nvidia.PRIMARY_MODEL

        async def boom(*a, **k):
            raise AssertionError("OpenRouter must not run after NVIDIA hit")

        monkeypatch.setattr(nvidia, "nvidia_enabled", lambda s=None: True)
        monkeypatch.setattr(nvidia, "complete_json_nvidia_tracked", nv_ok)
        monkeypatch.setattr(llm, "get_llm_key", lambda s=None: "sk-or")
        monkeypatch.setattr(llm, "_json_openrouter", boom)

        yes = _run(yn.ask_yes_no("sys", "user", role="json"))
        assert yes.accepted is True
        assert yes.engine == "nvidia-deepseek"
        assert yes.raw["score"] == 0.9


class TestCallersKeepOwnPrompts:
    def test_three_prompts_stay_three_prompts(self):
        gk = inspect.getsource(llm.gatekeeper_check)
        assert "Gatekeeper Protocol" in gk
        assert "MARINE/OCEAN/COASTAL" in gk
        assert "ask_yes_no" in gk
        assert "port d'entrée" not in gk.lower()
        assert "aire marine" not in gk.lower()

        assert "plaisance" in enr.JUDGE_SYSTEM.lower()
        assert "cargo" in enr.JUDGE_SYSTEM.lower()
        assert "visite" not in enr.JUDGE_SYSTEM.lower()

        assert "visite d'aire marine" in amp_visit.VISIT_JUDGE_SYSTEM
        assert "N'invente aucune URL" in amp_visit.VISIT_JUDGE_SYSTEM
        assert "is_poe" not in amp_visit.VISIT_JUDGE_SYSTEM
        assert "Gatekeeper Protocol" not in amp_visit.VISIT_JUDGE_SYSTEM

        assert "catalogue de projets" in pl.LISTING_JUDGE_SYSTEM
        assert "N'invente aucune URL" in pl.LISTING_JUDGE_SYSTEM
        assert "visite d'aire marine" not in pl.LISTING_JUDGE_SYSTEM
        assert "is_poe" not in pl.LISTING_JUDGE_SYSTEM
        assert "Gatekeeper Protocol" not in pl.LISTING_JUDGE_SYSTEM

    def test_callers_use_ask_yes_no(self):
        assert "ask_yes_no" in inspect.getsource(llm.gatekeeper_check)
        assert "ask_yes_no" in inspect.getsource(amp_visit.llm_judge_visit)
        assert "ask_yes_no" in inspect.getsource(enr._judge_llm)
        assert "ask_yes_no" in inspect.getsource(pl.llm_judge_listing)

    def test_amp_judge_rejects_invented_url(self, monkeypatch):
        async def fake_yes(*a, **k):
            assert k.get("allowed_urls")
            return yn.parse_yes_no(
                {"accept": True, "url": "https://evil.example/invented"},
                engine="nvidia-muse",
                allowed_urls=k["allowed_urls"],
                forbidden_urls=k.get("forbidden_urls"),
                url_key=k.get("url_key"),
            )

        monkeypatch.setattr(yn, "ask_yes_no", fake_yes)
        chosen = _run(amp_visit.llm_judge_visit(
            {"name": "Cerbère", "manager_url": "https://parc.fr"},
            [{"url": "https://ofb.gouv.fr/visite", "title": "Visite"}],
        ))
        assert chosen is None

    def test_amp_judge_keeps_listed_url(self, monkeypatch):
        async def fake_yes(*a, **k):
            return yn.parse_yes_no(
                {"accept": True, "url": "https://ofb.gouv.fr/visite-cerbere"},
                engine="nvidia-muse",
                allowed_urls=k["allowed_urls"],
                forbidden_urls=k.get("forbidden_urls"),
                url_key=k.get("url_key"),
            )

        monkeypatch.setattr(yn, "ask_yes_no", fake_yes)
        doc = {"name": "Cerbère", "manager_url": "https://parc.fr"}
        chosen = _run(amp_visit.llm_judge_visit(
            doc,
            [{"url": "https://ofb.gouv.fr/visite-cerbere", "title": "Visite"}],
        ))
        assert chosen == "https://ofb.gouv.fr/visite-cerbere"
        assert doc["visit_url_judge"] == "nvidia-muse"

    def test_listing_judge_rejects_invented_url(self, monkeypatch):
        async def fake_yes(*a, **k):
            assert k.get("role") == "json"
            assert k.get("allowed_urls")
            return yn.parse_yes_no(
                {"accept": True, "url": "https://evil.example/invented"},
                engine="nvidia-muse",
                allowed_urls=k["allowed_urls"],
                forbidden_urls=k.get("forbidden_urls"),
                url_key=k.get("url_key"),
            )

        monkeypatch.setattr(yn, "ask_yes_no", fake_yes)
        chosen = _run(pl.llm_judge_listing(
            {"name": "Example Ocean", "url": "https://example.org/"},
            [
                {"url": "https://example.org/our-programmes", "title": "P"},
                {"url": "https://example.org/research", "title": "R"},
            ],
        ))
        assert chosen is None

    def test_listing_judge_keeps_listed_url(self, monkeypatch):
        async def fake_yes(*a, **k):
            return yn.parse_yes_no(
                {"accept": True, "url": "https://example.org/our-programmes"},
                engine="nvidia-muse",
                allowed_urls=k["allowed_urls"],
                forbidden_urls=k.get("forbidden_urls"),
                url_key=k.get("url_key"),
            )

        monkeypatch.setattr(yn, "ask_yes_no", fake_yes)
        chosen = _run(pl.llm_judge_listing(
            {"name": "Example Ocean", "url": "https://example.org/"},
            [
                "https://example.org/research",
                "https://example.org/our-programmes",
            ],
        ))
        assert chosen == "https://example.org/our-programmes"

    def test_gatekeeper_string_false_is_reject(self, monkeypatch):
        async def fake_yes(*a, **k):
            assert k.get("role") == "json"
            assert k.get("max_tokens") == 400
            return yn.YesNo(
                accepted=False, url=None, reason="terrestrial",
                engine="nvidia-deepseek",
                raw={"marine": "false", "score": 0.9, "reason": "forest"},
            )

        monkeypatch.setattr(llm, "has_llm", lambda s=None: True)
        monkeypatch.setattr("app.core.judge.ask_yes_no", fake_yes)
        import app.core.ml as ml
        monkeypatch.setattr(ml, "predict_relevance", lambda t: None)
        out = _run(llm.gatekeeper_check("Forest", "mountain rainforest", {}))
        assert out["accepted"] is False
        assert out["engine"] == "NVIDIA Gatekeeper"
