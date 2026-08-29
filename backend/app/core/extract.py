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
import threading
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

# PyMuPDF n'est pas sûr en usage concurrent multi-threads (crash natif
# « double free or corruption » constaté en run complet) — parsing sérialisé.
_pdf_lock = threading.Lock()

UA_BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
# r.jina.ai renvoie 403 (Cloudflare) si on se présente comme Chrome ; un UA lecteur suffit.
UA_READER = {
    "User-Agent": "Mozilla/5.0 (compatible; BlueIntelligence-Reader/1.0)",
    "Accept": "text/plain, */*;q=0.8",
}

HARD_CHALLENGE_RE = re.compile(
    r"challenge validation|sec-cpt-if|sec-container|akamai",
    re.I,
)

# --- Filtrage SERP : exclusion regex avant tout parsing -----------------------
SERP_EXCLUDE_RE = re.compile(
    r"(tripadvisor|booking\.com|expedia|airbnb|pinterest|facebook\.com|instagram\.com"
    r"|youtube\.com|twitter\.com|/x\.com|linkedin\.com|reddit\.com|quora\.com"
    r"|hotels?\.com|kayak\.|skyscanner|cruisemapper|vesselfinder"
    r"|brochure|touris[mt]|baggage|luggage|duty.?free|/vts[-_/.]|vts.?manual"
    # dictionnaires / encyclopédies / how-to / « ports TCP » : jamais des sources de PoE
    r"|merriam-webster|dictionary\.com|thefreedictionary|cambridge\.org/(?:\w+/)?dictionary"
    r"|wiktionary|britannica\.com|wikihow|howtogeek|investopedia|linguee|wordreference"
    r"|vocabulary\.com|twominenglish|askdifference|factsinstitute"
    r"|guiahardware|stationx\.net|common-ports-cheat|ip-tracker\.org"
    r"|doordash\.com"
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
    r"|unblock request|access from your area has been temporarily limited"
    r"|challenge validation|sec-cpt-if|sec-container",
    re.I,
)

FOLLOWUP_PATTERNS = (
    "annuaire", "contact", "directory", "port-of-entry", "ports-of-entry",
    "clearance", "douane", "customs", "bureaux", "offices", "liste", "list-of",
    "projets", "projects", "annexe", "habilit", "designated", "decreto",
    "gazette", "legislation", "aduana", "anexo",
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
def parse_pdf_text(content: bytes, max_pages: int = 180) -> str:
    import fitz
    with _pdf_lock:
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


def _is_mirror_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("jina.ai") or host.endswith("web.archive.org") or host.endswith("archive.org")


# « 4.- Ensenada », « 1. Apia », ou premier item Jina « [1.-](url)Bahía Colonet »
_HEAD = r"(?:\[\d+\.-\]\([^)]+\)|\d+\.-\s+|\d+[.)]\s+)"
_CATALOG_HEAD = re.compile(
    rf"(?:^|\n)(?:#{{1,6}}\s+)?{_HEAD}([^\n|#]{{2,80}})\n"
    rf"((?:.*\n){{0,16}}?)(?=(?:#{{1,6}}\s+)?{_HEAD}|\Z)",
    re.M,
)
# Jina : **Latitud:**31.89  — EN : Latitude: -13.8  — tables : | Latitud: | 31.89 |
_CATALOG_SEP = r"[\s|*]*"
_CATALOG_LAT = re.compile(rf"(?:latitud(?:e)?|lat\.?):{_CATALOG_SEP}([+-]?\d+(?:\.\d+)?)", re.I)
_CATALOG_LON = re.compile(rf"(?:longitud(?:e)?|long\.?|lng|lon):{_CATALOG_SEP}([+-]?\d+(?:\.\d+)?)", re.I)
_CATALOG_STATE = re.compile(
    rf"(?:entidad federativa|province|state|région|region|departamento|governorate):"
    rf"{_CATALOG_SEP}([^\n|*]+)",
    re.I,
)
# Tournures légales : port of Alofi, port de Papeete, puerto de Ensenada, porto de Santos…
_PORT_OF_RE = re.compile(
    r"\b(?:ports?\s+of\s+|porto?s?\s+d(?:e\s+|['’])|puertos?\s+de\s+|"
    r"portos?\s+de\s+|havens?\s+van\s+|hafen\s+von\s+|porti?\s+di\s+)"
    r"([A-ZÀ-Ý][\w'’. -]{0,40}?)(?=,|;|\.| the | or |\n| et | ou | y | e | und | oder )",
    re.I,
)
_PORT_OF_SKIP = frozenset({
    "entry", "entries", "entrée", "entree", "entrada", "ingresso",
    "call", "departure", "the", "a", "an", "any",
    "registry", "register", "registre", "destination",
    "commerce", "plaisance", "recreo", "recreio", "mer", "mar",
    "base", "principal",
})
_CATALOG_MARKERS_RE = re.compile(
    r"puertos habilitados|designated ports|ports? d['’]entrée|"
    r"ports? of entry|puertos de entrada|portos de entrada",
    re.I,
)
_PDF_ABS_RE = re.compile(r"https?://[^\s\]\)'\"<>]+\.pdf(?:\?[^\s\]\)'\"<>]*)?", re.I)
_PDF_HREF_RE = re.compile(
    r"""(?:href|src)\s*=\s*["']([^"']+\.pdf(?:\?[^"']*)?)["']""",
    re.I,
)
_PDF_MD_RE = re.compile(r"\[[^\]]*\]\(([^)]+\.pdf(?:\?[^)]*)?)\)", re.I)
_LIST_PDF_RE = re.compile(
    r"puerto|terminal|habilit|port.?of.?entry|ports.?of.?entry|"
    r"customs|douane|aduana|clearance|gazett|legislat|designat|liste",
    re.I,
)


def looks_hard_challenge(text: str = "", html: str = "", title: str = "") -> bool:
    """Challenge Akamai / « Challenge Validation » : Chromium n'y peut rien."""
    probe = " ".join(p for p in (title or "", (text or "")[:2000], (html or "")[:4000]) if p)
    return bool(probe and HARD_CHALLENGE_RE.search(probe))


def looks_like_port_catalog(text: str) -> bool:
    """Vrai catalogue (coords ou décret numéroté), pas une loi quelconque
    qui contient « 1. Article »."""
    if not text:
        return False
    lat_hits = len(re.findall(r"latitud(?:e)?\s*:", text, re.I))
    if lat_hits >= 8:
        return True
    if _CATALOG_MARKERS_RE.search(text) and (text.count(".-") >= 8 or lat_hits >= 3):
        return True
    return False


def extract_structured_ports(text: str) -> list[dict]:
    """Lit une liste officielle dans le texte source (pas une liste figée) :
    titres « N.- Nom » + lat/lon, ou tournure légale « port of X ».
    Les coordonnées du décret sont conservées pour éviter un géocodage de masse.
    Chaque bloc [SOURCE: …] est lu isolément : concaténer un PDF de loi à un
    catalogue ne doit pas avaler le dernier port."""
    if not text:
        return []
    parts = re.split(r"\n(?=\[SOURCE: )", text) if "[SOURCE:" in text else [text]
    if len(parts) == 1:
        return _extract_structured_ports_one(text)
    out, seen_keys = [], set()
    for part in parts:
        for p in _extract_structured_ports_one(part):
            key = p["name"].casefold()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            out.append(p)
    return out


def _extract_structured_ports_one(text: str) -> list[dict]:
    out, seen = [], set()
    for m in _CATALOG_HEAD.finditer(text or ""):
        name = " ".join(m.group(1).split()).strip()
        block = m.group(2) or ""
        lat_m, lon_m = _CATALOG_LAT.search(block), _CATALOG_LON.search(block)
        if not name or not lat_m or not lon_m:
            continue
        st = _CATALOG_STATE.search(block)
        state = st.group(1).strip() if st else None
        key = name.casefold()
        if key in seen and state:
            name = f"{name} ({state})"
            key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "name": name[:120], "city": state,
            "lat": float(lat_m.group(1)), "lon": float(lon_m.group(1)),
            "note": "catalogue officiel (nom + coordonnées dans la source)",
            "extraction_engine": "catalog",
        })
    for m in _PORT_OF_RE.finditer(text or ""):
        name = m.group(1).strip().rstrip(".")
        first = name.split()[0].casefold() if name else ""
        if not name or first in _PORT_OF_SKIP or name.casefold() in seen:
            continue
        if len(name) < 3 or len(name) > 60:
            continue
        seen.add(name.casefold())
        out.append({
            "name": name[:120], "city": None,
            "note": "tournure légale (« port of / port de / puerto de … »)",
            "extraction_engine": "catalog",
        })
    return out


def official_attachments(text: str, base_url: str, limit: int = 2) -> list[str]:
    """PDF officiels liés depuis une page d'État (pièce jointe de liste, décret)."""
    if not text or not base_url:
        return []
    raw: list[str] = list(_PDF_ABS_RE.findall(text))
    raw += [urljoin(base_url, h) for h in _PDF_HREF_RE.findall(text)]
    raw += [urljoin(base_url, h) for h in _PDF_MD_RE.findall(text)]
    base_host = (urlparse(base_url).hostname or "").lower()
    scored, seen = [], set()
    for u in raw:
        u = (u or "").split("#")[0]
        if not u.startswith("http") or u in seen or _is_mirror_url(u):
            continue
        if SERP_EXCLUDE_RE.search(u):
            continue
        host = (urlparse(u).hostname or "").lower()
        listish = bool(_LIST_PDF_RE.search(u))
        if host != base_host and not listish:
            continue
        seen.add(u)
        scored.append((0 if listish else 1, u))
    scored.sort()
    return [u for _, u in scored[:limit]]


def should_follow_attachments(text: str, url: str) -> bool:
    """Suivre un PDF même si la page est déjà longue (leçon SCT : la liste
    est souvent le fichier lié, pas le HTML)."""
    blob = f"{url} {text[:4000]}"
    return (looks_like_port_catalog(text or "")
            or bool(_CATALOG_MARKERS_RE.search(blob))
            or bool(_LIST_PDF_RE.search(url or ""))
            or len(text or "") < 800)


async def _fetch_bytes(url: str, headers: dict, timeout: float):
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content, (r.headers.get("content-type") or "").lower()


async def _wayback_snapshot_url(url: str) -> str | None:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=UA_BROWSER) as client:
        r = await client.get("https://web.archive.org/cdx/search/cdx", params={
            "url": url, "output": "json", "filter": "statuscode:200",
            "fl": "timestamp,original", "limit": 1,
        })
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list) or len(rows) < 2:
            return None
        ts, orig = rows[1][0], rows[1][1]
        return f"https://web.archive.org/web/{ts}id_/{orig}"


def _mirror_http_err(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


async def fetch_mirror_text(url: str, log=None) -> tuple[str, str] | None:
    """Miroir générique quand la page officielle est derrière un challenge.
    Jina d'abord (markdown structuré, meilleur pour les catalogues), Wayback
    ensuite. L'URL d'origine reste la source ; le miroir n'est qu'un lecteur."""
    log = log or (lambda m: None)
    if _is_mirror_url(url):
        return None

    for attempt in range(2):
        try:
            content, _ = await _fetch_bytes(f"https://r.jina.ai/{url}", UA_READER, 90)
            text = content.decode("utf-8", errors="replace")
            if text and len(text) >= 400 and not looks_blocked(text):
                log(f"miroir Jina: {len(text)} chars")
                return text, "N3-mirror-jina"
        except Exception as e:
            log(f"miroir Jina: indisponible ({_mirror_http_err(e)})")
            if attempt == 0:
                await asyncio.sleep(1.2)

    try:
        snap = await _wayback_snapshot_url(url)
        if snap:
            content, ctype = await _fetch_bytes(snap, UA_BROWSER, 45)
            if content[:5] == b"%PDF-" or "pdf" in ctype:
                text = await asyncio.to_thread(parse_pdf_text, content)
            else:
                parsed = await dual_parse_html(content.decode("utf-8", errors="replace"))
                text = parsed.get("text") or ""
            if text and len(text) >= 400 and not looks_blocked(text):
                log(f"miroir Wayback: {len(text)} chars")
                return text, "N3-mirror-wayback"
    except Exception as e:
        log(f"miroir Wayback: indisponible ({_mirror_http_err(e)})")
    return None


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
    # Un challenge Akamai dur n'est jamais résolu par Chromium : on passe au miroir.
    hard = looks_hard_challenge(out.get("text") or "", out.get("html") or "", out.get("title") or "")
    needs_render = (not out["is_pdf"]) and (out["blocked"] or len(out["text"]) < min_chars)
    if needs_render and allow_render and hard:
        log("challenge anti-bot dur — rendu Chromium sauté, tentative de miroir")
    if needs_render and allow_render and not hard:
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

    # Miroir générique : page officielle bloquée ou trop courte (challenge Akamai…).
    if (out["blocked"] or len(out["text"]) < min_chars) and not _is_mirror_url(url):
        mirrored = await fetch_mirror_text(url, log=log)
        if mirrored:
            text, level = mirrored
            out["text"] = text
            out["level"] = level
            out["blocked"] = False
            out["html"] = text if text.lstrip().startswith(("#", "Title:")) else out.get("html")

    if out["blocked"]:
        out["text"] = ""
        out["level"] = "blocked"
        return out

    if out["text"]:
        out["md5"] = hashlib.md5(out["text"].encode("utf-8")).hexdigest()
        if out["level"] == "failed":
            out["level"] = "N2-readability"
    return out
