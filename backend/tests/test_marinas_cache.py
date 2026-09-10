"""Cache stale-while-revalidate du dump GeoJSON marinas (GET /api/marinas).

Sur un Mongo distant, reconstruire les ~32 000 features prend plusieurs
minutes : ces tests verrouillent le contrat du cache — une seule lecture
Mongo par reconstruction, l'ancien contenu servi pendant le rafraîchissement,
et une invalidation qui ne casse jamais un contexte sans boucle asyncio.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.routers import marinas as marinas_router


@pytest.fixture(autouse=True)
def _isolate_disk_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(marinas_router, "_MARINAS_FC_DISK", tmp_path / "marinas.json")


def _fake_docs(tag: str, n: int = 2) -> list[dict]:
    return [
        {"_id": f"{tag}{i}", "name": f"Marina {tag}{i}",
         "lat": 43.0 + i, "lon": 5.0 + i}
        for i in range(n)
    ]


def _reset_cache(monkeypatch, fc=None, built_at=0.0):
    monkeypatch.setattr(marinas_router, "_MARINAS_FC_CACHE",
                        {"fc": fc, "built_at": built_at})
    monkeypatch.setattr(marinas_router, "_marinas_fc_task", None)


def _fake_all(calls: dict, tag: str = "a"):
    async def fake(q=None, projection=None):
        calls["n"] += 1
        return _fake_docs(tag)
    return fake


def test_cache_froid_une_seule_lecture_puis_service_depuis_le_cache(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(marinas_router, "_all_marinas", _fake_all(calls))
    _reset_cache(monkeypatch)

    async def scenario():
        first = await marinas_router.list_marinas()
        second = await marinas_router.list_marinas()
        return first, second

    first, second = asyncio.run(scenario())
    assert first["type"] == "FeatureCollection"
    assert len(first["features"]) == 2
    assert second is first, "le cache doit servir le même objet"
    assert calls["n"] == 1, "une seule lecture Mongo pour deux GET"


def test_cache_perime_sert_l_ancien_et_reconstruit_en_fond(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(marinas_router, "_all_marinas", _fake_all(calls, tag="neuf"))
    stale_fc = {"type": "FeatureCollection", "features": [], "attribution": "vieux"}
    _reset_cache(monkeypatch, fc=stale_fc,
                 built_at=time.monotonic() - marinas_router._MARINAS_FC_TTL_S - 60)

    async def scenario():
        served = await marinas_router.list_marinas()
        task = marinas_router._marinas_fc_task
        assert task is not None, "une reconstruction doit partir en arrière-plan"
        await task
        return served

    served = asyncio.run(scenario())
    assert served is stale_fc, "l'ancien contenu est servi sans attendre"
    assert calls["n"] == 1
    new_fc = marinas_router._MARINAS_FC_CACHE["fc"]
    assert new_fc is not stale_fc
    assert new_fc["features"][0]["properties"]["name"] == "Marina neuf0"


def test_requetes_filtrees_ne_passent_pas_par_le_cache(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(marinas_router, "_all_marinas", _fake_all(calls))
    poisoned = {"type": "FeatureCollection", "features": ["POISON"]}
    _reset_cache(monkeypatch, fc=poisoned, built_at=time.monotonic())

    out = asyncio.run(marinas_router.list_marinas(source="openstreetmap"))
    assert out is not poisoned
    assert calls["n"] == 1, "un filtre force une lecture Mongo directe"


def test_mark_stale_sans_boucle_asyncio_ne_leve_pas(monkeypatch):
    _reset_cache(monkeypatch, fc={"type": "FeatureCollection", "features": []},
                 built_at=time.monotonic())
    marinas_router.mark_marinas_fc_stale()  # hors event loop : ne doit pas lever
    assert marinas_router._MARINAS_FC_CACHE["built_at"] == 0.0


def test_warmup_sert_le_disque_sans_attendre_mongo(monkeypatch, tmp_path):
    disk_fc = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {"name": "Disque"}}],
    }
    (tmp_path / "marinas.json").write_text(json.dumps(disk_fc), encoding="utf-8")
    calls = {"n": 0}

    async def fake_all(q=None, projection=None):
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return _fake_docs("mongo")

    monkeypatch.setattr(marinas_router, "_all_marinas", fake_all)
    _reset_cache(monkeypatch)

    async def scenario():
        marinas_router.start_marinas_fc_warmup()
        served = await marinas_router.list_marinas()
        await marinas_router._marinas_fc_task
        return served

    served = asyncio.run(scenario())
    assert served["features"][0]["properties"]["name"] == "Disque"
    assert calls["n"] == 1, "Mongo part en arrière-plan au warmup"


def test_rebuild_ecrit_le_cache_disque(monkeypatch, tmp_path):
    calls = {"n": 0}
    monkeypatch.setattr(marinas_router, "_all_marinas", _fake_all(calls))
    _reset_cache(monkeypatch)

    asyncio.run(marinas_router.list_marinas())
    saved = json.loads((tmp_path / "marinas.json").read_text(encoding="utf-8"))
    assert len(saved["features"]) == 2
    assert saved["features"][0]["properties"]["name"] == "Marina a0"
