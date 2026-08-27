"""
extract_core.py — Extraction hybride en cascade (économie de crédits TinyFish).

  N1 (gratuit, ms)   : httpx direct + trafilatura (HTML) / PyMuPDF (PDF)
  N2 (gratuit)       : Readability-lxml + BeautifulSoup
  N3 (payant, capé)  : TinyFish — uniquement si N1 et N2 échouent ET autorisé

Fournit aussi : filtrage SERP par regex, métadonnées de page (og:image, liens
externes), et suivi sélectif des liens internes (depth=2 : /annuaire, /contacts…).
"""
import asyncio
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
    r"|\.docx?($|\?)|\.xlsx?($|\?)|\.pptx?($|\?)|\.zip($|\?)|\.exe($|\?))",
    re.I,
)

FOLLOWUP_PATTERNS = (
    "annuaire", "contact", "directory", "port-of-entry", "ports-of-entry",
    "clearance", "douane", "customs", "bureaux", "offices", "liste", "list-of",
    "projets", "projects", "annexe",
)


def serp_filter(results: list[dict], url_key: str = "url", extra_re=None) -> list[dict]:
    """Rejette les URLs non pertinentes (agrégateurs, réseaux sociaux, binaires)."""
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
# N3 — TinyFish (dernier recours payant, capé à 120 s)
# ---------------------------------------------------------------------------
TF_TEXT_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "title": {"type": "string"}},
    "required": ["text"],
}


async def _tinyfish_text(url: str, key: str, log=None) -> dict:
    from tinyfish_client import tf_run_async, tf_get_run
    log = log or (lambda m: None)
    goal = ("Extract the complete readable text content of this page, including any "
            "list of ports of entry, project descriptions, contact directories or "
            "regulatory annexes. Navigate pagination if present. Do not invent content.")
    body = await tf_run_async(url, goal, TF_TEXT_SCHEMA, key, max_duration_s=120)
    run_id = body.get("run_id")
    if not run_id:
        raise ValueError(body.get("error", "no run_id"))
    for _ in range(48):
        await asyncio.sleep(3)
        run = await tf_get_run(run_id, key)
        st = run.get("status", "")
        if st in ("COMPLETED", "FAILED", "CANCELLED"):
            if st != "COMPLETED":
                raise ValueError(f"tinyfish run {st}: {str(run.get('error'))[:100]}")
            return run.get("result") or {}
    raise TimeoutError("tinyfish N3 timed out (144s)")


# ---------------------------------------------------------------------------
# Cascade principale
# ---------------------------------------------------------------------------
async def fetch_raw(url: str, timeout: int = 25):
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=UA_BROWSER) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content, (r.headers.get("content-type") or "").lower()


async def extract_cascade(url: str, min_chars: int = 200, allow_tinyfish: bool = False,
                          tinyfish_key: str | None = None, log=None) -> dict:
    """
    Retourne {url, text, md5, level, title, meta_desc, image, ext_links, is_pdf, html}.
    level ∈ N1-pymupdf | N1-trafilatura | N2-readability | N3-tinyfish | failed.
    md5 = empreinte du texte extrait (stable) sinon du contenu brut.
    """
    log = log or (lambda m: None)
    out = {"url": url, "text": "", "md5": None, "level": "failed", "title": "",
           "meta_desc": "", "image": None, "ext_links": [], "is_pdf": False, "html": None}

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
            # N1 — trafilatura (ultra-rapide, gratuit)
            try:
                text = await asyncio.to_thread(parse_html_n1, html)
                out["text"] = (text or "").strip()
                if len(out["text"]) >= min_chars:
                    out["level"] = "N1-trafilatura"
            except Exception as e:
                log(f"N1 trafilatura: échec ({type(e).__name__})")
            # N2 — Readability + BeautifulSoup si N1 trop pauvre
            if len(out["text"]) < min_chars:
                try:
                    n2 = await asyncio.to_thread(parse_html_n2, html)
                    if len(n2["text"]) > len(out["text"]):
                        out["text"] = n2["text"]
                        out["title"] = out["title"] or n2["title"]
                    if len(out["text"]) >= min_chars:
                        out["level"] = "N2-readability"
                except Exception as e:
                    log(f"N2 readability: échec ({type(e).__name__})")

    # N3 — TinyFish uniquement en dernier recours ET si explicitement autorisé
    if len(out["text"]) < min_chars and allow_tinyfish and tinyfish_key:
        try:
            log("N1/N2 épuisés → N3 TinyFish (dernier recours payant, cap 120s)")
            res = await _tinyfish_text(url, tinyfish_key, log)
            text = (res.get("text") or "").strip()
            if len(text) > len(out["text"]):
                out["text"] = text
                out["title"] = out["title"] or (res.get("title") or "")
                out["level"] = "N3-tinyfish"
        except Exception as e:
            log(f"N3 TinyFish: échec ({type(e).__name__}: {str(e)[:80]})")

    if out["text"]:
        out["md5"] = hashlib.md5(out["text"].encode("utf-8")).hexdigest()
        if out["level"] == "failed":
            out["level"] = "N2-readability"
    return out
