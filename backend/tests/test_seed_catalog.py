"""Audit / enrichissement MasterSeeds hors Complet."""
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "bi_test_seed_catalog")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import master_seeds as ms
from app.services.project_listing import is_listing_url, needs_listing_hop
from app.services.seed_catalog import (
    build_enriched_master_seeds, classify_home, classify_name,
    infer_own_listing, is_crawl_ready,
)
from app.static_data.seeds import CURATED_SEEDS


def test_classify_name_keeps_single_org_and():
    assert classify_name("Gordon and Betty Moore Foundation") == "ok"
    assert classify_name("National Fish and Wildlife Foundation") == "ok"
    assert classify_name("CEA and CNRS") == "compound"
    assert classify_name("JPI Oceans and JPI Climate") == "compound"
    assert classify_name("CORAL and MAR Fund") == "compound"
    assert classify_name("Aqua-Firma, Shark Foundation, Waterlust") == "compound"
    assert classify_name("Unknown") == "exclude"
    assert classify_name("In-kind") == "exclude"
    assert classify_name("NEMA (partner)") == "ok"


def test_classify_home_borrowed_vs_owner():
    decade = [
        "https://oceandecade.org/actions/a",
        "https://oceandecade.org/actions/b",
    ]
    bmkg = classify_home("Agency for Meteorology (BMKG) – Indonesia", decade)
    assert bmkg["home_status"] == "borrowed_hub"
    assert bmkg["home_url"] is None
    assert bmkg["borrowed_domain"] == "oceandecade.org"
    own = classify_home("Ocean Decade", decade)
    assert own["home_status"] == "official"
    assert own["home_url"] == "https://oceandecade.org/"
    surf = classify_home(
        "California Coastal Commission",
        ["https://surfrider.org/campaigns/x"],
    )
    assert surf["home_status"] == "borrowed_hub"
    ok = classify_home(
        "Surfrider Foundation",
        ["https://surfrider.org/campaigns/x"],
    )
    assert ok["home_status"] == "official"
    assert ok["home_url"] == "https://surfrider.org/"
    prog = classify_home(
        "Ocean Decade Programme SMARTNET",
        ["https://oceandecade.org/actions/x"],
    )
    assert prog["home_status"] == "borrowed_hub"


def test_infer_listing_own_domain_only():
    sos = infer_own_listing(
        "Save Our Seas Foundation",
        [
            "https://saveourseas.com/project/alpha",
            "https://saveourseas.com/project/beta",
        ],
        "https://saveourseas.com/",
    )
    assert sos == "https://saveourseas.com/project/"
    stolen = infer_own_listing(
        "NOAA",
        [
            "https://surfrider.org/campaigns/a",
            "https://surfrider.org/campaigns/b",
        ],
        "https://surfrider.org/",
    )
    assert stolen is None
    fdm = infer_own_listing(
        "Fondation de la Mer",
        [
            "https://fondationdelamer.org/nos-programmes/alpha/",
            "https://fondationdelamer.org/nos-programmes/beta/",
        ],
        "https://fondationdelamer.org/",
    )
    assert fdm == "https://fondationdelamer.org/nos-programmes/"
    assert is_listing_url(fdm)
    oceans = infer_own_listing(
        "Oceans 5",
        [
            "https://oceans5.org/project/alpha",
            "https://oceans5.org/project/beta",
            "https://oceans5.org/",
        ],
        "https://oceans5.org/",
    )
    assert oceans == "https://oceans5.org/project/"


def test_enriched_catalog_keeps_horizon_and_queues_sos():
    projects = [
        {"url": "https://oceandecade.org/actions/a", "funder": "Agency for Meteorology (BMKG) – Indonesia"},
        {"url": "https://oceandecade.org/actions/b", "funder": "Agency for Meteorology (BMKG) – Indonesia"},
        {"url": "https://cordis.europa.eu/project/id/1", "funder": "Horizon Europe"},
        {"url": "https://saveourseas.com/project/alpha", "funder": "Save Our Seas Foundation"},
        {"url": "https://saveourseas.com/project/beta", "funder": "Save Our Seas Foundation"},
        {"url": "https://oceanfdn.org/projects/one", "funder": "The Ocean Foundation"},
        {"url": "https://surfrider.org/campaigns/x", "funder": "CEA and CNRS"},
    ]
    seeds = build_enriched_master_seeds(projects, CURATED_SEEDS)
    by = {s["name"]: s for s in seeds}
    assert "Horizon Europe" in by
    assert by["Horizon Europe"]["queue"] == "resolve"
    assert by["Horizon Europe"]["home_status"] == "borrowed_hub"
    assert by["Agency for Meteorology (BMKG) – Indonesia"]["queue"] == "resolve"
    sos = by["Save Our Seas Foundation"]
    assert sos["queue"] == "crawl"
    assert sos["listing_url"] == "https://saveourseas.com/project/"
    assert sos["home_status"] == "official"
    assert by["The Ocean Foundation"]["source"] == "curated"
    assert by["CEA and CNRS"]["name_status"] == "compound"
    assert by["CEA and CNRS"]["queue"] == "resolve"
    queued = ms.seeds_for_run(seeds)
    names = {s["name"] for s in queued}
    assert "Save Our Seas Foundation" in names
    assert "The Ocean Foundation" in names
    assert "Horizon Europe" not in names
    assert "CEA and CNRS" not in names


def test_is_crawl_ready_legacy_partner_url():
    partner = {"name": "Wild Oysters", "url": "https://wild-oysters.org/"}
    assert is_crawl_ready(partner) is True
    hub = {"name": "BMKG", "url": "https://oceandecade.org/"}
    assert is_crawl_ready(hub) is False


def test_names_soft_match_foundation_suffix():
    assert ms.names_soft_match("Pure Ocean", "Pure Ocean Foundation")
    assert ms.names_soft_match("The Ocean Foundation", "Ocean Foundation")
    assert not ms.names_soft_match("Horizon Europe", "CORDIS Europe")


def test_wcs_initials_match_domain():
    assert "wcs" in ms.official_name_tokens("Wildlife Conservation Society Marine")
    assert ms.domain_matches_org("https://wcs.org/", "Wildlife Conservation Society Marine")


def test_curated_homes_are_not_fake_indexes():
    mer = next(s for s in CURATED_SEEDS if s["name"] == "Fondation de la Mer")
    assert mer["listing_kind"] == "projects_index"
    assert needs_listing_hop(mer) is False
    assert not needs_listing_hop({"listing_kind": "home_only", "url": "https://www.ifremer.fr/fr"})
