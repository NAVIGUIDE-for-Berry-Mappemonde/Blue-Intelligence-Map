"""Parseur HTML Noonsite — listes PoE / non-PoE depuis le panneau Main Ports.

Le badge orange ``Port of Entry`` (classe ``nsdd-badge``) est le signal positif.
Un port listé sans badge est un port / mouillage, pas un PoE.
"""
from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

ORIGIN = "https://www.noonsite.com"
FAQ_RE = re.compile(r"Where can I enter\?\s*(.+?)(?:\n|Are fees|What security|$)", re.I | re.S)


def normalize_slug(value: str) -> str:
    s = (value or "").strip().lower()
    s = re.sub(r"^https?://([^/]+\.)?noonsite\.com/place/", "", s)
    s = s.split("?")[0].split("#")[0].strip("/").split("/")[0]
    s = re.sub(r"[^a-z0-9-]+", "-", s).strip("-")
    return s


def country_url(slug: str) -> str:
    return f"{ORIGIN}/place/{normalize_slug(slug)}/"


def _text(el) -> str:
    if el is None:
        return ""
    return unescape(re.sub(r"\s+", " ", el.get_text(" ", strip=True))).strip()


def _dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        key = (it.get("url") or "").rstrip("/") or it.get("name", "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _faq_entry(soup: BeautifulSoup) -> str:
    for strong in soup.find_all(["strong", "b"]):
        if re.search(r"Where can I enter\?", _text(strong), re.I):
            parent = strong.parent
            blob = _text(parent)
            m = FAQ_RE.search(blob)
            return (m.group(1) if m else blob)[:400]
    m = FAQ_RE.search(soup.get_text("\n", strip=True))
    return (m.group(1).strip() if m else "")[:400]


def _country_name(soup: BeautifulSoup, slug: str) -> str:
    h1 = soup.find(["h1", "h2"], string=re.compile(r".+\s*-\s*Facts", re.I))
    if h1:
        return re.sub(r"\s*-\s*Facts.*$", "", _text(h1), flags=re.I).strip()
    title = _text(soup.find("title"))
    title = re.sub(r"\s*[–—-]\s*Noonsite.*$", "", title, flags=re.I).strip()
    return title or slug.replace("-", " ").title()


def _item_from_anchor(a) -> dict | None:
    """Une ligne Main Ports : lien plat (``.nsdd-link``) ou entrée d'archipel
    (``.nsdd-menu-link``). Les libellés de groupe (Australs, Kadavu…) ne sont
    pas des ports."""
    name = _text(a.select_one(":scope > .nsdd-label")) or _text(a.select_one(".nsdd-label"))
    if not name:
        name = re.sub(r"\s*Port of Entry\s*$", "", _text(a), flags=re.I).strip()
    if not name:
        return None
    href = (a.get("href") or "").strip()
    if href and not href.startswith("http"):
        href = urljoin(ORIGIN, href)
    badge = _text(a.select_one(".nsdd-badge"))
    group = None
    row = a.find_parent(class_="nsdd-row")
    if row is not None:
        trig = row.select_one(".nsdd-trigger > .nsdd-label")
        g = _text(trig)
        if g and g.lower() != name.lower():
            group = g
    return {
        "name": name,
        "url": href,
        "is_port_of_entry": "port of entry" in badge.lower(),
        "group": group,
    }


def parse_country_html(html: str, slug: str) -> dict:
    """Extrait les deux listes depuis une page pays Noonsite (HTML public)."""
    soup = BeautifulSoup(html or "", "html.parser")
    slug = normalize_slug(slug)
    poe, other = [], []
    for nav in soup.select('nav[aria-label="Main ports navigation"]'):
        anchors = nav.select("a.nsdd-link, a.nsdd-menu-link")
        for a in anchors:
            item = _item_from_anchor(a)
            if not item:
                continue
            (poe if item["is_port_of_entry"] else other).append(item)
    return {
        "slug": slug,
        "name": _country_name(soup, slug),
        "url": country_url(slug),
        "ports_of_entry": _dedupe(poe),
        "other_ports": _dedupe(other),
        "faq_where_can_i_enter": _faq_entry(soup),
        "source": "main_ports_nav",
    }
