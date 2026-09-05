#!/usr/bin/env python3
"""Outil latéral Noonsite — listes PoE / non-PoE par pays.

Indépendant du pipeline Blue Intelligence. Ne touche pas à Mongo, ni aux
source_urls officielles. Plafond dur : 3 pays par invocation (quota gratuit).

Usage :
  python harvest.py saba niue
  NOONSITE_EMAIL=… NOONSITE_PASSWORD=… python harvest.py saba niue --login

Par défaut : GET HTTP de la page pays (le panneau Main Ports est dans le HTML).
``--login`` ouvre Formalities/Clearance en session (Playwright) sans débloquer
d'autre pays que ceux demandés.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from parse import country_url, normalize_slug, parse_country_html

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


def fetch_http(slug: str) -> dict:
    url = country_url(slug)
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": UA}) as client:
        r = client.get(url)
        r.raise_for_status()
        rec = parse_country_html(r.text, slug)
        rec["http_status"] = r.status_code
        rec["fetched_at"] = _now()
        rec["engine"] = "httpx"
        return rec


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
    return {
        "generated_at": _now(),
        "disclaimer": (
            "Signal Noonsite, pas un Gold Dataset. Un badge Port of Entry "
            "est un signal positif ; l'absence d'un port ne le réfute pas."
        ),
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
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Listes PoE / non-PoE Noonsite (outil latéral)")
    ap.add_argument("slugs", nargs="*", default=["niue", "saba"],
                    help="Slugs pays (défaut: niue saba)")
    ap.add_argument("--login", action="store_true",
                    help="Session Playwright (NOONSITE_EMAIL / NOONSITE_PASSWORD)")
    ap.add_argument("--out", type=Path, default=OUT_DIR / "latest.json")
    args = ap.parse_args(argv)

    _load_dotenv()
    slugs = [normalize_slug(s) for s in args.slugs]
    slugs = [s for s in slugs if s]
    if not slugs:
        print("Aucun slug.", file=sys.stderr)
        return 2
    if len(slugs) > MONTHLY_CAP:
        print(f"Refus : {len(slugs)} pays demandés, plafond {MONTHLY_CAP}.", file=sys.stderr)
        return 2

    if args.login:
        email = (os.environ.get("NOONSITE_EMAIL") or "").strip()
        password = os.environ.get("NOONSITE_PASSWORD") or ""
        if not email or not password:
            print("NOONSITE_EMAIL et NOONSITE_PASSWORD requis avec --login.", file=sys.stderr)
            return 2
        countries = fetch_logged_in(slugs, email, password)
    else:
        countries = [fetch_http(s) for s in slugs]

    doc = summarize(countries)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
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
