"""Corroboration Noonsite — quota, parsing, matching. Aucun réseau."""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.tinyfish import automation_payload
from app.services import noonsite as ns
from app.services.poe_pipeline import ports_to_geojson


def _run(coro):
    return asyncio.run(coro)


class TestSlugAndQuota:
    def test_normalize_slug_from_url(self):
        assert ns.normalize_slug("https://www.noonsite.com/place/saba/view/clearance/") == "saba"
        assert ns.normalize_slug("Saba") == "saba"
        assert ns.normalize_slug("  Saint-Barthélemy ") == "saint-barthelemy"

    def test_country_url(self):
        assert ns.country_url("Saba") == "https://www.noonsite.com/place/saba/"

    def test_month_key(self):
        assert ns.month_key(datetime(2026, 9, 5, tzinfo=timezone.utc)) == "2026-09"

    def test_reharvest_does_not_consume(self):
        assert ns.can_harvest("saba", ["saba", "martinique"])
        assert ns.remaining_slots(["saba", "martinique"]) == 1

    def test_fourth_country_blocked(self):
        used = ["saba", "martinique", "guadeloupe"]
        assert not ns.can_harvest("antigua", used)
        assert ns.remaining_slots(used) == 0

    def test_planned_slugs_caps_new_countries(self):
        watch = [
            {"slug": "saba", "name": "Saba"},
            {"slug": "martinique", "name": "Martinique"},
            {"slug": "guadeloupe", "name": "Guadeloupe"},
            {"slug": "antigua", "name": "Antigua"},
        ]
        planned = ns.planned_slugs(watch, ["saba"])
        assert planned[0] == "saba"
        assert "antigua" not in planned
        assert len(planned) == 3

    def test_sanitize_watchlist_dedup(self):
        out = ns.sanitize_watchlist([
            {"slug": "https://www.noonsite.com/place/saba/", "name": "Saba", "mrgid": "8397"},
            {"slug": "saba", "name": "dup"},
            {"name": ""},
        ])
        assert out == [{"slug": "saba", "name": "Saba", "mrgid": 8397}]


class TestParseAndMatch:
    def test_saba_faq_payload(self):
        raw = {
            "country": "Saba",
            "country_slug": "saba",
            "logged_in": True,
            "access_granted": True,
            "quota_blocked": False,
            "ports_of_entry": [
                {"name": "Fort Bay (Fort Baii)", "is_port_of_entry": True,
                 "page_url": "https://www.noonsite.com/place/saba/fort-bay-fort-baai/",
                 "evidence": "There is one Port of Entry, which is Fort Bay"},
                {"name": "Wells Bay", "is_port_of_entry": False,
                 "evidence": "anchorage only, clearance at Fort Bay"},
            ],
        }
        parsed = ns.parse_extract_result(raw)
        assert parsed["country_slug"] == "saba"
        assert parsed["ports"][0]["name"].startswith("Fort Bay")
        assert parsed["ports"][0]["is_port_of_entry"] is True
        assert parsed["ports"][1]["is_port_of_entry"] is False
        assert len(parsed["ports"][0]["evidence"]) <= 120

    def test_nested_result_and_junk(self):
        assert ns.parse_extract_result(None)["ports"] == []
        parsed = ns.parse_extract_result({
            "result": {"country": "Saba", "logged_in": True, "access_granted": True,
                       "quota_blocked": False,
                       "ports_of_entry": [{"name": "Fort Bay", "is_port_of_entry": True}]},
        })
        assert parsed["ports"][0]["name"] == "Fort Bay"

    def test_match_fort_bay(self):
        ports = [
            {"_id": "1", "name": "Fort Bay", "city": "The Bottom"},
            {"_id": "2", "name": "Oranjestad", "city": None},
        ]
        match, score = ns.best_port_match("Fort Bay (Fort Baii)", ports)
        assert match["_id"] == "1"
        assert score >= ns.MATCH_THRESHOLD

    def test_no_false_match(self):
        match, _ = ns.best_port_match("Fort Bay", [
            {"_id": "2", "name": "Gustavia", "city": None},
        ])
        assert match is None


class TestSchemaAndPayload:
    def test_schema_tinyfish_safe(self):
        blob = json.dumps(ns.EXTRACT_SCHEMA)
        for forbidden in ("description", "additionalProperties", "oneOf", "const", "examples"):
            assert forbidden not in blob

    def test_automation_payload_uses_vault_not_password(self):
        settings = {
            "noonsite_use_vault": True,
            "noonsite_use_profile": True,
            "noonsite_profile_id": "prof_abc123def4567890",
            "noonsite_credential_item_ids": ["cred:conn-abc:Work:item-123"],
            "noonsite_browser_profile": "stealth",
        }
        payload = ns.preview_automation_payload(settings, "saba")
        assert payload["use_vault"] is True
        assert payload["use_profile"] is True
        assert payload["profile_id"] == "prof_abc123def4567890"
        assert payload["credential_item_ids"] == ["cred:conn-abc:Work:item-123"]
        assert payload["browser_profile"] == "stealth"
        assert payload["url"] == "https://www.noonsite.com/place/saba/"
        dumped = json.dumps(payload)
        assert "password" not in dumped.lower()
        assert "noonsite_password" not in dumped

    def test_console_snippet_mentions_faq(self):
        assert "Where can I enter" in ns.CONSOLE_SNIPPET
        assert "ports_of_entry" in ns.CONSOLE_SNIPPET
        assert "clipboard" in ns.CONSOLE_SNIPPET

    def test_geojson_exposes_badge_fields(self):
        fc = ports_to_geojson([{
            "_id": "x", "name": "Fort Bay", "lat": 17.62, "lon": -63.25,
            "noonsite_confirmed": True,
            "noonsite_url": "https://www.noonsite.com/place/saba/fort-bay-fort-baai/",
            "noonsite_checked_at": "2026-09-05T00:00:00Z",
        }])
        props = fc["features"][0]["properties"]
        assert props["noonsite_confirmed"] is True
        assert "saba" in props["noonsite_url"]


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, n):
        return list(self._docs)


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find(self, q=None, *a, **k):
        q = q or {}
        out = []
        for d in self.docs:
            ok = True
            for key, val in q.items():
                if key == "$or":
                    ok = any(d.get(list(cl)[0]) == list(cl.values())[0]
                             or True for cl in val)
                    continue
                if d.get(key) != val:
                    ok = False
            if ok:
                out.append(d)
        return _FakeCursor(out)

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                d.update(upd.get("$set") or {})
                return
        if upsert:
            doc = dict(q)
            doc.update(upd.get("$set") or {})
            self.docs.append(doc)

    async def insert_one(self, doc):
        self.docs.append(doc)

    async def insert_many(self, docs):
        self.docs.extend(docs)

    async def find_one(self, q):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return d
        return None

    def sort(self, *a, **k):
        return self

    async def count_documents(self, q):
        return len((await self.find(q).to_list(1000)))


class _FakeDB:
    def __init__(self):
        self.poe_ports = _FakeColl([
            {"_id": "p1", "name": "Fort Bay", "city": None, "mrgid": 99, "zone_name": "Saba"},
        ])
        self.noonsite_signals = _FakeColl()
        self.noonsite_months = _FakeColl()
        self.noonsite_harvests = _FakeColl()


class TestApplyAndImport:
    def test_positive_signal_only(self):
        db = _FakeDB()
        stats = _run(ns.apply_corroboration(
            db, slug="saba",
            place={"slug": "saba", "name": "Saba", "mrgid": 99},
            ports=[
                {"name": "Fort Bay (Fort Baii)", "is_port_of_entry": True,
                 "page_url": "https://www.noonsite.com/place/saba/fort-bay-fort-baai/",
                 "evidence": "one Port of Entry"},
                {"name": "New Harbour", "is_port_of_entry": True, "page_url": "", "evidence": ""},
            ],
            harvest_id="h1", month="2026-09", engine="console",
        ))
        assert stats["confirmed"] == 1
        assert stats["unmatched"] == 1
        port = db.poe_ports.docs[0]
        assert port["noonsite_confirmed"] is True
        assert port["noonsite_url"].endswith("fort-baai/")
        assert len(db.poe_ports.docs) == 1
        kinds = {s["match_kind"] for s in db.noonsite_signals.docs}
        assert kinds == {"confirmed", "unmatched"}

    def test_import_counts_quota_and_rejects_fourth(self):
        db = _FakeDB()
        settings = {"noonsite_watchlist": [
            {"slug": "saba", "name": "Saba", "mrgid": 99},
            {"slug": "martinique", "name": "Martinique"},
            {"slug": "guadeloupe", "name": "Guadeloupe"},
            {"slug": "antigua", "name": "Antigua"},
        ]}
        payload = {
            "country": "Saba", "country_slug": "saba", "logged_in": True,
            "access_granted": True, "quota_blocked": False,
            "ports_of_entry": [{"name": "Fort Bay", "is_port_of_entry": True}],
        }
        rec = _run(ns.import_payload(db, settings, payload))
        assert rec["status"] == "ok"
        assert rec["confirmed"] == 1
        month = ns.month_key()
        _run(ns.reserve_country(db, "martinique", month))
        _run(ns.reserve_country(db, "guadeloupe", month))
        with pytest.raises(ValueError, match="Quota"):
            _run(ns.import_payload(db, settings, {
                **payload, "country_slug": "antigua",
                "ports_of_entry": [{"name": "St John's", "is_port_of_entry": True}],
            }))
        assert db.poe_ports.docs[0]["noonsite_confirmed"] is True


class TestTinyfishPayloadHelper:
    def test_lite_default_unchanged(self):
        p = automation_payload("https://example.com", "g", {"type": "object", "properties": {}})
        assert p["browser_profile"] == "lite"
        assert "use_vault" not in p
        assert "use_profile" not in p
