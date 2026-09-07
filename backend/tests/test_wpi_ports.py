"""WPI contre-liste — parse, appariement, jamais une preuve PoE. Hors réseau."""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.geo import destination_point  # noqa: E402
from app.services.poe_confidence import score_port  # noqa: E402
from app.services.poe_seed_enrich import apply_judge_verdict, _judge_prompt  # noqa: E402
from app.services.poe_seeds import (  # noqa: E402
    attach_wpi_commercial, format_seed_line, union_extracted, verdict_for_seed,
)
from app.services.wpi_ports import (  # noqa: E402
    WPI_FILE, WPI_PROXIMITY_KM, ingest_wpi_csv, load_wpi_ports, match_wpi_port,
    parse_wpi_coord, parse_wpi_csv, parse_wpi_row,
)

_CSV = """OID_,World Port Index Number,Main Port Name,Alternate Port Name,UN/LOCODE,Country Code,Harbor Use,Latitude,Longitude,First Port of Entry,Facilities - Container
1,100.0,Rotterdam, ,NLRTM,Netherlands,Cargo,51.90,4.50,Yes,Yes
2,200.0,Fort Bay, , ,Saba,Unknown,17.62,-63.25,Yes,Unknown
3,300.0,Yacht Club Marina, , ,Saba,Unknown,17.80,-63.10,No,No
"""


def _seed(name, lat=None, lon=None, **kw):
    d = {"name": name, "mrgid": 26518, "lat": lat, "lon": lon,
         "has_coords": lat is not None, "seed_sources": kw.pop("sources", ["v1"])}
    d.update(kw)
    return d


def test_parse_csv_and_ignore_first_port_of_entry():
    ports = parse_wpi_csv(io.StringIO(_CSV))
    assert len(ports) == 3
    rot = next(p for p in ports if p["name"] == "Rotterdam")
    assert rot["index"] == "100"
    assert rot["harbor_use"] == "Cargo"
    assert rot["unlocode"] == "NLRTM"
    assert "first_port_of_entry" not in rot
    doc = ingest_wpi_csv(io.StringIO(_CSV))
    assert doc["n"] == 3
    assert "preuve PoE" in doc["note"]
    assert doc["license"].startswith("United States")


def test_parse_decimal_and_dms_coords():
    assert parse_wpi_coord("51.9") == 51.9
    dms = parse_wpi_coord("36°50'00\"N")
    assert dms is not None and abs(dms - 36.833333) < 0.01
    west = parse_wpi_coord("74°15'00\"W")
    assert west is not None and west < 0
    assert parse_wpi_coord("") is None
    rec = parse_wpi_row({
        "name": "X", "lat": 1.5, "lon": 2.5, "index": "9.0",
        "harbor_use": "Cargo",
    })
    assert rec["index"] == "9"
    assert rec["lat"] == 1.5


def test_match_name_and_1km_not_far_marina():
    ports = parse_wpi_csv(io.StringIO(_CSV))
    hit = match_wpi_port(_seed("Fort Bay", 17.62, -63.25), ports)
    assert hit is not None and hit["name"] == "Fort Bay"
    near_lat, near_lon = destination_point(17.62, -63.25, 0, 0.4)
    assert match_wpi_port(_seed("Fort Bay", near_lat, near_lon), ports)
    far_lat, far_lon = destination_point(17.62, -63.25, 0, 3.0)
    assert match_wpi_port(_seed("Fort Bay", far_lat, far_lon), ports) is None
    # Même GPS, autre nom : pas de jeton (marina à côté d'un terminal).
    assert match_wpi_port(_seed("Yacht Basin", 17.62, -63.25), ports) is None
    assert match_wpi_port(_seed("Yacht Club Superba", 17.62, -63.25), ports) is None
    assert WPI_PROXIMITY_KM == 1.0


def test_attach_token_does_not_create_or_confirm():
    ports_doc = ingest_wpi_csv(io.StringIO(_CSV))
    extracted = union_extracted([
        ("v1", [_seed("Fort Bay", 17.62, -63.25)]),
    ])
    before = verdict_for_seed(extracted[0])
    stats = attach_wpi_commercial(extracted, ports_doc)
    assert stats["wpi_created"] == 0
    assert stats["wrote_poe_ports"] is False
    assert stats["wpi_matched"] == 1
    seed = extracted[0]
    assert seed["wpi_commercial"] is True
    assert seed["wpi_index"] == "200"
    assert seed["lat"] == 17.62 and seed["lon"] == -63.25
    assert "wpi" not in (seed.get("seed_sources") or [])
    assert "wpi_commercial" not in (seed.get("seed_sources") or [])
    assert verdict_for_seed(seed) == before == "unverified"
    assert "wpi_commercial" in format_seed_line(seed)
    # WPI First Port of Entry = Yes n'en fait pas un listing PoE.
    assert verdict_for_seed({
        **seed, "seed_sources": ["wpi"], "wpi_commercial": True,
        "has_coords": True,
    }) == "unverified"


def test_wpi_is_not_a_poe_proof_for_judge_or_score():
    seed = _seed("Rotterdam", 51.90, 4.50, sources=["v1"])
    seed["wpi_commercial"] = True
    seed["wpi_index"] = "100"
    seed["seed_line"] = format_seed_line(seed)
    assert "wpi_commercial" in seed["seed_line"]
    assert apply_judge_verdict(seed, {"judge_status": "accepted"}) == "probable"
    prompt = _judge_prompt(seed, {"name": "Netherlands", "iso2": "NL"}, "extrait")
    assert "wpi_commercial" not in prompt
    assert "wpi_index" not in prompt
    assert "listing:poe" not in prompt
    base = {
        "name": "Rotterdam", "lat": 51.9, "lon": 4.5, "validated": True,
        "spatial_kind": "in_eez", "source_urls": ["https://example.invalid"],
    }
    a = score_port(base, official_source=False)
    b = score_port({**base, "wpi_commercial": True}, official_source=False)
    assert a["confidence"] == b["confidence"]
    assert any("contre-liste" in r for r in b["reasons"])


def test_name_only_unique_match_without_creating_seed():
    ports = parse_wpi_csv(io.StringIO(_CSV))
    hit = match_wpi_port(_seed("Rotterdam"), ports)
    assert hit["name"] == "Rotterdam"
    seed = _seed("Rotterdam")
    stats = attach_wpi_commercial([seed], ingest_wpi_csv(io.StringIO(_CSV)))
    assert seed["wpi_commercial"] is True
    assert seed.get("lat") is None and seed.get("lon") is None
    extracted = []
    empty = attach_wpi_commercial(extracted, ingest_wpi_csv(io.StringIO(_CSV)))
    assert extracted == []
    assert stats["wpi_created"] == empty["wpi_created"] == 0
    assert empty["wpi_matched"] == 0


def test_snapshot_slim_counterlist_not_legal_status():
    assert WPI_FILE.is_file()
    doc = load_wpi_ports()
    assert doc["n"] >= 3000
    assert len(doc["ports"]) == doc["n"]
    sample = doc["ports"][0]
    assert "first_port_of_entry" not in sample
    assert "name" in sample and "lat" in sample and "lon" in sample
    assert "preuve PoE" in (doc.get("note") or "")
