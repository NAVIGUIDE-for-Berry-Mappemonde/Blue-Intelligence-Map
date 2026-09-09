"""Ordre commun d'enrichissement marina / capitainerie — aucun réseau."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import enrich as pe  # noqa: E402
from app.services import capitainerie_enrich as ce  # noqa: E402
from app.services import marina_enrich as me  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class TestCollectPageUrls:
    def test_official_skips_search(self):
        async def boom():
            raise AssertionError("search must not run when an official URL exists")

        urls = _run(pe.collect_page_urls(
            "https://port.example/hm",
            extra=["https://port.example/hm"],
            search=boom,
            url_ok_fn=lambda u: True,
        ))
        assert urls == ["https://port.example/hm"]

    def test_search_only_without_official(self):
        async def search():
            return ["https://www.tripadvisor.com/x", "https://port.example/hm"]

        urls = _run(pe.collect_page_urls(
            None, search=search, max_urls=5))
        assert urls == ["https://port.example/hm"]
        assert all("tripadvisor" not in u for u in urls)

    def test_tripadvisor_official_falls_through_to_search(self):
        async def search():
            return ["https://larochelle.port.fr/capitainerie"]

        urls = _run(pe.collect_page_urls(
            "https://www.tripadvisor.com/Marina", search=search))
        assert urls == ["https://larochelle.port.fr/capitainerie"]


class TestFillEmpty:
    def test_does_not_overwrite(self):
        base = {"telephone": "+33 5", "canal_vhf": None}
        out = pe.fill_empty(
            base, {"telephone": "should-not-win", "canal_vhf": "9"},
            ("telephone", "canal_vhf"))
        assert out["telephone"] == "+33 5"
        assert out["canal_vhf"] == "9"

    def test_apply_incoming_counts_new_holes_only(self):
        working = {"telephone": "+33 5", "canal_vhf": None}
        after, filled = pe.apply_incoming(
            working,
            {"telephone": "other", "canal_vhf": "9"},
            ("telephone", "canal_vhf"),
            lambda w, inc: pe.fill_empty(w, inc, ("telephone", "canal_vhf")),
        )
        assert filled is True
        assert after["telephone"] == "+33 5"
        assert after["canal_vhf"] == "9"


class TestMarinaChain:
    def test_complete_osm_tags_skip_paid(self, monkeypatch):
        async def boom(*a, **k):
            raise AssertionError("must not search when OSM tags are complete")

        monkeypatch.setattr(me, "discover_marina_urls", boom)
        monkeypatch.setattr(me, "enrich_via_nvidia", boom)
        monkeypatch.setattr(me, "enrich_via_openrouter", boom)
        monkeypatch.setattr(me, "enrich_via_tinyfish", boom)
        marina = {
            "name": "Minimes", "lat": 46.15, "lon": -1.16,
            "tags": {
                "phone": "+33 5 46 00 00 00",
                "vhf_channel": "9",
                "capacity": "320",
                "max_depth": "3.5",
                "shower": "yes",
                "website": "https://minimes.port.fr",
            },
        }
        out = _run(me.enrich_marina(
            marina, tinyfish_key="tf", openrouter_key="or",
            settings={"nvidia_api_key": "nv"}))
        assert out["enrichment_source"] == "tags"
        assert out["telephone_capitainerie"]
        assert out["canal_vhf"] == "9"
        assert out["places_visiteurs"] == 320
        assert out["_tinyfish_attempted"] is False

    def test_regex_phone_vhf_still_asks_llm_for_berths(self, monkeypatch):
        order = []

        async def urls(*a, **k):
            return ["https://minimes.port.fr"]

        async def pages(u, tinyfish_key=None, logger=None):
            return [{
                "url": u[0], "title": "Minimes",
                "text": "Capitainerie tél. 05 46 41 44 20 — VHF 9 / 16. Visitor berths.",
            }]

        async def nvidia(*a, **k):
            order.append("nvidia")
            return {
                "places_visiteurs": 320, "tirant_eau_max_metres": 3.5,
                "services_disponibles": ["eau"],
                "telephone_capitainerie": "should-not-win",
                "_engine": "nvidia-deepseek",
            }

        async def boom_or(*a, **k):
            raise AssertionError("OpenRouter must not run after NVIDIA filled holes")

        async def boom_tf(*a, **k):
            raise AssertionError("TinyFish must not run after holes are filled")

        monkeypatch.setattr(me, "discover_marina_urls", urls)
        monkeypatch.setattr(me, "fetch_marina_pages", pages)
        monkeypatch.setattr(me, "enrich_via_nvidia", nvidia)
        monkeypatch.setattr(me, "enrich_via_openrouter", boom_or)
        monkeypatch.setattr(me, "enrich_via_tinyfish", boom_tf)
        out = _run(me.enrich_marina(
            {"name": "Minimes", "lat": 46.1, "lon": -1.1,
             "website": "https://minimes.port.fr", "tags": {}},
            tinyfish_key="tf", openrouter_key="or",
            settings={"nvidia_api_key": "nv"}))
        assert order == ["nvidia"]
        assert out["enrichment_source"] == "nvidia-deepseek"
        assert out["telephone_capitainerie"]
        assert "should-not-win" not in (out["telephone_capitainerie"] or "")
        assert out["canal_vhf"] == "9/16"
        assert out["places_visiteurs"] == 320

    def test_nvidia_hit_skips_openrouter(self, monkeypatch):
        async def urls(*a, **k):
            return ["https://minimes.port.fr"]

        async def pages(u, tinyfish_key=None, logger=None):
            return [{"url": u[0], "title": "Minimes",
                     "text": "The marina welcomes visiting yachts."}]

        async def fake_nv(*a, **k):
            return {"canal_vhf": "9", "places_visiteurs": 320,
                    "tirant_eau_max_metres": 3.5, "score_protection_meteo": None,
                    "services_disponibles": ["eau"], "telephone_capitainerie": "05",
                    "resume_avis": None}

        async def boom_or(*a, **k):
            raise AssertionError("OpenRouter must not run after NVIDIA hit")

        async def boom_tf(*a, **k):
            raise AssertionError("TinyFish must not run after NVIDIA hit")

        monkeypatch.setattr(me, "discover_marina_urls", urls)
        monkeypatch.setattr(me, "fetch_marina_pages", pages)
        monkeypatch.setattr(me, "enrich_via_nvidia", fake_nv)
        monkeypatch.setattr(me, "enrich_via_openrouter", boom_or)
        monkeypatch.setattr(me, "enrich_via_tinyfish", boom_tf)
        out = _run(me.enrich_marina(
            {"name": "Minimes", "lat": 46.1, "lon": -1.1, "tags": {}},
            tinyfish_key="tf", openrouter_key="or",
            settings={"nvidia_api_key": "nv"}))
        assert out["enrichment_source"] == "nvidia"
        assert out["canal_vhf"] == "9"

    def test_keeps_osm_phone_when_nvidia_adds_rest(self, monkeypatch):
        async def urls(*a, **k):
            return ["https://minimes.port.fr"]

        async def pages(u, tinyfish_key=None, logger=None):
            return [{"url": u[0], "title": "Minimes", "text": "Visitor berths on pontoon A."}]

        async def nvidia(*a, **k):
            return {
                "telephone_capitainerie": "invented",
                "canal_vhf": "9",
                "places_visiteurs": 12,
                "tirant_eau_max_metres": 2.5,
                "services_disponibles": ["eau"],
            }

        monkeypatch.setattr(me, "discover_marina_urls", urls)
        monkeypatch.setattr(me, "fetch_marina_pages", pages)
        monkeypatch.setattr(me, "enrich_via_nvidia", nvidia)
        marina = {
            "name": "Minimes", "lat": 46.1, "lon": -1.1,
            "website": "https://minimes.port.fr",
            "tags": {"phone": "+33 5 46 00 00 00"},
        }
        out = _run(me.enrich_marina(
            marina, tinyfish_key="tf", openrouter_key=None,
            settings={"nvidia_api_key": "nv"}))
        assert out["telephone_capitainerie"].startswith("+33")
        assert "invented" not in out["telephone_capitainerie"]
        assert out["canal_vhf"] == "9"
        assert out["places_visiteurs"] == 12

    def test_agent_skipped_on_search_hit(self, monkeypatch):
        async def urls(*a, **k):
            return ["https://blog.example/marina-minimes"]

        async def pages(u, tinyfish_key=None, logger=None):
            return [{"url": u[0], "title": "Blog", "text": "A nice harbour."}]

        async def empty_nv(*a, **k):
            return None

        async def empty_or(*a, **k):
            return None

        async def boom_tf(*a, **k):
            raise AssertionError("Agent must not run on a search hit")

        monkeypatch.setattr(me, "discover_marina_urls", urls)
        monkeypatch.setattr(me, "fetch_marina_pages", pages)
        monkeypatch.setattr(me, "enrich_via_nvidia", empty_nv)
        monkeypatch.setattr(me, "enrich_via_openrouter", empty_or)
        monkeypatch.setattr(me, "enrich_via_tinyfish", boom_tf)
        out = _run(me.enrich_marina(
            {"name": "Minimes", "lat": 46.1, "lon": -1.1, "tags": {}},
            tinyfish_key="tf", openrouter_key="or"))
        assert out["_tinyfish_attempted"] is False

    def test_schemas_stay_distinct(self):
        assert "places_visiteurs" in me.ENRICH_FIELDS
        assert "tirant_eau_max_metres" in me.ENRICH_FIELDS
        assert "places_visiteurs" not in ce.ENRICH_FIELDS
        assert ce.ENRICH_FIELDS == ("telephone", "canal_vhf")


class TestCapitainerieOfficialSkipsSearch:
    def test_official_website_does_not_search(self, monkeypatch):
        async def boom(*a, **k):
            raise AssertionError("search must not run when official website exists")

        monkeypatch.setattr(ce, "search_named", boom)
        urls = _run(ce.discover_contact_urls({
            "name": "Capitainerie des Minimes",
            "lat": 46.15, "lon": -1.16,
            "website": "https://larochelle.port.fr/capitainerie",
            "tags": {"website": "https://larochelle.port.fr/capitainerie"},
        }, tinyfish_key="k"))
        assert urls == ["https://larochelle.port.fr/capitainerie"]
