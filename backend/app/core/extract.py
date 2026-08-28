"""
extract_core.py — Extraction hybride en cascade, 100 % locale et gratuite.

  N1/N2 (gratuit, ms)    : httpx direct + DOUBLE PARSING comparé
                           trafilatura ∥ Readability/BS4 (le plus riche gagne,
                           la similarité entre les deux est un signal de qualité)
  N3 (gratuit, local)    : rendu navigateur Playwright/Chromium (render_core)
                           pour les pages JavaScript et les challenges « soft ».

Fournit aussi : filtrage SERP par regex (agrégateurs, réseaux sociaux, pages
interstitielles anti-bot), détection des pages de blocage (un challenge n'est
JAMAIS ingéré comme du contenu), métadonnées de page (og:image, liens externes)
et suivi sélectif des liens internes (depth=2 : /annuaire, /contacts…).
"""
import asyncio
import difflib
import hashlib
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

UA_BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

# --- Filtrage SERP : exclusion regex avant tout parsing -----------------------
SERP_EXCLUDE_RE = re.compile(
    r"(tripadvisor|booking\.com|expedia|airbnb|pinterest|facebook\.com|instagram\.com"
    r"|youtube\.com|twitter\.com|/x\.com|linkedin\.com|reddit\.com|quora\.com"
    r"|hotels?\.com|kayak\.|skyscanner|cruisemapper|vesselfinder"
    r"|brochure|touris[mt]|baggage|luggage|duty.?free|/vts[-_/.]|vts.?manual"
    # pages interstitielles / anti-bot : jamais des sources légitimes
    r"|//unblock\.|\.unblock\.|/cdn-cgi/|captcha|datadome|perimeterx"
    r"|queue-it\.net|incapsula|distilnetworks"
    r"|\.docx?($|\?)|\.xlsx?($|\?)|\.pptx?($|\?)|\.zip($|\?)|\.exe($|\?))",
    re.I,
)

# --- Détection des pages de blocage (challenges anti-bot, interstitiels) ------
BLOCKED_MARKERS_RE = re.compile(
    r"checking your browser|just a moment|verify (?:that )?you are (?:a )?human"
    r"|are you a robot|enable javascript and cookies|cf-browser-verification"
    r"|_cf_chl_|cf_chl_opt|attention required.{0,4}cloudflare|cloudflare ray id"
    r"|px-captcha|datadome|request unsuccessful|incapsula incident"
    r"|access to this page has been denied|pardon our interruption"
    r"|please complete the security check|request has been blocked"
    r"|automated access to this (?:site|page)|ddos protection by"
    r"|complete the captcha|prove (?:that )?you are human|browser verification"
    r"|unblock request|access from your area has been temporarily limited",
    re.I,
)

FOLLOWUP_PATTERNS = (
    "annuaire", "contact", "directory", "port-of-entry", "ports-of-entry",
    "clearance", "douane", "customs", "bureaux", "offices", "liste", "list-of",
    "projets", "projects", "annexe",
)


def serp_filter(results: list[dict], url_key: str = "url", extra_re=None) -> list[dict]:
    """Rejette les URLs non pertinentes (agrégateurs, réseaux sociaux, binaires,
    pages interstitielles anti-bot)."""
    out = []
    for r in results:
        u = r.get(url_key) or ""
        if not u.startswith("http"):
            continue
        if SERP_EXCLUDE_RE.search(u):
            continue
        if extra_re and extra_re.search(u):
            continue
        out.append(r)
    return out


def looks_blocked(text: str, html: str = "", title: str = "") -> bool:
    """True si la page est un challenge anti-bot / interstitiel de blocage.
    Un vrai contenu réglementaire long qui *cite* ces mots reste accepté."""
    probe = " ".join(p for p in (title or "", (text or "")[:4000], (html or "")[:6000]) if p)
    if not probe or not BLOCKED_MARKERS_RE.search(probe):
        return False
    return len((text or "").strip()) < 1500


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------
def parse_pdf_text(content: bytes, max_pages: int = 60) -> str:
    import fitz
    with fitz.open(stream=content, filetype="pdf") as pdf:
        return "\n".join(page.get_text() for page in pdf[:max_pages])


def parse_html_n1(html: str) -> str:
    import trafilatura
    return trafilatura.extract(html) or ""


def parse_html_n2(html: str) -> dict:
    from readability import Document as ReadabilityDoc
    doc = ReadabilityDoc(html)
    title = (doc.short_title() or "").strip()
    soup = BeautifulSoup(doc.summary(), "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    if len(text) < 200:
        full = BeautifulSoup(html, "html.parser")
        text = re.sub(r"\s+", " ", full.get_text(" ")).strip()[:12000]
    return {"text": text, "title": title}


def _parse_similarity(a: str, b: str) -> float:
    """Similarité entre les textes des deux parseurs (signal de qualité)."""
    if not a or not b:
        return 0.0
    na = re.sub(r"\s+", " ", a)[:3000]
    nb = re.sub(r"\s+", " ", b)[:3000]
    return round(difflib.SequenceMatcher(None, na, nb).ratio(), 3)


async def dual_parse_html(html: str) -> dict:
    """PARSING PARALLÈLE comparé : trafilatura ∥ Readability sur le même HTML.
    Le texte le plus riche gagne ; la similarité entre les deux est conservée
    comme signal (accord fort = extraction robuste, divergence = à inspecter).
    Retourne {text, level, title, n1_chars, n2_chars, similarity, agree}."""
    async def _n1():
        try:
            return (await asyncio.to_thread(parse_html_n1, html)).strip()
        except Exception:
            return ""

    async def _n2():
        try:
            return await asyncio.to_thread(parse_html_n2, html)
        except Exception:
            return {"text": "", "title": ""}

    t1, n2 = await asyncio.gather(_n1(), _n2())
    t2, title2 = (n2.get("text") or "").strip(), (n2.get("title") or "").strip()
    sim = _parse_similarity(t1, t2)
    if len(t1) >= len(t2):
        text, level = t1, "N1-trafilatura"
    else:
        text, level = t2, "N2-readability"
    return {
        "text": text, "level": level, "title": title2,
        "n1_chars": len(t1), "n2_chars": len(t2),
        "similarity": sim, "agree": (sim >= 0.55) if (t1 and t2) else None,
    }


def page_metadata(html: str, url: str) -> dict:
    """Titre, meta description, image principale, liens externes (BS4)."""
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text().strip() if soup.title else "") or ""
    meta = soup.find("meta", attrs={"name": "description"}) or \
        soup.find("meta", attrs={"property": "og:description"})
    meta_desc = meta.get("content", "").strip() if meta else ""
    image = None
    for attrs in ({"property": "og:image"}, {"name": "twitter:image"}, {"property": "twitter:image"}):
        m = soup.find("meta", attrs=attrs)
        if m and m.get("content", "").strip():
            image = urljoin(url, m["content"].strip())
            break
    if not image:
        for img in soup.find_all("img", src=True):
            src = img["src"].strip()
            low = src.lower()
            if src.startswith("data:") or low.endswith(".svg"):
                continue
            if any(b in low for b in ("logo", "icon", "sprite", "avatar", "placeholder", "pixel")):
                continue
            image = urljoin(url, src)
            break
    base_host = urlparse(url).netloc
    ext_links, seen_d = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"]).split("#")[0]
        d = urlparse(href).netloc
        name = re.sub(r"\s+", " ", a.get_text(" ")).strip()
        if href.startswith("http") and d and d != base_host and d not in seen_d and 3 < len(name) < 80:
            seen_d.add(d)
            ext_links.append({"name": name, "url": href})
        if len(ext_links) >= 15:
            break
    return {"title": title, "meta_desc": meta_desc, "image": image, "ext_links": ext_links}


def internal_followups(html: str, base_url: str, patterns=FOLLOWUP_PATTERNS, limit: int = 3) -> list[str]:
    """Depth=2 sélectif : liens internes de type /annuaire, /contacts, /clearance…"""
    soup = BeautifulSoup(html, "html.parser")
    base_host = urlparse(base_url).netloc
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        if urlparse(href).netloc != base_host or href.rstrip("/") == base_url.rstrip("/"):
            continue
        path = urlparse(href).path.lower()
        if any(p in path for p in patterns) and href not in seen and not SERP_EXCLUDE_RE.search(href):
            seen.add(href)
            out.append(href)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Cascade principale
# ---------------------------------------------------------------------------
async def fetch_raw(url: str, timeout: int = 25):
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=UA_BROWSER) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content, (r.headers.get("content-type") or "").lower()


async def extract_cascade(url: str, min_chars: int = 200, allow_render: bool = True,
                          log=None) -> dict:
    """
    Retourne {url, text, md5, level, title, meta_desc, image, ext_links,
              is_pdf, html, blocked, render_used, parse}.
    level ∈ N1-pymupdf | N1-trafilatura | N2-readability | N3-render | blocked | failed.
    md5 = empreinte du texte extrait (stable) sinon du contenu brut.
    blocked = page interstitielle anti-bot détectée (contenu invalidé, jamais ingéré).
    parse = {n1_chars, n2_chars, similarity, agree} — double parsing comparé.
    """
    log = log or (lambda m: None)
    out = {"url": url, "text": "", "md5": None, "level": "failed", "title": "",
           "meta_desc": "", "image": None, "ext_links": [], "is_pdf": False,
           "html": None, "blocked": False, "render_used": False, "parse": None}

    content = None
    ctype = ""
    try:
        content, ctype = await fetch_raw(url)
    except Exception as e:
        log(f"N1 fetch: échec ({type(e).__name__})")

    if content is not None:
        out["md5"] = hashlib.md5(content).hexdigest()
        is_pdf = content[:5] == b"%PDF-" or "pdf" in ctype or url.lower().endswith(".pdf")
        out["is_pdf"] = is_pdf
        if is_pdf:
            try:
                text = await asyncio.to_thread(parse_pdf_text, content)
                out["text"] = (text or "").strip()
                if out["text"]:
                    out["level"] = "N1-pymupdf"
            except Exception as e:
                log(f"N1 PyMuPDF: échec ({type(e).__name__})")
        else:
            html = content.decode("utf-8", errors="replace")
            out["html"] = html
            try:
                meta = await asyncio.to_thread(page_metadata, html, url)
                out.update({k: meta[k] for k in ("title", "meta_desc", "image", "ext_links")})
            except Exception:
                pass
            parsed = await dual_parse_html(html)
            out["parse"] = {k: parsed[k] for k in ("n1_chars", "n2_chars", "similarity", "agree")}
            out["title"] = out["title"] or parsed["title"]
            if looks_blocked(parsed["text"], html, out["title"]):
                out["blocked"] = True
                log("page interstitielle anti-bot détectée — contenu invalidé")
            elif len(parsed["text"]) >= min_chars:
                out["text"] = parsed["text"]
                out["level"] = parsed["level"]
            elif parsed["text"]:
                out["text"] = parsed["text"]

    # N3 — rendu navigateur local (gratuit) : pages JS et challenges « soft ».
    needs_render = (not out["is_pdf"]) and (out["blocked"] or len(out["text"]) < min_chars)
    if needs_render and allow_render:
        from app.core.render import render_html
        rendered = await render_html(url, log=log)
        if rendered:
            out["render_used"] = True
            parsed = await dual_parse_html(rendered)
            r_blocked = looks_blocked(parsed["text"], rendered, parsed["title"])
            if not r_blocked and len(parsed["text"]) > len(out["text"]):
                out["text"] = parsed["text"]
                out["html"] = rendered
                out["title"] = out["title"] or parsed["title"]
                out["parse"] = {k: parsed[k] for k in ("n1_chars", "n2_chars", "similarity", "agree")}
                out["level"] = "N3-render"
                out["blocked"] = False
                try:
                    meta = await asyncio.to_thread(page_metadata, rendered, url)
                    for k in ("meta_desc", "image", "ext_links"):
                        out[k] = out[k] or meta[k]
                except Exception:
                    pass
                log(f"N3-render: {len(out['text'])} chars via Chromium local")
            elif r_blocked:
                out["blocked"] = True

    if out["blocked"]:
        out["text"] = ""
        out["level"] = "blocked"
        return out

    if out["text"]:
        out["md5"] = hashlib.md5(out["text"].encode("utf-8")).hexdigest()
        if out["level"] == "failed":
            out["level"] = "N2-readability"
    return out
