"""Registre GPS arbitrés — JSON git, scorer, pas de réseau."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from shapely.geometry import box
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.geo import (  # noqa: E402
    GEOCODE_CANDIDATE_LIMIT,
    haversine_km,
    select_geocode_candidate,
)
from app.services.poe_confirmed_gps_audit import (  # noqa: E402
    BANDAR_BINTAN_TELANI_KEY,
    BINTAN_CLUSTER,
    TANJUNG_PINANG_KEY,
)
from app.services.poe_gps_registry import (  # noqa: E402
    GPS_REGISTRY_PATH,
    accepted_by_key,
    entries_with_candidates,
    load_gps_registry,
    public_view,
    registry_hit,
)
from app.services import poe_seed_enrich as enr  # noqa: E402

BBT = (1.1605006, 104.3201677)
PICK_KM = 2.0


def _geom(entry: dict):
    boxes = entry.get("eez_boxes") or []
    if not boxes:
        return None
    geoms = [box(b[0], b[1], b[2], b[3]) for b in boxes]
    return unary_union(geoms) if len(geoms) > 1 else geoms[0]


def _port(entry: dict) -> dict:
    return {
        "name": entry.get("name") or entry["dedup_key"],
        "listing_name": entry.get("listing_name") or entry.get("name"),
        "listing_group": entry.get("listing_group") or "",
        "geocode_peers": list(entry.get("peers") or []),
        "dedup_key": entry["dedup_key"],
    }


def _cands(entry: dict) -> list[dict]:
    out = []
    for key in ("wrong", "right"):
        c = entry[key]
        out.append({
            "source": "nominatim",
            "lat": c["lat"],
            "lon": c["lon"],
            "label": c.get("label") or "",
            "osm_class": c.get("osm_class") or "",
            "osm_type": c.get("osm_type") or "",
        })
    return out


def test_registry_file_loads_and_is_in_git_tree():
    data = load_gps_registry(force=True)
    assert GPS_REGISTRY_PATH.is_file()
    assert data["version"] == 1
    assert len(data["entries"]) >= 16
    keys = [e["dedup_key"] for e in data["entries"]]
    assert len(keys) == len(set(keys))
    view = public_view()
    assert view["wrote_poe_ports"] is False
    assert view["seeds_build"] is False
    assert view["n_keep"] == 1
    assert view["n_correct"] >= 15


def test_geocode_candidate_limit_is_ten():
    assert GEOCODE_CANDIDATE_LIMIT == 10


@pytest.mark.parametrize(
    "entry",
    entries_with_candidates(),
    ids=lambda e: e["dedup_key"],
)
def test_scorer_picks_right_candidate_from_registry(entry):
    geom = _geom(entry)
    port = _port(entry)
    zone = {"iso2": entry.get("country_iso2") or ""}
    sel = select_geocode_candidate(_cands(entry), port, zone, geom, None)
    assert sel["status"] == "ok"
    chosen = sel["chosen"]
    right = entry["right"]
    dist = haversine_km(chosen["lat"], chosen["lon"], right["lat"], right["lon"])
    assert dist < PICK_KM, (
        f"{entry['dedup_key']}: choisi {chosen['lat']},{chosen['lon']} "
        f"({chosen.get('label')}) à {dist:.1f} km du right"
    )
    wrong = entry["wrong"]
    assert haversine_km(
        chosen["lat"], chosen["lon"], wrong["lat"], wrong["lon"]) > PICK_KM


def test_melilla_keep_not_moved():
    e = accepted_by_key("5693:puertodemelilla")
    assert e is not None
    assert e["action"] == "keep"
    assert e["status"] == "accepted"
    assert abs(e["lat"] - 35.2909189) < 1e-6
    assert abs(e["lon"] + 2.928011) < 1e-6
    assert not e.get("wrong")
    assert not e.get("right")


def test_tanjung_registry_is_bintan_not_bbt():
    e = accepted_by_key(TANJUNG_PINANG_KEY)
    assert e is not None
    assert e["action"] == "correct"
    assert abs(e["lat"] - BINTAN_CLUSTER[0]) < 1e-6
    assert abs(e["lon"] - BINTAN_CLUSTER[1]) < 1e-6
    d_bbt = haversine_km(e["lat"], e["lon"], BBT[0], BBT[1])
    assert d_bbt > 5.0
    copies = e.get("never_copy") or []
    assert copies
    assert copies[0]["dedup_key"] == BANDAR_BINTAN_TELANI_KEY
    assert abs(copies[0]["lat"] - BBT[0]) < 1e-6
    assert registry_hit(BANDAR_BINTAN_TELANI_KEY) is None


def test_geocode_one_uses_registry_before_nominatim(monkeypatch):
    async def boom(*_a, **_k):
        raise AssertionError("Nominatim ne doit pas être appelé")

    monkeypatch.setattr(enr, "geocode_port_dual", boom)
    out = asyncio.run(enr.geocode_one(
        {"dedup_key": "8456:astoria", "name": "Astoria",
         "seed_sources": ["listing"]},
        {"name": "United States", "iso2": "US", "_geom": None, "_prep": None},
        lambda m: None,
    ))
    assert out["geocode_arbitration"] == "gps_registry"
    assert abs(out["lat"] - 46.1879) < 1e-4
    assert abs(out["lon"] + 123.8313) < 1e-4


def test_geocode_one_keep_melilla_skips_nominatim(monkeypatch):
    async def boom(*_a, **_k):
        raise AssertionError("Nominatim ne doit pas être appelé")

    monkeypatch.setattr(enr, "geocode_port_dual", boom)
    out = asyncio.run(enr.geocode_one(
        {"dedup_key": "5693:puertodemelilla", "name": "Puerto de Melilla",
         "lat": 35.2909189, "lon": -2.928011, "seed_sources": ["listing"]},
        {"name": "Spain", "iso2": "ES", "_geom": None, "_prep": None},
        lambda m: None,
    ))
    assert out["geocode_arbitration"] == "gps_registry"
    assert out.get("geocode_kept_previous") is True
    assert abs(out["lat"] - 35.2909189) < 1e-6
    assert abs(out["lon"] + 2.928011) < 1e-6
