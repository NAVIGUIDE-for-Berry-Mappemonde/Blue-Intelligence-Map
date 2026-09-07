"""Sources officielles attendues (FR hexagone, MX, VE, NU, NZ, NC).

Les URL sont des *cibles de découverte*, pas l'affichage fiche.
Les graines sont indexées par iso2 du polygone (Mayotte ≠ FR, Niue ≠ NZ).
"""
import asyncio

from app.core.extract import official_attachments, should_follow_attachments
from app.services import poe_pipeline as poe

EXAMPLE_ZONES = {
    5677: {
        "iso2": "FR", "sov_iso2": "FR", "name": "France", "sovereign": "France",
        "pol_type": "200NM", "mrgid": 5677,
    },
    8429: {
        "iso2": "MX", "sov_iso2": "MX", "name": "Mexico", "sovereign": "Mexico",
        "pol_type": "200NM", "mrgid": 8429,
    },
    8433: {
        "iso2": "VE", "sov_iso2": "VE", "name": "Venezuela", "sovereign": "Venezuela",
        "pol_type": "200NM", "mrgid": 8433,
    },
    8447: {
        "iso2": "NU", "sov_iso2": "NZ", "name": "Niue", "sovereign": "New Zealand",
        "pol_type": "200NM", "mrgid": 8447,
    },
    8455: {
        "iso2": "NZ", "sov_iso2": "NZ", "name": "New Zealand", "sovereign": "New Zealand",
        "pol_type": "200NM", "mrgid": 8455,
    },
    8312: {
        "iso2": "NC", "sov_iso2": "FR", "name": "New Caledonia", "sovereign": "France",
        "pol_type": "200NM", "mrgid": 8312,
    },
    21803: {
        "iso2": "SX", "sov_iso2": "NL", "name": "Sint-Maarten", "sovereign": "Netherlands",
        "pol_type": "200NM", "mrgid": 21803,
    },
}

PINNED_NEEDLES = {
    5677: ["vous-naviguez-en-provenance"],
    8429: ["puertos-y-terminales"],
    8433: ["Ley-de-Marinas-y-Actividades-Conexas.pdf",
           "CAPITANIAS-DE-PUERTO"],
    8447: ["niue_laws_vol4_part1"],
    8455: ["places-of-first-arrival-seaports", "sailing-to-new-zealand-this-small-craft-season"],
    8312: ["formalites-douanieres-pour-les-navires-de-plaisance"],
    21803: ["sintmaartengov.org", "Pages/Customs.aspx"],
}

FOREIGN_NEEDLES = {
    5677: ["mpi.govt.nz", "inea.gob.ve", "gouv.nc", "sintmaartengov"],
    8429: ["vous-naviguez", "mpi.govt.nz", "sintmaartengov"],
    8433: ["vous-naviguez", "mpi.govt.nz", "sintmaartengov"],
    8447: ["mpi.govt.nz", "customs.govt.nz", "vous-naviguez"],
    8455: ["niue_laws", "vous-naviguez", "gouv.nc", "sintmaartengov"],
    8312: ["vous-naviguez-en-provenance", "mpi.govt.nz", "sintmaartengov"],
    21803: ["vous-naviguez", "mpi.govt.nz", "inea.gob.ve", "gouv.nc"],
}


def _pinned(zone):
    return poe.seed_url_candidates(zone) + poe.landing_url_candidates(zone)


def test_example_zones_pin_expected_pages_only():
    for mrgid, zone in EXAMPLE_ZONES.items():
        blob = " ".join(c["url"] for c in _pinned(zone))
        for needle in PINNED_NEEDLES[mrgid]:
            assert needle in blob, (mrgid, needle, blob)
        for foreign in FOREIGN_NEEDLES[mrgid]:
            assert foreign not in blob, (mrgid, foreign, blob)


def test_france_hexagon_not_mayotte_and_not_caledonia():
    hexagon = _pinned(EXAMPLE_ZONES[5677])
    mayotte = poe.seed_url_candidates({
        "iso2": "YT", "sov_iso2": "FR", "name": "Mayotte", "mrgid": 48944,
    })
    nc = _pinned(EXAMPLE_ZONES[8312])
    h = " ".join(c["url"] for c in hexagon)
    assert "vous-naviguez" in h
    assert not any("vous-naviguez" in c["url"] for c in mayotte)
    assert not any("vous-naviguez-en-provenance" in c["url"] for c in nc)
    assert any("formalites-douanieres" in c["url"] for c in nc)


def test_france_landing_still_yields_current_list_and_ppf():
    html = """
    <a href="/sites/default/files/2022-07/11/carte-ppf-maritimes.pdf">old</a>
    <a href="https://www.douane.gouv.fr/sites/default/files/uploads/files/carte-PPF-maritimes.pdf">PPF</a>
    <a href="/sites/default/files/2022-07/11/formulaire-immigration.pdf">form</a>
    <a href="/sites/default/files/2026-07/06/Liste-ports-de-plaisance-eligibles.pdf">liste</a>
    """
    base = ("https://www.douane.gouv.fr/particuliers/vous-naviguez/"
            "vous-naviguez-en-provenance-ou-destination-dun-pays-non-membre-de")
    atts = official_attachments(html, base)
    blob = " ".join(atts)
    assert "Liste-ports-de-plaisance-eligibles.pdf" in blob
    assert "uploads/files/carte-PPF-maritimes.pdf" in blob
    assert should_follow_attachments(html, base)


def test_venezuela_inea_attachments_keep_ley_and_reglamento():
    html = """
    <a href="/wp-content/uploads/2026/04/Ley-de-Marinas-y-Actividades-Conexas.pdf">ley</a>
    <a href="/wp-content/uploads/2026/04/REGLAMENTO-QUE-DETERMINA-LA-JURISDICCION-DE-LAS-CAPITANIAS-DE-PUERTO-DE-LA-REPUBLICA.pdf">reg</a>
    <a href="/wp-content/uploads/2024/01/logo-inea.pdf">logo</a>
    """
    base = "https://inea.gob.ve/"
    atts = official_attachments(html, base)
    blob = " ".join(atts)
    assert "Ley-de-Marinas-y-Actividades-Conexas.pdf" in blob
    assert "CAPITANIAS-DE-PUERTO" in blob
    assert should_follow_attachments(html, base)


def test_example_hints_stay_on_the_polygon():
    nz = " ".join(poe.search_hint_queries(EXAMPLE_ZONES[8455]))
    nu = " ".join(poe.search_hint_queries(EXAMPLE_ZONES[8447]))
    nc = " ".join(poe.search_hint_queries(EXAMPLE_ZONES[8312]))
    fr = " ".join(poe.search_hint_queries(EXAMPLE_ZONES[5677]))
    ve = " ".join(poe.search_hint_queries(EXAMPLE_ZONES[8433]))
    sx = " ".join(poe.search_hint_queries(EXAMPLE_ZONES[21803]))
    assert "places of first arrival" in nz and "Niue" not in nz
    assert "Customs Act" in nu and "places of first arrival" not in nu
    assert "plaisance" in nc and "PPF" not in nc
    assert "PPF" in fr and "Mayotte" not in fr and "Calédonie" not in fr
    assert "Ley de Marinas" in ve and "capitanías" in ve
    assert "Sint Maarten customs" in sx
    assert "havens van binnenkomst" not in sx
    assert poe.zone_search_lang(EXAMPLE_ZONES[21803]) is None
    assert "sintmaartengov.org" in poe.build_whitelist("SX", "NL")
    assert "government.nl" not in poe.build_whitelist("SX", "NL")
    qsx = poe.localized_query(EXAMPLE_ZONES[21803]) or ""
    assert "customs department" in qsx and "binnenkomst" not in qsx


def test_collect_follows_list_pdfs_hidden_in_html(monkeypatch):
    landing = (
        "https://www.douane.gouv.fr/particuliers/vous-naviguez/"
        "vous-naviguez-en-provenance-ou-destination-dun-pays-non-membre-de"
    )
    liste = ("https://www.douane.gouv.fr/sites/default/files/2026-07/06/"
             "Liste-ports-de-plaisance-eligibles.pdf")
    carte = ("https://www.douane.gouv.fr/sites/default/files/uploads/files/"
             "carte-PPF-maritimes.pdf")
    html = (
        f'<a href="{carte}">PPF</a>'
        f'<a href="{liste}">liste</a>'
    )
    prose = "Formalités pour les plaisanciers en provenance d'un pays tiers. " * 40

    async def fake_cascade(url, min_chars=200, log=None):
        if "carte-PPF" in url:
            return {"text": "Points de passage frontaliers maritimes",
                    "html": "", "md5": "c", "level": "N1-pymupdf", "blocked": False}
        if url.endswith(".pdf"):
            return {"text": "1.- Port Alpha latitude: 46.1 longitude: -1.1\n" * 8,
                    "html": "", "md5": "p", "level": "N1", "blocked": False}
        return {"text": prose, "html": html, "md5": "h", "level": "N1", "blocked": False}

    monkeypatch.setattr(poe, "extract_cascade", fake_cascade)
    _texts, _h, used, _ex = asyncio.run(poe._collect_texts(
        [{"url": landing, "domain": "douane.gouv.fr"}], lambda m: None))
    blob = " ".join(c["url"] for c in used)
    assert liste in blob
    assert carte in blob


def test_attachments_beat_remaining_serp_queue(monkeypatch):
    landing = (
        "https://www.douane.gouv.fr/particuliers/vous-naviguez/"
        "vous-naviguez-en-provenance-ou-destination-dun-pays-non-membre-de"
    )
    liste = ("https://www.douane.gouv.fr/sites/default/files/2026-07/06/"
             "Liste-ports-de-plaisance-eligibles.pdf")
    carte = ("https://www.douane.gouv.fr/sites/default/files/uploads/files/"
             "carte-PPF-maritimes.pdf")
    html = f'<a href="{carte}">PPF</a><a href="{liste}">liste</a>'
    junk = [
        "https://www.douane.gouv.fr/french-customs-information-available-english",
        "https://www.douane.gouv.fr/sites/default/files/2018-11/10-questions-before-exporting-en.pdf",
        "https://www.service-public.fr/particuliers/vosdroits/F1234",
    ]

    async def fake_cascade(url, min_chars=200, log=None):
        if url in (liste, carte):
            return {"text": "1.- Port Alpha latitude: 46.1 longitude: -1.1\n" * 8,
                    "html": "", "md5": "p", "level": "N1", "blocked": False}
        if url == landing:
            return {"text": "Formalités plaisance. " * 40, "html": html,
                    "md5": "h", "level": "N1", "blocked": False}
        return {"text": "page d'accueil douanes " * 40, "html": "",
                "md5": "j", "level": "N1", "blocked": False}

    monkeypatch.setattr(poe, "extract_cascade", fake_cascade)
    official = ([{"url": landing, "domain": "douane.gouv.fr"}]
                + [{"url": u, "domain": "douane.gouv.fr"} for u in junk])
    _t, _h, used, _e = asyncio.run(poe._collect_texts(official, lambda m: None, max_fetch=5))
    blob = " ".join(c["url"] for c in used)
    assert liste in blob
    assert carte in blob
