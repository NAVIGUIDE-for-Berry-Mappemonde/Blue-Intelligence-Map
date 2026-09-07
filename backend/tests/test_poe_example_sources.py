"""Sources officielles attendues (FR hexagone, MX, VE, NU, NZ, NC).

Les URL sont des *cibles de découverte*, pas l'affichage fiche.
Les graines sont indexées par iso2 du polygone (Mayotte ≠ FR, Niue ≠ NZ).
"""
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
}

PINNED_NEEDLES = {
    5677: ["vous-naviguez-en-provenance"],
    8429: ["puertos-y-terminales"],
    8433: ["inea.gob.ve", "inventario-de-puertos"],
    8447: ["niue_laws_vol4_part1"],
    8455: ["places-of-first-arrival-seaports", "sailing-to-new-zealand-this-small-craft-season"],
    8312: ["formalites-douanieres-pour-les-navires-de-plaisance"],
}

FOREIGN_NEEDLES = {
    5677: ["mpi.govt.nz", "inea.gob.ve", "gouv.nc"],
    8429: ["vous-naviguez", "mpi.govt.nz"],
    8433: ["vous-naviguez", "mpi.govt.nz"],
    8447: ["mpi.govt.nz", "customs.govt.nz", "vous-naviguez"],
    8455: ["niue_laws", "vous-naviguez", "gouv.nc"],
    8312: ["vous-naviguez-en-provenance", "mpi.govt.nz"],
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


def test_example_hints_stay_on_the_polygon():
    nz = " ".join(poe.search_hint_queries(EXAMPLE_ZONES[8455]))
    nu = " ".join(poe.search_hint_queries(EXAMPLE_ZONES[8447]))
    nc = " ".join(poe.search_hint_queries(EXAMPLE_ZONES[8312]))
    fr = " ".join(poe.search_hint_queries(EXAMPLE_ZONES[5677]))
    ve = " ".join(poe.search_hint_queries(EXAMPLE_ZONES[8433]))
    assert "places of first arrival" in nz and "Niue" not in nz
    assert "Customs Act" in nu and "places of first arrival" not in nu
    assert "plaisance" in nc and "PPF" not in nc
    assert "PPF" in fr and "Mayotte" not in fr and "Calédonie" not in fr
    assert "INEA" in ve
