"""
Tests reconstruction v2 — hygiène (filtre interstitiels, détection de blocage),
parallèle-comparaison (double parsing, double géocodage, LLM∥NER), journal
d'événements, diff port par port et rapport de run.

Aucun serveur ni réseau requis. Les tests Mongo utilisent une base dédiée
(bi_test_poe_v2), détruite à la fin.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import geo  # noqa: E402
from app.core.events import RunRecorder, RUNS_DIR  # noqa: E402
from app.core.extract import dual_parse_html, looks_blocked, serp_filter  # noqa: E402
from app.services import poe_pipeline as poe  # noqa: E402
from app.services.poe_diff import diff_ports  # noqa: E402
from app.services.poe_report import report_to_markdown  # noqa: E402


# --- Hygiène : filtre SERP anti-interstitiels --------------------------------
class TestSerpFilterInterstitials:
    def test_unblock_and_challenge_urls_rejected(self):
        results = [
            {"url": "https://unblock.federalregister.gov/"},
            {"url": "https://example.gov/cdn-cgi/challenge-platform/x"},
            {"url": "https://geo.captcha-delivery.com/captcha/?initialCid=x"},
            {"url": "https://www.douane.gouv.fr/demarche/ports-entree"},
        ]
        kept = [r["url"] for r in serp_filter(results)]
        assert kept == ["https://www.douane.gouv.fr/demarche/ports-entree"]

    def test_regressions_still_filtered(self):
        results = [
            {"url": "https://www.tripadvisor.com/Attractions-g147-Fiji.html"},
            {"url": "https://customs.gov.fj/ports-of-entry"},
        ]
        kept = [r["url"] for r in serp_filter(results)]
        assert kept == ["https://customs.gov.fj/ports-of-entry"]

    def test_dictionary_and_tcp_port_sites_rejected(self):
        results = [
            {"url": "https://twominenglish.com/official-meaning/"},
            {"url": "https://www.askdifference.com/official-vs-unofficial/"},
            {"url": "https://www.vocabulary.com/dictionary/official"},
            {"url": "https://www.guiahardware.es/puertos-de-red-mas-conocidos/"},
            {"url": "https://www.stationx.net/common-ports-cheat-sheet/"},
            {"url": "https://www.douane.gouv.fr/demarche/ports-entree"},
        ]
        kept = [r["url"] for r in serp_filter(results)]
        assert kept == ["https://www.douane.gouv.fr/demarche/ports-entree"]


# --- Hygiène : détection des pages de blocage --------------------------------
class TestLooksBlocked:
    def test_cloudflare_challenge_detected(self):
        text = "Just a moment... Enable JavaScript and cookies to continue"
        assert looks_blocked(text, html="<html>cf-browser-verification</html>",
                             title="Just a moment...") is True

    def test_unblock_interstitial_detected(self):
        text = ("Request unsuccessful. Please complete the security check. "
                "Automated access to this site is forbidden.")
        assert looks_blocked(text) is True

    def test_legit_long_customs_page_not_blocked(self):
        text = ("The designated ports of entry for foreign pleasure craft are "
                "Papeete, Uturoa and Taiohae. " * 60)  # > 1500 chars, aucun marqueur
        assert looks_blocked(text) is False

    def test_long_text_with_marker_not_blocked(self):
        # Un vrai contenu réglementaire long qui cite « access denied » reste accepté
        text = ("Access to this page has been denied in the past for vessels without "
                "clearance. The full regulation follows. " * 40)
        assert looks_blocked(text) is False


# --- Parallèle : double parsing comparé --------------------------------------
class TestDualParse:
    def test_dual_parse_returns_comparison_signals(self):
        html = ("<html><head><title>Ports</title></head><body><article>"
                + "<p>The official ports of entry are Alpha Harbour and Beta Marina. "
                  "Foreign yachts must clear customs on arrival.</p>" * 12
                + "</article></body></html>")
        res = asyncio.run(dual_parse_html(html))
        assert res["text"]
        assert res["level"] in ("N1-trafilatura", "N2-readability")
        assert res["n1_chars"] >= 0 and res["n2_chars"] > 0
        assert 0.0 <= res["similarity"] <= 1.0


# --- Parallèle : géocodage double Nominatim ∥ GeoNames ------------------------
class TestGeocodeDual:
    def _run(self, monkeypatch, nomi_rows, geon_rows):
        async def fake_nomi(query, country_code=None, limit=1):
            return nomi_rows

        async def fake_geon(query, country_code=None, limit=1):
            return geon_rows

        monkeypatch.setattr(geo, "_nominatim_rows", fake_nomi)
        monkeypatch.setattr(geo, "_geonames_rows", fake_geon)
        monkeypatch.setenv("GEONAMES_USERNAME", "test")
        monkeypatch.setattr(geo, "_geonames_disabled_reason", None)
        port = {"name": "Port Alpha", "city": None}
        zone = {"name": "Testland", "iso2": "TL", "sovereign": "Testland"}
        return asyncio.run(geo.geocode_port_dual(port, zone))

    def test_agreement_under_2km(self, monkeypatch):
        res = self._run(monkeypatch,
                        [{"lat": "10.0", "lon": "20.0", "display_name": "Port Alpha"}],
                        [{"lat": "10.001", "lng": "20.001", "name": "Port Alpha"}])
        assert res["nominatim"] == [10.0, 20.0]
        assert res["geonames"] == [10.001, 20.001]
        assert res["agree"] is True
        assert res["agreement_km"] < 2.0

    def test_disagreement_flagged(self, monkeypatch):
        res = self._run(monkeypatch,
                        [{"lat": "10.0", "lon": "20.0", "display_name": "Port Alpha"}],
                        [{"lat": "11.0", "lng": "21.0", "name": "Port Alpha"}])
        assert res["agree"] is False
        assert res["agreement_km"] > 100

    def test_single_provider_neutral(self, monkeypatch):
        res = self._run(monkeypatch,
                        [{"lat": "10.0", "lon": "20.0", "display_name": "Port Alpha"}],
                        [])
        assert res["agree"] is None
        assert res["agreement_km"] is None
        assert res["nominatim"] and not res["geonames"]


# --- Parallèle : extraction LLM ∥ NER ------------------------------------------
class FakeRec:
    def __init__(self):
        self.events = []

    async def event(self, step, **payload):
        self.events.append({"step": step, **payload})


class TestExtractionCompare:
    def test_agreement_flags_and_ner_only_candidates(self, monkeypatch):
        async def fake_llm(context, zone, settings=None, log=None):
            return [{"name": "Port Alpha", "city": None, "note": None},
                    {"name": "Zeta Marina", "city": None, "note": None}]

        import app.core.ml as ml
        monkeypatch.setattr(poe, "extract_ports", fake_llm)
        monkeypatch.setattr(ml, "extract_entities",
                            lambda text: [{"text": "Port Alpha", "label": "PORT_NAME"},
                                          {"text": "Beta Quay", "label": "PORT_NAME"}])
        rec = FakeRec()
        ports = asyncio.run(poe.extract_ports_llm("ctx", {"name": "Testland"},
                                                  lambda m: None, rec=rec))
        by_name = {p["name"]: p for p in ports}
        assert by_name["Port Alpha"]["extraction_agreement"] is True
        assert by_name["Zeta Marina"]["extraction_agreement"] is False
        ev = next(e for e in rec.events if e["step"] == "extraction_compare")
        assert ev["ner_only"] == ["Beta Quay"]
        assert ev["both"] == ["Port Alpha"]

    def test_empty_ner_is_neutral_not_disagreement(self, monkeypatch):
        async def fake_llm(context, zone, settings=None, log=None):
            return [{"name": "Port Alpha", "city": None, "note": None}]

        import app.core.ml as ml
        monkeypatch.setattr(poe, "extract_ports", fake_llm)
        monkeypatch.setattr(ml, "extract_entities", lambda text: [])  # NER muet
        ports = asyncio.run(poe.extract_ports_llm("ctx", {"name": "Testland"},
                                                  lambda m: None))
        assert ports[0]["extraction_agreement"] is None

    def test_llm_failure_falls_back_to_ner(self, monkeypatch):
        async def broken_llm(context, zone, settings=None, log=None):
            raise RuntimeError("no key")

        import app.core.ml as ml
        monkeypatch.setattr(poe, "extract_ports", broken_llm)
        monkeypatch.setattr(ml, "extract_entities",
                            lambda text: [{"text": "Gamma Wharf", "label": "PORT_NAME"}])
        ports = asyncio.run(poe.extract_ports_llm("ctx", {"name": "Testland"},
                                                  lambda m: None))
        assert len(ports) == 1
        assert ports[0]["name"] == "Gamma Wharf"
        assert ports[0]["extraction_engine"] == "ner"


# --- Journal d'événements (JSONL, sans Mongo) ----------------------------------
class TestRunRecorder:
    def test_jsonl_written_with_sequence(self):
        rec = RunRecorder("testrun-jsonl", db=None)
        path = RUNS_DIR / "testrun-jsonl.jsonl"
        try:
            asyncio.run(rec.event("zone_start", mrgid=1, zone="Z", whitelist=["gov.tl"]))
            asyncio.run(rec.event("fetch", mrgid=1, zone="Z", url="https://x", chars=12))
            lines = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
            assert [l["seq"] for l in lines] == [1, 2]
            assert lines[0]["step"] == "zone_start"
            assert lines[0]["payload"]["whitelist"] == ["gov.tl"]
        finally:
            path.unlink(missing_ok=True)

    def test_long_payload_clipped(self):
        rec = RunRecorder("testrun-clip", db=None)
        path = RUNS_DIR / "testrun-clip.jsonl"
        try:
            asyncio.run(rec.event("llm", raw="x" * 10000))
            line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            assert len(line["payload"]["raw"]) < 5000
        finally:
            path.unlink(missing_ok=True)


# --- Diff port par port -----------------------------------------------------------
def _port(mrgid, name, lat=None, lon=None, sources=None, zone="TestZone"):
    from app.core.dedup import normalize_name
    return {"mrgid": mrgid, "zone_name": zone, "name": name, "lat": lat, "lon": lon,
            "source_urls": sources or [], "validated": lat is not None,
            "dedup_key": f"{mrgid}:{normalize_name(name)}"}


class TestDiffPorts:
    def test_categories(self):
        v1 = [
            _port(100, "Port Alpha", 10.0, 20.0, ["https://gov.tl/a"]),
            _port(100, "Port Beta", 10.5, 20.5, ["https://gov.tl/b"]),
            _port(100, "Port Gamma", 11.0, 21.0, ["https://gov.tl/c"]),
            _port(100, "Port Delta", 12.0, 22.0, ["https://gov.tl/d"]),
        ]
        v2 = [
            _port(100, "Port Alpha", 10.0, 20.0, ["https://gov.tl/a"]),      # inchangé
            _port(100, "Beta Port", 10.5, 20.5, ["https://gov.tl/b"]),       # renommé
            _port(100, "Port Gamma", 11.1, 21.0, ["https://douane.tl/c"]),   # déplacé + re-sourcé
            _port(100, "Port Epsilon", 13.0, 23.0, ["https://gov.tl/e"]),    # nouveau
        ]
        d = diff_ports(v1, v2, moved_km=2.0)
        s = d["summary"]
        assert s["matched"] == 3
        assert s["unchanged"] == 1
        assert s["renamed"] == 1
        assert s["moved"] == 1
        assert s["resourced"] == 1
        assert s["added"] == 1 and d["added"][0]["name"] == "Port Epsilon"
        assert s["removed"] == 1 and d["removed"][0]["name"] == "Port Delta"
        gamma = next(m for m in d["matched"] if m["v2"]["name"] == "Port Gamma")
        assert set(gamma["flags"]) == {"moved", "resourced"}
        assert gamma["move_km"] > 2.0

    def test_zones_isolated(self):
        # Deux ports homonymes dans deux zones différentes ne s'apparient pas
        v1 = [_port(100, "Port Alpha", 10.0, 20.0)]
        v2 = [_port(200, "Port Alpha", 10.0, 20.0)]
        d = diff_ports(v1, v2)
        assert d["summary"]["matched"] == 0
        assert d["summary"]["added"] == 1 and d["summary"]["removed"] == 1


# --- Rapport de run (Mongo dédiée) + rendu markdown -------------------------------
@pytest.fixture(scope="module")
def seeded_db():
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _seed():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        tdb = client["bi_test_poe_v2"]
        await client.drop_database("bi_test_poe_v2")
        await tdb.poe_runs.insert_one({
            "_id": "r1", "label": "test", "state": "done",
            "zones_total": 1, "zones_done": 1, "created_at": "2026-08-28T00:00:00Z",
            "started_at": "2026-08-28T00:00:00Z", "finished_at": "2026-08-28T00:10:00Z"})
        await tdb.poe_run_zones.insert_one({
            "run_id": "r1", "mrgid": 100, "name": "TestZone", "status": "ia", "poe_count": 2})
        await tdb.poe_run_ports.insert_many([
            {**_port(100, "Port Alpha", 10.0, 20.0, ["https://gov.tl/a"]), "run_id": "r1",
             "extraction_agreement": True, "geocode_agree": True},
            {**_port(100, "Port Epsilon", 13.0, 23.0, ["https://gov.tl/e"]), "run_id": "r1",
             "extraction_agreement": False, "geocode_agree": None},
        ])
        await tdb.poe_ports.insert_many([
            _port(100, "Port Alpha", 10.0, 20.0, ["https://gov.tl/a"]),
            _port(100, "Port Delta", 12.0, 22.0, ["https://gov.tl/d"]),
        ])
        await tdb.poe_run_events.insert_many([
            {"run_id": "r1", "seq": 1, "step": "search", "mrgid": 100, "zone": "TestZone",
             "payload": {"engine": "searxng", "lang": "en", "n": 5, "results": []}},
            {"run_id": "r1", "seq": 2, "step": "gatekeeper", "mrgid": 100, "zone": "TestZone",
             "payload": {"official": ["gov.tl"], "rejected": ["blog.tl"], "strictly_official": True}},
            {"run_id": "r1", "seq": 3, "step": "fetch", "mrgid": 100, "zone": "TestZone",
             "payload": {"url": "https://gov.tl/a", "level": "N1-trafilatura", "chars": 900,
                         "blocked": False, "render_used": False,
                         "parse": {"n1_chars": 900, "n2_chars": 850, "similarity": 0.9, "agree": True}}},
            {"run_id": "r1", "seq": 4, "step": "extraction_compare", "mrgid": 100, "zone": "TestZone",
             "payload": {"llm_n": 2, "ner_n": 1, "both": ["Port Alpha"],
                         "llm_only": ["Port Epsilon"], "ner_only": []}},
            {"run_id": "r1", "seq": 5, "step": "geocode", "mrgid": 100, "zone": "TestZone",
             "payload": {"port": "Port Alpha", "nominatim": [10.0, 20.0], "geonames": [10.001, 20.001],
                         "agreement_km": 0.15, "agree": True, "chosen": "nominatim",
                         "arbitration": "agree", "geonames_available": True}},
            {"run_id": "r1", "seq": 6, "step": "zone_done", "mrgid": 100, "zone": "TestZone",
             "payload": {"status": "ia", "poe_count": 2, "duration_s": 42.5}},
        ])
        return tdb

    loop = asyncio.new_event_loop()
    tdb = loop.run_until_complete(_seed())
    yield tdb, loop
    loop.run_until_complete(tdb.client.drop_database("bi_test_poe_v2"))
    loop.close()


class TestRunReport:
    def test_report_structure_and_diff(self, seeded_db):
        from app.services.poe_report import build_run_report
        tdb, loop = seeded_db
        rep = loop.run_until_complete(build_run_report(tdb, "r1"))
        assert rep["run"]["run_id"] == "r1"
        assert rep["search"]["by_engine"]["searxng"] == 1
        assert rep["gatekeeper"]["strictly_official"] == 1
        assert rep["fetch"]["by_level"] == {"N1-trafilatura": 1}
        assert rep["extraction"]["confirmed_llm_and_ner"] == 1
        assert rep["geocode"]["agree"] == 1
        assert rep["ports"]["total"] == 2
        assert rep["zones"]["duration_s"]["n"] == 1
        ds = rep["diff"]["summary"]
        assert ds["matched"] == 1 and ds["added"] == 1 and ds["removed"] == 1

    def test_markdown_rendering(self, seeded_db):
        from app.services.poe_report import build_run_report
        tdb, loop = seeded_db
        rep = loop.run_until_complete(build_run_report(tdb, "r1"))
        md = report_to_markdown(rep)
        assert "# Rapport de run PoE" in md
        assert "Comparaison port par port" in md
        assert "Géocodage double" in md


# --- Découverte automatique (catalogue source + seeds, pas une liste figée) --
class TestStructuredDiscovery:
    # Format réel r.jina.ai (gras), pas une table markdown de test.
    _MX_JINA = """
### **Puertos habilitados**
#### [1.-](https://www.gob.mx/puertosymarinamercante/acciones-y-programas/puertos-y-terminales#)Bahía Colonet
**Entidad federativa:**Baja California
**Latitud:**30.96571843
**Longitud:**-116.2804389
#### 4.- Ensenada
**Entidad federativa:**Baja California
**Latitud:**31.8522146
**Longitud:**-116.625788
**Tipo de actividad:**Comercial Pesquera Turística
#### 34.- Manzanillo
**Entidad federativa:**Colima
**Latitud:**19.057546
**Longitud:**-104.313762
**Tipo de actividad:**Comercial Turística
"""
    _MX_TABLE = """
#### 4.- Ensenada
| Entidad federativa: | Baja California |
| Latitud: | 31.8522146 |
| Longitud: | -116.625788 |
"""

    def test_catalog_reads_jina_bold_and_markdown_table(self):
        from app.core.extract import extract_structured_ports, looks_like_port_catalog
        ports = extract_structured_ports(self._MX_JINA)
        by = {p["name"]: p for p in ports}
        assert "Bahía Colonet" in by and "Ensenada" in by and "Manzanillo" in by
        assert abs(by["Ensenada"]["lat"] - 31.8522146) < 1e-6
        assert abs(by["Bahía Colonet"]["lat"] - 30.96571843) < 1e-6
        assert by["Ensenada"]["city"] == "Baja California"
        assert by["Ensenada"]["extraction_engine"] == "catalog"
        table = extract_structured_ports(self._MX_TABLE)
        assert table and abs(table[0]["lat"] - 31.8522146) < 1e-6
        long = self._MX_JINA + "\n".join(
            f"#### {i}.- Puerto{i}\n**Latitud:**1.0\n**Longitud:**1.0"
            for i in range(10, 20))
        assert looks_like_port_catalog(long)

    def test_legal_port_of_phrasing(self):
        from app.core.extract import extract_structured_ports
        text = ("No plant material may be imported into Niue except through "
                "the port of Alofi, the Hanan International Airport, or the Post Office.")
        ports = extract_structured_ports(text)
        names = {p["name"] for p in ports}
        assert "Alofi" in names
        assert not any("Entry" in n or "Hanan" in n for n in names)

    def test_seed_urls_point_to_official_pages_not_names(self):
        mx = poe.seed_url_candidates({"iso2": "MX"})
        nu = poe.seed_url_candidates({"iso2": "NU"})
        blob = " ".join(c["url"] for c in mx + nu)
        assert any("puertos-y-terminales" in c["url"] for c in mx)
        assert any(c["url"].endswith(".pdf") and "gov.nu" in c["url"] for c in nu)
        assert "Ensenada" not in blob and "Alofi" not in blob
        assert poe.search_hint_queries({"iso2": "MX"})
        assert poe.search_hint_queries({"iso2": "NU"})
        assert not any("Alofi" in q for q in poe.search_hint_queries({"iso2": "NU"}))

    def test_challenge_page_is_blocked(self):
        from app.core.extract import looks_blocked, looks_hard_challenge, UA_READER, UA_BROWSER
        assert looks_blocked("Challenge Validation", html="<div class='sec-container'>",
                             title="Challenge Validation") is True
        assert looks_hard_challenge(html="<div class='sec-container'>",
                                    title="Challenge Validation") is True
        assert "Chrome/" not in UA_READER["User-Agent"]
        assert UA_READER["User-Agent"] != UA_BROWSER["User-Agent"]


# --- UNCLOS : îles vides du run ----------------------------------------------
class TestUnclosEmptyIslands:
    def test_uninhabited_run_islands(self):
        for name in (
            "Macquarie Island", "Clipperton Island", "Jarvis Island",
            "Palmyra Atoll", "Howland and Baker Islands", "Juan de Nova Island",
            "Bassas da India",
        ):
            q = poe.qualify_unclos({"poe_count": 0, "pol_type": "200NM",
                                    "anchor": [0, 10], "name": name})
            assert q and q["code"] == "uninhabited", (name, q)

    def test_overlapping_uninhabited_stays_claim(self):
        for name in (
            "Wake Island / Enenkio", "Glorioso Islands", "Ile Tromelin",
            "Abu musa, Greater and Lesser Tunb", "Navassa Island",
        ):
            q = poe.qualify_unclos({"poe_count": 0, "pol_type": "Overlapping claim",
                                    "anchor": [0, 10], "name": name})
            assert q and q["code"] == "overlapping_claim", (name, q)

    def test_abu_musa_uninhabited_when_not_overlapping(self):
        q = poe.qualify_unclos({"poe_count": 0, "pol_type": "200NM",
                                "anchor": [0, 10], "name": "Abu musa, Greater and Lesser Tunb"})
        assert q and q["code"] == "uninhabited", q


# --- NER réentraîné : texte réglementaire, plus seulement « Nom, ville (zone) »
class TestNerRegulatory:
    def test_extracts_ports_from_prose(self):
        from app.core.ml import extract_entities, has_ner_model
        assert has_ner_model()
        samples = {
            "The designated ports of entry for foreign pleasure craft include Ensenada.": "Ensenada",
            "Foreign yachts must clear customs at Alofi in Niue.": "Alofi",
            "Port de Papeete, Tahiti (French Polynesia). Clearance douanière au quai.": "Papeete",
        }
        for text, needle in samples.items():
            ports = [e["text"] for e in extract_entities(text) if e["label"] == "PORT_NAME"]
            assert any(needle in p for p in ports), (text, ports)
