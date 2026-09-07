"""Audit GPS confirmed — Tanjung Pinang, St-Nazaire, Sidney ; pas de merge BBT."""
from __future__ import annotations

from shapely.geometry import box
from shapely.ops import unary_union

from app.services.poe_confirmed_gps_audit import (
    BINTAN_CLUSTER,
    REASON_GROUP_OUTLIER,
    REASON_HOMONYM_PAREN,
    REASON_INLAND_FAR,
    REASON_NOMINATIM_INLAND,
    TANJUNG_PINANG_KEY,
    audit_confirmed_seeds,
    persist_gps_audit,
)


def _bintan_geom():
    bintan = box(104.2, 0.9, 104.7, 1.4)
    anambas = box(105.8, 2.8, 106.6, 3.5)
    return {8492: unary_union([bintan, anambas])}


def _mexico_geom():
    return {8429: box(-117.2, 31.2, -116.2, 32.2)}


def _canada_geom():
    return {8493: box(-125.0, 48.0, -122.0, 49.5)}


def _france_atlantic_geom():
    atlantic = box(-5.5, 43.0, 0.5, 51.2)
    med = box(3.0, 42.0, 7.6, 43.45)
    return {5677: unary_union([atlantic, med])}


def _usa_geom():
    # ZEE USA : les deux côtes (Astoria OR in_eez, Astoria NY aussi).
    west = box(-125.5, 32.0, -116.5, 49.0)
    east = box(-80.0, 32.0, -70.0, 45.0)
    return {8456: unary_union([west, east])}


class _FakeCol:
    def __init__(self, docs: list[dict]):
        self.docs = {d["_id"]: dict(d) for d in docs}
        self.inserted: list[dict] = []

    def find_one(self, q, proj=None):
        if not q:
            return next(iter(self.docs.values()), None)
        if "$or" in q:
            for clause in q["$or"]:
                hit = self.find_one(clause)
                if hit is not None:
                    return hit
            return None
        if "_id" in q:
            return self.docs.get(q["_id"])
        if "dedup_key" in q:
            for d in self.docs.values():
                if d.get("dedup_key") == q["dedup_key"] or d["_id"] == q["dedup_key"]:
                    return d
        return None

    def update_one(self, q, upd, upsert=False):
        doc = self.find_one(q)
        if doc is None:
            return
        if "$set" in upd:
            doc.update(upd["$set"])
        if "$unset" in upd:
            for k in upd["$unset"]:
                doc.pop(k, None)

    def insert_one(self, doc):
        self.inserted.append(dict(doc))

    def count_documents(self, q=None):
        q = q or {}
        if not q:
            return len(self.docs)
        n = 0
        for d in self.docs.values():
            ok = True
            for k, v in q.items():
                if d.get(k) != v:
                    ok = False
                    break
            if ok:
                n += 1
        return n

    def find(self, q=None):
        q = q or {}
        out = []
        for d in self.docs.values():
            ok = True
            for k, v in q.items():
                if d.get(k) != v:
                    ok = False
                    break
            if ok:
                out.append(d)
        return out


class _DB:
    def __init__(self, seeds, ports, n_ports=None):
        self.poe_seed_ports = _FakeCol(seeds)
        self.poe_ports = _FakeCol(ports)
        if n_ports is not None:
            # padding count only — unused ids
            while len(self.poe_ports.docs) < n_ports:
                i = len(self.poe_ports.docs)
                self.poe_ports.docs[f"pad:{i}"] = {"_id": f"pad:{i}"}
        self.poe_audit_log = _FakeCol([])


def _tanjung_seeds():
    return [
        {
            "_id": TANJUNG_PINANG_KEY,
            "dedup_key": TANJUNG_PINANG_KEY,
            "name": "Tanjung Pinang (Bintan Island, Riau Islands)",
            "mrgid": 8492, "zone_name": "Indonesia", "country_iso2": "ID",
            "lat": -3.3564491, "lon": 104.6572233, "has_coords": True,
            "verify_verdict": "confirmed", "listing_role": "poe",
            "seed_sources": ["listing"], "geocode_source": "nominatim",
            "observations": [{"origin": "listing",
                              "name": "Tanjung Pinang (Bintan Island, Riau Islands)"}],
        },
        {
            "_id": "8492:bandarbintantelani",
            "dedup_key": "8492:bandarbintantelani",
            "name": "Bandar Bintan Telani",
            "listing_name": "Bandar Bintan Telani (BBT) – Bintan Island",
            "mrgid": 8492, "lat": 1.1605006, "lon": 104.3201677,
            "verify_verdict": "confirmed", "seed_sources": ["v1", "listing"],
        },
        {
            "_id": "8492:tarempasiantananambasislands",
            "dedup_key": "8492:tarempasiantananambasislands",
            "name": "Tarempa, Siantan (Anambas Islands)",
            "mrgid": 8492, "lat": 3.2161386, "lon": 106.2193643,
            "verify_verdict": "confirmed", "seed_sources": ["listing"],
        },
    ]


def _bintan_listing():
    return [{
        "dedup_key": TANJUNG_PINANG_KEY,
        "name": "Tanjung Pinang (Bintan Island, Riau Islands)",
        "mrgid": 8492,
        "group": "Western Indonesia - Bintan, Lingga, Riau and Anambas Islands",
    }, {
        "dedup_key": "8492:bandarbintantelani",
        "name": "Bandar Bintan Telani",
        "mrgid": 8492,
        "group": "Western Indonesia - Bintan, Lingga, Riau and Anambas Islands",
    }, {
        "dedup_key": "8492:tarempasiantananambasislands",
        "name": "Tarempa, Siantan (Anambas Islands)",
        "mrgid": 8492,
        "group": "Western Indonesia - Bintan, Lingga, Riau and Anambas Islands",
    }]


def test_tanjung_pinang_flags_and_suggests_bintan_not_bbt():
    rep = audit_confirmed_seeds(
        _tanjung_seeds(), geoms=_bintan_geom(), listing_ports=_bintan_listing())
    by = {s["key"]: s for s in rep["flags"]}
    pinang = by[TANJUNG_PINANG_KEY]
    assert pinang["severity"] == "high"
    assert REASON_HOMONYM_PAREN in pinang["reasons"] or REASON_GROUP_OUTLIER in pinang["reasons"]
    assert REASON_INLAND_FAR in pinang["reasons"] or REASON_NOMINATIM_INLAND in pinang["reasons"]
    assert pinang["suggested_lat"] is not None
    assert 1.0 <= pinang["suggested_lat"] <= 1.2
    # Pas le GPS de Bandar Bintan Telani.
    assert abs(pinang["suggested_lat"] - 1.1605006) > 0.01
    assert abs(pinang["suggested_lon"] - 104.3201677) > 0.01
    assert pinang["will_correct"] is True
    assert "8492:bandarbintantelani" not in by
    assert "8492:tarempasiantananambasislands" not in by


def test_tanjung_pinang_persist_corrects_lat_positive_no_merge():
    seeds = _tanjung_seeds()
    geoms = _bintan_geom()
    listing = _bintan_listing()
    rep = audit_confirmed_seeds(seeds, geoms=geoms, listing_ports=listing)
    db = _DB(seeds, [], n_ports=1280)
    out = persist_gps_audit(db, rep, geoms=geoms, seeds=seeds)
    assert out["n_confirmed"] == 3
    assert out["poe_ports"] == 1280
    pinang = db.poe_seed_ports.docs[TANJUNG_PINANG_KEY]
    assert pinang["lat"] > 0
    assert 1.0 <= pinang["lat"] <= 1.2
    assert pinang["geocode_source"] == "manual_audit"
    assert pinang["gps_audit_status"] == "corrected"
    assert pinang["verify_verdict"] == "confirmed"
    assert pinang["spatial_class"] in ("in_eez", "coastal_land")
    bbt = db.poe_seed_ports.docs["8492:bandarbintantelani"]
    assert bbt["lat"] == 1.1605006
    assert bbt["lon"] == 104.3201677
    assert bbt["gps_audit_status"] == "ok"
    assert db.poe_audit_log.inserted
    assert db.poe_audit_log.inserted[0]["action"] == "gps_audit_correct"
    assert abs(pinang["lat"] - BINTAN_CLUSTER[0]) < 1e-6
    # Relance : le GPS corrigé n'est plus flaggé, le statut corrected reste.
    seeds2 = list(db.poe_seed_ports.docs.values())
    rep2 = audit_confirmed_seeds(seeds2, geoms=geoms, listing_ports=listing)
    assert TANJUNG_PINANG_KEY not in {s["key"] for s in rep2["flags"]}
    persist_gps_audit(db, rep2, geoms=geoms, seeds=seeds2)
    pinang2 = db.poe_seed_ports.docs[TANJUNG_PINANG_KEY]
    assert pinang2["gps_audit_status"] == "corrected"
    assert pinang2["lat"] > 0


def test_parnu_prefers_same_name_in_eez_over_port_of_variant():
    seeds = [{
        "_id": "5675:parnu2parnuport", "dedup_key": "5675:parnu2parnuport",
        "name": "Pärnu 2 (Pärnu Port)", "listing_name": "Parnu",
        "mrgid": 5675, "country_iso2": "EE",
        "lat": 57.771889, "lon": 26.0296356,
        "verify_verdict": "confirmed", "listing_role": "poe",
        "seed_sources": ["v1", "listing"],
        "observations": [
            {"origin": "v1", "name": "Pärnu 2 (Pärnu Port)",
             "lat": 57.771889, "lon": 26.0296356},
            {"origin": "run:a", "name": "Pärnu", "lat": 58.3775193, "lon": 24.5007085},
            {"origin": "run:b", "name": "Port of Pärnu", "lat": 58.1412071, "lon": 24.0213604},
        ],
    }]
    # Côte ouest estonienne (les deux obs y sont) ; le GPS v1 est inland est.
    geoms = {5675: box(23.5, 57.9, 24.8, 58.6)}
    rep = audit_confirmed_seeds(seeds, geoms=geoms, listing_ports=[])
    assert rep["n_flagged"] == 1
    s = rep["flags"][0]
    assert s["will_correct"] is True
    assert abs(s["suggested_lat"] - 58.3775193) < 1e-6


def test_ensenada_corrects_from_same_name_in_eez_observation():
    seeds = [{
        "_id": "8429:ensenada", "dedup_key": "8429:ensenada",
        "name": "Ensenada", "mrgid": 8429, "country_iso2": "MX",
        "lat": 24.058876, "lon": -106.6994959,
        "verify_verdict": "confirmed",
        "seed_sources": ["v1", "listing"],
        "listing_role": "poe",
        "observations": [
            {"origin": "v1", "name": "Ensenada", "lat": 24.058876, "lon": -106.6994959},
            {"origin": "run:good", "name": "Ensenada", "lat": 31.8522146, "lon": -116.625788},
        ],
    }]
    geoms = _mexico_geom()
    rep = audit_confirmed_seeds(seeds, geoms=geoms, listing_ports=[])
    assert rep["n_flagged"] == 1
    s = rep["flags"][0]
    assert s["will_correct"] is True
    assert abs(s["suggested_lat"] - 31.8522146) < 1e-6
    assert s["suggested_source"] == "observation"
    db = _DB(seeds, [{
        "_id": "port-ensenada", "dedup_key": "8429:ensenada",
        "name": "Ensenada", "lat": 24.058876, "lon": -106.6994959,
    }], n_ports=1280)
    out = persist_gps_audit(db, rep, geoms=geoms, seeds=seeds)
    assert out["poe_ports"] == 1280
    assert out["poe_ports_patched"] == 1
    seed = db.poe_seed_ports.docs["8429:ensenada"]
    assert abs(seed["lat"] - 31.8522146) < 1e-6
    assert seed["geocode_source"] == "observation"
    assert seed["verify_verdict"] == "confirmed"
    port = db.poe_ports.docs["port-ensenada"]
    assert abs(port["lat"] - 31.8522146) < 1e-6


def test_sidney_bc_not_flagged_for_sydney_ns_observation():
    seeds = [{
        "_id": "8493:portofsidney", "dedup_key": "8493:portofsidney",
        "name": "Port of Sidney", "mrgid": 8493, "country_iso2": "CA",
        "lat": 48.6505788, "lon": -123.398324,
        "verify_verdict": "confirmed",
        "seed_sources": ["v1", "osm", "listing"],
        "observations": [
            {"origin": "v1", "lat": 48.6505788, "lon": -123.398324, "name": "Port of Sidney"},
            {"origin": "osm", "lat": 48.65269, "lon": -123.39382, "name": "Port Sidney Marina"},
            {"origin": "run:sydney-ns", "name": "Sydney", "lat": 46.1382112, "lon": -60.1941912},
        ],
    }]
    rep = audit_confirmed_seeds(seeds, geoms=_canada_geom(), listing_ports=[])
    assert rep["n_flagged"] == 0
    assert rep["n_confirmed"] == 1


def test_coastal_in_eez_not_flagged():
    seeds = [{
        "_id": "5677:nice", "dedup_key": "5677:nice",
        "name": "Nice", "mrgid": 5677, "country_iso2": "FR",
        "lat": 43.70, "lon": 7.27,
        "verify_verdict": "confirmed",
        "seed_sources": ["v1", "listing"],
        "listing_role": "poe",
    }]
    geoms = {5677: box(7.20, 43.62, 7.35, 43.75)}
    rep = audit_confirmed_seeds(seeds, geoms=geoms, listing_ports=[])
    assert rep["n_flagged"] == 0


def test_st_nazaire_gard_flagged_not_corrected():
    seeds = [
        {
            "_id": "5677:stnazaire", "dedup_key": "5677:stnazaire",
            "name": "St Nazaire", "mrgid": 5677, "country_iso2": "FR",
            "lat": 44.1986, "lon": 4.62529,
            "verify_verdict": "confirmed", "listing_role": "poe",
            "seed_sources": ["listing"], "geocode_source": "nominatim",
            "observations": [{"origin": "listing", "name": "St Nazaire"}],
        },
        {
            "_id": "5677:brest", "dedup_key": "5677:brest",
            "name": "Brest", "mrgid": 5677,
            "lat": 48.3905, "lon": -4.4860,
            "verify_verdict": "confirmed", "seed_sources": ["listing"],
        },
        {
            "_id": "5677:larochelle", "dedup_key": "5677:larochelle",
            "name": "La Rochelle", "mrgid": 5677,
            "lat": 46.1591, "lon": -1.1520,
            "verify_verdict": "confirmed", "seed_sources": ["listing"],
        },
    ]
    listing = [
        {"dedup_key": k, "name": n, "mrgid": 5677, "group": "Atlantic (France)"}
        for k, n in (
            ("5677:stnazaire", "St Nazaire"),
            ("5677:brest", "Brest"),
            ("5677:larochelle", "La Rochelle"),
        )
    ]
    geoms = _france_atlantic_geom()
    rep = audit_confirmed_seeds(seeds, geoms=geoms, listing_ports=listing)
    by = {s["key"]: s for s in rep["flags"]}
    assert "5677:stnazaire" in by
    st = by["5677:stnazaire"]
    assert st["will_correct"] is False
    assert REASON_INLAND_FAR in st["reasons"] or REASON_GROUP_OUTLIER in st["reasons"]
    assert REASON_NOMINATIM_INLAND in st["reasons"] or REASON_GROUP_OUTLIER in st["reasons"]
    assert "5677:brest" not in by
    db = _DB(seeds, [], n_ports=1280)
    out = persist_gps_audit(db, rep, geoms=geoms, seeds=seeds)
    st_doc = db.poe_seed_ports.docs["5677:stnazaire"]
    assert st_doc["lat"] == 44.1986
    assert st_doc["gps_audit_status"] == "flagged"
    assert st_doc["verify_verdict"] == "confirmed"
    assert out["corrected"] == 0


def test_astoria_west_coast_group_flagged_not_corrected():
    seeds = [
        {
            "_id": "8456:astoria", "dedup_key": "8456:astoria",
            "name": "Astoria", "mrgid": 8456, "lat": 40.7720145, "lon": -73.9302673,
            "verify_verdict": "confirmed", "seed_sources": ["listing"],
            "geocode_source": "nominatim", "listing_role": "poe",
        },
        {
            "_id": "8456:coosbay", "dedup_key": "8456:coosbay",
            "name": "Coos Bay", "mrgid": 8456, "lat": 43.3678937, "lon": -124.2174647,
            "verify_verdict": "confirmed", "seed_sources": ["listing"],
        },
        {
            "_id": "8456:sandiego", "dedup_key": "8456:sandiego",
            "name": "San Diego", "mrgid": 8456, "lat": 32.7174202, "lon": -117.162772,
            "verify_verdict": "confirmed", "seed_sources": ["listing"],
        },
    ]
    listing = [
        {"dedup_key": k, "name": n, "mrgid": 8456, "group": "West Coast (USA)"}
        for k, n in (
            ("8456:astoria", "Astoria"),
            ("8456:coosbay", "Coos Bay"),
            ("8456:sandiego", "San Diego"),
        )
    ]
    rep = audit_confirmed_seeds(seeds, geoms=_usa_geom(), listing_ports=listing)
    by = {s["key"]: s for s in rep["flags"]}
    assert "8456:astoria" in by
    assert REASON_GROUP_OUTLIER in by["8456:astoria"]["reasons"]
    assert by["8456:astoria"]["will_correct"] is False
    assert "8456:coosbay" not in by


def test_skips_non_confirmed():
    seeds = [{
        "_id": "1:x", "dedup_key": "1:x", "name": "X", "mrgid": 1,
        "lat": 0, "lon": 0, "verify_verdict": "probable",
    }]
    rep = audit_confirmed_seeds(seeds, geoms={1: box(-1, -1, 1, 1)}, listing_ports=[])
    assert rep["n_confirmed"] == 0
    assert rep["n_flagged"] == 0


def test_persist_does_not_change_ports_count_without_matching_gps():
    seeds = _tanjung_seeds()
    geoms = _bintan_geom()
    listing = _bintan_listing()
    rep = audit_confirmed_seeds(seeds, geoms=geoms, listing_ports=listing)
    db = _DB(seeds, [{
        "_id": "other", "dedup_key": "8456:other",
        "lat": 1.0, "lon": 2.0,
    }], n_ports=1280)
    out = persist_gps_audit(db, rep, geoms=geoms, seeds=seeds)
    assert out["poe_ports"] == 1280
    assert out["poe_ports_patched"] == 0
