"""Score d'homonymes au géocodage — pas de réseau."""
from shapely.geometry import box
from shapely.ops import unary_union

from app.core.geo import (
    GEOCODE_CANDIDATE_LIMIT,
    listing_group_penalty,
    port_name_variants,
    select_geocode_candidate,
)
from app.services.poe_seed_enrich import _needs_geocode, pick_geocode


def test_geocode_candidate_limit_is_a_net_of_ten():
    assert GEOCODE_CANDIDATE_LIMIT == 10


def test_port_name_variants_keeps_paren_first():
    vs = port_name_variants("Tanjung Pinang (Bintan Island)")
    assert vs[0] == "Tanjung Pinang (Bintan Island)"
    assert any("Bintan" in v for v in vs)
    assert "Tanjung Pinang" in vs


def test_scorer_prefers_bintan_over_sumatra():
    geoms = box(104.2, 0.9, 104.7, 1.4)
    cands = [
        {"source": "nominatim", "lat": -3.356, "lon": 104.657,
         "label": "Tanjung Pinang, Ogan Ilir, Sumatera Selatan, Indonesia",
         "osm_class": "place", "osm_type": "village"},
        {"source": "nominatim", "lat": 0.927, "lon": 104.446,
         "label": "Tanjungpinang, Bintan Island, Riau Islands, Indonesia",
         "osm_class": "place", "osm_type": "city"},
    ]
    port = {"name": "Tanjung Pinang (Bintan Island)",
            "listing_group": "Western Indonesia - Bintan, Lingga, Riau"}
    zone = {"iso2": "ID", "name": "Indonesia"}
    sel = select_geocode_candidate(cands, port, zone, geoms, None)
    assert sel["status"] == "ok"
    assert sel["chosen"]["lat"] > 0
    assert "Bintan" in sel["chosen"]["label"]


def test_scorer_astoria_west_coast_not_queens():
    west = box(-125.5, 32.0, -116.5, 49.0)
    east = box(-80.0, 32.0, -70.0, 45.0)
    geom = unary_union([west, east])
    cands = [
        {"source": "nominatim", "lat": 40.772, "lon": -73.930,
         "label": "Astoria, Queens, New York, United States",
         "osm_class": "place", "osm_type": "suburb"},
        {"source": "nominatim", "lat": 46.188, "lon": -123.831,
         "label": "Astoria, Clatsop County, Oregon, United States",
         "osm_class": "harbour", "osm_type": "harbour"},
    ]
    port = {
        "name": "Astoria",
        "listing_group": "West Coast (USA)",
        "geocode_peers": [
            {"lat": 43.368, "lon": -124.217, "name": "Coos Bay"},
            {"lat": 32.717, "lon": -117.163, "name": "San Diego"},
        ],
    }
    sel = select_geocode_candidate(cands, port, {"iso2": "US"}, geom, None)
    assert sel["status"] == "ok"
    assert sel["chosen"]["lon"] < -120


def test_scorer_ambiguous_two_basins_without_hint():
    geom = unary_union([box(-125, 32, -116, 49), box(-80, 32, -70, 45)])
    cands = [
        {"source": "nominatim", "lat": 40.77, "lon": -73.93,
         "label": "Springfield, New York", "osm_class": "place", "osm_type": "city"},
        {"source": "nominatim", "lat": 44.05, "lon": -123.02,
         "label": "Springfield, Oregon", "osm_class": "place", "osm_type": "city"},
    ]
    port = {"name": "Springfield"}
    sel = select_geocode_candidate(cands, port, {"iso2": "US"}, geom, None)
    assert sel["status"] == "ambiguous"
    assert sel["chosen"] is None


def test_listing_group_penalty_west_coast_usa():
    assert listing_group_penalty("West Coast (USA)", 40.77, -73.93) == -45.0
    assert listing_group_penalty("West Coast (USA)", 46.19, -123.83) == 0.0
    assert listing_group_penalty("Atlantic (France)", 44.20, 4.63) == -45.0
    assert listing_group_penalty("Atlantic (France)", 47.28, -2.20) == 0.0


def test_needs_geocode_skips_confirmed_ok():
    assert _needs_geocode({
        "verify_verdict": "confirmed", "gps_audit_status": "ok",
        "lat": 1.0, "lon": 2.0, "spatial_kind": "inland_river",
        "dist_km_to_eez_poly": 80,
    }) is False
    assert _needs_geocode({
        "verify_verdict": "confirmed", "gps_audit_status": "corrected",
        "lat": 1.0, "lon": 2.0,
    }) is False


def test_needs_geocode_inland_far_probable_and_name_only():
    assert _needs_geocode({
        "verify_verdict": "probable",
        "spatial_kind": "inland_river", "dist_km_to_eez_poly": 86,
        "lat": -10.7, "lon": 39.0, "geocoded_at": "t",
    }) is True
    assert _needs_geocode({
        "verify_verdict": "name_only",
    }) is True
    assert _needs_geocode({
        "verify_verdict": "probable",
        "spatial_kind": "in_eez", "lat": 1, "lon": 2, "geocoded_at": "t",
    }) is False
    assert _needs_geocode({
        "verify_verdict": "unverified", "geocode_status": "ambiguous",
        "lat": 1, "lon": 2,
    }) is True


def test_scorer_keeps_seville_river_over_roses():
    # Atlantique (embouchure) + sliver Méditerranée : Roses est in_eez harbour,
    # Séville inland ~50 km. On garde le toponyme, pas Roses.
    atlantic = box(-7.0, 36.55, -6.15, 36.95)
    med = box(2.8, 42.05, 3.4, 42.5)
    geom = unary_union([atlantic, med])
    cands = [
        {"source": "nominatim", "lat": 37.389, "lon": -5.995,
         "label": "Sevilla, Andalucía, España",
         "osm_class": "place", "osm_type": "city"},
        {"source": "nominatim", "lat": 42.337, "lon": 3.203,
         "label": "Roses, Girona, Catalunya, España",
         "osm_class": "harbour", "osm_type": "harbour"},
    ]
    port = {"name": "Sevilla"}
    sel = select_geocode_candidate(cands, port, {"iso2": "ES"}, geom, None)
    assert sel["chosen"] is not None
    assert abs(sel["chosen"]["lon"] + 5.995) < 0.1


def test_pick_geocode_ambiguous_no_coords():
    dual = {
        "nominatim": [40.77, -73.93],
        "geonames": [46.19, -123.83],
        "agree": False,
        "pick": {"status": "ambiguous", "chosen": None, "ranked": [
            {"lat": 40.77, "lon": -73.93, "source": "nominatim", "score": 50,
             "label": "A"},
            {"lat": 46.19, "lon": -123.83, "source": "geonames", "score": 49,
             "label": "B"},
        ]},
        "candidates": [],
    }
    out = pick_geocode(dual, {"name": "X"}, {"iso2": "US"}, object(), None)
    assert out["has_coords"] is False
    assert out["lat"] is None
    assert out["geocode_arbitration"] == "ambiguous"
