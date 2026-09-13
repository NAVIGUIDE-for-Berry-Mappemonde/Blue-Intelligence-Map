"""Catalogue des règles : principe, intervalles, snapshot, bind."""
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "bi_test_run_rules")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.core import dedup, extract, geo
from app.core.run_rules import (
    RuleError, attach_rules, bind_rules, catalog_default, get_rule, load_catalog,
    public_catalog, reload_catalog, reset_rules, resolve_rules, rules_for_mode,
    rules_hash, snapshot_for_run,
)
from app.services import marina_world, osm_seeds, poe_runs, wpi_ports


def test_catalog_loads_and_intervals():
    cat = reload_catalog()
    assert cat["version"] == 1
    assert cat["rules"]
    ids = [r["id"] for r in cat["rules"]]
    assert len(ids) == len(set(ids))
    for rule in cat["rules"]:
        if rule["kind"] == "loi" or rule.get("value") is None:
            assert rule.get("vary") is False or rule["kind"] == "loi"
            continue
        if isinstance(rule["value"], bool):
            continue
        interval = rule.get("interval")
        if interval:
            lo, hi = interval
            assert lo <= rule["value"] <= hi, rule["id"]


def test_cdc_numbers_are_catalogued():
    ids = {r["id"] for r in load_catalog()["rules"]}
    for rid in (
        "projects.max_inland_km", "projects.gatekeeper_accept",
        "projects.gatekeeper_reject", "projects.min_marine_score",
        "formalities.eez_sliver_km", "formalities.coastal_land_km",
        "formalities.inland_river_max_km", "formalities.marina_control_m",
        "formalities.wpi_proximity_km", "formalities.catalog_min_coords",
        "formalities.listing_coverage_publish", "formalities.zone_timeout_s",
        "marinas.corridor_radius_nm", "marinas.waypoint_radius_nm",
        "marinas.overpass_throttle_s",
        "capitaineries.overpass_throttle_s", "capitaineries.merge_km",
        "amp.visit_url_must_differ", "amp.min_zoom", "amp.bbox_max_deg",
        "shared.dedup_dist_km", "shared.no_snap",
        "projects.tinyfish_agents", "projects.listing_judge_concurrency",
        "marinas.place_match_m",
        "formalities.geocode_candidate_limit", "formalities.basin_split_km",
        "formalities.peer_near_km", "formalities.listing_name_sim_mid",
        "shared.extract_agree_sim", "shared.llm_geocode_min_confidence",
        "shared.content_changed_sim",
    ):
        assert rid in ids


def test_defaults_match_code_constants():
    assert catalog_default("formalities.eez_sliver_km") == geo.IN_EEZ_SLIVER_KM
    assert catalog_default("formalities.coastal_land_km") == geo.COASTAL_LAND_KM
    assert catalog_default("formalities.inland_river_max_km") == geo.INLAND_RIVER_MAX_KM
    assert catalog_default("shared.dedup_dist_km") == dedup.DIST_THRESHOLD_KM
    assert catalog_default("shared.dedup_sim_low") == dedup.SIM_THRESHOLD_LOW
    assert catalog_default("shared.dedup_sim_high") == dedup.SIM_THRESHOLD_HIGH
    assert catalog_default("formalities.wpi_proximity_km") == wpi_ports.WPI_PROXIMITY_KM
    assert catalog_default("formalities.marina_control_m") == osm_seeds.MARINA_CONTROL_RADIUS_M
    assert catalog_default("formalities.zone_timeout_s") == poe_runs.ZONE_TIMEOUT_S
    assert catalog_default("marinas.overpass_throttle_s") == marina_world.OVERPASS_THROTTLE_S
    from app.core import identity
    from app.services import capitainerie_world
    assert catalog_default("capitaineries.overpass_throttle_s") == capitainerie_world.OVERPASS_THROTTLE_S
    assert catalog_default("capitaineries.merge_km") == capitainerie_world.SHOM_MERGE_KM
    assert catalog_default("capitaineries.merge_km") == identity.OVERLAY_RADIUS_KM
    assert capitainerie_world.NOAA_MERGE_KM == capitainerie_world.SHOM_MERGE_KM
    assert catalog_default("formalities.geocode_candidate_limit") == geo.GEOCODE_CANDIDATE_LIMIT
    assert catalog_default("formalities.peer_near_km") == geo.PEER_NEAR_KM
    assert catalog_default("formalities.basin_split_km") == geo.BASIN_SPLIT_KM
    from app.services.marina_maps_place import MAX_PLACE_DISTANCE_M
    assert catalog_default("marinas.place_match_m") == MAX_PLACE_DISTANCE_M
    assert catalog_default("projects.tinyfish_agents") == 2
    assert catalog_default("projects.listing_judge_concurrency") == 2
    assert catalog_default("shared.extract_agree_sim") == 0.55
    assert catalog_default("shared.llm_geocode_min_confidence") == 0.4
    assert catalog_default("shared.content_changed_sim") == 0.95
    assert catalog_default("formalities.listing_name_sim_mid") == 0.82


def test_loi_cannot_be_overridden():
    with pytest.raises(RuleError, match="loi"):
        resolve_rules(mode="projects", overrides={"shared.no_snap": False})


def test_unknown_rule_rejected():
    with pytest.raises(RuleError, match="inconnues"):
        resolve_rules(mode="projects", overrides={"projects.magic": 1})


def test_out_of_interval_rejected():
    with pytest.raises(RuleError, match="hors intervalle"):
        resolve_rules(mode="formalities",
                      overrides={"formalities.eez_sliver_km": 20})


def test_settings_then_override():
    snap = resolve_rules(
        mode="projects",
        settings={"max_inland_km": 12},
        overrides={"projects.max_inland_km": 10},
    )
    chosen = snap["chosen"]["projects.max_inland_km"]
    assert chosen["value"] == 10
    assert chosen["source"] == "override"

    snap2 = resolve_rules(mode="projects", settings={"max_inland_km": 12})
    assert snap2["chosen"]["projects.max_inland_km"]["value"] == 12
    assert snap2["chosen"]["projects.max_inland_km"]["source"] == "settings"


def test_profile_strict_and_recall():
    strict = snapshot_for_run(mode="formalities", profile="strict")
    recall = snapshot_for_run(mode="formalities", profile="recall")
    assert strict["chosen"]["formalities.eez_sliver_km"]["value"] == 1.8
    assert recall["chosen"]["formalities.eez_sliver_km"]["value"] == 3.5
    assert strict["hash"] != recall["hash"]
    assert strict["chosen"]["formalities.eez_sliver_km"]["source"] == "profile"


def test_strict_recall_move_identity_radii():
    cap_s = snapshot_for_run(mode="capitaineries", profile="strict")
    cap_r = snapshot_for_run(mode="capitaineries", profile="recall")
    assert cap_s["chosen"]["capitaineries.merge_km"]["value"] == 0.15
    assert cap_r["chosen"]["capitaineries.merge_km"]["value"] == 0.4
    proj_s = snapshot_for_run(mode="projects", profile="strict")
    proj_r = snapshot_for_run(mode="projects", profile="recall")
    assert proj_s["chosen"]["shared.dedup_dist_km"]["value"] == 0.35
    assert proj_r["chosen"]["shared.dedup_dist_km"]["value"] == 0.7
    assert cap_s["chosen"]["capitaineries.merge_km"]["source"] == "profile"


def test_snapshot_hash_stable():
    a = snapshot_for_run(mode="marinas")
    b = snapshot_for_run(mode="marinas")
    assert a["hash"] == b["hash"]
    amp = snapshot_for_run(mode="amp")
    assert amp["chosen"]["amp.visit_url_must_differ"]["value"] is True
    assert amp["chosen"]["amp.visit_url_must_differ"]["source"] == "loi"
    cap = snapshot_for_run(mode="capitaineries")
    assert cap["chosen"]["capitaineries.merge_km"]["value"] == 0.25
    assert a["hash"] == rules_hash(a["chosen"])
    assert a["counts"]["total"] == len(a["chosen"])


def test_get_rule_bind_changes_catalog_sufficient():
    ports = [
        {"lat": 1.0, "lon": 1.0},
        {"lat": 2.0, "lon": 2.0},
        {"lat": 3.0, "lon": 3.0},
    ]
    assert extract.catalog_is_sufficient(ports) is True
    snap = snapshot_for_run(
        mode="formalities",
        overrides={"formalities.catalog_min_coords": 5},
    )
    token = bind_rules(snap)
    try:
        assert get_rule("formalities.catalog_min_coords") == 5
        assert extract.catalog_is_sufficient(ports) is False
    finally:
        reset_rules(token)
    assert extract.catalog_is_sufficient(ports) is True


def test_mode_filter_excludes_other_modes():
    ids = {r["id"] for r in rules_for_mode("projects")}
    assert "projects.max_inland_km" in ids
    assert "shared.dedup_dist_km" in ids
    assert "marinas.corridor_radius_nm" not in ids


def test_public_catalog_has_principle():
    pub = public_catalog("marinas")
    assert "phénomène" in pub["principle"] or "loi" in pub["principle"]
    assert "cdc_default" in pub["profiles"]
    assert any(r["id"] == "marinas.corridor_radius_nm" for r in pub["rules"])


def test_catalog_title_help_group():
    cat = load_catalog()
    assert {g["id"] for g in cat["groups"]} == {
        "identity", "space", "qualification", "geocode", "reading", "budget", "contracts",
    }
    for rule in cat["rules"]:
        assert rule.get("group") in {
            "identity", "space", "qualification", "geocode", "reading", "budget", "contracts",
        }, rule["id"]
        assert (rule.get("title") or {}).get("fr")
        assert (rule.get("title") or {}).get("en")
        assert (rule.get("help") or {}).get("fr")
        assert (rule.get("help") or {}).get("en")
        if rule["kind"] == "loi":
            assert rule["group"] == "contracts"
    pub = public_catalog("projects")
    inland = next(r for r in pub["rules"] if r["id"] == "projects.max_inland_km")
    assert inland["title"]["fr"].startswith("Hinterland")
    assert inland["group"] == "space"
    assert pub["identity_banner"]["help"]["fr"]
    assert pub["profiles"]["cdc_default"]["label"]["fr"] == "Défaut"
    coast = next(r for r in pub["rules"] if r["id"] == "projects.max_coast_km")
    assert coast["legacy"] is True


def test_preview_without_settings_is_pure_profile():
    with_s = snapshot_for_run(
        mode="projects", profile="cdc_default", settings={"max_inland_km": 12})
    pure = snapshot_for_run(mode="projects", profile="cdc_default", settings={})
    assert with_s["chosen"]["projects.max_inland_km"]["value"] == 12
    assert with_s["chosen"]["projects.max_inland_km"]["source"] == "settings"
    assert pure["chosen"]["projects.max_inland_km"]["value"] == catalog_default(
        "projects.max_inland_km")
    assert pure["chosen"]["projects.max_inland_km"]["source"] == "catalog"


def test_bind_changes_same_site_distance():
    from app.core.geo import destination_point
    a = {"title": "Port de Papeete", "lat": 46.15, "lon": -1.16}
    lat2, lon2 = destination_point(a["lat"], a["lon"], 90, 0.60)
    b = {"title": "Papeete", "lat": lat2, "lon": lon2}
    assert dedup.is_duplicate(a, b) is False
    snap = snapshot_for_run(
        mode="projects", overrides={"shared.dedup_dist_km": 0.70})
    token = bind_rules(snap)
    try:
        assert get_rule("shared.dedup_dist_km") == 0.70
        assert dedup.is_duplicate(a, b) is True
    finally:
        reset_rules(token)
    assert dedup.is_duplicate(a, b) is False


def test_bind_changes_place_match_and_geocode_hits():
    from app.core.geo import destination_point
    from app.services.marina_maps_place import place_hit_matches

    lat, lon = 46.15, -1.16
    lat2, lon2 = destination_point(lat, lon, 90, 9.0)
    url = f"https://www.google.com/maps/place/Minimes+Marina/@{lat2},{lon2},15z"
    hit = {"title": "Minimes Marina", "url": url, "snippet": "yacht harbour"}
    assert place_hit_matches("Minimes Marina", hit, lat=lat, lon=lon) is False
    snap = snapshot_for_run(
        mode="marinas", overrides={"marinas.place_match_m": 20000})
    token = bind_rules(snap)
    try:
        assert get_rule("marinas.place_match_m") == 20000
        assert place_hit_matches("Minimes Marina", hit, lat=lat, lon=lon) is True
        assert geo._geocode_candidate_limit() == 10
    finally:
        reset_rules(token)

    snap2 = snapshot_for_run(
        mode="formalities",
        overrides={"formalities.geocode_candidate_limit": 6})
    token2 = bind_rules(snap2)
    try:
        assert geo._geocode_candidate_limit() == 6
    finally:
        reset_rules(token2)
    assert geo._geocode_candidate_limit() == 10


def test_post_bodies_accept_profile_and_rules():
    from app.routers.amp import DiscoverBody
    from app.routers.capitaineries import BuildBody, EnrichBatchBody
    from app.routers.marinas import MarinasBuildBody
    for model in (BuildBody, EnrichBatchBody, DiscoverBody, MarinasBuildBody):
        fields = model.model_fields
        assert "profile" in fields, model.__name__
        assert "rules" in fields, model.__name__


def test_attach_rules_nests_snapshot():
    snap = snapshot_for_run(mode="projects", profile="strict")
    params = attach_rules({"mode": "test"}, snap)
    assert params["mode"] == "test"
    assert params["rules"]["hash"] == snap["hash"]
    assert params["rules"]["chosen"]["projects.gatekeeper_accept"]["value"] == 0.9
