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
    td_urls = [s["url"] for s in fiche["sources_td"]]
    bu_urls = [s["url"] for s in fiche["sources_bu"]]
    assert td_urls == ["https://douane.gouv.fr/saba-list"]
    assert bu_urls == ["https://www.rvo.nl/saba-clearance"]
    assert all("noonsite" not in u.lower() for u in td_urls + bu_urls)
    assert fiche["ports"][0]["name"] == "Fort Bay"
    assert "noonsite" not in "".join(fiche["ports"][0]["source_urls"]).lower()
    assert fiche["kind"] == "general_list"
    assert fiche["confidence_avg"] == 72


def test_url_in_both_arms_is_gold():
    zone = {
        **_ZONE,
        "sources_td": ["https://gov.example/list"],
        "sources_bu": ["https://gov.example/list"],
        "sources": [],
    }
    fiche = assemble_zone_fiche(zone, [])
    assert fiche["urls"][0]["from_arm"] == "both"
    assert fiche["sources_td"][0]["from_arm"] == "both"
    assert fiche["sources_bu"][0]["from_arm"] == "both"


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


def test_build_zone_fiche_reads_only():
    from app.services.poe_zone_fiche import build_zone_fiche

    db = _FakeDB(
        zones=[_ZONE],
        ports=[{"_id": "p1", "name": "Fort Bay", "mrgid": 26518,
                "lat": 17.62, "lon": -63.25, "source_urls": ["https://gov.bq/x"]}],
        seeds=[{"mrgid": 26518, "judge_sources": ["https://gov.bq/bu"]}],
    )
    fiche = asyncio.run(build_zone_fiche(db, 26518))
    assert fiche["ports"][0]["name"] == "Fort Bay"
    assert any(s["from_arm"] in ("bu", "both") for s in fiche["sources_bu"])
    missing = asyncio.run(build_zone_fiche(db, 999999))
    assert missing is None


def test_frontend_fiche_has_no_generate_button():
    root = Path(__file__).resolve().parents[2] / "frontend" / "src"
    popup = (root / "components" / "map" / "zonePopup.js").read_text(encoding="utf-8")
    fiche = (root / "components" / "ZoneFiche.js").read_text(encoding="utf-8")
    panel = (root / "components" / "FormalitiesPanel.js").read_text(encoding="utf-8")
    for src in (popup, fiche, panel):
        assert "generate-btn" not in src
        assert "poe-generate" not in src
        assert "/generate" not in src
    assert "wpi_commercial" not in fiche
    assert "sources_td" in popup or "poeSourcesTd" in popup
    assert "poe-zone-fiche" in fiche
    assert "ExternalLink" in fiche

