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
    assert len(fiche["sources_td"]) == 1
    assert fiche["ports"][0]["name"] == "Fort Bay"
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
    assert len(fiche["sources_td"]) == 1
    by = {p["name"]: p["url_bu"]["url"] for p in fiche["ports"]}
    assert by["Fort Bay"] == "https://gov.bq/fort-bay"
    assert by["Ladder Bay"] == "https://gov.bq/ladder"
    assert by["Fort Bay"] != by["Ladder Bay"]


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


def test_one_url_per_domain_prefers_list_pdf():
    zone = {
        **_ZONE,
        "sources": [
            {"url": "https://douane.gouv.fr/accueil", "domain": "douane.gouv.fr"},
            {"url": "https://douane.gouv.fr/ports-entree.pdf", "domain": "douane.gouv.fr"},
        ],
    }
    fiche = assemble_zone_fiche(zone, [])
    assert fiche["sources_td_total"] == 2
    assert len(fiche["sources_td"]) == 1
    assert fiche["url_td"]["url"].endswith(".pdf")


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
    assert f1["wrote_poe_ports"] is False


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
    assert "poe-fiche-port-bu" in fiche
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
    label_js = (root / "components" / "map" / "zoneLabel.js").read_text(encoding="utf-8")
    assert "disambiguated" in label_js
    assert "qualifier_key" in label_js

