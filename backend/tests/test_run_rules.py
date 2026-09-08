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
        "amp.visit_url_must_differ", "amp.min_zoom", "amp.bbox_max_deg",
        "shared.dedup_dist_km", "shared.no_snap",
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


def test_snapshot_hash_stable():
    a = snapshot_for_run(mode="marinas")
    b = snapshot_for_run(mode="marinas")
    assert a["hash"] == b["hash"]
    amp = snapshot_for_run(mode="amp")
    assert amp["chosen"]["amp.visit_url_must_differ"]["value"] is True
    assert amp["chosen"]["amp.visit_url_must_differ"]["source"] == "loi"
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


def test_attach_rules_nests_snapshot():
    snap = snapshot_for_run(mode="projects", profile="strict")
    params = attach_rules({"mode": "test"}, snap)
    assert params["mode"] == "test"
    assert params["rules"]["hash"] == snap["hash"]
    assert params["rules"]["chosen"]["projects.gatekeeper_accept"]["value"] == 0.9
