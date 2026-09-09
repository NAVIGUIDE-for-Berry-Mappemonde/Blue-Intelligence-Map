"""Porte unique read_url / extract_cascade — aucun réseau."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import extract as ext  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class _FakeResp:
    def __init__(self, content: bytes, content_type="text/html",
                 disposition="", url="https://example.gov/x"):
        self.content = content
        self.headers = {
            "content-type": content_type,
            "content-disposition": disposition,
        }
        self.url = url

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")


class TestContentIsPdf:
    def test_magic_bytes(self):
        assert ext.content_is_pdf(b"%PDF-1.4 rest", "text/html", "https://x") is True

    def test_html_at_pdf_url_is_not_pdf(self):
        html = b"<!DOCTYPE html><html><body>error</body></html>"
        assert ext.content_is_pdf(
            html, "text/html", "https://gov.example/decreto.pdf") is False

    def test_content_disposition(self):
        assert ext.content_is_pdf(
            b"%PDF-1.7", "application/octet-stream",
            "https://gov.example/download",
            'attachment; filename="lista.pdf"') is True

    def test_html_not_pdf_despite_disposition_name(self):
        html = b"<html><p>not a pdf</p></html>"
        assert ext.content_is_pdf(
            html, "text/html", "https://gov.example/x",
            'attachment; filename="lista.pdf"') is False


class TestMapsUrl:
    def test_place_and_search(self):
        assert ext.is_maps_render_url(
            "https://www.google.com/maps/place/Port+des+Minimes/") is True
        assert ext.is_maps_render_url(
            "https://www.google.com/maps/search/?api=1&query=Marina+46,-1") is True
        assert ext.is_maps_render_url("https://douane.gouv.fr/ports") is False


class TestFetchUsable:
    def test_blocked_not_usable(self):
        rec = {"text": "Just a moment", "blocked": True}
        assert ext.fetch_record_usable(rec, min_chars=10) is False

    def test_keep_if_links(self):
        rec = {"text": "", "links": ["https://parc.fr/visite"]}
        assert ext.fetch_record_usable(rec, min_chars=200) is False
        assert ext.fetch_record_usable(rec, min_chars=200, keep_if_links=True) is True

    def test_long_text(self):
        rec = {"text": "Ports of entry " * 40}
        assert ext.fetch_record_usable(rec, min_chars=200) is True


class TestReadUrls:
    def test_fetch_success_skips_cascade(self, monkeypatch):
        called = []

        async def fake_tf(urls, key, **k):
            return {u: {"text": "Official designated ports of entry. " * 20,
                        "title": "List", "links": []} for u in urls}

        async def boom_cascade(url, **k):
            called.append(url)
            raise AssertionError("cascade must not run on usable Fetch")

        monkeypatch.setattr("app.core.tinyfish.tf_fetch", fake_tf)
        monkeypatch.setattr("app.core.tinyfish.tf_api_key", lambda settings=None: "k")
        monkeypatch.setattr(ext, "extract_cascade", boom_cascade)

        page = _run(ext.read_url(
            "https://douane.gouv.fr/decreto.pdf",
            prefer_fetch=True, fetch_key="k", min_chars=200))
        assert called == []
        assert page["level"] == "N3-fetch"
        assert "designated ports" in page["text"]
        assert page.get("render_used") is False

    def test_empty_fetch_falls_back_to_cascade(self, monkeypatch):
        seen = []

        async def empty_tf(urls, key, **k):
            return {u: {"text": "", "error": "empty"} for u in urls}

        async def fake_cascade(url, **k):
            seen.append(k.get("skip_fetch_mirror"))
            page = ext.empty_page(url, level="N1-pymupdf")
            page["text"] = "1.- Puerto X\nLatitud:10.1\nLongitud:-20.2\n" * 8
            return page

        monkeypatch.setattr("app.core.tinyfish.tf_fetch", empty_tf)
        monkeypatch.setattr(ext, "extract_cascade", fake_cascade)

        page = _run(ext.read_url(
            "https://dof.gob.mx/nota.pdf", prefer_fetch=True, fetch_key="k"))
        assert seen == [True]
        assert page["level"] == "N1-pymupdf"
        assert "Puerto X" in page["text"]

    def test_maps_never_cascades(self, monkeypatch):
        called = []
        maps = "https://www.google.com/maps/place/Port+des+Minimes/"

        async def fake_tf(urls, key, **k):
            return {u: {"text": "Maps pin DOM", "links": [maps]} for u in urls}

        async def boom_cascade(url, **k):
            called.append(url)
            return ext.empty_page(url)

        monkeypatch.setattr("app.core.tinyfish.tf_fetch", fake_tf)
        monkeypatch.setattr(ext, "extract_cascade", boom_cascade)

        page = _run(ext.read_url(maps, prefer_fetch=True, fetch_key="k"))
        assert called == []
        assert page["level"] == "N3-fetch"
        assert page["links"]

    def test_extract_cascade_skips_maps(self):
        page = _run(ext.extract_cascade(
            "https://www.google.com/maps/place/Foo/"))
        assert page["error"] == "maps_render_url"
        assert page["text"] == ""
        assert page["render_used"] is False

    def test_html_at_pdf_url_parsed_as_html(self, monkeypatch):
        body = ("<html><body><p>" + ("port of entry Nouméa " * 40)
                + "</p></body></html>")

        async def fake_raw(url, timeout=25):
            return _FakeResp(body.encode(), "text/html",
                             url="https://gob.mx/nota.pdf")

        async def no_render(url, log=None):
            raise AssertionError("no chromium")

        async def no_mirror(url, log=None, skip_tinyfish=False):
            return None

        monkeypatch.setattr(ext, "fetch_raw", fake_raw)
        monkeypatch.setattr("app.core.render.render_html", no_render)
        monkeypatch.setattr(ext, "fetch_mirror_text", no_mirror)

        page = _run(ext.extract_cascade("https://gob.mx/nota.pdf", min_chars=200))
        assert page["is_pdf"] is False
        assert len(page["text"]) >= 200
        assert page["level"] in ("N1-trafilatura", "N2-readability")

    def test_pdf_magic_uses_pymupdf(self, monkeypatch):
        async def fake_raw(url, timeout=25):
            return _FakeResp(
                b"%PDF-1.4 fake", "application/pdf",
                disposition='attachment; filename="decreto.pdf"',
                url="https://gob.mx/download")

        monkeypatch.setattr(ext, "fetch_raw", fake_raw)
        monkeypatch.setattr(
            ext, "parse_pdf_text",
            lambda content, max_pages=180: "Articulo 1 puertos habilitados. " * 20)

        async def no_mirror(url, log=None, skip_tinyfish=False):
            return None

        monkeypatch.setattr(ext, "fetch_mirror_text", no_mirror)

        page = _run(ext.extract_cascade("https://gob.mx/download", min_chars=80))
        assert page["is_pdf"] is True
        assert page["level"] == "N1-pymupdf"
        assert page["render_used"] is False

    def test_skip_fetch_mirror_skips_tinyfish(self, monkeypatch):
        tf_called = []

        async def fake_tf(url, log):
            tf_called.append(url)
            return "tinyfish catalog " * 80, []

        async def fake_jina(url, log):
            return None

        async def fake_wb(url, log):
            return None

        monkeypatch.setattr(ext, "_tinyfish_mirror_text", fake_tf)
        monkeypatch.setattr(ext, "_jina_mirror_text", fake_jina)
        monkeypatch.setattr(ext, "_wayback_mirror_text", fake_wb)
        monkeypatch.setattr("app.core.tinyfish.tf_api_key", lambda settings=None: "k")

        _run(ext.fetch_mirror_text("https://aduana.gob.mx/list", skip_tinyfish=True))
        assert tf_called == []

    def test_complete_with_cascade_replaces_empty_fetch(self, monkeypatch):
        url = "https://gob.mx/decreto.pdf"
        fetched = {url: {"text": "", "error": "empty"}}

        async def fake_cascade(u, **k):
            page = ext.empty_page(u, level="N1-pymupdf")
            page["text"] = "Decreto oficial " * 30
            return page

        monkeypatch.setattr(ext, "extract_cascade", fake_cascade)
        out = _run(ext.complete_with_cascade([url], fetched, min_chars=200))
        rec = out[url]
        assert "Decreto oficial" in rec["text"]
        assert rec["level"] == "N1-pymupdf"

    def test_complete_with_cascade_keeps_maps(self, monkeypatch):
        maps = "https://www.google.com/maps/place/X/"

        async def boom(u, **k):
            raise AssertionError("maps must not enter cascade")

        monkeypatch.setattr(ext, "extract_cascade", boom)
        out = _run(ext.complete_with_cascade(
            [maps], {maps: {"text": "", "links": []}}))
        assert out[maps]["text"] == ""

    def test_html_hrefs_keeps_internal(self):
        html = '<html><a href="/visite">Visite</a><a href="https://ext.example/x">x</a></html>'
        links = ext.html_hrefs(html, "https://parc.fr/index")
        assert "https://parc.fr/visite" in links
        assert "https://ext.example/x" in links


class TestKeepIfLinks:
    def test_amp_empty_text_with_links_skips_cascade(self, monkeypatch):
        called = []
        url = "https://parc.fr/"

        async def fake_tf(urls, key, **k):
            return {u: {"text": "", "links": ["https://parc.fr/visite"]} for u in urls}

        async def boom(u, **k):
            called.append(u)
            return ext.empty_page(u)

        monkeypatch.setattr("app.core.tinyfish.tf_fetch", fake_tf)
        monkeypatch.setattr(ext, "extract_cascade", boom)

        pages = _run(ext.read_urls(
            [url], prefer_fetch=True, fetch_key="k", keep_if_links=True, min_chars=200))
        assert called == []
        assert pages[url]["links"] == ["https://parc.fr/visite"]
