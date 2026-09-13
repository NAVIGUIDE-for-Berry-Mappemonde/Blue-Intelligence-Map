"""Audit / enrichissement MasterSeeds hors Complet."""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "bi_test_seed_catalog")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import master_seeds as ms
from app.services.project_listing import (
    is_listing_url, listing_from_hits, needs_listing_hop, parent_listing_url,
)
from app.services.seed_catalog import (
    FTM_DISCOVER, FTM_SEARCH, FTM_SKIP, accept_partner_url,
    append_search_journal, apply_compound_splits, apply_home_review,
    apply_listing_result, apply_official_site_result, assign_queue,
    build_enriched_master_seeds, classify_home, classify_name,
    decide_follow_the_money_partner, dump_catalog,
    infer_listings_onto_official_homes, infer_own_listing, is_crawl_ready,
    is_wide_corporate_home, journal_done_names, listing_candidates,
    load_search_journal, name_needs_official_search, overlay_home_reviews,
    overlay_listing_results, overlay_search_results, search_candidates,
    split_compound_parts, write_audit,
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
    assert classify_name("International Association of Oil and Gas Producers (IOGP)") == "ok"
    assert classify_name("Arctic and Antarctic Research Institute (AARI)") == "ok"
    assert classify_name("Seychelles Conservation and Climate Adaptation Trust (SeyCCAT)") == "ok"
    assert classify_name("BlueInvest, Bpifrance") == "compound"
    assert classify_name("Oceana, Google") == "compound"
    assert classify_name("La chasse en France") == "exclude"
    assert classify_name("Hunting Association") == "exclude"
    assert classify_name(
        "Alfred-Wegener-Institut, Helmholtz-Zentrum für Polar- und Meeresforschung (AWI)"
    ) == "ok"


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
    assert ms.names_soft_match("WWF Oceans", "WWF International", ["WWF"])
    assert ms.names_soft_match("WWF Oceans", "WWF", ["WWF"])
    assert not ms.names_soft_match("WWF Oceans", "Horizon Europe", ["WWF"])
    assert not ms.names_soft_match("Rare Fish Forever", "Wild Oysters", ["Rare"])
    assert not ms.names_soft_match("CEA and CNRS", "CEA")
    assert not ms.names_soft_match("Wild Trust", "Wild Oysters")


def test_name_needs_official_search_short_or_one_syllable():
    assert name_needs_official_search("Wacan") is True
    assert name_needs_official_search("WWF") is True
    assert name_needs_official_search("Shell") is True
    assert name_needs_official_search("Mawimbi") is False
    assert name_needs_official_search("Save Our Seas Foundation") is False


def test_wide_corporate_home_and_queue():
    axa = {
        "name": "AXA Atout Coeur",
        "url": "https://www.axa.com/",
        "home_url": "https://www.axa.com/",
        "home_status": "official",
        "name_status": "ok",
        "listing_kind": "homepage",
    }
    assert is_wide_corporate_home(axa) is True
    assert assign_queue(axa) == "resolve"
    assert is_crawl_ready(axa) is False
    bloom = {
        "name": "Bloomberg Philanthropies",
        "url": "https://www.bloomberg.org/",
        "home_url": "https://www.bloomberg.org/",
        "home_status": "official",
        "name_status": "ok",
    }
    assert is_wide_corporate_home(bloom) is True
    ocean = {
        "name": "AXA Research Fund",
        "url": "https://www.axa.com/en/about-us/axa-research-fund-ocean",
        "home_url": "https://www.axa.com/",
        "listing_kind": "projects_index",
        "home_status": "official",
        "name_status": "ok",
    }
    assert is_wide_corporate_home(ocean) is False


def test_wcs_initials_match_domain():
    assert "wcs" in ms.official_name_tokens("Wildlife Conservation Society Marine")
    assert ms.domain_matches_org("https://wcs.org/", "Wildlife Conservation Society Marine")


def test_curated_homes_are_not_fake_indexes():
    mer = next(s for s in CURATED_SEEDS if s["name"] == "Fondation de la Mer")
    assert mer["listing_kind"] == "projects_index"
    assert needs_listing_hop(mer) is False
    assert not needs_listing_hop({"listing_kind": "home_only", "url": "https://www.ifremer.fr/fr"})


def test_apply_official_site_keeps_borrowed_domain():
    seed = {
        "name": "BMKG",
        "home_status": "borrowed_hub",
        "borrowed_domain": "oceandecade.org",
        "listing_url": "https://oceandecade.org/actions/",
        "listing_kind": "unknown",
        "queue": "resolve",
    }
    apply_official_site_result(seed, "https://bmkg.go.id/")
    assert seed["home_status"] == "official"
    assert seed["home_source"] == "search"
    assert seed["queue"] == "crawl"
    assert seed["home_url"] == "https://bmkg.go.id/"
    assert seed["url"] == "https://bmkg.go.id/"
    assert seed["listing_url"] is None
    assert seed["borrowed_domain"] == "oceandecade.org"
    miss = {
        "name": "Obscure Org",
        "home_status": "unknown",
        "borrowed_domain": "surfrider.org",
        "queue": "resolve",
    }
    apply_official_site_result(miss, "")
    assert miss["home_status"] == "unknown"
    assert miss["home_source"] == "search"
    assert miss["queue"] == "resolve"
    assert miss["borrowed_domain"] == "surfrider.org"


def test_search_journal_append_resume_and_overlay(tmp_path):
    journal = tmp_path / "official_homes_search.jsonl"
    append_search_journal(journal, {
        "name": "BMKG", "site": "https://bmkg.go.id/", "ok": True, "error": None,
    })
    append_search_journal(journal, {
        "name": "Ghost Fund", "site": None, "ok": False, "error": None,
    })
    append_search_journal(journal, {
        "name": "Flaky", "site": None, "ok": False, "error": "tinyfish_empty",
    })
    loaded = load_search_journal(journal)
    assert loaded["BMKG"]["site"] == "https://bmkg.go.id/"
    done = journal_done_names(loaded)
    assert "bmkg" in done
    assert "ghost fund" in done
    assert "flaky" not in done
    done_retry = journal_done_names(loaded, retry_unknown=True)
    assert "ghost fund" not in done_retry
    assert "bmkg" in done_retry

    seeds = [
        {
            "name": "BMKG",
            "name_status": "ok",
            "home_status": "borrowed_hub",
            "queue": "resolve",
            "borrowed_domain": "oceandecade.org",
        },
        {
            "name": "Ghost Fund",
            "name_status": "ok",
            "home_status": "unknown",
            "queue": "resolve",
        },
        {
            "name": "Still Todo",
            "name_status": "ok",
            "home_status": "borrowed_hub",
            "queue": "resolve",
        },
    ]
    n = overlay_search_results(seeds, journal=loaded)
    assert n == 2
    by = {s["name"]: s for s in seeds}
    assert by["BMKG"]["home_url"] == "https://bmkg.go.id/"
    assert by["BMKG"]["home_source"] == "search"
    assert by["Ghost Fund"]["home_source"] == "search"
    assert by["Ghost Fund"]["queue"] == "resolve"
    todo = search_candidates(seeds, done_names=done)
    assert [s["name"] for s in todo] == ["Still Todo"]


def test_search_candidates_skip_already_searched():
    seeds = [
        {"name": "A", "name_status": "ok", "home_status": "borrowed_hub", "queue": "resolve"},
        {"name": "B", "name_status": "ok", "home_status": "official", "home_source": "search", "queue": "crawl"},
        {"name": "C", "name_status": "compound", "home_status": "unknown", "queue": "resolve"},
        {"name": "D", "name_status": "ok", "home_status": "unknown", "home_source": "search", "queue": "resolve"},
    ]
    names = {s["name"] for s in search_candidates(seeds)}
    assert names == {"A"}
    retry = {s["name"] for s in search_candidates(seeds, retry_unknown=True)}
    assert retry == {"A", "D"}


def test_dump_catalog_atomic_and_overlay_survives_rebuild(tmp_path):
    catalog = tmp_path / "master_seeds.json"
    seeds = [
        {
            "name": "Save Our Seas Foundation",
            "url": "https://saveourseas.com/",
            "home_url": "https://saveourseas.com/",
            "home_status": "official",
            "home_source": "v1_url",
            "name_status": "ok",
            "queue": "crawl",
            "listing_kind": "homepage",
            "project_count": 2,
        },
        {
            "name": "BMKG",
            "url": "https://bmkg.go.id/",
            "home_url": "https://bmkg.go.id/",
            "home_status": "official",
            "home_source": "search",
            "name_status": "ok",
            "queue": "crawl",
            "listing_kind": "homepage",
            "borrowed_domain": "oceandecade.org",
            "project_count": 2,
        },
    ]
    dump_catalog(seeds, catalog, source="test")
    assert catalog.is_file()
    assert not (tmp_path / "master_seeds.json.tmp").exists()
    data = json.loads(catalog.read_text(encoding="utf-8"))
    assert data["n"] == 2
    audit = tmp_path / "audit.json"
    write_audit(seeds, audit, source="test")
    assert audit.with_suffix(".csv").is_file()

    rebuilt = [
        {
            "name": "BMKG",
            "home_status": "borrowed_hub",
            "home_url": None,
            "url": None,
            "home_source": "",
            "queue": "resolve",
            "name_status": "ok",
            "borrowed_domain": "oceandecade.org",
        },
        {
            "name": "Save Our Seas Foundation",
            "home_status": "official",
            "home_source": "v1_url",
            "queue": "crawl",
            "name_status": "ok",
        },
    ]
    previous = data["seeds"]
    overlay_search_results(rebuilt, previous=previous)
    bmkg = next(s for s in rebuilt if s["name"] == "BMKG")
    assert bmkg["home_source"] == "search"
    assert bmkg["home_url"] == "https://bmkg.go.id/"
    assert bmkg["queue"] == "crawl"
    assert bmkg["borrowed_domain"] == "oceandecade.org"


def test_listing_from_hits_same_host_and_parent_fiche():
    seed = {"name": "Save Our Seas Foundation", "home_url": "https://saveourseas.com/"}
    assert listing_from_hits(
        [{"url": "https://other.org/projects/"}, {"url": "https://saveourseas.com/projects/"}],
        seed,
    ) == "https://saveourseas.com/projects/"
    assert parent_listing_url("https://saveourseas.com/project/alpha") == "https://saveourseas.com/project/"
    assert listing_from_hits(
        [{"url": "https://saveourseas.com/project/alpha"}],
        seed,
    ) == "https://saveourseas.com/project/"
    assert listing_from_hits([{"url": "https://saveourseas.com/about/"}], seed) == ""


def test_listing_candidates_and_apply_and_resume(tmp_path):
    seeds = [
        {
            "name": "SOS",
            "name_status": "ok",
            "home_status": "official",
            "home_url": "https://saveourseas.com/",
            "url": "https://saveourseas.com/",
            "listing_kind": "homepage",
            "queue": "crawl",
        },
        {
            "name": "Ifremer",
            "name_status": "ok",
            "home_status": "official",
            "home_url": "https://ifremer.fr/",
            "url": "https://ifremer.fr/",
            "listing_kind": "home_only",
            "queue": "crawl",
        },
        {
            "name": "Ocean Fdn",
            "name_status": "ok",
            "home_status": "official",
            "listing_kind": "projects_index",
            "listing_url": "https://oceanfdn.org/projects/",
            "home_url": "https://oceanfdn.org/",
            "url": "https://oceanfdn.org/projects/",
            "queue": "crawl",
        },
    ]
    assert [s["name"] for s in listing_candidates(seeds)] == ["SOS"]
    apply_listing_result(seeds[0], "https://saveourseas.com/projects/")
    assert seeds[0]["listing_kind"] == "projects_index"
    assert seeds[0]["listing_source"] == "search"
    assert seeds[0]["url"] == "https://saveourseas.com/projects/"
    journal = tmp_path / "listings.jsonl"
    append_search_journal(journal, {
        "name": "SOS", "listing": "https://saveourseas.com/projects/", "ok": True,
    })
    rebuilt = [
        {
            "name": "SOS",
            "name_status": "ok",
            "home_status": "official",
            "home_url": "https://saveourseas.com/",
            "url": "https://saveourseas.com/",
            "listing_kind": "homepage",
            "queue": "crawl",
        },
    ]
    overlay_listing_results(rebuilt, journal=journal)
    assert rebuilt[0]["listing_url"] == "https://saveourseas.com/projects/"
    done = journal_done_names(load_search_journal(journal), result_key="listing")
    assert listing_candidates(rebuilt, done_names=done) == []


def test_infer_listings_onto_new_official_home():
    seeds = [{
        "name": "Save Our Seas Foundation",
        "name_status": "ok",
        "home_status": "official",
        "home_url": "https://saveourseas.com/",
        "url": "https://saveourseas.com/",
        "listing_kind": "homepage",
        "queue": "crawl",
    }]
    n = infer_listings_onto_official_homes(seeds, [
        {"url": "https://saveourseas.com/project/alpha", "funder": "Save Our Seas Foundation"},
        {"url": "https://saveourseas.com/project/beta", "funder": "Save Our Seas Foundation"},
    ])
    assert n == 1
    assert seeds[0]["listing_url"] == "https://saveourseas.com/project/"
    assert seeds[0]["listing_source"] == "v1_url"


def test_split_compounds_merge_create_and_reclassify():
    assert split_compound_parts("CEA and CNRS") == ["CEA", "CNRS"]
    assert split_compound_parts("Gordon and Betty Moore Foundation") is None
    assert split_compound_parts(
        "Government Secretariat of Science, Technology and Productive Innovation - Argentina"
    ) is None
    seeds = [
        {
            "name": "Fondation de la Mer",
            "name_status": "ok",
            "home_status": "official",
            "home_url": "https://fondationdelamer.org/",
            "url": "https://fondationdelamer.org/nos-programmes/",
            "listing_kind": "projects_index",
            "queue": "crawl",
            "aliases": [],
        },
        {
            "name": "Fondation de la Mer, Fondation Ecoalf",
            "name_status": "compound",
            "home_status": "borrowed_hub",
            "queue": "resolve",
        },
        {
            "name": "International Association of Oil and Gas Producers (IOGP)",
            "name_status": "compound",
            "home_status": "borrowed_hub",
            "queue": "resolve",
        },
        {
            "name": "CEA and CNRS",
            "name_status": "compound",
            "home_status": "unknown",
            "queue": "resolve",
        },
    ]
    report = apply_compound_splits(seeds)
    by = {s["name"]: s for s in seeds}
    assert by["International Association of Oil and Gas Producers (IOGP)"]["name_status"] == "ok"
    assert by["International Association of Oil and Gas Producers (IOGP)"]["queue"] == "resolve"
    assert by["Fondation de la Mer, Fondation Ecoalf"]["queue"] == "skip"
    assert "Fondation Ecoalf" in by
    assert by["Fondation Ecoalf"]["source"] == "split"
    assert by["Fondation Ecoalf"]["queue"] == "resolve"
    assert not is_crawl_ready(by["Fondation Ecoalf"])
    assert "CEA" in by and "CNRS" in by
    assert assign_queue(by["Fondation de la Mer"]) == "crawl"
    assert "Fondation de la Mer, Fondation Ecoalf" in report["split_sources"]


def test_home_review_reject_keep_and_no_projects():
    assert is_listing_url("https://www.monacoexplorations.org/missions/")
    monaco = {
        "name": "Monaco",
        "home_status": "official",
        "home_source": "search",
        "home_url": "https://www.asmonaco.com/",
        "url": "https://www.asmonaco.com/",
        "queue": "crawl",
        "name_status": "ok",
        "listing_kind": "homepage",
    }
    apply_home_review(monaco, {"name": "Monaco", "action": "reject"})
    assert monaco["home_status"] == "unknown"
    assert monaco["queue"] == "resolve"
    assert monaco["home_url"] is None
    assert not is_crawl_ready(monaco)
    expl = {
        "name": "Monaco Explorations",
        "home_status": "official",
        "home_source": "search",
        "home_url": "https://www.monacoexplorations.org/",
        "url": "https://www.monacoexplorations.org/",
        "queue": "crawl",
        "name_status": "ok",
        "listing_kind": "homepage",
    }
    apply_home_review(expl, {
        "name": "Monaco Explorations",
        "action": "keep",
        "home_url": "https://www.monacoexplorations.org/",
        "listing_url": "https://www.monacoexplorations.org/missions/",
    })
    assert expl["listing_url"] == "https://www.monacoexplorations.org/missions/"
    assert expl["listing_kind"] == "projects_index"
    assert expl["queue"] == "crawl"
    assert is_crawl_ready(expl)
    drake = {
        "name": "Drake Enterprise Foundation",
        "home_status": "official",
        "home_url": "https://drakespm.com/",
        "url": "https://drakespm.com/",
        "queue": "crawl",
        "name_status": "ok",
    }
    apply_home_review(drake, {
        "name": "Drake Enterprise Foundation",
        "action": "no_projects",
        "home_url": "https://drakespm.com/",
    })
    assert drake["listing_kind"] == "home_only"
    assert drake["queue"] == "skip"
    assert not is_crawl_ready(drake)
    seeds = [monaco]
    overlay_search_results(seeds, journal={
        "Monaco": {"name": "Monaco", "site": "https://www.asmonaco.com/", "ok": True},
    })
    overlay_home_reviews(seeds, [{"name": "Monaco", "action": "reject"}])
    assert seeds[0]["home_status"] == "unknown"
    assert search_candidates(seeds) == []


def test_accept_partner_url_rejects_hub_publisher_and_mismatch():
    listing = accept_partner_url(
        "Wild Oysters", "https://wild-oysters.org/projects/")
    assert listing["url"] == "https://wild-oysters.org/projects/"
    assert listing["listing_kind"] == "projects_index"
    assert listing["home_status"] == "official"
    home = accept_partner_url("Wild Oysters", "https://wild-oysters.org/about/")
    assert home["url"] == "https://wild-oysters.org/"
    assert home["listing_kind"] == "homepage"
    owner = accept_partner_url("Ocean Decade", "https://oceandecade.org/actions/")
    assert owner and owner["listing_kind"] == "projects_index"
    assert accept_partner_url("BMKG", "https://oceandecade.org/actions/") is None
    assert accept_partner_url("BMKG", "https://www.nature.com/articles/x") is None
    assert accept_partner_url("Another New", "https://brand-new.example/") is None
    assert accept_partner_url("Wild Oysters", "https://facebook.com/wild") is None


def test_decide_ftm_uses_catalog_or_skips():
    catalog = [{
        "name": "Rare Fish Forever",
        "url": "https://rare.org/program/fish-forever/",
        "listing_url": "https://rare.org/program/fish-forever/",
        "home_url": "https://rare.org/",
        "home_status": "official",
        "name_status": "ok",
        "queue": "crawl",
        "listing_kind": "projects_index",
        "aliases": ["Rare"],
        "source": "curated",
    }]
    hit = decide_follow_the_money_partner(
        "Rare", "https://rare.org/our-work/", catalog=catalog)
    assert hit["action"] == FTM_DISCOVER
    assert hit["reason"] == "catalog"
    assert hit["seed"]["url"] == "https://rare.org/program/fish-forever/"
    assert hit["needs_search"] is False

    borrowed = [{
        "name": "BMKG",
        "url": "https://oceandecade.org/",
        "home_status": "borrowed_hub",
        "queue": "resolve",
        "name_status": "ok",
    }]
    skip_hub = decide_follow_the_money_partner(
        "BMKG", "https://bmkg.go.id/", catalog=borrowed)
    assert skip_hub["action"] == FTM_SKIP
    assert skip_hub["reason"] == "catalog_not_ready"
    assert skip_hub["needs_search"] is False

    rejected = [{
        "name": "Monaco",
        "home_status": "unknown",
        "queue": "resolve",
        "review_action": "reject",
        "name_status": "ok",
    }]
    skip_rev = decide_follow_the_money_partner(
        "Monaco", "https://www.asmonaco.com/", catalog=rejected)
    assert skip_rev["action"] == FTM_SKIP
    assert skip_rev["reason"] == "catalog_not_ready"

    drake = [{
        "name": "Drake Enterprise Foundation",
        "url": "https://drakespm.com/",
        "home_status": "official",
        "queue": "skip",
        "review_action": "no_projects",
        "listing_kind": "home_only",
        "name_status": "ok",
    }]
    skip_np = decide_follow_the_money_partner(
        "Drake Enterprise Foundation", "https://drakespm.com/", catalog=drake)
    assert skip_np["action"] == FTM_SKIP
    assert not is_crawl_ready(drake[0])


def test_decide_ftm_name_and_search_gates():
    assert decide_follow_the_money_partner("Unknown", "https://unknown.org/")["reason"] == "exclude"
    assert decide_follow_the_money_partner("CEA and CNRS", "https://cnrs.fr/")["reason"] == "compound"
    need = decide_follow_the_money_partner("Wild Oysters", None)
    assert need["action"] == FTM_SEARCH
    assert need["needs_search"] is True
    bad = decide_follow_the_money_partner("BMKG", "https://oceandecade.org/actions/")
    assert bad["action"] == FTM_SEARCH
    found = decide_follow_the_money_partner(
        "BMKG", "https://oceandecade.org/actions/",
        searched_home="https://bmkg.go.id/", did_search=True,
    )
    assert found["action"] == FTM_DISCOVER
    assert found["reason"] == "search"
    assert found["seed"]["url"] == "https://bmkg.go.id/"
    empty = decide_follow_the_money_partner(
        "Wild Oysters", None, searched_home="", did_search=True)
    assert empty["action"] == FTM_SKIP
    assert empty["reason"] == "search_empty"

    hunt = decide_follow_the_money_partner(
        "La chasse en France", "https://www.chasseurdefrance.com/")
    assert hunt["action"] == FTM_SKIP
    assert hunt["reason"] == "exclude"

    wacan = decide_follow_the_money_partner(
        "Wacan", "https://www.wacan.com/")
    assert wacan["action"] == FTM_SEARCH
    assert wacan["reason"] == "short_name"
    assert wacan["needs_search"] is True

    wacan_empty = decide_follow_the_money_partner(
        "Wacan", "https://www.wacan.com/", searched_home="", did_search=True)
    assert wacan_empty["action"] == FTM_SKIP
    assert wacan_empty["reason"] == "search_empty"

    wwf_cat = [{
        "name": "WWF Oceans",
        "url": "https://www.worldwildlife.org/initiatives/oceans",
        "home_url": "https://worldwildlife.org/",
        "home_status": "official",
        "name_status": "ok",
        "queue": "crawl",
        "listing_kind": "projects_index",
        "aliases": ["WWF"],
        "source": "curated",
    }]
    wwf = decide_follow_the_money_partner(
        "WWF International", "https://www.wwf.org/", catalog=wwf_cat)
    assert wwf["action"] == FTM_DISCOVER
    assert wwf["reason"] == "catalog"
    assert "worldwildlife.org" in wwf["seed"]["url"]
