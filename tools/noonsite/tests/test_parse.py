import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parse import parse_country_html

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def test_saba_splits_poe_and_other():
    html = (FIX / "saba_main_ports.html").read_text(encoding="utf-8")
    rec = parse_country_html(html, "saba")
    assert [p["name"] for p in rec["ports_of_entry"]] == ["Fort Bay (Fort Baai)"]
    assert [p["name"] for p in rec["other_ports"]] == ["Well's and Ladder Bays"]
    assert rec["ports_of_entry"][0]["is_port_of_entry"] is True
    assert rec["other_ports"][0]["is_port_of_entry"] is False
    assert "Fort Bay" in rec["faq_where_can_i_enter"]


def test_niue_single_poe():
    html = (FIX / "niue_main_ports.html").read_text(encoding="utf-8")
    rec = parse_country_html(html, "https://www.noonsite.com/place/niue/")
    assert rec["slug"] == "niue"
    assert [p["name"] for p in rec["ports_of_entry"]] == ["Alofi"]
    assert rec["other_ports"] == []
