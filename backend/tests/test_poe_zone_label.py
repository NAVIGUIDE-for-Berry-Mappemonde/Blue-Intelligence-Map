"""Une fiche = un polygone VLIZ : France (hexagone) ≠ France (Mayotte)."""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.poe_zone_label import attach_zone_labels, zone_sort_key  # noqa: E402

_INDEX = Path(__file__).resolve().parents[1] / "data" / "listing_control" / "eez_index.json"


def _indexed_zones():
    raw = json.loads(_INDEX.read_text(encoding="utf-8"))
    return [copy.deepcopy(z) for z in raw["zones"]]


def test_belgium_stays_plain_when_unique():
    zones = attach_zone_labels(_indexed_zones())
    be = next(z for z in zones if z["mrgid"] == 3293)
    assert be["disambiguated"] is False
    assert be["label"] == "Belgium"
    assert be["qualifier_key"] is None


def test_france_hexagon_and_mayotte_are_distinct_labels():
    zones = attach_zone_labels(_indexed_zones())
    by_id = {z["mrgid"]: z for z in zones}
    hexagon = by_id[5677]
    mayotte = by_id[48944]
    reunion = by_id[8338]
    joint_it = by_id[48976]
    joint_es = by_id[48966]
    assert hexagon["disambiguated"] is True
    assert hexagon["qualifier_key"] == "hexagone"
    assert hexagon["label"] == "France (hexagone)"
    assert mayotte["label"] == "France (Mayotte)"
    assert reunion["label"] == "France (Réunion)"
    assert hexagon["label"] != mayotte["label"]
    assert "Mayotte" not in hexagon["label"]
    assert joint_it["qualifier_key"] == "joint"
    assert "Italy" in joint_it["label"]
    assert "Spain" in joint_es["label"]
    assert joint_it["label"] != joint_es["label"] != hexagon["label"]


def test_every_french_polygon_has_a_unique_label():
    zones = attach_zone_labels(_indexed_zones())
    fr = [z for z in zones if z.get("sovereign") == "France"]
    assert len(fr) == 23
    labels = [z["label"] for z in fr]
    assert len(set(labels)) == 23, labels
    assert all(lab.startswith("France (") for lab in labels)


def test_netherlands_saba_is_not_the_metropole():
    zones = attach_zone_labels(_indexed_zones())
    saba = next(z for z in zones if z["mrgid"] == 26518)
    nl = next(z for z in zones if z["mrgid"] == 5668)
    assert saba["label"] == "Netherlands (Saba)"
    assert nl["qualifier_key"] == "metropole"
    assert nl["label"] == "Netherlands (métropole)"


def test_homonym_territories_are_split():
    zones = attach_zone_labels(_indexed_zones())
    pr_nm = next(z for z in zones if z["mrgid"] == 33179)
    pr_ov = next(z for z in zones if z["mrgid"] == 48982)
    assert pr_nm["label"] != pr_ov["label"]
    assert "Puerto Rico" in pr_nm["label"]
    assert "Puerto Rico" in pr_ov["label"]


def test_sort_puts_hexagon_first_in_france_group():
    zones = attach_zone_labels(_indexed_zones())
    ordered = sorted(zones, key=zone_sort_key)
    fr = [z for z in ordered if z.get("sovereign") == "France"]
    assert fr[0]["mrgid"] == 5677
    assert fr[0]["qualifier_key"] == "hexagone"


def test_search_polygon_name_is_not_the_country_aggregate():
    from app.services.poe_zone_label import search_polygon_name
    zones = _indexed_zones()
    by_id = {z["mrgid"]: z for z in zones}
    hexagon = search_polygon_name(by_id[5677], zones)
    mayotte = search_polygon_name(by_id[48944], zones)
    reunion = search_polygon_name(by_id[8338], zones)
    belgium = search_polygon_name(next(z for z in zones if z["mrgid"] == 3293), zones)
    saba = search_polygon_name(next(z for z in zones if z["mrgid"] == 26518), zones)
    nl = search_polygon_name(next(z for z in zones if z["mrgid"] == 5668), zones)
    assert hexagon == "France hexagone"
    assert mayotte == "Mayotte"
    assert reunion == "Réunion"
    assert "Mayotte" not in hexagon
    assert belgium == "Belgium"
    assert saba == "Saba"
    assert "métropole" in nl
    assert hexagon != mayotte


def test_serp_place_name_drops_internal_hexagone_qualifier():
    from app.services.poe_zone_label import serp_place_name
    zones = _indexed_zones()
    by_id = {z["mrgid"]: z for z in zones}
    assert serp_place_name(by_id[5677], zones) == "France"
    assert serp_place_name(by_id[48944], zones) == "Mayotte"
    assert "hexagone" not in serp_place_name(by_id[5677], zones)


def test_keep_extracted_skips_other_polygon():
    from app.services.poe_zone_label import keep_extracted_in_zone
    assert keep_extracted_in_zone("spatial_rejected") is False
    assert keep_extracted_in_zone("llm_spatial_rejected") is True
    assert keep_extracted_in_zone(None) is True
    assert keep_extracted_in_zone("agree") is True
    assert keep_extracted_in_zone("not_geocodeable") is True


def test_no_duplicate_labels_under_the_same_sovereign():
    zones = attach_zone_labels(_indexed_zones())
    by_sov: dict[str, list[str]] = {}
    for z in zones:
        sov = z.get("sovereign") or ""
        by_sov.setdefault(sov, []).append(z["label"])
    for sov, labels in by_sov.items():
        assert len(labels) == len(set(labels)), (sov, labels)
