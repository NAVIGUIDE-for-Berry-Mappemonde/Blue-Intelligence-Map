"""P0 run mondial : PDF hors process, cache géocode, lock exceptions.

Aucun seuil TinyFish / SERP n'est exercé ici. Mongo dédiée bi_test_p0_survive.
"""
import asyncio
import inspect
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import extract, geo  # noqa: E402
from app.core.pdf_worker import extract_pdf_file, main as pdf_worker_main  # noqa: E402
from app.services import poe_pipeline as poe  # noqa: E402


def _tiny_pdf_bytes(text: str = "Port of Entry Alpha Harbour") -> bytes:
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


class TestPdfIsolation:
    def test_extract_module_does_not_import_fitz(self):
        src = inspect.getsource(extract)
        assert "import fitz" not in src
        assert "app.core.pdf_worker" in src

    def test_worker_extracts_text(self, tmp_path):
        inp = tmp_path / "in.pdf"
        out = tmp_path / "out.txt"
        inp.write_bytes(_tiny_pdf_bytes("Gazette Port Bravo"))
        assert pdf_worker_main([str(inp), str(out), "10"]) == 0
        assert "Bravo" in out.read_text(encoding="utf-8")

    def test_invalid_pdf_is_confined_to_worker(self, tmp_path, monkeypatch):
        monkeypatch.setattr(extract, "PDF_CACHE_DIR", tmp_path)
        with pytest.raises(RuntimeError, match="pdf_worker exit"):
            extract.parse_pdf_text(b"this is not a pdf")

    def test_disk_cache_skips_second_spawn(self, tmp_path, monkeypatch):
        monkeypatch.setattr(extract, "PDF_CACHE_DIR", tmp_path)
        content = _tiny_pdf_bytes("Catalog Port Charlie designated")
        first = extract.parse_pdf_text(content)
        assert "Charlie" in first
        digest = extract.pdf_cache_key(content)
        assert (tmp_path / f"{digest}.act1.txt").is_file()

        def boom(*_a, **_k):
            raise AssertionError("subprocess should not run on cache hit")

        monkeypatch.setattr(extract, "_run_pdf_worker", boom)
        second = extract.parse_pdf_text(content)
        assert second == first

    def test_worker_direct_helper(self, tmp_path):
        inp = tmp_path / "g.pdf"
        out = tmp_path / "g.txt"
        inp.write_bytes(_tiny_pdf_bytes("Port Delta"))
        extract_pdf_file(str(inp), str(out), 5)
        assert "Delta" in out.read_text(encoding="utf-8")


class _FakeResp:
    def __init__(self, payload, status=200, content_type="application/json"):
        self._payload = payload
        self.status_code = status
        self.headers = {"content-type": content_type}

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, handler):
        self._handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        return self._handler(url, params)


@pytest.fixture
def geo_testdb():
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _prep():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        tdb = client["bi_test_p0_survive"]
        await client.drop_database("bi_test_p0_survive")
        return tdb

    loop = asyncio.new_event_loop()
    tdb = loop.run_until_complete(_prep())
    geo._row_mem.clear()
    geo._last_nominatim = 0.0
    geo._last_geonames = 0.0
    yield tdb, loop
    loop.run_until_complete(tdb.client.drop_database("bi_test_p0_survive"))
    tdb.client.close()
    loop.close()
    geo._row_mem.clear()


class TestGeocodeCacheAndThrottle:
    def test_cache_id_is_stable_and_normalized(self):
        a = geo.geocode_cache_id("nominatim", " Port Alpha ", "Fj", 3)
        b = geo.geocode_cache_id("nominatim", "port alpha", "fj", 3)
        c = geo.geocode_cache_id("nominatim", "port alpha", "fj", 1)
        assert a == b
        assert a != c

    def test_nominatim_second_call_uses_cache(self, monkeypatch, geo_testdb):
        tdb, loop = geo_testdb
        calls = []

        def handler(url, params):
            calls.append(params)
            return _FakeResp([{"lat": "-17.5", "lon": "177.4", "display_name": "Suva"}])

        monkeypatch.setattr(geo, "_geodb", lambda: tdb)
        monkeypatch.setattr(geo, "NOMINATIM_INTERVAL_S", 0)
        monkeypatch.setattr(geo, "_mongo_claim_slot", lambda *a, **k: asyncio.sleep(0))
        monkeypatch.setattr(geo.httpx, "AsyncClient", lambda **k: _FakeClient(handler))

        rows1 = loop.run_until_complete(geo._nominatim_rows("Suva", "fj", 1))
        geo._row_mem.clear()
        rows2 = loop.run_until_complete(geo._nominatim_rows("Suva", "fj", 1))
        assert rows1 == rows2 == [{"lat": "-17.5", "lon": "177.4", "display_name": "Suva"}]
        assert len(calls) == 1
        stored = loop.run_until_complete(
            tdb.geocode_cache.find_one({"provider": "nominatim"}))
        assert stored and stored["rows"][0]["lat"] == "-17.5"

    def test_http_error_is_not_cached(self, monkeypatch, geo_testdb):
        tdb, loop = geo_testdb
        calls = []

        def handler(url, params):
            calls.append(params)
            return _FakeResp({"error": "busy"}, status=503)

        monkeypatch.setattr(geo, "_geodb", lambda: tdb)
        monkeypatch.setattr(geo, "NOMINATIM_INTERVAL_S", 0)
        monkeypatch.setattr(geo, "_mongo_claim_slot", lambda *a, **k: asyncio.sleep(0))
        monkeypatch.setattr(geo.httpx, "AsyncClient", lambda **k: _FakeClient(handler))

        a = loop.run_until_complete(geo._nominatim_rows("Unknown Port", "fj", 1))
        b = loop.run_until_complete(geo._nominatim_rows("Unknown Port", "fj", 1))
        assert a == b == []
        assert len(calls) == 2
        assert loop.run_until_complete(tdb.geocode_cache.count_documents({})) == 0

    def test_shared_throttle_spaces_claims(self, monkeypatch, geo_testdb):
        tdb, loop = geo_testdb
        monkeypatch.setattr(geo, "_geodb", lambda: tdb)

        async def _two():
            t0 = time.monotonic()
            await geo._mongo_claim_slot("p0-test-nomi", 0.25)
            await geo._mongo_claim_slot("p0-test-nomi", 0.25)
            return time.monotonic() - t0

        elapsed = loop.run_until_complete(_two())
        assert elapsed >= 0.2


class TestExceptionsLock:
    def test_merge_unions_auto_buckets(self):
        disk = {"manual": {"FR": ["gouv.fr"]}, "auto": {"VU": ["gov.vu"]}}
        incoming = {"auto": {"MX": ["gob.mx"], "VU": ["ports.gov.vu"]}}
        merged = poe.merge_exceptions(disk, incoming)
        assert merged["manual"]["FR"] == ["gouv.fr"]
        assert merged["auto"]["VU"] == ["gov.vu", "ports.gov.vu"]
        assert merged["auto"]["MX"] == ["gob.mx"]

    def test_concurrent_saves_keep_both_countries(self, tmp_path, monkeypatch):
        path = tmp_path / "poe_exceptions.json"
        path.write_text(json.dumps({"manual": {}, "auto": {}}), encoding="utf-8")
        monkeypatch.setattr(poe, "EXCEPTIONS_FILE", path)

        errors = []

        def writer(iso, domain):
            try:
                poe.save_exceptions({"manual": {}, "auto": {iso: [domain]}})
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=("VU", "gov.vu")),
            threading.Thread(target=writer, args=("MX", "gob.mx")),
            threading.Thread(target=writer, args=("NU", "gov.nu")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["auto"]["VU"] == ["gov.vu"]
        assert data["auto"]["MX"] == ["gob.mx"]
        assert data["auto"]["NU"] == ["gov.nu"]
        json.loads(path.read_text(encoding="utf-8"))  # JSON intact

    def test_load_sees_locked_write(self, tmp_path, monkeypatch):
        path = tmp_path / "poe_exceptions.json"
        monkeypatch.setattr(poe, "EXCEPTIONS_FILE", path)
        poe.save_exceptions({"manual": {"FR": ["gouv.fr"]}, "auto": {}})
        loaded = poe.load_exceptions()
        assert loaded["manual"]["FR"] == ["gouv.fr"]
