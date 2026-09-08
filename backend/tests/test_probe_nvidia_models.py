"""Helpers du sonde NVIDIA — aucun réseau."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import probe_nvidia_models as probe  # noqa: E402


class TestChatFilter:
    def test_skips_embed_and_asr(self):
        assert probe.is_chat_candidate("nvidia/nemotron-3-embed-1b") is False
        assert probe.is_chat_candidate("nvidia/parakeet-ctc-1.1b-asr") is False
        assert probe.is_chat_candidate("nvidia/llama-3.1-nemoguard-8b-content-safety") is False

    def test_keeps_text_llms(self):
        assert probe.is_chat_candidate("meta/muse-glimmer-30b") is True
        assert probe.is_chat_candidate("moonshotai/kimi-k3") is True
        assert probe.is_chat_candidate("poolside/laguna-xs-2.1") is True
        assert probe.is_chat_candidate("nvidia/nemotron-3.5-lightning-30b-a3b") is True


class TestScoring:
    def test_extract_accepts_official_list(self):
        ports = [{"name": n} for n in
                 ("Dunkerque", "Calais", "Saint-Malo", "Brest", "La Rochelle")]
        assert probe.score_extract(ports)["ok"] is True

    def test_extract_rejects_invented_airport(self):
        ports = [{"name": "Dunkerque"}, {"name": "Aéroport CDG"}]
        assert probe.score_extract(ports)["ok"] is False
        assert "Aéroport CDG" in probe.score_extract(ports)["invented"]

    def test_judge_fort_bay(self):
        case = probe.JUDGE_CASES[0]
        scored = probe.score_judge(case, {
            "is_poe": True, "confidence": 90, "kind": "pleasure",
            "reason": "official yacht entry",
        })
        assert scored["ok"] is True
        assert scored["kind_ok"] is True

    def test_judge_cargo_forced_rejected(self):
        case = probe.JUDGE_CASES[1]
        scored = probe.score_judge(case, {
            "is_poe": True, "confidence": 90, "kind": "cargo",
            "reason": "smelter",
        })
        assert scored["ok"] is True
        assert scored["status"] == "rejected"
