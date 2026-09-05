#!/usr/bin/env python3
"""Outil latéral Noonsite — listes PoE / non-PoE par pays.

Indépendant du pipeline Blue Intelligence. Ne touche pas à Mongo, ni aux
source_urls officielles.

Usage :
  python harvest.py saba niue
  python harvest.py --all          # toutes les pages pays (HTTP public, sans login)
  NOONSITE_EMAIL=… NOONSITE_PASSWORD=… python harvest.py saba niue --login

Par défaut : GET HTTP de la page pays (le panneau Main Ports est dans le HTML).
``--login`` ouvre Formalities/Clearance (plafond 3 pays — quota gratuit).
``--all`` n'utilise jamais le login.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import httpx

from parse import ORIGIN, country_url, normalize_slug, parse_country_html

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "output"
MONTHLY_CAP = 3
UA = "BlueIntelligence-NoonsiteSideTool/1.0"


def _load_dotenv() -> None:
    """Charge tools/noonsite/.env s'il existe (jamais commité)."""
    path = HERE / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
PLACE_SITEMAPS = (
    f"{ORIGIN}/wp-sitemap-posts-jet_places-1.xml",
    f"{ORIGIN}/wp-sitemap-posts-jet_places-2.xml",
)


def _client() -> httpx.Client:
    return httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": UA})


def discover_country_slugs(client: httpx.Client | None = None) -> list[str]:
    """Pages pays : ``/place/{slug}/`` (un seul segment) depuis les sitemaps jet_places."""
    own = client is None
    client = client or _client()
    urls: list[str] = []
    try:
        for sm in PLACE_SITEMAPS:
            r = client.get(sm)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            urls.extend(el.text or "" for el in root.findall(".//sm:loc", SITEMAP_NS))
    finally:
        if own:
            client.close()
    slugs = set()
    for u in urls:
        parts = urlparse(u).path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "place" and parts[1]:
            slugs.add(normalize_slug(parts[1]))
    return sorted(s for s in slugs if s)


def fetch_http(slug: str, client: httpx.Client | None = None) -> dict:
    own = client is None
    client = client or _client()
    url = country_url(slug)
    try:
        r = client.get(url)
        rec = parse_country_html(r.text, slug)
        rec["http_status"] = r.status_code
        rec["fetched_at"] = _now()
        rec["engine"] = "httpx"
        if r.status_code >= 400:
            rec["error"] = f"http_{r.status_code}"
        return rec
    except Exception as e:
        return {
            "slug": normalize_slug(slug), "name": slug, "url": url,
            "ports_of_entry": [], "other_ports": [],
            "http_status": None, "error": f"{type(e).__name__}: {e}",
            "fetched_at": _now(), "engine": "httpx",
        }
    finally:
        if own:
            client.close()


def fetch_logged_in(slugs: list[str], email: str, password: str) -> list[dict]:
    """Session Playwright : login une fois, puis uniquement les slugs demandés."""
    from playwright.sync_api import sync_playwright

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=UA, locale="en-GB")
        page = context.new_page()
        page.goto("https://www.noonsite.com/login/", wait_until="domcontentloaded", timeout=45000)
        page.locator("#loginform #user_login").first.fill(email)
        page.locator("#loginform #user_pass").first.fill(password)
        page.locator("#loginform #wp-submit").first.click()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(1500)
        if page.locator("#loginform #user_login").count() and "login" in page.url.lower():
            raise RuntimeError("Login Noonsite refusé — identifiants ou anti-bot")
        for slug in slugs:
            url = country_url(slug)
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(800)
            html = page.content()
            rec = parse_country_html(html, slug)
            rec["fetched_at"] = _now()
            rec["engine"] = "playwright"
            rec["logged_in"] = True
            rec["page_url"] = page.url
            try:
                page.goto(url.rstrip("/") + "/view/clearance/", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(600)
                body = page.inner_text("body")[:800]
                rec["clearance_preview"] = body
                rec["clearance_locked"] = bool(re.search(
                    r"unlock this country|upgrade to|monthly (limit|allowance)",
                    body, re.I))
            except Exception as e:
                rec["clearance_error"] = type(e).__name__
            results.append(rec)
        context.close()
        browser.close()
    return results


def summarize(countries: list[dict]) -> dict:
    poe_flat = []
    for c in countries:
        for p in c.get("ports_of_entry") or []:
            poe_flat.append({
                "country": c.get("name"),
                "slug": c.get("slug"),
                "name": p.get("name"),
                "url": p.get("url"),
                "group": p.get("group"),
            })
    return {
        "generated_at": _now(),
        "disclaimer": (
            "Signal Noonsite, pas un Gold Dataset. Un badge Port of Entry "
            "est un signal positif ; l'absence d'un port ne le réfute pas. "
            "Listes lues dans le HTML public Main Ports, sans compte."
        ),
        "stats": {
            "countries": len(countries),
            "countries_with_poe": sum(1 for c in countries if c.get("ports_of_entry")),
            "ports_of_entry": len(poe_flat),
            "other_ports": sum(len(c.get("other_ports") or []) for c in countries),
        },
        "quota": {"cap": MONTHLY_CAP, "requested": [c["slug"] for c in countries]},
        "countries": countries,
        "by_country": {
            c["slug"]: {
                "name": c.get("name"),
                "ports_of_entry": [p["name"] for p in c.get("ports_of_entry") or []],
                "other_ports": [p["name"] for p in c.get("other_ports") or []],
            }
            for c in countries
        },
        "ports_of_entry": poe_flat,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Listes PoE / non-PoE Noonsite (outil latéral)")
    ap.add_argument("slugs", nargs="*", default=[],
                    help="Slugs pays (défaut: niue saba, sauf --all)")
    ap.add_argument("--all", action="store_true",
                    help="Toutes les pages pays du sitemap (HTTP public, sans login)")
    ap.add_argument("--login", action="store_true",
                    help="Session Playwright (NOONSITE_EMAIL / NOONSITE_PASSWORD), max 3 pays")
    ap.add_argument("--sleep", type=float, default=0.2,
                    help="Pause entre pays en HTTP (défaut 0.2 s)")
    ap.add_argument("--out", type=Path, default=OUT_DIR / "latest.json")
    args = ap.parse_args(argv)

    _load_dotenv()
    if args.all and args.login:
        print("--all est HTTP public uniquement : retirez --login.", file=sys.stderr)
        return 2

    if args.all:
        slugs = discover_country_slugs()
        print(f"{len(slugs)} pays dans le sitemap jet_places", file=sys.stderr)
    else:
        raw = args.slugs or ["niue", "saba"]
        slugs = [normalize_slug(s) for s in raw]
        slugs = [s for s in slugs if s]
    if not slugs:
        print("Aucun slug.", file=sys.stderr)
        return 2
    if args.login and len(slugs) > MONTHLY_CAP:
        print(f"Refus : {len(slugs)} pays demandés, plafond login {MONTHLY_CAP}.", file=sys.stderr)
        return 2

    if args.login:
        email = (os.environ.get("NOONSITE_EMAIL") or "").strip()
        password = os.environ.get("NOONSITE_PASSWORD") or ""
        if not email or not password:
            print("NOONSITE_EMAIL et NOONSITE_PASSWORD requis avec --login.", file=sys.stderr)
            return 2
        countries = fetch_logged_in(slugs, email, password)
    else:
        countries = []
        with _client() as client:
            for i, s in enumerate(slugs, 1):
                rec = fetch_http(s, client)
                countries.append(rec)
                n = len(rec.get("ports_of_entry") or [])
                print(f"[{i}/{len(slugs)}] {s}: {n} PoE", file=sys.stderr)
                if i < len(slugs) and args.sleep > 0:
                    time.sleep(args.sleep)

    doc = summarize(countries)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.all:
        print(json.dumps(doc.get("stats"), ensure_ascii=False, indent=2))
        for slug, row in doc["by_country"].items():
            names = row["ports_of_entry"]
            if not names:
                continue
            print(f"{row.get('name') or slug}: {', '.join(names)}")
    else:
        for slug, row in doc["by_country"].items():
            poe = ", ".join(row["ports_of_entry"]) or "—"
            other = ", ".join(row["other_ports"]) or "—"
            print(f"{row.get('name') or slug}")
            print(f"  PoE     : {poe}")
            print(f"  non-PoE : {other}")
        print(json.dumps(doc["by_country"], ensure_ascii=False, indent=2))
    print(f"\n→ {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
