"""
extract_core.py — Extraction hybride en cascade, 100 % locale et gratuite.

  N1/N2 (gratuit, ms)    : httpx direct + DOUBLE PARSING comparé
                           trafilatura ∥ Readability/BS4 (le plus riche gagne,
                           la similarité entre les deux est un signal de qualité)
  N3 (gratuit, local)    : rendu navigateur Playwright/Chromium (render_core)
                           pour les pages JavaScript et les challenges « soft ».
  Miroir                 : Jina ∥ TinyFish Fetch (si clé), puis Wayback.

Fournit aussi : filtrage SERP par regex (agrégateurs, réseaux sociaux, pages
interstitielles anti-bot), détection des pages de blocage (un challenge n'est
JAMAIS ingéré comme du contenu), métadonnées de page (og:image, liens externes)
et suivi sélectif des liens internes (depth=2 : /annuaire, /contacts…).
"""
import asyncio
import difflib
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import threading
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

# Désactivé pour les variants v1/v2 (SearXNG only) — TinyFish Fetch reste
# réservé au variant « tinyfish ». Défaut True pour ne pas casser le Swarm.
allow_tinyfish_fetch: ContextVar[bool] = ContextVar("allow_tinyfish_fetch", default=True)

import httpx
from bs4 import BeautifulSoup

# PyMuPDF n'est pas sûr dans le process API (crash natif « double free »).
# Extraction dans un sous-processus + cache disque sha256 → texte.
# Le sémaphore limite la RAM (gazettes jusqu'à 180 pages), ce n'est plus un
# verrou de sûreté : plusieurs PDF peuvent avancer en parallèle.
from app.config import BACKEND_DIR, DATA_DIR

PDF_CACHE_DIR = DATA_DIR / "cached_pdfs"
PDF_SUBPROCESS_TIMEOUT_S = 25
PDF_MAX_CONCURRENT = 3
_pdf_slots = threading.Semaphore(PDF_MAX_CONCURRENT)

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
# Couperet DUR : réseaux, OTA, dictionnaires, challenges — jamais une source PoE.
SERP_HARD_RE = re.compile(
    r"(tripadvisor|booking\.com|expedia|airbnb|pinterest|facebook\.com|instagram\.com"
    r"|youtube\.com|twitter\.com|/x\.com|linkedin\.com|reddit\.com|quora\.com"
    r"|hotels?\.com|kayak\.|skyscanner|cruisemapper|vesselfinder"
    r"|merriam-webster|dictionary\.com|thefreedictionary|cambridge\.org/(?:\w+/)?dictionary"
    r"|wiktionary|britannica\.com|wikihow|howtogeek|investopedia|linguee|wordreference"
    r"|vocabulary\.com|twominenglish|askdifference|factsinstitute"
    r"|guiahardware|stationx\.net|common-ports-cheat|ip-tracker\.org"
    r"|doordash\.com"
    r"|//unblock\.|\.unblock\.|/cdn-cgi/|captcha|datadome|perimeterx"
    r"|queue-it\.net|incapsula|distilnetworks"
    r"|\.docx?($|\?)|\.xlsx?($|\?)|\.pptx?($|\?)|\.zip($|\?)|\.exe($|\?))",
    re.I,
)

# Couperet SOUPLE : mots touristiques qui existent aussi sur des pages d'État
# (…/tourism-yacht-clearance). Un domaine officiel n'est pas jeté pour ça.
SERP_SOFT_RE = re.compile(
    r"(brochure|touris[mt]|baggage|luggage|duty.?free|/vts[-_/.]|vts.?manual)",
    re.I,
)

# Rétrocompat Swarm / tests : dur + souple (sans protection de domaine).
SERP_EXCLUDE_RE = re.compile(
    r"(?:%s)|(?:%s)" % (SERP_HARD_RE.pattern, SERP_SOFT_RE.pattern),
    re.I,
)

_OFFICIAL_URL_RE = re.compile(
    r"gov|gouv|gob|douane|customs|aduana|zoll|immigration|border|"
    r"maritime|port.?authority|coast.?guard|admin",
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


def looks_official_url(url: str) -> bool:
    """Domaine ou chemin qui sent l'État / la douane (pas une preuve, un filet)."""
    return bool(url and _OFFICIAL_URL_RE.search(url))


def serp_drop_reason(url: str, extra_re=None, protect: bool = False) -> str | None:
    """Pourquoi jeter cette URL, ou None pour la garder. Auditable."""
    if not (url or "").startswith("http"):
        return "not_http"
    if SERP_HARD_RE.search(url):
        return "hard"
    if extra_re and extra_re.search(url):
        return "extra"
    if SERP_SOFT_RE.search(url) and not (protect or looks_official_url(url)):
        return "soft_tourism"
    return None


def audit_serp_filter(results: list[dict], url_key: str = "url", extra_re=None,
                      protect_fn=None) -> list[dict]:
    """Journal {url, kept, reason} — pour relire ce que le filtre a fait."""
    out = []
    for r in results:
        u = r.get(url_key) or ""
        protect = bool(protect_fn(u)) if protect_fn else looks_official_url(u)
        reason = serp_drop_reason(u, extra_re=extra_re, protect=protect)
        out.append({"url": u, "kept": reason is None, "reason": reason,
                    "protected": protect})
    return out


def serp_filter(results: list[dict], url_key: str = "url", extra_re=None,
                protect_fn=None) -> list[dict]:
    """Rejette les URLs non pertinentes. Un domaine d'État n'est jamais
    écarté pour un mot touristique dans le chemin."""
    out = []
    for r in results:
        u = r.get(url_key) or ""
        protect = bool(protect_fn(u)) if protect_fn else looks_official_url(u)
        if serp_drop_reason(u, extra_re=extra_re, protect=protect) is None:
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
def pdf_cache_key(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _pdf_cache_path(digest: str) -> Path:
    return Path(PDF_CACHE_DIR) / f"{digest}.txt"


def _read_pdf_cache(digest: str) -> str | None:
    path = _pdf_cache_path(digest)
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    except OSError:
        return None
    return None


def _write_pdf_cache(digest: str, text: str) -> None:
    cache_dir = Path(PDF_CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _pdf_cache_path(digest)
    tmp = cache_dir / f".{digest}.txt.partial"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _pdf_worker_env() -> dict:
    env = os.environ.copy()
    backend = str(BACKEND_DIR)
    current = env.get("PYTHONPATH", "")
    parts = [p for p in current.split(os.pathsep) if p]
    if backend not in parts:
        env["PYTHONPATH"] = os.pathsep.join([backend, *parts]) if parts else backend
    return env


def _run_pdf_worker(inp: str, out: str, max_pages: int) -> None:
    """Spawn ``app.core.pdf_worker`` — hookable depuis les tests."""
    proc = subprocess.run(
        [sys.executable, "-m", "app.core.pdf_worker", inp, out, str(max_pages)],
        timeout=PDF_SUBPROCESS_TIMEOUT_S,
        capture_output=True,
        env=_pdf_worker_env(),
        cwd=str(BACKEND_DIR),
    )
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace")[:300]
        raise RuntimeError(f"pdf_worker exit {proc.returncode}: {err}")


def parse_pdf_text(content: bytes, max_pages: int = 180) -> str:
    """Extrait le texte d'un PDF hors process, avec cache sha256 sur disque.

    Le process API n'importe pas ``fitz`` : un crash natif reste confiné au
    sous-processus. Un hit cache évite tout spawn (gazettes rejouées).
    """
    if not content:
        return ""
    digest = pdf_cache_key(content)
    cached = _read_pdf_cache(digest)
    if cached is not None:
        return cached
    with _pdf_slots:
        cached = _read_pdf_cache(digest)
        if cached is not None:
            return cached
        fd, inp = tempfile.mkstemp(suffix=".pdf")
        out = inp + ".txt"
        try:
            os.write(fd, content)
            os.close(fd)
            fd = -1
            _run_pdf_worker(inp, out, max_pages)
            text = Path(out).read_text(encoding="utf-8")
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
            for p in (inp, out):
                try:
                    os.unlink(p)
                except OSError:
                    pass
    try:
        _write_pdf_cache(digest, text)
    except OSError:
        pass
    return text


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
        if any(p in path for p in patterns) and href not in seen and not SERP_HARD_RE.search(href):
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
# Chemin seulement — « douane » / « customs » dans le hostname matchent
# toutes les brochures d'une home douanes (leçon France : 31 PDF anglais).
_LIST_PDF_PATH_RE = re.compile(
    r"liste|listen|plaisance|eligibles|ppf|puerto|terminal|habilit|"
    r"port.?of.?entry|ports.?of.?entry|ports-entree|portos-de-entrada|"
    r"points-d-entree|points-of-entry|designat|gazett|legislat|"
    r"decreto|decret|arrete|clearance",
    re.I,
)
_JUNK_PDF_PATH_RE = re.compile(
    r"formulaire|immigration|export|brexit|travellers?|tax-refund|"
    r"leaflet|brochure|results-en|counterfeit",
    re.I,
)
_YEAR_IN_PATH_RE = re.compile(r"/20(\d{2})/")


def looks_hard_challenge(text: str = "", html: str = "", title: str = "") -> bool:
    """Challenge Akamai / « Challenge Validation » : Chromium n'y peut rien."""
    probe = " ".join(p for p in (title or "", (text or "")[:2000], (html or "")[:4000]) if p)
    return bool(probe and HARD_CHALLENGE_RE.search(probe))


def looks_like_port_catalog(text: str) -> bool:
    """Vrai catalogue (coords ou décret numéroté), pas une loi quelconque
    qui contient « 1. Article »."""
    if not text:
        return False
    from app.core.run_rules import get_rule
    lat_hits = len(re.findall(r"latitud(?:e)?\s*:", text, re.I))
    lat_need = int(get_rule("formalities.catalog_lat_hits", 8))
    if lat_hits >= lat_need:
        return True
    if _CATALOG_MARKERS_RE.search(text) and (text.count(".-") >= lat_need or lat_hits >= 3):
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


def catalog_ports_with_coords(ports: list | None) -> list[dict]:
    """Sous-ensemble catalogue qui a réellement lat/lon dans la source."""
    return [
        p for p in (ports or [])
        if p.get("lat") is not None and p.get("lon") is not None
    ]


def catalog_is_sufficient(ports: list | None, text: str = "") -> bool:
    """Skip LLM seulement si le parseur a lu une vraie table (noms + coords).

    - ≥ 3 ports avec lat/lon (catalogue type SCT) ;
    - ou looks_like_port_catalog + ≥ 1 port coordonné.
    Un décompte de fragments (« port de X », phrases) ne suffit plus :
    Haiku doit lire ces pages. Au skip, ne renvoyer que les ports coordonnés.
    """
    if not ports:
        return False
    from app.core.run_rules import get_rule
    with_coords = len(catalog_ports_with_coords(ports))
    min_coords = int(get_rule("formalities.catalog_min_coords", 3))
    like_min = int(get_rule("formalities.catalog_looks_like_min_coords", 1))
    if with_coords >= min_coords:
        return True
    return bool(looks_like_port_catalog(text or "") and with_coords >= like_min)


_JUNK_NAME_RE = re.compile(
    r"\b(moet|worden|ingediend|ligt|binnenkomst|uniforme|armes|"
    r"continuously|conducted|described|consists)\b",
    re.I,
)
_GEOCODE_STOP = frozenset({
    "the", "and", "or", "of", "a", "an", "to", "for", "in", "on",
    "de", "het", "van", "een", "is", "la", "le", "les", "du", "des",
    "un", "une", "et", "ou", "el", "los", "las", "y",
})

# Raison sociale / autorité portuaire — pas « port of / port de » (Port of Spain).
_CORPORATE_PORT_PREFIXES = (
    "ports autonomes de ", "ports autonomes d'",
    "port autonome de ", "port autonome d'",
    "autorité portuaire de ", "autorite portuaire de ",
    "autoridad portuaria de ", "port authority of ",
    "office portuaire de ",
)


def geocode_query_name(name: str) -> str:
    """Toponyme à géocoder : Nouméa, pas « Port autonome de Nouméa ».

    Ne strippe pas « port of / port de / puerto de » — « Port of Spain »
    resterait « Spain ».
    """
    n = (name or "").strip()
    low = n.lower()
    for p in _CORPORATE_PORT_PREFIXES:
        if low.startswith(p):
            rest = n[len(p):].strip(" \t-–,")
            return rest or n
    return n


def is_geocodeable_name(name: str, geocodeable=None) -> bool:
    """False → ne pas appeler Nominatim/GeoNames (fragment, pas un toponyme).

    `geocodeable is False` (flag LLM) gagne toujours. Un filet local recale
    les phrases type canari NL/CI même si le flag est absent ou True.
    La raison sociale « Port autonome de … » est jugée sur l'alias listing.
    """
    if geocodeable is False:
        return False
    n = geocode_query_name(name or "")
    if len(n) < 2 or len(n) > 80:
        return False
    if _JUNK_NAME_RE.search(n):
        return False
    tokens = re.findall(r"[^\W\d_]+", n, flags=re.UNICODE)
    if not tokens:
        return False
    if all(t.casefold() in _GEOCODE_STOP for t in tokens):
        return False
    caps = sum(1 for t in tokens if t[:1].isupper())
    if len(tokens) >= 3 and caps == 0:
        return False
    return True


def _pdf_path(url: str) -> str:
    return unquote(urlparse(url or "").path or "")


def _pdf_recency_bonus(path: str) -> int:
    """Préfère le millésime courant à une carte PPF de 2022 encore en lien."""
    years = [2000 + int(y) for y in _YEAR_IN_PATH_RE.findall(path or "")]
    if years:
        return max(0, max(years) - 2020)
    if "/uploads/" in (path or "").lower():
        return 4
    return 0


def _pdf_list_score(url: str) -> int:
    """Score le chemin du PDF, jamais le hostname (douane.gouv.fr ≠ liste)."""
    path = _pdf_path(url)
    if not path:
        return 0
    score = 0
    if _LIST_PDF_PATH_RE.search(path):
        score += 2
    low = path.lower()
    for tok, pts in (
        ("plaisance", 3), ("eligibles", 2), ("ppf", 2), ("liste", 2),
        ("habilit", 2), ("ports-entree", 2), ("port-of-entry", 2),
    ):
        if tok in low:
            score += pts
    if _JUNK_PDF_PATH_RE.search(path):
        score -= 4
    score += _pdf_recency_bonus(path)
    return score


def official_attachments(text: str, base_url: str, limit: int = 4) -> list[str]:
    """PDF officiels liés depuis une page d'État (pièce jointe de liste, décret).

    On ne garde que les PDF dont le *chemin* ressemble à une liste. Un PDF
    « 10-questions-before-exporting-en.pdf » sur douane.gouv.fr n'en est pas une.
    """
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
        if SERP_HARD_RE.search(u):
            continue
        host = (urlparse(u).hostname or "").lower()
        score = _pdf_list_score(u)
        if host != base_host and score <= 0:
            continue
        if score <= 0:
            continue
        seen.add(u)
        scored.append((-score, u))
    scored.sort()
    return [u for _, u in scored[:limit]]


def should_follow_attachments(text: str, url: str) -> bool:
    """Suivre un PDF même si la page est déjà longue (leçon SCT : la liste
    est souvent le fichier lié, pas le HTML)."""
    blob = (text or "")[:4000]
    path = _pdf_path(url)
    if (looks_like_port_catalog(text or "")
            or bool(_CATALOG_MARKERS_RE.search(blob))
            or bool(_LIST_PDF_PATH_RE.search(path))):
        return True
    # Page sans marqueur catalogue, mais un PDF « liste / PPF » est déjà lié.
    return bool(url and official_attachments(text or "", url, limit=1))


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


def _mirror_usable(text: str | None) -> bool:
    return bool(text and len(text) >= 400 and not looks_blocked(text))


def _append_fetch_links(text: str, links: list | None) -> str:
    extra = [u for u in (links or []) if isinstance(u, str) and u.startswith("http")]
    if not extra:
        return text
    return (text or "") + "\n" + "\n".join(extra[:20])


def _arbitrate_mirror_texts(jina_text: str | None, tf_text: str | None) -> tuple[str, str, dict] | None:
    """Jina ∥ TinyFish Fetch : challenge écarté, catalogue gagne, sinon le plus long."""
    j_ok = _mirror_usable(jina_text)
    t_ok = _mirror_usable(tf_text)
    sim = _parse_similarity(jina_text or "", tf_text or "") if (j_ok and t_ok) else None
    compare = {
        "jina_chars": len(jina_text or ""),
        "tf_chars": len(tf_text or ""),
        "similarity": sim,
        "winner": None,
        "catalog": None,
    }
    if j_ok and t_ok:
        j_cat = looks_like_port_catalog(jina_text or "")
        t_cat = looks_like_port_catalog(tf_text or "")
        compare["catalog"] = {"jina": j_cat, "tinyfish": t_cat}
        if j_cat != t_cat:
            winner, text = ("tinyfish", tf_text) if t_cat else ("jina", jina_text)
        elif sim is not None and sim < 0.55 and (j_cat or t_cat):
            winner, text = ("tinyfish", tf_text) if t_cat else ("jina", jina_text)
        else:
            winner, text = (("tinyfish", tf_text)
                            if len(tf_text or "") >= len(jina_text or "")
                            else ("jina", jina_text))
        compare["winner"] = winner
        level = "N3-mirror-tinyfish" if winner == "tinyfish" else "N3-mirror-jina"
        return text, level, compare
    if t_ok:
        compare["winner"] = "tinyfish"
        return tf_text, "N3-mirror-tinyfish", compare
    if j_ok:
        compare["winner"] = "jina"
        return jina_text, "N3-mirror-jina", compare
    return None


async def _jina_mirror_text(url: str, log) -> str | None:
    for attempt in range(2):
        try:
            content, _ = await _fetch_bytes(f"https://r.jina.ai/{url}", UA_READER, 90)
            text = content.decode("utf-8", errors="replace")
            if _mirror_usable(text):
                log(f"miroir Jina: {len(text)} chars")
                return text
            if text:
                log(f"miroir Jina: texte inutilisable ({len(text)} chars)")
        except Exception as e:
            log(f"miroir Jina: indisponible ({_mirror_http_err(e)})")
            if attempt == 0:
                await asyncio.sleep(1.2)
    return None


async def _tinyfish_mirror_text(url: str, log) -> tuple[str | None, list]:
    from app.core.tinyfish import tf_api_key, tf_fetch
    key = tf_api_key()
    if not key:
        return None, []
    try:
        recs = await tf_fetch([url], key, ttl=0, links=True, log=log)
    except Exception as e:
        log(f"miroir TinyFish: échec ({type(e).__name__})")
        return None, []
    rec = recs.get(url) or {}
    if rec.get("blocked"):
        log("miroir TinyFish: bot_blocked — contenu invalidé")
        return None, []
    text = rec.get("text") or ""
    links = rec.get("links") or []
    text = _append_fetch_links(text, links)
    if not _mirror_usable(text):
        return None, links
    log(f"miroir TinyFish: {len(text)} chars")
    return text, links


async def _wayback_mirror_text(url: str, log) -> str | None:
    try:
        snap = await _wayback_snapshot_url(url)
        if snap:
            content, ctype = await _fetch_bytes(snap, UA_BROWSER, 45)
            if content[:5] == b"%PDF-" or "pdf" in ctype:
                text = await asyncio.to_thread(parse_pdf_text, content)
            else:
                parsed = await dual_parse_html(content.decode("utf-8", errors="replace"))
                text = parsed.get("text") or ""
            if _mirror_usable(text):
                log(f"miroir Wayback: {len(text)} chars")
                return text
    except Exception as e:
        log(f"miroir Wayback: indisponible ({_mirror_http_err(e)})")
    return None


async def fetch_mirror_text(url: str, log=None) -> tuple[str, str] | None:
    """Miroir générique quand la page officielle est derrière un challenge.
    Jina ∥ TinyFish Fetch (si clé), Wayback ensuite. L'URL d'origine reste
    la source ; le miroir n'est qu'un lecteur.

    Retourne (texte, level) — compare optionnelle en 3e élément si arbitrage."""
    log = log or (lambda m: None)
    if _is_mirror_url(url):
        return None

    from app.core.tinyfish import tf_api_key
    if allow_tinyfish_fetch.get() and tf_api_key():
        jina_text, tf_pair = await asyncio.gather(
            _jina_mirror_text(url, log),
            _tinyfish_mirror_text(url, log),
        )
        tf_text, _links = tf_pair if isinstance(tf_pair, tuple) else (None, [])
        picked = _arbitrate_mirror_texts(jina_text, tf_text)
        if picked:
            return picked
    else:
        jina_text = await _jina_mirror_text(url, log)
        if _mirror_usable(jina_text):
            return jina_text, "N3-mirror-jina"

    wb = await _wayback_mirror_text(url, log)
    if wb:
        return wb, "N3-mirror-wayback"
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
           "html": None, "blocked": False, "render_used": False, "parse": None,
           "fetch_compare": None}

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
            text, level = mirrored[0], mirrored[1]
            out["text"] = text
            out["level"] = level
            out["blocked"] = False
            out["html"] = text if text.lstrip().startswith(("#", "Title:")) else out.get("html")
            if len(mirrored) > 2 and isinstance(mirrored[2], dict):
                out["fetch_compare"] = mirrored[2]

    if out["blocked"]:
        out["text"] = ""
        out["level"] = "blocked"
        return out

    if out["text"]:
        out["md5"] = hashlib.md5(out["text"].encode("utf-8")).hexdigest()
        if out["level"] == "failed":
            out["level"] = "N2-readability"
    return out
