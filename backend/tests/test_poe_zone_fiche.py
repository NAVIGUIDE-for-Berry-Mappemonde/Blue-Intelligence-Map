"""Fiche ZEE — PoE + URLs TD/BU, jamais une preuve Noonsite, 0 écriture Atlas."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.poe_zone_fiche import (  # noqa: E402
    assemble_zone_fiche, url_is_community,
)


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, n):
        return list(self._docs)[:n]


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find(self, q, proj=None):
        out = [d for d in self.docs if all(d.get(k) == v for k, v in (q or {}).items())]
        return _FakeCursor(out)

    async def find_one(self, q, proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in (q or {}).items()):
                return d
        return None


class _FakeDB:
    def __init__(self, *, zones=None, ports=None, seeds=None, run_ports=None,
                 run_zones=None):
        self.eez_zones = _FakeColl(zones)
        self.poe_ports = _FakeColl(ports)
        self.poe_seed_ports = _FakeColl(seeds)
        self.poe_run_ports = _FakeColl(run_ports)
        self.poe_run_zones = _FakeColl(run_zones)


_ZONE = {
    "mrgid": 26518, "name": "Saba", "geoname": "Saba", "iso2": "BQ",
    "sov_iso2": "NL", "sovereign": "Netherlands", "status": "ia",
    "poe_count": 1, "confidence_avg": 72, "bbox": [1, 2, 3, 4],
    "anchor": [-63.24, 17.63],
    "sources": [{
        "url": "https://douane.gouv.fr/saba-list",
        "domain": "douane.gouv.fr", "official": True,
        "collected_at": "2026-09-01T00:00:00Z",
    }],
}


def test_community_urls_are_dropped():
    assert url_is_community("https://www.noonsite.com/saba")
    assert url_is_community("https://en.wikipedia.org/wiki/Saba")
    assert not url_is_community("https://douane.gouv.fr/ports")


def test_assemble_td_bu_ports_no_write_and_no_noonsite():
    ports = [{
        "_id": "p1", "name": "Fort Bay", "lat": 17.62, "lon": -63.25,
        "confidence": 80, "validated": True, "spatial_kind": "in_eez",
        "source_urls": [
            "https://douane.gouv.fr/saba-list",
            "https://www.noonsite.com/fort-bay",
        ],
    }]
    seeds = [{
        "mrgid": 26518, "name": "Fort Bay",
        "judge_sources": [
            "https://www.rvo.nl/saba-clearance",
            "https://noonsite.com/x",
        ],
    }]
    fiche = assemble_zone_fiche(_ZONE, ports, seeds=seeds)
    assert fiche["wrote_poe_ports"] is False
    assert fiche["crawled"] is False
    assert fiche["mrgid"] == 26518
    assert fiche["url_td"]["url"] == "https://douane.gouv.fr/saba-list"
    assert [s["url"] for s in fiche["sources_td"]] == ["https://douane.gouv.fr/saba-list"]
    assert fiche["ports"][0]["name"] == "Fort Bay"
    assert fiche["ports"][0]["port_id"] == "26518:fortbay"
    assert fiche["ports"][0]["url_bu"]["url"] == "https://www.rvo.nl/saba-clearance"
    assert "noonsite" not in (fiche["ports"][0]["url_bu"]["url"] or "").lower()
    assert "noonsite" not in (fiche["url_td"]["url"] or "").lower()
    assert fiche["kind"] == "general_list"
    assert fiche["confidence_avg"] == 72


def test_url_in_both_arms_is_gold():
    zone = {
        **_ZONE,
        "sources": [{"url": "https://gov.example/list", "domain": "gov.example"}],
        "sources_td": [],
        "sources_bu": [],
    }
    ports = [{"_id": "p1", "name": "Fort Bay", "lat": 17.62, "lon": -63.25}]
    seeds = [{"name": "Fort Bay", "judge_sources": ["https://gov.example/list"]}]
    fiche = assemble_zone_fiche(zone, ports, seeds=seeds)
    assert fiche["url_td"]["url"] == "https://gov.example/list"
    assert fiche["url_td"]["from_arm"] == "both"
    assert fiche["ports"][0]["url_bu"]["url"] == "https://gov.example/list"
    assert fiche["ports"][0]["url_bu"]["from_arm"] == "both"


def test_one_bu_url_per_port_not_a_zone_pile():
    zone = {**_ZONE, "sources": [
        {"url": "https://gov.example/accueil", "domain": "gov.example"},
        {"url": "https://gov.example/ports-entree.pdf", "domain": "gov.example"},
    ]}
    ports = [
        {"_id": "a", "name": "Fort Bay"},
        {"_id": "b", "name": "Ladder Bay"},
    ]
    seeds = [
        {"name": "Fort Bay", "judge_sources": ["https://gov.bq/fort-bay"]},
        {"name": "Ladder Bay", "judge_sources": ["https://gov.bq/ladder"]},
    ]
    fiche = assemble_zone_fiche(zone, ports, seeds=seeds)
    assert fiche["url_td"]["url"].endswith("ports-entree.pdf")
    td_urls = [s["url"] for s in fiche["sources_td"]]
    assert td_urls[0].endswith("ports-entree.pdf")
    assert "https://gov.example/accueil" in td_urls
    assert len(td_urls) == 2
    by = {p["name"]: p["url_bu"]["url"] for p in fiche["ports"]}
    assert by["Fort Bay"] == "https://gov.bq/fort-bay"
    assert by["Ladder Bay"] == "https://gov.bq/ladder"
    assert by["Fort Bay"] != by["Ladder Bay"]
    assert fiche["ports"][0]["urls_bu"][0]["url"] in by.values()


def test_unclos_without_sources_is_kind_none():
    zone = {**_ZONE, "sources": [], "unclos": {"code": "uninhabited"}}
    fiche = assemble_zone_fiche(zone, [])
    assert fiche["kind"] == "none"
    assert fiche["ports"] == []
    assert fiche["sources_td"] == []
    assert fiche["sources_bu"] == []


def test_empty_seeds_create_zero_ports():
    fiche = assemble_zone_fiche(_ZONE, [], seeds=[], run_ports=[])
    assert fiche["ports"] == []
    assert fiche["wrote_poe_ports"] is False


def test_http_https_and_www_are_same_td():
    zone = {
        **_ZONE,
        "sources": [
            {"url": "http://www.douane.gouv.fr/ports-entree.pdf", "domain": "douane.gouv.fr"},
            {"url": "https://douane.gouv.fr/ports-entree.pdf", "domain": "douane.gouv.fr"},
            {"url": "https://douane.gouv.fr/accueil", "domain": "douane.gouv.fr"},
        ],
    }
    fiche = assemble_zone_fiche(zone, [])
    urls = [s["url"] for s in fiche["sources_td"]]
    assert len(urls) == 2
    assert urls[0].startswith("https://") and urls[0].endswith("ports-entree.pdf")
    assert any(u.endswith("/accueil") for u in urls)


def test_all_td_urls_kept_pdf_first():
    zone = {
        **_ZONE,
        "sources": [
            {"url": "https://douane.gouv.fr/accueil", "domain": "douane.gouv.fr"},
            {"url": "https://douane.gouv.fr/ports-entree.pdf", "domain": "douane.gouv.fr"},
        ],
    }
    fiche = assemble_zone_fiche(zone, [])
    assert fiche["sources_td_total"] == 2
    assert len(fiche["sources_td"]) == 2
    assert fiche["url_td"]["url"].endswith(".pdf")
    assert fiche["sources_td"][0]["url"].endswith(".pdf")
    assert fiche["sources_td"][1]["url"].endswith("/accueil")


def test_english_customs_homepage_loses_to_list_pdf():
    zone = {
        **_ZONE,
        "sources": [
            {
                "url": "http://www.douane.gouv.fr/french-customs-information-available-english",
                "domain": "douane.gouv.fr", "official": True,
            },
            {
                "url": "https://www.douane.gouv.fr/sites/default/files/2025-02/28/Liste%20des%20ports%20de%20plaisance%20rattach%C3%A9s%20au%20dispositif.pdf",
                "domain": "douane.gouv.fr", "official": True,
            },
        ],
    }
    fiche = assemble_zone_fiche(zone, [])
    assert "dispositif.pdf" in fiche["url_td"]["url"]
    assert "information-available-english" not in fiche["url_td"]["url"]


def test_france_hexagon_uses_curated_pleasure_list():
    from app.services.poe_zone_fiche import build_zone_fiche

    hexagon = {
        "mrgid": 5677, "name": "France", "geoname": "French Exclusive Economic Zone",
        "iso2": "FR", "sov_iso2": "FR", "sovereign": "France", "pol_type": "200NM",
        "status": "ia", "poe_count": 0, "sources": [
            {"url": "http://www.douane.gouv.fr/french-customs-information-available-english",
             "domain": "douane.gouv.fr", "official": True},
        ],
    }
    db = _FakeDB(zones=[hexagon], ports=[])
    fiche = asyncio.run(build_zone_fiche(db, 5677))
    assert "plaisance" in (fiche["url_td"]["url"] or "").lower()
    assert "information-available-english" not in (fiche["url_td"]["url"] or "")


def test_mayotte_does_not_inherit_metropolitan_pdf():
    from app.services.poe_zone_fiche import build_zone_fiche

    mayotte = {
        "mrgid": 48944, "name": "Mayotte",
        "geoname": "Overlapping claim Mayotte: France / Comores",
        "iso2": "YT", "sov_iso2": "FR", "sovereign": "France",
        "pol_type": "Overlapping claim", "status": "non_generee", "poe_count": 0,
        "sources": [],
    }
    db = _FakeDB(zones=[mayotte], ports=[])
    fiche = asyncio.run(build_zone_fiche(db, 48944))
    url = (fiche.get("url_td") or {}).get("url") or ""
    assert "plaisance" not in url.lower()
    assert "ics-liste" in url or "mayotte" in url


def test_list_like_seed_can_become_td():
    zone = {**_ZONE, "mrgid": 5670, "sources": [
        {"url": "https://dogana.gov.al/accueil", "domain": "dogana.gov.al"},
    ]}
    seeds = [{
        "mrgid": 5670, "name": "Durrës",
        "judge_sources": [
            "https://asp.gov.al/wp-content/uploads/2024/11/Udhezim-PER-LISTEN-E-PKK.pdf",
        ],
    }]
    fiche = assemble_zone_fiche(zone, [], seeds=seeds)
    assert fiche["url_td"]["url"].endswith("LISTEN-E-PKK.pdf")


def test_build_zone_fiche_reads_only():
    from app.services.poe_zone_fiche import build_zone_fiche

    db = _FakeDB(
        zones=[_ZONE],
        ports=[{"_id": "p1", "name": "Fort Bay", "mrgid": 26518,
                "lat": 17.62, "lon": -63.25, "source_urls": ["https://gov.bq/x"]}],
        seeds=[{"mrgid": 26518, "name": "Fort Bay", "judge_sources": ["https://gov.bq/bu"]}],
    )
    fiche = asyncio.run(build_zone_fiche(db, 26518))
    assert fiche["ports"][0]["name"] == "Fort Bay"
    assert fiche["ports"][0]["url_bu"]["url"] == "https://gov.bq/bu"
    missing = asyncio.run(build_zone_fiche(db, 999999))
    assert missing is None


def test_france_hexagon_fiche_does_not_absorb_mayotte():
    from app.services.poe_zone_fiche import build_zone_fiche

    hexagon = {
        "mrgid": 5677, "name": "France", "geoname": "French Exclusive Economic Zone",
        "iso2": "FR", "sov_iso2": "FR", "sovereign": "France", "pol_type": "200NM",
        "status": "ia", "poe_count": 1, "sources": [],
    }
    mayotte = {
        "mrgid": 48944, "name": "Mayotte",
        "geoname": "Overlapping claim Mayotte: France / Comores",
        "iso2": "YT", "sov_iso2": "FR", "sovereign": "France",
        "pol_type": "Overlapping claim", "status": "non_generee", "poe_count": 0,
        "sources": [],
    }
    db = _FakeDB(
        zones=[hexagon, mayotte],
        ports=[
            {"_id": "p1", "name": "Marseille", "mrgid": 5677, "lat": 43.3, "lon": 5.3,
             "source_urls": ["https://douane.gouv.fr/marseille"]},
            {"_id": "p2", "name": "Mamoudzou", "mrgid": 48944, "lat": -12.78, "lon": 45.23,
             "source_urls": ["https://douane.gouv.fr/mayotte"]},
        ],
    )
    f1 = asyncio.run(build_zone_fiche(db, 5677))
    f2 = asyncio.run(build_zone_fiche(db, 48944))
    assert f1["label"] == "France (hexagone)"
    assert f2["label"] == "France (Mayotte)"
    assert [p["name"] for p in f1["ports"]] == ["Marseille"]
    assert [p["name"] for p in f2["ports"]] == ["Mamoudzou"]
    assert "plaisance" in (f1["url_td"]["url"] or "").lower()
    assert "plaisance" not in ((f2.get("url_td") or {}).get("url") or "").lower()
    assert f1["wrote_poe_ports"] is False


def test_published_union_keeps_all_td_and_run_only_ports():
    from app.services.poe_zone_fiche import build_zone_fiche

    albania = {
        "mrgid": 5670, "name": "Albania", "geoname": "Albanian Exclusive Economic Zone",
        "iso2": "AL", "sov_iso2": "AL", "sovereign": "Albania", "pol_type": "200NM",
        "status": "ia", "poe_count": 1,
        "sources": [{"url": "https://dogana.gov.al/accueil", "domain": "dogana.gov.al"}],
    }
    db = _FakeDB(
        zones=[albania],
        ports=[{
            "_id": "v1", "name": "Durrës", "mrgid": 5670, "lat": 41.3, "lon": 19.4,
            "confidence": 80, "validated": True,
        }],
        seeds=[{
            "mrgid": 5670, "name": "Durrës",
            "judge_sources": ["https://dogana.gov.al/durres"],
        }, {
            "mrgid": 5670, "name": "Vlorë",
            "judge_sources": ["https://dogana.gov.al/vlore"],
        }],
        run_ports=[
            {
                "_id": "r1", "run_id": "bestof3-complete", "name": "Sarandë",
                "mrgid": 5670, "lat": 39.87, "lon": 20.0,
                "judge_sources": [
                    "https://asp.gov.al/sarande",
                    "https://asp.gov.al/sarande.pdf",
                ],
            },
            {
                "_id": "r2", "run_id": "tinyfish-vs-v1-full", "name": "Durrës",
                "mrgid": 5670,
            },
            {
                "_id": "rc", "run_id": "canary-1", "name": "Canary Port",
                "mrgid": 5670,
            },
        ],
        run_zones=[
            {**albania, "run_id": "bestof3-complete", "sources": [{
                "url": "https://asp.gov.al/wp-content/uploads/2024/11/Udhezim-PER-LISTEN-E-PKK.pdf",
                "domain": "asp.gov.al", "official": True,
            }]},
            {**albania, "run_id": "tinyfish-vs-v1-full", "sources": [{
                "url": "https://dogana.gov.al/accueil", "domain": "dogana.gov.al",
            }]},
            {**albania, "run_id": "canary-1", "sources": [{
                "url": "https://canary.test/al", "domain": "canary.test",
                "official": True,
            }]},
        ],
    )
    fiche = asyncio.run(build_zone_fiche(db, 5670, union=True))
    names = [p["name"] for p in fiche["ports"]]
    assert names == ["Durrës", "Sarandë", "Vlorë"]
    assert fiche["fiche_scope"] == "union"
    td_urls = [s["url"] for s in fiche["sources_td"]]
    assert any("LISTEN-E-PKK.pdf" in u for u in td_urls)
    assert any("dogana.gov.al/accueil" in u for u in td_urls)
    assert not any("canary.test" in u for u in td_urls)
    assert fiche["url_td"]["url"].endswith(".pdf")
    sarande = next(p for p in fiche["ports"] if p["name"] == "Sarandë")
    assert [u["url"] for u in sarande["urls_bu"]][0].endswith(".pdf")
    assert len(sarande["urls_bu"]) == 2
    mapped = asyncio.run(build_zone_fiche(db, 5670))
    assert [p["name"] for p in mapped["ports"]] == ["Durrës"]
    assert mapped["fiche_scope"] == "published"
    assert any("LISTEN-E-PKK.pdf" in u for u in [s["url"] for s in mapped["sources_td"]])


def test_frontend_fiche_has_no_generate_button():
    root = Path(__file__).resolve().parents[2] / "frontend" / "src"
    popup = (root / "components" / "map" / "zonePopup.js").read_text(encoding="utf-8")
    fiche = (root / "components" / "ZoneFiche.js").read_text(encoding="utf-8")
    panel = (root / "components" / "FormalitiesPanel.js").read_text(encoding="utf-8")
    review = (root / "components" / "ReviewView.js").read_text(encoding="utf-8")
    header = (root / "components" / "Header.js").read_text(encoding="utf-8")
    for src in (popup, fiche, panel, review, header):
        assert "generate-btn" not in src
        assert "poe-generate" not in src
        assert "/generate" not in src
    assert "wpi_commercial" not in fiche
    assert "poe-fiche-td-url" in fiche
    assert "poe-fiche-td-path" in fiche
    assert "poe-fiche-td-list" in fiche
    assert "poe-fiche-port-bu" in fiche
    assert "poe-fiche-td-keep" in fiche
    assert "poe-fiche-port-keep" in fiche
    assert "poe-fiche-bu-keep" in fiche
    assert "poe-fiche-sources-bu" not in fiche
    assert "poe-zone-fiche" in fiche
    assert "ExternalLink" in fiche
    assert "poe-fiche-popup-td" in popup
    assert "poe-fiche-popup-port-bu" in popup
    assert "poe-fiche-popup-bu" not in popup
    assert "zoneDisplayName" in fiche
    assert "view-toggle-review" in header
    assert "review-comment" in review
    assert "review-gold" in review
    assert "review-kind-switch" not in review
    assert "review-gold" in review
    assert "onChoice" in review
    assert "map-show-review" in (root / "components" / "MapView.js").read_text(encoding="utf-8")
    assert "reviewShowReview" in (root / "i18n.js").read_text(encoding="utf-8")
    label_js = (root / "components" / "map" / "zoneLabel.js").read_text(encoding="utf-8")
    assert "disambiguated" in label_js
    assert "qualifier_key" in label_js

