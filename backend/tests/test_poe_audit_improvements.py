"""Audit PoE : whitelist ZEE, filtre SERP, RAG listes, spatial, score, monitoring."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.extract import audit_serp_filter, serp_filter
from app.core.geo import classify_poe_point
from app.core.rag import list_like_score, select_list_context
from app.services import poe_pipeline as poe
from app.services.poe_confidence import score_port


class TestWhitelistEezOnly:
    def test_nepal_not_constructed(self):
        assert poe.build_whitelist("NP", "NP") == []

    def test_slovakia_not_constructed(self):
        assert poe.build_whitelist("SK", "SK") == []

    def test_belgium_has_domains(self):
        wl = poe.build_whitelist("BE", "BE")
        assert "belgium.be" in wl or "fgov.be" in wl

    def test_ukraine_still_gov(self):
        assert "gov.ua" in poe.build_whitelist("UA", "UA")

    def test_jamaica_not_seven_labels(self):
        wl = poe.build_whitelist("JM", "JM")
        gov_like = [d for d in wl if d.endswith(".jm") and d.split(".")[0] in poe.GOV_LABELS]
        assert len(gov_like) <= 1, wl


class TestSerpProtectOfficial:
    def test_tourism_on_gov_kept(self):
        results = [
            {"url": "https://www.douane.gouv.fr/tourism-yacht-clearance"},
            {"url": "https://www.tripadvisor.com/Attractions-g147-Fiji.html"},
        ]
        kept = [r["url"] for r in serp_filter(results)]
        assert kept == ["https://www.douane.gouv.fr/tourism-yacht-clearance"]

    def test_audit_explains_drops(self):
        rows = audit_serp_filter([
            {"url": "https://www.tripadvisor.com/x"},
            {"url": "https://www.douane.gouv.fr/brochure-plaisance"},
        ])
        by = {r["url"]: r for r in rows}
        assert by["https://www.tripadvisor.com/x"]["kept"] is False
        assert by["https://www.tripadvisor.com/x"]["reason"] == "hard"
        assert by["https://www.douane.gouv.fr/brochure-plaisance"]["kept"] is True
        assert by["https://www.douane.gouv.fr/brochure-plaisance"]["protected"] is True


class TestBestPerDomainPageAndPdf:
    def test_keeps_decree_pdf_and_page(self):
        cands = [
            {"url": "https://aduana.gob.mx/noticias", "domain": "aduana.gob.mx",
             "score_serp": 0.4},
            {"url": "https://aduana.gob.mx/decreto.pdf", "domain": "aduana.gob.mx",
             "score_serp": 0.4},
        ]
        best = poe._best_per_domain(cands)
        urls = [c["url"] for c in best]
        assert any(u.endswith(".pdf") for u in urls)
        assert any("noticias" in u for u in urls)
        assert len(best) == 2


class TestListAwareRag:
    def test_list_chunk_outranks_prose(self):
        prose = "The ministry was established in 1992 and reformed several times. "
        listing = "1.- Port Alpha latitude: 10.0 longitude: 20.0. 2.- Port Beta "
        text = (prose * 80) + listing + (prose * 80)
        ctx = select_list_context("ports of entry", text, max_chars=800, size=200)
        assert "Port Alpha" in ctx
        assert list_like_score(listing) > list_like_score(prose)


class TestSpatialCoastal:
    def test_point_inside_polygon(self):
        from shapely.geometry import box
        geom = box(-2, 48, 2, 51)  # lon/lat
        out = classify_poe_point(49.5, 0.0, geom)
        assert out["kind"] == "in_eez"
        assert out["validated"] is True

    def test_far_inland_rejected(self):
        from shapely.geometry import box
        geom = box(-2, 48, 2, 51)
        # Paris-ish, well inland north of... wait lat 48-51 is the box.
        # Point south of box on land: 47.0, 2.0 is south of Brittany box
        out = classify_poe_point(45.0, 2.0, geom)
        assert out["validated"] is False
        assert out["kind"] in ("inland", "other_water")


class TestConfidenceScore:
    def test_official_catalog_in_eez_is_high(self):
        port = {
            "name": "Papeete",
            "extraction_engine": "catalog",
            "extraction_agreement": True,
            "claude_agreement": True,
            "validated": True,
            "spatial_kind": "in_eez",
            "geocode_agree": True,
            "lat": -17.5, "lon": -149.5,
            "note": "catalogue officiel (nom + coordonnées dans la source)",
            "source_urls": ["https://douane.gouv.fr/x"],
        }
        s = score_port(port, official_source=True)
        assert s["confidence"] >= 70
        assert "source d'État" in s["reasons"]

    def test_synthesis_only_is_low(self):
        port = {
            "name": "Somewhere",
            "from_synthesis": True,
            "extraction_engine": "llm",
            "validated": False,
            "spatial_kind": "rejected",
            "source_urls": [],
        }
        s = score_port(port, official_source=False)
        assert s["confidence"] < 40


class TestMonitoringOnlyOnRefresh:
    def test_skip_requires_refresh_flag_in_signature(self):
        import inspect
        sig = inspect.signature(poe.generate_zone_poe)
        assert "refresh" in sig.parameters
        assert sig.parameters["refresh"].default is False
