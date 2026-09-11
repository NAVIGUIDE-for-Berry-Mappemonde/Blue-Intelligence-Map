"""Graines OSM — tags wiki/Taginfo, parsing Overpass, sans réseau."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.osm_seeds import (  # noqa: E402
    COMMERCIAL_CATHAF, MARINA_CONTROL_RADIUS_M, OSM_POE_TAGS, OSM_SEED_CLAUSES,
    TAGINFO_CATALOG, _overpass_marina_near_control_query, _overpass_query,
    cache_doc_to_seed, collect_control_points, element_coords, element_name,
    enrich_elements, has_commercial_category, how_many_ports, is_control_facility,
    is_marina_only, is_seed_candidate, nearest_control, osm_confidence, osm_role,
    osm_tag_list, taginfo_snapshot,
)


def test_element_coords_node_and_way_center():
    assert element_coords({"lat": 1.5, "lon": 2.5}) == (1.5, 2.5)
    assert element_coords({"center": {"lat": 3, "lon": 4}}) == (3.0, 4.0)
    assert element_coords({"type": "way", "id": 1}) is None


def test_element_name_prefers_english_then_seamark():
    tags = {"name": "Le Havre", "name:en": "Le Havre Port"}
    assert element_name(tags) == "Le Havre Port"
    assert element_name({"official_name": "X"}) == "X"
    assert element_name({"seamark:harbour:name": "Fort Bay"}) == "Fort Bay"
    assert element_name({}) == ""


def test_console_test_tile_is_small():
    from app.services.osm_seeds import TEST_TILE, WORLD_TILES
    s, w, n, e = TEST_TILE
    assert (n - s) < 5 and (e - w) < 5
    assert TEST_TILE not in WORLD_TILES


def test_osm_tag_list_documents_relevant_tags():
    tags = {
        "harbour": "yes",
        "leisure": "marina",
        "industrial": "port",
        "port_of_entry": "yes",
        "seamark:harbour:category": "fishing;marina",
    }
    listed = osm_tag_list(tags)
    assert "harbour=yes" in listed
    assert "industrial=port" in listed
    assert "port_of_entry=yes" in listed
    assert "leisure=marina" in listed
    assert "seamark:harbour:category=fishing;marina" in listed


def test_old_three_tags_are_no_longer_the_query():
    assert ("harbour", "yes") in OSM_POE_TAGS
    assert ("industrial", "port") in OSM_POE_TAGS
    assert ("port_of_entry", "yes") in OSM_POE_TAGS
    assert ("landuse", "harbour") in OSM_POE_TAGS
    assert ("seamark:type", "harbour") not in OSM_POE_TAGS


def test_osm_confidence_named_in_eez():
    assert osm_confidence("Fort Bay", {"harbour": "yes"}, True) == 0.7
    assert osm_confidence("", {"harbour": "yes"}, True) == 0.6
    assert osm_confidence("", {}, False) == 0.35
    assert osm_confidence("Gustavia", {"port_of_entry": "yes"}, True) == 0.95
    assert osm_confidence("Port", {"industrial": "port"}, False) == 0.75


def test_cache_doc_to_seed_named():
    seed = cache_doc_to_seed({
        "osm_id": "node/42",
        "name": "Fort Bay",
        "lat": 17.62,
        "lon": -63.25,
        "tags": {"harbour": "yes"},
        "mrgid": 26518,
        "iso": "BQ",
        "zone_name": "Saba",
        "in_eez": True,
        "osm_confidence": 0.7,
    })
    assert seed["name"] == "Fort Bay"
    assert seed["seed_sources"] == ["osm"]
    assert seed["has_coords"] is True
    assert seed["osm_ids"] == ["node/42"]
    assert seed["dedup_key"] == "26518:fortbay"
    assert "openstreetmap.org/node/42" in seed["source_urls"][0]


def test_cache_doc_to_seed_rejects_bad_coords():
    assert cache_doc_to_seed({"name": "X"}) is None


def test_cache_doc_to_seed_rejects_marina_only():
    assert cache_doc_to_seed({
        "osm_id": "node/1",
        "name": "Yacht Club",
        "lat": 1.0,
        "lon": 2.0,
        "tags": {
            "leisure": "marina",
            "seamark:type": "harbour",
            "seamark:harbour:category": "marina",
        },
        "mrgid": 1,
        "in_eez": True,
    }) is None


def test_cache_doc_to_seed_keeps_marina_near_control():
    seed = cache_doc_to_seed({
        "osm_id": "node/1",
        "name": "Yacht Club",
        "lat": 1.0,
        "lon": 2.0,
        "tags": {
            "leisure": "marina",
            "seamark:type": "harbour",
            "seamark:harbour:category": "marina",
        },
        "mrgid": 1,
        "in_eez": True,
        "osm_near_control": True,
        "osm_customs": True,
        "osm_border": False,
    })
    assert seed is not None
    assert seed["osm_role"] == "marina_pleasure"
    assert seed["osm_near_control"] is True
    assert seed["osm_customs"] is True
    assert "marina" in seed["osm_kinds"]


def test_marina_only_vs_commercial():
    marina = {
        "leisure": "marina",
        "seamark:type": "harbour",
        "seamark:harbour:category": "marina",
    }
    assert is_marina_only(marina) is True
    assert is_seed_candidate(marina) is False
    assert osm_role(marina) == "marina_only"

    mixed = {
        "leisure": "marina",
        "seamark:type": "harbour",
        "seamark:harbour:category": "fishing;marina",
    }
    assert is_marina_only(mixed) is False
    assert is_seed_candidate(mixed) is True
    assert has_commercial_category(mixed) is True
    assert osm_role(mixed) == "commercial_harbour"

    poe_marina = {"leisure": "marina", "port_of_entry": "yes"}
    assert is_marina_only(poe_marina) is False
    assert is_seed_candidate(poe_marina) is True
    assert osm_role(poe_marina) == "poe_explicit"

    assert is_seed_candidate(marina, near_control=True) is True
    assert osm_role(marina, near_control=True) == "marina_pleasure"
    assert osm_confidence("Yacht Club", marina, True, near_control=True) == 0.55


def test_seed_candidates_from_wiki_tags():
    assert is_seed_candidate({"industrial": "port"}) is True
    assert is_seed_candidate({"landuse": "harbour"}) is True
    assert is_seed_candidate({"water": "harbour"}) is True
    assert is_seed_candidate({"seamark:type": "harbour_basin"}) is True
    assert is_seed_candidate({"seamark:type": "harbour"}) is True
    assert is_seed_candidate({"port": "cargo"}) is True
    assert is_seed_candidate({"port:type": "seaport"}) is True
    assert is_seed_candidate({"harbour": "fishing"}) is True
    assert is_seed_candidate({"amenity": "ferry_terminal"}) is False
    assert is_seed_candidate({"seamark:type": "berth"}) is False
    assert is_seed_candidate({"government": "customs"}) is False
    assert is_seed_candidate({"government": "customs"}, near_control=True) is False


def test_overpass_query_uses_wiki_tags_not_all_hbrfac():
    q = _overpass_query(10, -70, 20, -60)
    assert 'nwr["port_of_entry"="yes"]' in q
    assert 'nwr["industrial"="port"]' in q
    assert 'nwr["landuse"="harbour"]' in q
    assert 'nwr["water"="harbour"]' in q
    assert 'nwr["seamark:type"="harbour_basin"]' in q
    assert 'nwr["port"]' in q
    assert "seamark:harbour:category" in q
    assert 'nwr["seamark:type"="harbour"][!"seamark:harbour:category"]' in q
    assert 'nwr["leisure"="marina"]' not in q
    assert 'nwr["amenity"="ferry_terminal"]' not in q
    # Ne plus dump les 25k HBRFAC.
    assert 'nwr["seamark:type"="harbour"](10.0000,-70.0000,20.0000,-60.0000);' not in q
    kinds = {c[0] for c in OSM_SEED_CLAUSES}
    assert "eq" in kinds and "regex" in kinds and "and" in kinds


def test_overpass_marina_query_uses_around_control_not_world_dump():
    q = _overpass_marina_near_control_query(10, -70, 20, -60)
    assert f"(around.ctrl:{MARINA_CONTROL_RADIUS_M})" in q
    assert 'nwr["leisure"="marina"]' in q
    assert "->.ctrl" in q
    assert '["government"' in q or "government" in q
    assert '["amenity"="customs"]' in q
    assert '["barrier"="border_control"]' in q
    assert '["port_of_entry"="yes"]' in q
    main = _overpass_query(10, -70, 20, -60)
    assert "(around.ctrl:" not in main
    assert 'nwr["leisure"="marina"]' not in main


def test_catalog_covers_taginfo_layers():
    tags = {row["tag"] for row in TAGINFO_CATALOG}
    assert "port_of_entry=yes" in tags
    assert "seamark:type=harbour" in tags
    assert "leisure=marina" in tags
    assert "industrial=port" in tags
    assert "landuse=harbour" in tags
    seeds = [row for row in TAGINFO_CATALOG if row["seed"]]
    not_seeds = [row for row in TAGINFO_CATALOG if not row["seed"]]
    assert any(r["tag"] == "port_of_entry=yes" for r in seeds)
    assert any(r["tag"] == "leisure=marina" for r in not_seeds)
    assert any(r["tag"] == "seamark:type=harbour" for r in not_seeds)
    assert "marina" not in COMMERCIAL_CATHAF


def test_how_many_ports_has_no_single_count():
    rows = [
        {**entry, "count": entry["measured"]}
        for entry in TAGINFO_CATALOG
    ]
    answer = how_many_ports(rows)
    assert answer["no_single_count"] is True
    assert answer["poe_explicit_yes"] == 59
    assert answer["openseamap_harbour_facilities"] == 25070
    assert answer["leisure_marina"] == 31792
    assert answer["openseamap_commercial_cathaf_sum"] == (
        1145 + 159 + 136 + 125 + 112 + 87 + 82 + 57 + 32 + 86
    )
    assert "25 070" in answer["old_query_problem"]


def test_osm_validate_scores_port_of_entry():
    from app.services.osm_validate import _build_query, score_confidence
    q = _build_query(17.62, -63.25, 3000)
    assert '["port_of_entry"]' in q
    assert '["landuse"="harbour"]' in q
    assert '["water"="harbour"]' in q
    conf, tags, n = score_confidence([
        {"tags": {"port_of_entry": "yes", "harbour": "yes"}},
    ])
    assert "port_of_entry=yes" in tags
    assert conf >= 0.9
    assert n == 1


def test_taginfo_snapshot_offline_uses_measured():
    snap = taginfo_snapshot(live=False)
    assert snap["how_many_ports"]["poe_explicit_yes"] == 59
    assert snap["included_tags"]["port_of_entry=yes"] == 59
    assert snap["excluded_tags"]["leisure=marina"] == 31792
    assert "harbours" in snap["wiki"]
    assert "≤ 800 m" in snap["note"]


def _el(osm_id: str, lat: float, lon: float, tags: dict, name: str = ""):
    typ, raw_id = osm_id.split("/", 1)
    t = dict(tags)
    if name:
        t["name"] = name
    return {"type": typ, "id": int(raw_id), "lat": lat, "lon": lon, "tags": t}


def test_nearest_control_radius_is_800m_inclusive():
    from app.core.geo import destination_point, haversine_km

    clat, clon = 17.62, -63.25
    controls = [(clat, clon, {"government": "customs"})]
    close_lat, close_lon = destination_point(clat, clon, 0, 0.4)
    assert haversine_km(clat, clon, close_lat, close_lon) <= 0.8
    assert nearest_control(close_lat, close_lon, controls) is not None
    far_lat, far_lon = destination_point(clat, clon, 0, 2.0)
    assert haversine_km(clat, clon, far_lat, far_lon) > 0.8
    assert nearest_control(far_lat, far_lon, controls) is None
    edge_lat, edge_lon = destination_point(clat, clon, 90, 0.79)
    hit = nearest_control(edge_lat, edge_lon, controls)
    assert hit is not None
    assert hit[0] <= 0.8
    out_lat, out_lon = destination_point(clat, clon, 90, 0.81)
    assert nearest_control(out_lat, out_lon, controls) is None


def test_airport_customs_is_not_a_marina_anchor():
    docs = [{
        "lat": 17.62, "lon": -63.25,
        "tags": {"amenity": "customs", "name": "Princess Juliana Airport Customs"},
    }]
    assert collect_control_points(docs) == []
    assert is_control_facility({"amenity": "customs"}) is True


def test_enrich_keeps_marina_near_customs_drops_far_and_office():
    from app.core.geo import destination_point

    clat, clon = 17.62, -63.25
    near_lat, near_lon = destination_point(clat, clon, 0, 0.3)
    far_lat, far_lon = destination_point(clat, clon, 0, 3.0)
    elements = [
        _el("node/1", clat, clon, {"government": "customs"}, "Fort Bay Customs"),
        _el("node/2", near_lat, near_lon, {"leisure": "marina"}, "Yacht Basin"),
        _el("node/3", far_lat, far_lon, {"leisure": "marina"}, "Remote Club"),
        _el("way/4", 17.70, -63.20, {"harbour": "yes"}, "Ladder Bay"),
    ]
    docs = enrich_elements(elements, zones=[])
    by_id = {d["osm_id"]: d for d in docs}
    assert "node/1" not in by_id
    assert "node/3" not in by_id
    marina = by_id["node/2"]
    assert marina["osm_role"] == "marina_pleasure"
    assert marina["osm_near_control"] is True
    assert marina["osm_customs"] is True
    assert marina["osm_kinds"] == ["marina"]
    assert by_id["way/4"]["osm_role"] == "harbour_facility"
    assert by_id["way/4"]["osm_near_control"] is False
