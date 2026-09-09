"""Porte unique geocode_name — Nominatim ∥ GeoNames, deux tests d'espace. Aucun réseau."""
from __future__ import annotations

import ast
import asyncio
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import geo  # noqa: E402
from app.core import project_geo as pgeo  # noqa: E402
from app.core.geo import (  # noqa: E402
    choose_from_dual, geocode, geocode_dual, geocode_name, pack_geocode_dual,
    tiebreak_user_prompt,
)
from app.services import swarm_pipeline as swarm  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


GASCOGNE = [45.5, -5.0]
PARIS = [48.8566, 2.3522]


def _nomi_row(lat, lon, name="X"):
    return {"lat": str(lat), "lon": str(lon), "display_name": name,
            "class": "place", "type": "city"}


def _geon_row(lat, lon, name="X"):
    return {"lat": lat, "lng": lon, "name": name, "fcode": "PPL"}


def _patch_rows(monkeypatch, nomi_rows, geon_rows):
    calls = {"nominatim": 0, "geonames": 0}

    async def fake_nomi(query, country_code=None, limit=1):
        calls["nominatim"] += 1
        return list(nomi_rows)

    async def fake_geon(query, country_code=None, limit=1):
        calls["geonames"] += 1
        return list(geon_rows)

    monkeypatch.setattr(geo, "_nominatim_rows", fake_nomi)
    monkeypatch.setattr(geo, "_geonames_rows", fake_geon)
    monkeypatch.setenv("GEONAMES_USERNAME", "test")
    monkeypatch.setattr(geo, "_geonames_disabled_reason", None)
    return calls


class TestGeocodeDualParallel:
    def test_empty_query_skips_providers(self, monkeypatch):
        calls = _patch_rows(monkeypatch, [_nomi_row(1, 2)], [])
        dual = _run(geocode_dual("  "))
        assert dual["nominatim"] is None
        assert dual["geonames"] is None
        assert dual["agree"] is None
        assert calls == {"nominatim": 0, "geonames": 0}

    def test_both_providers_called_even_if_nominatim_hits(self, monkeypatch):
        calls = _patch_rows(
            monkeypatch,
            [_nomi_row(10.0, 20.0, "Alpha")],
            [_geon_row(10.001, 20.001, "Alpha")],
        )
        dual = _run(geocode_dual("Port Alpha"))
        assert calls["nominatim"] == 1
        assert calls["geonames"] == 1
        assert dual["agree"] is True
        assert dual["agreement_km"] < 2.0
        assert dual["nominatim"] == [10.0, 20.0]
        assert dual["geonames"] == [10.001, 20.001]

    def test_disagreement_flagged(self, monkeypatch):
        _patch_rows(
            monkeypatch,
            [_nomi_row(10.0, 20.0)],
            [_geon_row(11.0, 21.0)],
        )
        dual = _run(geocode_dual("Kingston"))
        assert dual["agree"] is False
        assert dual["agreement_km"] > 100

    def test_single_provider_neutral(self, monkeypatch):
        _patch_rows(monkeypatch, [_nomi_row(10.0, 20.0)], [])
        dual = _run(geocode_dual("Suva"))
        assert dual["agree"] is None
        assert dual["nominatim"] and not dual["geonames"]

    def test_does_not_score_eez_or_havre(self):
        src = inspect.getsource(geocode_dual) + inspect.getsource(geocode_name)
        src += inspect.getsource(pack_geocode_dual)
        src += inspect.getsource(choose_from_dual)
        assert "classify_poe_point" not in src
        assert "site_publishable" not in src
        assert "select_geocode_candidate" not in src


class TestChooseFromDual:
    def test_agree_prefers_nominatim(self):
        dual = pack_geocode_dual(
            {"lat": 10.0, "lon": 20.0, "source": "nominatim"},
            {"lat": 10.001, "lon": 20.001, "source": "geonames"},
        )
        hit = choose_from_dual(dual)
        assert hit["source"] == "nominatim"
        assert hit["arbitration"] == "agree"
        assert hit["lat"] == 10.0

    def test_explicit_choice_geonames(self):
        dual = pack_geocode_dual(
            {"lat": 10.0, "lon": 20.0, "source": "nominatim"},
            {"lat": 11.0, "lon": 21.0, "source": "geonames"},
        )
        hit = choose_from_dual(dual, choice="geonames")
        assert hit["source"] == "geonames"
        assert hit["lat"] == 11.0

    def test_disagree_without_choice_is_empty(self):
        dual = pack_geocode_dual(
            {"lat": 10.0, "lon": 20.0, "source": "nominatim"},
            {"lat": 11.0, "lon": 21.0, "source": "geonames"},
        )
        hit = choose_from_dual(dual)
        assert hit["arbitration"] == "disagree"
        assert hit["lat"] is None


class TestGeocodeCompat:
    def test_agree_returns_tuple(self, monkeypatch):
        _patch_rows(
            monkeypatch,
            [_nomi_row(10.0, 20.0)],
            [_geon_row(10.001, 20.001)],
        )
        assert _run(geocode("Alpha")) == (10.0, 20.0)

    def test_disagree_returns_none_without_arbitration(self, monkeypatch):
        _patch_rows(
            monkeypatch,
            [_nomi_row(10.0, 20.0)],
            [_geon_row(40.0, -70.0)],
        )
        assert _run(geocode("Kingston")) is None


class TestGeocodeNameArbitration:
    def test_picks_geonames_on_disagree(self, monkeypatch):
        _patch_rows(
            monkeypatch,
            [_nomi_row(10.0, 20.0)],
            [_geon_row(11.0, 21.0)],
        )

        async def fake_arb(zone, items, settings=None, log=None):
            assert items[0]["name"] == "Kingston"
            return {"Kingston": "geonames", "kingston": "geonames"}

        monkeypatch.setattr("app.core.llm.arbitrate_geocode", fake_arb)
        hit = _run(geocode_name(
            "Kingston", settings={},
            context={"name": "Kingston", "title": "Reef restore"}))
        assert hit["source"] == "geonames"
        assert hit["arbitration"] == "haiku_tiebreak"
        assert hit["lat"] == 11.0

    def test_haiku_none_invents_nothing(self, monkeypatch):
        _patch_rows(
            monkeypatch,
            [_nomi_row(10.0, 20.0)],
            [_geon_row(11.0, 21.0)],
        )

        async def fake_arb(zone, items, settings=None, log=None):
            return {"X": "none", "x": "none"}

        monkeypatch.setattr("app.core.llm.arbitrate_geocode", fake_arb)
        hit = _run(geocode_name("X", settings={}, context={"name": "X"}))
        assert hit["arbitration"] == "haiku_none"
        assert hit["lat"] is None


class TestTiebreakPrompt:
    def test_poe_zone_keeps_port_wording(self):
        text = tiebreak_user_prompt(
            {"name": "France", "sovereign": "France", "mrgid": 5677},
            [{"name": "Marseille", "nominatim": [43.3, 5.4],
              "geonames": [43.4, 5.3]}],
        )
        assert text.startswith("Zone : France (France).")
        assert "chaque port" in text
        assert "Marseille" in text

    def test_project_site_is_not_a_port_zone(self):
        text = tiebreak_user_prompt(
            {"name": "Hope Spot", "title": "Hope Spot",
             "location": "Raja Ampat"},
            [{"name": "Raja Ampat", "nominatim": PARIS, "geonames": GASCOGNE}],
        )
        assert text.startswith("Lieu :")
        assert "port" not in text.lower()
        assert "Raja Ampat" in text


class TestApplyHavre:
    def test_switches_to_ocean_directory(self):
        hit = {
            "lat": PARIS[0], "lon": PARIS[1], "source": "nominatim",
            "arbitration": "haiku_tiebreak",
            "nominatim": PARIS, "geonames": GASCOGNE,
        }
        out = pgeo.apply_havre(hit, {"max_inland_km": 15})
        assert out["source"] == "geonames"
        assert out["arbitration"] == "spatial_switch"
        assert out["geo_kind"] == "ocean"
        assert out["lat"] == GASCOGNE[0]

    def test_both_inland_rejected(self):
        hit = {
            "lat": PARIS[0], "lon": PARIS[1], "source": "nominatim",
            "arbitration": "agree",
            "nominatim": PARIS, "geonames": PARIS,
        }
        out = pgeo.apply_havre(hit, {"max_inland_km": 15})
        assert out["lat"] is None
        assert out["arbitration"] == "spatial_rejected"
        assert out["geo_kind"] == "inland"

    def test_haiku_none_does_not_rescue_a_point(self):
        hit = {
            "lat": None, "lon": None, "source": None,
            "arbitration": "haiku_none",
            "nominatim": GASCOGNE, "geonames": PARIS,
        }
        out = pgeo.apply_havre(hit, {"max_inland_km": 15})
        assert out["lat"] is None
        assert out["arbitration"] == "haiku_none"

    def test_does_not_import_eez(self):
        src = inspect.getsource(pgeo)
        assert "classify_poe_point" not in src
        assert "geocode_port_dual" not in src


class TestGeocodeProjectSite:
    def test_location_then_title_then_llm(self, monkeypatch):
        seen = []

        async def fake_name(query, **k):
            seen.append(("name", query))
            return {
                "query": query, "lat": None, "lon": None, "source": None,
                "arbitration": "miss", "nominatim": None, "geonames": None,
            }

        async def fake_llm(location, title, settings):
            seen.append(("llm", location, title))
            return tuple(GASCOGNE)

        monkeypatch.setattr(pgeo, "geocode_name", fake_name)
        monkeypatch.setattr("app.core.llm.llm_geocode", fake_llm)
        out = _run(pgeo.geocode_project_site(
            "Unknown reef", "Coral Hope", {"max_inland_km": 15}))
        assert [s[0] for s in seen] == ["name", "name", "llm"]
        assert seen[0][1] == "Unknown reef"
        assert seen[1][1] == "Coral Hope"
        assert out["geo_source"] == "llm-geocoded"
        assert out["lat"] == GASCOGNE[0]

    def test_skips_llm_when_directory_hits(self, monkeypatch):
        async def fake_name(query, **k):
            return {
                "query": query, "lat": GASCOGNE[0], "lon": GASCOGNE[1],
                "source": "nominatim", "arbitration": "single",
                "nominatim": GASCOGNE, "geonames": None,
            }

        async def boom(*a, **k):
            raise AssertionError("llm_geocode must not run when a directory hits")

        monkeypatch.setattr(pgeo, "geocode_name", fake_name)
        monkeypatch.setattr("app.core.llm.llm_geocode", boom)
        out = _run(pgeo.geocode_project_site(
            "Golfe de Gascogne", "Project", {"max_inland_km": 15}))
        assert out["geo_source"] == "geocoded:location"
        assert out["geo_kind"] == "ocean"


class TestWiring:
    def test_port_dual_reuses_pack(self):
        src = inspect.getsource(geo.geocode_port_dual)
        assert "pack_geocode_dual" in src

    def test_swarm_uses_project_site_not_sequential_geocode(self):
        src = Path(swarm.__file__).read_text()
        assert "geocode_project_site" in src
        assert "from app.core.geo import geocode" not in src
        assert "llm_geocode" not in src
        assert "snap_to_ocean" not in src
        assert "ocean_fallback_coords" not in src

    def test_geocode_name_feature_flag(self):
        from app.services.run_fingerprint import build_code_fingerprint
        fp = build_code_fingerprint({})
        assert fp["features"]["geocode_name"] is True

    def test_poe_llm_geocode_is_port_prompt_not_conservation(self):
        from app.core import llm as llm_mod
        port_src = inspect.getsource(llm_mod.llm_geocode_port)
        proj_src = inspect.getsource(llm_mod.llm_geocode)
        assert "port of entry" in port_src
        assert "mrgid" in port_src
        assert "reef" not in port_src.lower()
        assert "MPA" not in port_src
        assert "conservation" in proj_src.lower()
        assert "mrgid" not in proj_src
        assert "VLIZ" not in proj_src

    def test_pipelines_keep_distinct_llm_geocode(self):
        from app.core import project_geo as pgeo_mod
        from app.services import poe_pipeline, poe_seed_enrich
        p_src = inspect.getsource(pgeo_mod.geocode_project_site)
        assert "llm_geocode_port" not in p_src
        assert "llm_geocode(" in p_src
        assert "from app.core.llm import llm_geocode" in p_src
        for path in (poe_pipeline.__file__, poe_seed_enrich.__file__):
            tree = ast.parse(Path(path).read_text())
            imported, called = set(), set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "app.core.llm":
                    imported.update(a.name for a in node.names)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    called.add(node.func.id)
            assert "llm_geocode_port" in imported | called
            assert "llm_geocode" not in imported
            assert "llm_geocode" not in called
