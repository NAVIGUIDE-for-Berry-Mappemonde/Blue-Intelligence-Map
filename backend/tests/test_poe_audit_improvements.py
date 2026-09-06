"""Audit PoE : whitelist ZEE, filtre SERP, RAG listes, spatial, score, monitoring."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.extract import audit_serp_filter, serp_filter
from app.core.geo import (
    classify_poe_point, harbour_evidence, inland_exception_flags,
)
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

    def test_sliver_two_km_is_still_eez(self):
        from shapely.geometry import box
        geom = box(-2, 48, 2, 51)
        # ~2 km south of the southern edge (1° lat ≈ 111 km)
        out = classify_poe_point(47.982, 0.0, geom)
        assert out["kind"] == "in_eez"
        assert out["validated"] is True
        assert out["dist_km"] <= 2.2

    def test_ten_km_land_is_coastal(self):
        from shapely.geometry import box
        # Mer du Nord allemande (approx.) ; Hambourg est à terre plus au sud-est.
        geom = box(6.5, 53.9, 8.8, 55.2)
        # Cuxhaven / Elbe ~10 km au sud du polygone, à terre
        out = classify_poe_point(53.86, 8.70, geom)
        assert out["kind"] == "coastal_land"
        assert out["validated"] is True
        assert 2.2 < out["dist_km"] <= 15.0

    def test_hundred_km_city_rejected(self):
        from shapely.geometry import box
        geom = box(6.5, 53.9, 8.8, 55.2)
        # Munich : même pays, ville intérieure, pas un port
        out = classify_poe_point(
            48.14, 11.58, geom,
            inland={"country_ok": True, "harbour_like": False},
        )
        assert out["validated"] is False
        assert out["kind"] == "inland"

    def test_hundred_km_harbour_is_inland_river(self):
        from shapely.geometry import box
        geom = box(6.5, 53.9, 8.8, 55.2)
        # Hambourg / Elbe ~100 km dans les terres
        out = classify_poe_point(
            53.54, 9.99, geom,
            inland={"country_ok": True, "harbour_like": True},
        )
        assert out["kind"] == "inland_river"
        assert out["validated"] is True
        assert 15.0 < out["dist_km"] <= 400.0

    def test_five_hundred_km_harbour_rejected(self):
        from shapely.geometry import box
        geom = box(6.5, 53.9, 8.8, 55.2)
        # Trop loin même avec preuve de port
        out = classify_poe_point(
            48.14, 11.58, geom,
            inland={"country_ok": True, "harbour_like": True},
        )
        assert out["validated"] is False
        assert out["kind"] == "inland"
        assert out["dist_km"] > 400.0

    def test_far_inland_rejected(self):
        from shapely.geometry import box
        geom = box(-2, 48, 2, 51)
        out = classify_poe_point(45.0, 2.0, geom)
        assert out["validated"] is False
        assert out["kind"] in ("inland", "other_water")


class TestHarbourEvidence:
    def test_name_and_osm(self):
        assert harbour_evidence({"name": "Port of Hamburg"}) is True
        assert harbour_evidence({"name": "München"}) is False
        assert harbour_evidence({"name": "Hamburg"}, {"osm_type": "harbour"}) is True
        assert harbour_evidence({"name": "Hamburg"}, {"fcode": "HBR"}) is True
        assert harbour_evidence({"name": "Hamburg", "listing_role": "poe"}) is True
        assert harbour_evidence({
            "name": "Hamburg", "extraction_engine": "catalog", "lat": 53.5,
        }) is True

    def test_inland_flags_use_zone_iso_not_sovereign(self):
        flags = inland_exception_flags(
            {"name": "Bordeaux"},
            {"iso2": "MQ", "sov_iso2": "FR"},
            {"osm_type": "harbour"},
        )
        # iso2 de la zone (Martinique) : le géocodeur est déjà borné à MQ
        assert flags["country_ok"] is True
        assert flags["harbour_like"] is True
        empty = inland_exception_flags({"name": "Paris"}, {"iso2": ""})
        assert empty["country_ok"] is False
        assert empty["harbour_like"] is False


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

    def test_inland_river_scores_below_coastal(self):
        base = {
            "name": "Hamburg",
            "extraction_engine": "catalog",
            "validated": True,
            "lat": 53.54, "lon": 9.99,
            "source_urls": ["https://zoll.de/x"],
        }
        river = score_port({**base, "spatial_kind": "inland_river"},
                           official_source=True)
        coast = score_port({**base, "spatial_kind": "coastal_land"},
                           official_source=True)
        assert river["parts"]["map"] == 14
        assert coast["parts"]["map"] == 16
        assert river["confidence"] < coast["confidence"]


class TestMonitoringOnlyOnRefresh:
    def test_skip_requires_refresh_flag_in_signature(self):
        import inspect
        sig = inspect.signature(poe.generate_zone_poe)
        assert "refresh" in sig.parameters
        assert sig.parameters["refresh"].default is False
