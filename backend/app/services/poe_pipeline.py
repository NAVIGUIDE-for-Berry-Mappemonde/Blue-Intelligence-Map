"""
poe.py — Pipeline souverain [ZEE / Pays] -> [Ports d'Entrée plaisance].

Architecture :
  1. Délimitation ZEE      : VLIZ Marine Regions WFS (World EEZ v12, ~285 zones), simplifié shapely.
  2. Recherche ciblée      : SearXNG ∥ TinyFish Search (gratuits) -> filet
                             include_domains si discordance / 0 officiel ->
                             recherche groundée (OpenRouter :online) en dernier
                             + Level-2 Retry Query (organisation douanière).
  3. Whitelist automatique : ISO 3166-1 alpha-2 x motifs d'État validés PSL (tldextract)
                             + exceptions.json auto-enrichi + filtrage SERP regex (extract_core).
  4. Collecte & parsing    : cascade hybride extract_core — N1 httpx+trafilatura/PyMuPDF ->
                             N2 Readability/BS4 -> N3 TinyFish (1 seul appel max/zone, dernier recours).
                             Depth=2 sélectif sur liens internes réglementaires.
  5. Extraction structurée : llm_core (OpenRouter, JSON strict)
                             + RAG local (rag_core) sur les contextes longs.
  6. Géocodage             : geo_core (Nominatim -> GeoNames, re-ranking sémantique).
                             Validation spatiale point-in-EEZ (shapely).
  7. Monitoring            : hash MD5 + similarité sémantique (skip si changement mineur).
  8. Stockage              : upsert non-destructif via dedup_core (les enrichissements
                             Bottom-Up osm_confidence / anomalies sont préservés).
"""
import asyncio
import fcntl
import json
import os
import re
import threading
import time
import uuid

import httpx
import pycountry
import tldextract
from shapely.geometry import shape, mapping
from shapely.prepared import prep
from urllib.parse import urlparse, urlunparse

from app.core.dedup import deduplicate_list, find_duplicate_in_list, merge_docs, normalize_name, text_similarity
from app.core.events import ZoneRecorder, emit
from app.core.extract import (
    catalog_is_sufficient, extract_cascade, extract_structured_ports,
    internal_followups, looks_like_port_catalog, official_attachments,
    serp_filter, should_follow_attachments,
)
from app.core.geo import geocode_port_dual, point_in_eez
from app.core.llm import extract_ports, grounded_search
from app.core.rag import select_context, semantic_similarity

from app.config import DATA_DIR as DATA

EXCEPTIONS_FILE = DATA / "poe_exceptions.json"
MAP_FILE = DATA / "eez_world_map.geojson"

WFS_URL = "https://geo.vliz.be/geoserver/MarineRegions/wfs"
WFS_PAGE = 10
UA = "BerryMappemonde-BlueIntelligence/1.0 (+https://berrymappemonde.org; contact: clementfilisetti@berrymappemonde.org)"
EEZ_ATTRIBUTION = "Flanders Marine Institute — Marine Regions, Maritime Boundaries v12 (CC-BY 4.0)"

STALE_DAYS = 180
SIMPLIFY_STORE = 0.03
SIMPLIFY_MAP = 0.06

# Offline Public Suffix List snapshot (bundled with tldextract) — no network at import.
_tld = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=str(DATA / ".tld_cache"))

GOV_LABELS = ["gov", "gouv", "gob", "go", "govt", "gub", "gv"]
OFFICIAL_TOKENS = re.compile(
    r"gov|gouv|gob|douane|customs|aduana|zoll|immigration|border|maritime|port.?authority|coast.?guard|admin",
    re.I,
)

SEARX_PUBLIC_INSTANCES = [
    "https://searx.be",
    "https://search.inetol.net",
    "https://priv.au",
    "https://searx.tiekoetter.com",
    "https://paulgo.io",
    "https://search.sapti.me",
]

PIPELINE_VARIANTS = ("v1", "v2", "tinyfish")
_VARIANT_ALIASES = {
    "searx_only": "v2", "searx": "v2", "tf": "tinyfish", "v3": "tinyfish",
}


def normalize_variant(value: str | None) -> str:
    """v1 = SearXNG séquentiel ; v2 = SearXNG parallèle ; tinyfish = union."""
    raw = (value or "tinyfish").strip().lower()
    v = _VARIANT_ALIASES.get(raw, raw)
    if v not in PIPELINE_VARIANTS:
        raise ValueError(
            f"variant inconnue {value!r} — attendu {PIPELINE_VARIANTS}")
    return v


def searx_instances() -> list[str]:
    """Instance SearXNG auto-hébergée (SEARXNG_URL, cf. infra/searxng/) en tête,
    instances publiques en secours."""
    own = (os.environ.get("SEARXNG_URL") or "").strip().rstrip("/")
    return ([own] if own else []) + SEARX_PUBLIC_INSTANCES


# ---------------------------------------------------------------------------
# Matrice de recherche multilingue par ZEE (génération de requêtes localisées)
# ---------------------------------------------------------------------------
LANG_BY_ISO2 = {
    # fr
    "FR": "fr", "MC": "fr", "BE": "fr", "SN": "fr", "CI": "fr", "CM": "fr", "GA": "fr",
    "MG": "fr", "DJ": "fr", "KM": "fr", "BJ": "fr", "TG": "fr", "GN": "fr", "CG": "fr", "CD": "fr", "HT": "fr",
    # es
    "ES": "es", "MX": "es", "AR": "es", "CL": "es", "PE": "es", "CO": "es", "EC": "es",
    "VE": "es", "UY": "es", "PA": "es", "CR": "es", "GT": "es", "HN": "es", "NI": "es",
    "SV": "es", "DO": "es", "CU": "es", "GQ": "es",
    # pt
    "PT": "pt", "BR": "pt", "AO": "pt", "MZ": "pt", "CV": "pt", "GW": "pt", "ST": "pt", "TL": "pt",
    # ar
    "MA": "ar", "DZ": "ar", "TN": "ar", "LY": "ar", "EG": "ar", "SA": "ar", "AE": "ar",
    "QA": "ar", "KW": "ar", "BH": "ar", "OM": "ar", "YE": "ar", "JO": "ar", "LB": "ar", "SY": "ar", "IQ": "ar", "SD": "ar",
    # autres
    "ID": "id", "IT": "it", "GR": "el", "TR": "tr", "RU": "ru", "CN": "zh", "JP": "ja",
    "DE": "de", "NL": "nl", "TH": "th", "VN": "vi", "KR": "ko",
}
QUERY_TEMPLATES = {
    "fr": "ports d'entrée officiels liste douane décret désignés {name}",
    "es": "puertos habilitados puertos de entrada oficiales decreto aduana lista {name}",
    "pt": "portos de entrada oficiais lista alfândega decreto designados {name}",
    "ar": "موانئ الدخول الرسمية قائمة الجمارك مرسوم {name}",
    "id": "pelabuhan masuk resmi daftar bea cukai keputusan {name}",
    "it": "porti di ingresso ufficiali elenco dogana decreto {name}",
    "el": "επίσημα λιμάνια εισόδου κατάλογος τελωνείο διάταγμα {name}",
    "tr": "resmi giriş limanları liste gümrük kararname {name}",
    "ru": "официальные порты въезда список таможня указ {name}",
    "zh": "官方入境港口 名单 海关 法令 {name}",
    "ja": "公式入国港 一覧 税関 政令 {name}",
    "de": "offizielle Eingangshäfen Liste Zoll Verordnung {name}",
    "nl": "officiële havens van binnenkomst lijst douane besluit {name}",
    "th": "ท่าเรือเข้าเมืองอย่างเป็นทางการ รายชื่อ ศุลกากร {name}",
    "vi": "cảng nhập cảnh chính thức danh sách hải quan nghị định {name}",
    "ko": "공식 입국 항구 목록 세관 법령 {name}",
}

_LIST_URL_TOKENS = (
    "port-of-entry", "ports-of-entry", "habilit", "puertos", "designated",
    "decreto", "gazette", "customs", "douane", "aduana", "legislat",
    "portos-de-entrada", "ports-entree",
)


def localized_query(zone: dict) -> str | None:
    """Requête traduite dans la langue cible de la ZEE (matrice multilingue)."""
    lang = LANG_BY_ISO2.get((zone.get("sov_iso2") or zone.get("iso2") or "").upper())
    tpl = QUERY_TEMPLATES.get(lang or "")
    return tpl.format(name=zone.get("name") or zone.get("geoname") or "") if tpl else None


# ---------------------------------------------------------------------------
# Qualification juridique UNCLOS des ZEE sans PoE (logique métier)
# ---------------------------------------------------------------------------
UNINHABITED_RE = re.compile(
    r"bouvet|heard|mcdonald|clipperton|crozet|kerguelen|amsterdam|saint.?paul"
    r"|south georgia|sandwich|peter i|baker|howland|jarvis|johnston|kingman"
    r"|palmyra|wake|navassa|ashmore|cartier|coral sea|macquarie|prince edward isl"
    r"|tromelin|europa|glorioso|glorieuses|juan de nova|bassas da india|chagos"
    r"|clipperton|midway|paracel|spratly|scarborough|matthew|hunter"
    r"|abu musa|tunb|enenkio",
    re.I,
)


def qualify_unclos(zone: dict) -> dict | None:
    """Catégorise une ZEE dépourvue de PoE physique selon le droit maritime.
    Retourne None si la zone possède des PoE (aucune qualification requise)."""
    if (zone.get("poe_count") or 0) > 0:
        return None
    name = f"{zone.get('name') or ''} {zone.get('geoname') or ''}"
    pol = (zone.get("pol_type") or "").lower()
    anchor = zone.get("anchor") or [0, 0]
    lat = anchor[1] if len(anchor) > 1 else 0
    if lat < -60:
        return {"code": "antarctic", "basis": "Traité sur l'Antarctique art. VI"}
    if "overlapping" in pol:
        return {"code": "overlapping_claim", "basis": "UNCLOS art. 74/83"}
    if "joint" in pol:
        return {"code": "joint_regime", "basis": "UNCLOS art. 74(3)/83(3)"}
    if UNINHABITED_RE.search(name):
        return {"code": "uninhabited", "basis": "UNCLOS art. 2 & 25"}
    return {"code": "sovereign_entry", "basis": "UNCLOS art. 17-19"}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def is_stale(doc: dict) -> bool:
    g = doc.get("generated_at")
    if not g:
        return False
    try:
        gen = time.mktime(time.strptime(g[:19], "%Y-%m-%dT%H:%M:%S"))
        return (time.time() - gen) > STALE_DAYS * 86400
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Whitelist / Gatekeeper
# ---------------------------------------------------------------------------
_exceptions_thread_lock = threading.Lock()

_EXCEPTION_BUCKETS = ("manual", "auto", "seed_urls", "search_hints")


def _empty_exceptions() -> dict:
    return {"manual": {}, "auto": {}}


def _parse_exceptions_text(raw: str) -> dict:
    if not (raw or "").strip():
        return _empty_exceptions()
    data = json.loads(raw)
    return data if isinstance(data, dict) else _empty_exceptions()


def _merge_bucket(base: dict | None, incoming: dict | None) -> dict:
    out = {k: list(v) for k, v in (base or {}).items() if isinstance(v, list)}
    for key, vals in (incoming or {}).items():
        cur = out.setdefault(key, [])
        for item in vals or []:
            if item not in cur:
                cur.append(item)
    return out


def merge_exceptions(disk: dict, incoming: dict) -> dict:
    """Union des buckets (auto / seed_urls / …) pour ne pas perdre un
    bootstrap concurrent. Les clés hors buckets sont reprises du disque
    puis écrasées par l'entrant s'il les porte."""
    merged = dict(disk or {})
    merged.update({k: v for k, v in (incoming or {}).items()
                   if k not in _EXCEPTION_BUCKETS})
    for bucket in _EXCEPTION_BUCKETS:
        merged[bucket] = _merge_bucket((disk or {}).get(bucket),
                                       (incoming or {}).get(bucket))
    return merged


def load_exceptions() -> dict:
    try:
        with _exceptions_thread_lock:
            if not EXCEPTIONS_FILE.is_file():
                return _empty_exceptions()
            with open(EXCEPTIONS_FILE, "r", encoding="utf-8") as fh:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
                    return _parse_exceptions_text(fh.read())
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception:
        return _empty_exceptions()


def seed_url_candidates(zone: dict, exceptions: dict | None = None) -> list[dict]:
    """URLs officielles épinglées (page ou PDF d'État — jamais une liste de noms)."""
    exc = exceptions or load_exceptions()
    urls: list[str] = []
    for cc in (zone.get("iso2"), zone.get("sov_iso2")):
        if not cc:
            continue
        urls.extend((exc.get("seed_urls") or {}).get(cc.upper()) or [])
    seen, out = set(), []
    for u in urls:
        if not u or u in seen:
            continue
        seen.add(u)
        out.append({"url": u, "domain": domain_of(u)})
    return out


def default_search_hints(zone: dict) -> list[str]:
    """Leçon Niue / Mexique, pour TOUTE ZEE : loi douanière + liste désignée.
    Jamais un nom de port — seulement le souverain et des termes génériques."""
    sov = (zone.get("sovereign") or zone.get("name") or zone.get("geoname") or "").strip()
    if not sov:
        return []
    return [f"{sov} customs act designated ports of entry official legislation gazette"]


def search_hint_queries(zone: dict, exceptions: dict | None = None) -> list[str]:
    """Requêtes supplémentaires pour chaque ZEE (défauts + exceptions pays)."""
    exc = exceptions or load_exceptions()
    seen, out = set(), []
    for q in default_search_hints(zone):
        if q not in seen:
            seen.add(q)
            out.append(q)
    for cc in (zone.get("iso2"), zone.get("sov_iso2")):
        for q in (exc.get("search_hints") or {}).get((cc or "").upper(), []) or []:
            q = (q or "").strip()
            if q and q not in seen:
                seen.add(q)
                out.append(q)
    return out[:3]


def list_url_bonus(url: str) -> float:
    """Priorise les pages qui ressemblent à une liste officielle (leçon SCT)."""
    u = (url or "").lower()
    return sum(0.15 for tok in _LIST_URL_TOKENS if tok in u) + (0.1 if u.endswith(".pdf") else 0.0)


def remember_seed_urls(zone: dict, urls: list[str], exceptions: dict | None = None,
                       persist: bool = True, max_per_country: int = 4) -> list[str]:
    """Mémorise les URL officielles qui ont produit un catalogue — la prochaine
    ZEE du même pays n'attend plus le SERP (leçon Mexique / Niue généralisée)."""
    cc = (zone.get("iso2") or zone.get("sov_iso2") or "").upper()
    if not cc or not urls:
        return []
    exc = exceptions if exceptions is not None else load_exceptions()
    bucket = exc.setdefault("seed_urls", {}).setdefault(cc, [])
    added = []
    for u in urls:
        if not u or not str(u).startswith("http") or u in bucket:
            continue
        if not url_allowed(u, build_whitelist(zone.get("iso2"), zone.get("sov_iso2"), exc)):
            if not OFFICIAL_TOKENS.search(domain_of(u) or ""):
                continue
        if len(bucket) >= max_per_country:
            break
        bucket.append(u)
        added.append(u)
    if added and persist:
        save_exceptions(exc)
    return added


def urls_with_catalog(texts: list[str]) -> list[str]:
    out = []
    for block in texts or []:
        m = re.match(r"\[SOURCE: ([^\]]+)\]", (block or "").lstrip())
        if m and extract_structured_ports(block):
            out.append(m.group(1).strip())
    return out


def save_exceptions(exc: dict):
    """Écriture flock + merge-on-write : deux zones concurrentes n'écrasent
    plus leurs bootstraps respectifs (JSON corrompu ou domaines perdus)."""
    try:
        EXCEPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _exceptions_thread_lock:
            with open(EXCEPTIONS_FILE, "a+", encoding="utf-8") as fh:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                try:
                    fh.seek(0)
                    disk = _parse_exceptions_text(fh.read())
                    merged = merge_exceptions(disk, exc or {})
                    fh.seek(0)
                    fh.truncate()
                    json.dump(merged, fh, indent=2, ensure_ascii=False)
                    fh.write("\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                    if isinstance(exc, dict):
                        exc.clear()
                        exc.update(merged)
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass


def iso2_of(iso3: str | None) -> str | None:
    if not iso3:
        return None
    try:
        c = pycountry.countries.get(alpha_3=iso3.upper())
        return c.alpha_2 if c else None
    except Exception:
        return None


def _is_public_suffix(cand: str) -> bool:
    try:
        return _tld("x." + cand).suffix == cand
    except Exception:
        return False


def build_whitelist(iso2: str | None, sov_iso2: str | None, exceptions: dict | None = None) -> list[str]:
    """Croisement algorithmique code ISO x motifs d'État, validé par la PSL,
    + exceptions manuelles/auto-découvertes (par territoire ET par souverain)."""
    exc = exceptions or load_exceptions()
    out: set[str] = set()
    for cc in {c for c in (iso2, sov_iso2) if c}:
        low = cc.lower()
        for lbl in GOV_LABELS:
            cand = f"{lbl}.{low}"
            if _is_public_suffix(cand):
                out.add(cand)
        for bucket in ("manual", "auto"):
            for dom in (exc.get(bucket) or {}).get(cc.upper(), []):
                out.add(dom.lower())
    return sorted(out)


def url_allowed(url: str, whitelist: list[str]) -> bool:
    try:
        ext = _tld(url)
    except Exception:
        return False
    fqdn = ".".join(p for p in [ext.subdomain, ext.domain, ext.suffix] if p)
    for w in whitelist:
        if "." not in w:  # bare public suffix, e.g. "gov" (USA)
            if ext.suffix == w or ext.suffix.endswith("." + w):
                return True
        elif fqdn == w or fqdn.endswith("." + w):
            return True
    return False


def domain_of(url: str) -> str:
    try:
        ext = _tld(url)
        return ".".join(p for p in [ext.domain, ext.suffix] if p)
    except Exception:
        return ""


def is_foreign_gov_domain(domain: str, cc_ok: set[str]) -> bool:
    """Écarte un site régalien qui n'appartient pas à la ZEE (leçon Samoa :
    congress.gov / customs.gov.ph ne sont pas des sources samoanes)."""
    if not domain or not OFFICIAL_TOKENS.search(domain):
        return False
    suffix = domain.rsplit(".", 1)[-1].lower()
    if len(suffix) == 2 and suffix not in cc_ok:
        return True
    if suffix == "gov" and "us" not in cc_ok:
        return True
    return False


# ---------------------------------------------------------------------------
# 1. Référentiel ZEE (VLIZ WFS)
# ---------------------------------------------------------------------------
def _round_coords(obj, nd=3):
    if isinstance(obj, (list, tuple)):
        return [_round_coords(x, nd) for x in obj]
    if isinstance(obj, float):
        return round(obj, nd)
    return obj


def _simplify_for_mongo(geom):
    """Simplifie jusqu'à passer sous ~4 Mo sérialisés (limite Mongo 16 Mo)."""
    for tol in (SIMPLIFY_STORE, 0.08, 0.15, 0.3):
        simp = geom.simplify(tol, preserve_topology=True)
        gj = mapping(simp)
        gj["coordinates"] = _round_coords(gj["coordinates"], 4)
        if len(json.dumps(gj)) < 4_000_000:
            return gj, simp
    return gj, simp  # last attempt regardless


def _anchor_of(simp):
    """Point représentatif du plus grand composant — robuste à l'antiméridien."""
    try:
        geoms = list(simp.geoms) if hasattr(simp, "geoms") else [simp]
        big = max(geoms, key=lambda g: g.area)
        pt = big.representative_point()
        return [round(pt.x, 4), round(pt.y, 4)]
    except Exception:
        c = simp.centroid
        return [round(c.x, 4), round(c.y, 4)]


async def build_referential(db, state, force: bool = False):
    """Télécharge les ~285 ZEE mondiales (WFS paginé), simplifie, upsert Mongo,
    écrit le GeoJSON carte. Idempotent — préserve status/poe_count existants."""
    log = state.log
    exceptions = load_exceptions()
    async with httpx.AsyncClient(timeout=300, headers={"User-Agent": UA}) as client:
        base = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": "MarineRegions:eez", "outputFormat": "application/json",
            "srsName": "EPSG:4326", "sortBy": "mrgid",
        }
        r = await client.get(WFS_URL, params={**base, "count": 1, "propertyName": "mrgid"})
        r.raise_for_status()
        total = int(r.json().get("numberMatched") or 0)
        state.total = total
        log(f"VLIZ Marine Regions WFS: {total} ZEE mondiales à intégrer ({EEZ_ATTRIBUTION})")

        done = 0
        for start in range(0, total, WFS_PAGE):
            page = None
            for attempt in range(3):
                try:
                    r = await client.get(WFS_URL, params={**base, "count": WFS_PAGE, "startIndex": start})
                    r.raise_for_status()
                    page = r.json().get("features") or []
                    break
                except Exception as e:
                    log(f"page {start}: tentative {attempt + 1} échouée ({type(e).__name__}) — retry")
                    await asyncio.sleep(3)
            if page is None:
                raise RuntimeError(f"WFS page {start} unreachable after 3 attempts")

            for feat in page:
                props = feat.get("properties") or {}
                mrgid = props.get("mrgid")
                if not mrgid or not feat.get("geometry"):
                    continue

                def _work(f=feat):
                    g = shape(f["geometry"])
                    gj, simp = _simplify_for_mongo(g)
                    return gj, list(simp.bounds), _anchor_of(simp)

                gj, bbox, anchor = await asyncio.to_thread(_work)
                iso2 = iso2_of(props.get("iso_ter1"))
                sov2 = iso2_of(props.get("iso_sov1"))
                wl = build_whitelist(iso2, sov2, exceptions)
                base_doc = {
                    "mrgid": int(mrgid),
                    "geoname": props.get("geoname"),
                    "name": props.get("territory1") or props.get("geoname"),
                    "pol_type": props.get("pol_type"),
                    "iso_ter1": props.get("iso_ter1"),
                    "iso2": iso2,
                    "sovereign": props.get("sovereign1"),
                    "sov_iso2": sov2,
                    "area_km2": props.get("area_km2"),
                    "geometry": gj,
                    "bbox": bbox,
                    "anchor": anchor,
                    "whitelist": wl,
                    "updated_at": now_iso(),
                }
                await db.eez_zones.update_one(
                    {"mrgid": int(mrgid)},
                    {
                        "$set": base_doc,
                        "$setOnInsert": {
                            "_id": str(uuid.uuid4()), "status": "non_generee",
                            "poe_count": 0, "generated_at": None,
                            "sources": [], "source_hashes": {}, "last_error": None,
                        },
                    },
                    upsert=True,
                )
                done += 1
            state.progress = done
            log(f"{done}/{total} ZEE intégrées")

    # --- fichier carte (simplification supplémentaire) ---
    log("Construction du GeoJSON carte…")

    def _map_feature(doc):
        g = shape(doc["geometry"]).simplify(SIMPLIFY_MAP, preserve_topology=True)
        gj = mapping(g)
        gj["coordinates"] = _round_coords(gj["coordinates"], 3)
        return {
            "type": "Feature",
            "geometry": gj,
            "properties": {
                "mrgid": doc["mrgid"], "name": doc.get("name"),
                "geoname": doc.get("geoname"), "iso2": doc.get("iso2"),
                "sovereign": doc.get("sovereign"), "pol_type": doc.get("pol_type"),
            },
        }

    feats = []
    async for doc in db.eez_zones.find({}):
        feats.append(await asyncio.to_thread(_map_feature, doc))
    fc = {"type": "FeatureCollection", "attribution": EEZ_ATTRIBUTION, "features": feats}
    txt = await asyncio.to_thread(json.dumps, fc)
    MAP_FILE.write_text(txt, encoding="utf-8")
    log(f"GeoJSON carte écrit: {len(feats)} zones, {len(txt) // 1024} Ko")
    return {"zones": done, "map_file_kb": len(txt) // 1024}


# ---------------------------------------------------------------------------
# 2. Recherche : SearXNG -> recherche groundée (llm_core) + Level-2 Retry
# ---------------------------------------------------------------------------
async def search_searxng(query: str, log) -> list[dict]:
    for inst in searx_instances():
        local = inst.startswith("http://127.0.0.1") or inst.startswith("http://localhost")
        timeout = 20 if local else 8
        try:
            async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": UA}) as client:
                r = await client.get(f"{inst}/search", params={"q": query, "format": "json"})
                if r.status_code != 200:
                    continue
                ctype = (r.headers.get("content-type") or "").lower()
                if "json" not in ctype:
                    try:
                        payload = r.json()
                    except Exception:
                        continue
                else:
                    payload = r.json()
                results = (payload.get("results") or [])[:10]
                if results:
                    log(f"SearXNG {inst}: {len(results)} résultats")
                    return [{"url": x.get("url"), "domain": domain_of(x.get("url") or ""),
                             "engine": "searxng"} for x in results if x.get("url")]
        except Exception:
            continue
    log("SearXNG: aucune instance exploitable — bascule sur recherche groundée")
    return []


async def search_grounded(zone: dict, whitelist: list[str], log, query_override: str | None = None):
    """Recherche groundée via llm_core (OpenRouter :online)."""
    name = zone.get("name") or zone.get("geoname")
    hints = ", ".join(whitelist[:6]) if whitelist else "official government domains"
    prompt = query_override or (
        f"Find the OFFICIAL government sources (customs, immigration, maritime/port authority) that list "
        f"the designated ports of entry (clearance ports) for FOREIGN PLEASURE CRAFT / YACHTS in {name} "
        f"({zone.get('sovereign')}). Prefer official domains such as: {hints}. "
        f"List each official port of entry you find with its town, and cite the official URLs used."
    )
    return await grounded_search(prompt, log=log, domain_fn=domain_of)


def rank_candidates_ml(candidates: list[dict], log, scores_out: list | None = None) -> list[dict]:
    """Classifieur SERP (ml_core) : trie les candidats par probabilité de mener
    à une liste officielle de ports AVANT tout téléchargement, et écarte les
    scores très faibles quand des alternatives existent.
    scores_out (optionnel) reçoit [{url, domain, score}] pour le journal."""
    if len(candidates) < 2:
        return candidates
    try:
        from app.core.ml import predict_serp
        scored = []
        for c in candidates:
            s = (predict_serp(c.get("url") or "") or {}).get("score")
            c["score_serp"] = s
            scored.append((s, c))
    except Exception:
        return candidates
    if scores_out is not None:
        scores_out.extend({"url": c.get("url"), "domain": c.get("domain"), "score": s}
                          for s, c in scored)
    if all(s is None for s, _ in scored):
        return candidates
    scored.sort(key=lambda x: x[0] if x[0] is not None else 0.5, reverse=True)
    strong = [c for s, c in scored if s is None or s >= 0.1]
    ranked = strong if len(strong) >= 3 else [c for _, c in scored]
    dropped = len(scored) - len(ranked)
    top = ", ".join(f"{c.get('domain') or '?'}={s:.2f}" for s, c in scored[:3] if s is not None)
    log(f"classifieur SERP: priorisation avant téléchargement — {top}"
        + (f" ({dropped} écarté(s), score < 0.1)" if dropped else ""))
    return ranked


# ---------------------------------------------------------------------------
# 3. Collecte & parsing — cascade hybride N1/N2/N3 (extract_core)
# ---------------------------------------------------------------------------
async def fetch_and_parse(url: str, log) -> tuple[str | None, str | None]:
    """Retourne (texte, md5). Cascade N1/N2 + rendu Chromium local (gratuit).
    Une page bloquée (interstitiel anti-bot) est invalidée, jamais ingérée."""
    try:
        res = await extract_cascade(url, min_chars=200, log=log)
    except Exception as e:
        log(f"fetch {domain_of(url)}: échec ({type(e).__name__})")
        return None, None
    if res.get("blocked"):
        log(f"fetch {domain_of(url)}: page de blocage anti-bot — source invalidée")
        return None, None
    text = res["text"]
    if text:
        log(f"fetch {domain_of(url)}: {len(text)} chars via {res['level']} (md5 {(res['md5'] or '')[:8]}…)")
    return (text[:60000] if text else None), res["md5"]


# ---------------------------------------------------------------------------
# 4. Extraction PARALLÈLE comparée : LLM (OpenRouter) ∥ NER local (spaCy)
# ---------------------------------------------------------------------------
async def extract_ports_llm(context: str, zone: dict, log, rec=None,
                            catalog_text: str | None = None,
                            settings: dict | None = None) -> list[dict]:
    """LLM et NER local tournent EN PARALLÈLE sur le même contexte et leurs
    listes sont comparées port par port (plus de simple fallback) :
      - port vu par les deux  → extraction_agreement=True (signal de confiance) ;
      - port vu par le LLM seul → extraction_agreement=False (à recouper) ;
      - noms vus par le NER seul → journalisés comme candidats à vérifier ;
      - LLM indisponible → la liste NER devient le fallback (comportement conservé).
    Un catalogue officiel suffisant court-circuite le LLM (économie de crédits).
    """
    raw_catalog = catalog_text if catalog_text is not None else context
    catalog = extract_structured_ports(raw_catalog)
    if catalog_is_sufficient(catalog, raw_catalog):
        log(f"catalogue structuré suffisant ({len(catalog)} port(s)) — LLM sauté")
        await emit(rec, "extraction_compare", llm_n=None, ner_n=None,
                   catalog_n=len(catalog), fallback="catalog", skipped_llm=True)
        return catalog

    async def _llm():
        try:
            return await extract_ports(context, zone, settings=settings, log=log), None
        except Exception as e:
            return None, e

    async def _ner():
        try:
            from app.core.ml import extract_entities
            ents = await asyncio.to_thread(extract_entities, context[:20000])
            return [e["text"].strip()[:120] for e in ents if e["label"] == "PORT_NAME"]
        except Exception:
            return None  # NER indisponible (modèle absent) — signal neutre

    (llm_ports, llm_err), ner_names = await asyncio.gather(_llm(), _ner())
    ner_names = list(dict.fromkeys(ner_names)) if ner_names is not None else None

    if llm_ports is None:
        log(f"LLM: échec ({type(llm_err).__name__}: {str(llm_err)[:100]})")
        if catalog:
            log(f"catalogue structuré: {len(catalog)} port(s) lus dans la source (sans LLM)")
            await emit(rec, "extraction_compare", llm_n=None,
                       ner_n=(len(ner_names) if ner_names else 0),
                       catalog_n=len(catalog), fallback="catalog",
                       llm_error=str(llm_err)[:120])
            return catalog
        if ner_names:
            ports = [{"name": n, "city": None,
                      "note": "extraction NER locale (fallback sans LLM)",
                      "extraction_engine": "ner", "extraction_agreement": None}
                     for n in ner_names][:50]
            log(f"NER local: {len(ports)} port(s) extraits en fallback (sans LLM)")
            await emit(rec, "extraction_compare", llm_n=None, ner_n=len(ner_names),
                       fallback="ner", llm_error=str(llm_err)[:120])
            return ports
        await emit(rec, "extraction_compare", llm_n=None, ner_n=0,
                   fallback="none", llm_error=str(llm_err)[:120])
        return []

    # NER muet (modèle absent OU zéro entité détectée) → signal NEUTRE, pas un désaccord
    has_ner_signal = bool(ner_names)
    for p in llm_ports:
        p["extraction_engine"] = "llm"
        p["extraction_agreement"] = (
            any(text_similarity(p["name"], n) >= 0.6 for n in ner_names)
            if has_ner_signal else None
        )
    both = [p["name"] for p in llm_ports if p.get("extraction_agreement")]
    llm_only = [p["name"] for p in llm_ports if p.get("extraction_agreement") is False]
    ner_only = ([n for n in ner_names
                 if not any(text_similarity(n, p["name"]) >= 0.6 for p in llm_ports)]
                if has_ner_signal else [])
    if has_ner_signal:
        log(f"extraction comparée: {len(both)} port(s) confirmés LLM∩NER, "
            f"{len(llm_only)} LLM seul, {len(ner_only)} NER seul (candidats à vérifier)")
    await emit(rec, "extraction_compare", llm_n=len(llm_ports),
               ner_n=(len(ner_names) if ner_names is not None else None),
               both=both, llm_only=llm_only, ner_only=ner_only)
    if catalog:
        have = {normalize_name(p["name"]) for p in llm_ports}
        extra = []
        for c in catalog:
            key = normalize_name(c["name"])
            if not key or key in have:
                continue
            extra.append({**c, "extraction_agreement": None})
            have.add(key)
        if extra:
            log(f"catalogue structuré: {len(extra)} port(s) lus dans la source "
                f"(en plus des {len(llm_ports)} du LLM)")
            await emit(rec, "catalog_extract", n=len(extra),
                       names=[c["name"] for c in extra[:20]])
            llm_ports = llm_ports + extra
    return llm_ports


_normalize_name = normalize_name  # rétrocompat


# ---------------------------------------------------------------------------
# Pipeline complet pour UNE zone — orchestrateur + 5 étapes
# ---------------------------------------------------------------------------
async def _skip_if_unchanged(db, zone: dict, force: bool, log, rec=None) -> dict | None:
    """Étape 1 — Monitoring des sources CONNUES avant toute recherche.
    DOUBLE VERDICT PARALLÈLE : le hash MD5 et la similarité sémantique sont
    TOUS DEUX calculés et consignés pour chaque source (plus de cascade), puis
    une matrice de décision tranche :
      - MD5 identique                      → inchangé (skip) ;
      - MD5 différent, similarité >= 0.95  → changement cosmétique (skip, consigné) ;
      - similarité < 0.95 ou source K.O.   → ré-extraction complète.
    Retourne le doc zone (mis à jour) si la ré-extraction peut être sautée."""
    mrgid = int(zone["mrgid"])
    known_hashes = zone.get("source_hashes") or {}
    if force or not known_hashes or zone.get("status") not in ("ia", "ia_sans_source") or not zone.get("poe_count", 0):
        return None
    old_excerpts = zone.get("source_excerpts") or {}
    verdicts = []
    fresh_hashes = {}
    for url in list(known_hashes.keys())[:3]:
        text, md5 = await fetch_and_parse(url, log)
        md5_same = (md5 == known_hashes.get(url)) if md5 else None
        sim = None
        if text and old_excerpts.get(url):
            sim = round(semantic_similarity(old_excerpts[url], text), 4)
        verdicts.append({"url": url, "md5_same": md5_same, "semantic_sim": sim})
        if md5:
            fresh_hashes[url] = md5
        await emit(rec, "monitoring_source", url=url, md5_known=known_hashes.get(url),
                   md5_fresh=md5, md5_same=md5_same, semantic_sim=sim,
                   chars=len(text or ""))

    def _source_unchanged(v):
        if v["md5_same"] is True:
            return True
        return v["semantic_sim"] is not None and v["semantic_sim"] >= 0.95

    reachable = [v for v in verdicts if v["md5_same"] is not None or v["semantic_sim"] is not None]
    skip = bool(reachable) and all(_source_unchanged(v) for v in verdicts)
    if skip:
        cosmetic = [v["url"] for v in verdicts if v["md5_same"] is False]
        reason = "md5" if not cosmetic else "semantic"
        log("monitoring: sources inchangées "
            + ("(MD5 identiques)" if reason == "md5"
               else f"(MD5 modifiés mais similarité >= 0.95 : changement cosmétique sur {len(cosmetic)} source(s))")
            + " — ré-extraction sautée")
        await emit(rec, "monitoring_decision", skip=True, reason=reason, verdicts=verdicts)
        await db.eez_zones.update_one({"mrgid": mrgid}, {"$set": {
            "checked_at": now_iso(),
            "source_hashes": {**known_hashes, **fresh_hashes},
            "monitoring_verdicts": verdicts,
        }})
        return await db.eez_zones.find_one({"mrgid": mrgid})
    log("contenu source modifié ou source injoignable — pipeline complet relancé")
    await emit(rec, "monitoring_decision", skip=False, reason="changed_or_unreachable",
               verdicts=verdicts)
    return None


def _normalize_url(url: str) -> str:
    """Host lower, sans www., sans fragment, slash final retiré (query conservée)."""
    if not url or not isinstance(url, str):
        return ""
    try:
        p = urlparse(url.strip())
    except Exception:
        return url.strip().rstrip("/").lower()
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if p.port and p.port not in (80, 443):
        host = f"{host}:{p.port}"
    path = (p.path or "").rstrip("/")
    scheme = (p.scheme or "https").lower() or "https"
    return urlunparse((scheme, host, path, "", p.query or "", ""))


def _engine_set(c: dict) -> set[str]:
    e = c.get("engine")
    if isinstance(e, list):
        return {str(x) for x in e if x}
    if e:
        return {str(e)}
    return set()


def _merge_engines(*candidates: dict) -> str | list[str]:
    engines: set[str] = set()
    for c in candidates:
        engines |= _engine_set(c)
    if not engines:
        return "searxng"
    if len(engines) == 1:
        return next(iter(engines))
    return sorted(engines)


def _merge_candidates(*groups: list[dict]) -> list[dict]:
    """Union dédupliquée par URL normalisée (plusieurs chemins d'un domaine survivent)."""
    seen: dict[str, dict] = {}
    out: list[dict] = []
    for group in groups:
        for c in group or []:
            u = c.get("url")
            if not u:
                continue
            key = _normalize_url(u)
            if not key:
                continue
            if key in seen:
                prev = seen[key]
                prev["engine"] = _merge_engines(prev, c)
                for field in ("title", "snippet", "score_serp"):
                    if prev.get(field) in (None, "") and c.get(field) not in (None, ""):
                        prev[field] = c[field]
                continue
            item = dict(c)
            item["url"] = u
            item["domain"] = item.get("domain") or domain_of(u)
            seen[key] = item
            out.append(item)
    return out


def _best_per_domain(candidates: list[dict]) -> list[dict]:
    """Un URL par domaine après scoring (list_url_bonus + score SERP)."""
    best: dict[str, tuple[float, dict]] = {}
    order: list[str] = []
    for c in candidates or []:
        d = c.get("domain") or domain_of(c.get("url") or "")
        if not d:
            continue
        serp = c.get("score_serp")
        score = list_url_bonus(c.get("url") or "") + (serp if serp is not None else 0.5)
        prev = best.get(d)
        if prev is None:
            order.append(d)
            best[d] = (score, c)
        elif score > prev[0]:
            best[d] = (score, c)
    return [best[d][1] for d in order if d in best]


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _search_agreement(a: list[dict], b: list[dict]) -> dict:
    """Accord SearXNG ∥ TinyFish. Un moteur vide = panne, pas une discordance."""
    urls_a = {_normalize_url(c.get("url")) for c in (a or []) if c.get("url")}
    urls_b = {_normalize_url(c.get("url")) for c in (b or []) if c.get("url")}
    urls_a.discard("")
    urls_b.discard("")
    doms_a = {(c.get("domain") or domain_of(c.get("url") or "")) for c in (a or [])}
    doms_b = {(c.get("domain") or domain_of(c.get("url") or "")) for c in (b or [])}
    doms_a.discard("")
    doms_b.discard("")
    n_a, n_b = len(urls_a), len(urls_b)
    j_urls = round(_jaccard(urls_a, urls_b), 3)
    j_doms = round(_jaccard(doms_a, doms_b), 3)
    return {
        "n_a": n_a,
        "n_b": n_b,
        "jaccard_urls": j_urls,
        "jaccard_domains": j_doms,
        "discordant": bool(n_a >= 3 and n_b >= 3 and j_doms < 0.3),
    }


async def _resolve_tf_key(tf_key: str | None = None) -> str:
    if tf_key:
        return tf_key.strip()
    from app.core.tinyfish import tf_api_key
    key = tf_api_key()
    if key:
        return key
    try:
        from app.db import get_settings
        return tf_api_key(await get_settings())
    except Exception:
        return ""


async def _tf_search_safe(query: str, key: str, log, *, location=None, language=None,
                          include_domains=None) -> list[dict]:
    if not key or not query:
        return []
    from app.core.tinyfish import tf_search
    try:
        return await tf_search(
            query, key, location=location, language=language,
            include_domains=include_domains, log=log)
    except Exception as e:
        log(f"TinyFish Search: échec ({type(e).__name__})")
        return []


async def _find_sources(zone: dict, whitelist: list[str], exceptions: dict, log, rec=None,
                        tf_key: str | None = None, variant: str = "tinyfish",
                        ) -> tuple[list[dict], bool, str | None]:
    """Étape 2 — recherche selon le variant du run :
    v1 = SearXNG séquentiel (EN puis localisé si vide) ;
    v2 = SearXNG parallèle EN ∥ local, sans TinyFish ;
    tinyfish = SearXNG ∥ TinyFish + filet include_domains.
    :online en dernier dans tous les cas. Ne touche jamais poe_ports."""
    name = zone.get("name") or zone.get("geoname")
    variant = normalize_variant(variant)
    use_tf = variant == "tinyfish"
    key = (await _resolve_tf_key(tf_key)) if use_tf else ""
    iso = ((zone.get("sov_iso2") or zone.get("iso2") or "") or "").upper() or None
    lang = LANG_BY_ISO2.get(iso or "")

    query_en = (f"official designated ports of entry list customs gazette "
                f"decree legislation {name}")
    loc_q = localized_query(zone)

    searx_groups, tf_groups = [], []
    if variant == "v1":
        res_en = await search_searxng(query_en, log)
        await emit(rec, "search", engine="searxng", lang="en", query=query_en,
                   n=len(res_en or []), results=res_en or [], variant=variant)
        searx_groups.append(res_en or [])
        if not res_en and loc_q:
            log(f"v1: SearXNG EN vide — bascule localisée ({lang}): {loc_q[:80]}")
            res_loc = await search_searxng(loc_q, log)
            await emit(rec, "search", engine="searxng", lang=lang, query=loc_q,
                       n=len(res_loc or []), results=res_loc or [], variant=variant)
            searx_groups.append(res_loc or [])
    else:
        jobs = [search_searxng(query_en, log)]
        labels = [("searxng", "en", query_en)]
        if key:
            jobs.append(_tf_search_safe(query_en, key, log, location=iso, language="en"))
            labels.append(("tinyfish", "en", query_en))
        if loc_q:
            log(f"recherche parallèle EN ∥ localisée ({lang}): {loc_q[:80]}")
            jobs.append(search_searxng(loc_q, log))
            labels.append(("searxng", lang, loc_q))
            if key:
                jobs.append(_tf_search_safe(loc_q, key, log, location=iso, language=lang))
                labels.append(("tinyfish", lang, loc_q))

        results = await asyncio.gather(*jobs)
        for res, (engine, qlang, query) in zip(results, labels):
            await emit(rec, "search", engine=engine, lang=qlang, query=query,
                       n=len(res or []), results=res or [], variant=variant)
            if engine == "tinyfish":
                tf_groups.append(res or [])
            else:
                searx_groups.append(res or [])

    searx_set = _merge_candidates(*searx_groups)
    tf_set = _merge_candidates(*tf_groups)
    compare = _search_agreement(searx_set, tf_set)
    await emit(rec, "search_compare", **compare)
    if compare["discordant"]:
        log(f"search_compare: discordance Jaccard domaines={compare['jaccard_domains']} "
            f"(n_searx={compare['n_a']} n_tf={compare['n_b']})")

    candidates = _merge_candidates(searx_set, tf_set)
    if candidates:
        log(f"union des recherches: {compare['n_a']} SearXNG + {compare['n_b']} TinyFish "
            f"→ {len(candidates)} candidats")

    hints = search_hint_queries(zone, exceptions)
    if hints:
        hint_res = await asyncio.gather(*[search_searxng(q, log) for q in hints])
        for q, res in zip(hints, hint_res):
            await emit(rec, "search", engine="searxng", lang="hint", query=q,
                       n=len(res), results=res)
        candidates = _merge_candidates(candidates, *hint_res)
        log(f"requêtes épinglées: {len(hints)} → +{sum(len(r) for r in hint_res)} candidats")

    synthesis = None
    grounded_attempted = False
    if not candidates:
        candidates, synthesis = await search_grounded(zone, whitelist, log)
        grounded_attempted = True
        await emit(rec, "search", engine="grounded", lang="en", query="(prompt groundé)",
                   n=len(candidates), results=candidates,
                   synthesis_chars=len(synthesis or ""))

    before_filter = list(candidates)
    candidates = serp_filter(candidates)
    dropped_filter = [c.get("url") for c in before_filter if c not in candidates]
    if dropped_filter:
        await emit(rec, "serp_filter", kept=len(candidates), dropped=dropped_filter)
    scores: list = []
    candidates = rank_candidates_ml(candidates, log, scores_out=scores)
    if scores:
        await emit(rec, "serp_rank", scores=scores)

    official = [c for c in candidates if url_allowed(c["url"], whitelist)]

    scoped_added = False
    if key and (not official or compare.get("discordant")):
        scoped = await _tf_search_safe(
            query_en, key, log, location=iso, language="en",
            include_domains=whitelist[:8])
        await emit(rec, "search", engine="tinyfish", lang="en", query=query_en,
                   n=len(scoped), results=scoped, scoped=True)
        if scoped:
            scoped_added = True
            log(f"TinyFish Search scoped: {len(scoped)} résultat(s) include_domains")
            candidates = _merge_candidates(candidates, scoped)
            before_s = list(candidates)
            candidates = serp_filter(candidates)
            dropped_s = [c.get("url") for c in before_s if c not in candidates]
            if dropped_s:
                await emit(rec, "serp_filter", kept=len(candidates), dropped=dropped_s,
                           scoped=True)
            scores_s: list = []
            candidates = rank_candidates_ml(candidates, log, scores_out=scores_s)
            if scores_s:
                await emit(rec, "serp_rank", scores=scores_s, scoped=True)
            official = [c for c in candidates if url_allowed(c["url"], whitelist)]

    if not official:
        log("Level-2 retry: recherche ciblée sur l'organisation douanière nationale")
        q2 = (f"{zone.get('sovereign') or name} customs administration official website "
              f"designated ports of entry list gazette decree {name}")
        level2_jobs = [search_searxng(q2, log)]
        if key and not scoped_added:
            level2_jobs.append(_tf_search_safe(q2, key, log, location=iso, language="en"))
        extra_parts = await asyncio.gather(*level2_jobs)
        extra = _merge_candidates(*extra_parts)
        await emit(rec, "search", engine="searxng", lang="en", query=q2, level2=True,
                   n=len(extra_parts[0] or []), results=extra_parts[0] or [])
        if len(extra_parts) > 1:
            await emit(rec, "search", engine="tinyfish", lang="en", query=q2, level2=True,
                       n=len(extra_parts[1] or []), results=extra_parts[1] or [])
        syn2 = None
        if not extra and not grounded_attempted:
            extra, syn2 = await search_grounded(zone, whitelist, log, query_override=(
                f"Find the OFFICIAL national customs administration / border agency website of "
                f"{zone.get('sovereign') or name} and the page listing designated ports of entry "
                f"(clearance / designated / habilitados) in {name}. Cite the official URLs."
            ))
            await emit(rec, "search", engine="grounded", lang="en", query=q2, level2=True,
                       n=len(extra or []), results=extra or [],
                       synthesis_chars=len(syn2 or ""))
        if syn2 and not synthesis:
            synthesis = syn2
        known_urls = {_normalize_url(c.get("url")) for c in candidates}
        extra = serp_filter([c for c in (extra or [])
                             if _normalize_url(c.get("url") or "") not in known_urls])
        if extra:
            log(f"Level-2 retry: {len(extra)} source(s) supplémentaires trouvées")
            candidates += extra
            candidates = rank_candidates_ml(candidates, log)
        official = [c for c in candidates if url_allowed(c.get("url") or "", whitelist)]

    # Bootstrapping des exceptions (domaines d'État non couverts par la PSL)
    rejected = [c for c in candidates if c not in official]
    cc_low = (zone.get("iso2") or "").lower()
    if not official and rejected and cc_low:
        boot = [c for c in rejected if c["domain"].endswith("." + cc_low) and OFFICIAL_TOKENS.search(c["domain"])]
        if boot:
            auto = exceptions.setdefault("auto", {}).setdefault((zone.get("iso2") or "").upper(), [])
            for c in boot:
                if c["domain"] not in auto:
                    auto.append(c["domain"])
            save_exceptions(exceptions)
            log(f"bootstrapping: {[c['domain'] for c in boot]} ajoutés à exceptions.json (auto)")
            await emit(rec, "bootstrap", domains=[c["domain"] for c in boot])
            official = boot
    seeds = seed_url_candidates(zone, exceptions)
    if seeds:
        seed_urls = {c["url"] for c in seeds}
        rest = _best_per_domain([c for c in official if c["url"] not in seed_urls])
        official = seeds + rest
        log(f"sources épinglées: {[c['url'] for c in seeds]}")
    else:
        official = _best_per_domain(official)
    strictly_official = bool(official)
    if not official:
        # dernier recours : domaines du pays même non gouvernementaux (statut
        # ia_sans_source). Les sites GOUVERNEMENTAUX D'AUTRES PAYS sont exclus
        # (un ccTLD étranger + token régalien = ports du mauvais pays).
        cc_ok = {c for c in (cc_low, (zone.get("sov_iso2") or "").lower()) if c}

        national = [c for c in rejected if cc_low and c["domain"].endswith("." + cc_low)]
        official = (national or [c for c in rejected if not is_foreign_gov_domain(c["domain"], cc_ok)])[:2]
        log(f"gatekeeper: 0 domaine whitelisté — {len(official)} source(s) non officielles retenues (ia_sans_source)")
    else:
        log(f"gatekeeper: {len(official)} source(s) officielles retenues, {len(rejected)} rejetées")
    await emit(rec, "gatekeeper", whitelist=whitelist[:12],
               official=[c["domain"] for c in official],
               rejected=[c["domain"] for c in rejected],
               strictly_official=strictly_official)
    return official, strictly_official, synthesis


async def _collect_texts(official: list[dict], log, rec=None, max_fetch: int = 5
                         ) -> tuple[list[str], dict, list[dict], dict]:
    """Étape 3 — Collecte : cascade N1∥N2, miroir anti-bot, PDF joints officiels
    (même si la page est déjà longue), depth-2 si le texte est mince.
    Jusqu'à max_fetch URL : une page bloquée n'épuise plus le budget de 3."""
    texts, hashes, used_sources, excerpts = [], {}, [], {}
    queue = list(official)
    seen_urls: set[str] = set()
    fetched = 0
    while queue and fetched < max_fetch:
        c = queue.pop(0)
        url = c.get("url") or ""
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        fetched += 1
        try:
            res = await extract_cascade(url, min_chars=200, log=log)
        except Exception as e:
            log(f"fetch {c.get('domain') or domain_of(url)}: échec ({type(e).__name__})")
            await emit(rec, "fetch", url=url, domain=c.get("domain"),
                       level="failed", error=type(e).__name__)
            continue
        await emit(rec, "fetch", url=url, domain=c.get("domain"), level=res["level"],
                   chars=len(res["text"]), md5=res["md5"], blocked=res.get("blocked", False),
                   render_used=res.get("render_used", False), parse=res.get("parse"))
        if res.get("fetch_compare"):
            await emit(rec, "fetch_compare", url=url, domain=c.get("domain"),
                       **res["fetch_compare"])
        if res.get("blocked"):
            log(f"fetch {c.get('domain')}: page de blocage anti-bot — source écartée")
            continue
        if res["md5"]:
            hashes[url] = res["md5"]
        text = res["text"]
        log(f"fetch {c.get('domain') or domain_of(url)}: {len(text)} chars via {res['level']}")
        blob = (res.get("html") or "") + "\n" + (text or "")
        if should_follow_attachments(text or "", url):
            for att in official_attachments(blob, url, limit=2):
                if att not in seen_urls:
                    log(f"pièce jointe officielle: {att[:90]}")
                    await emit(rec, "attachment", parent=url, url=att)
                    queue.append({"url": att, "domain": domain_of(att)})
        if len(text) < 400 and res.get("html"):
            for fu in internal_followups(res["html"], url, limit=2):
                try:
                    sub = await extract_cascade(fu, min_chars=200, log=log)
                except Exception:
                    continue
                if sub["text"] and not sub.get("blocked"):
                    log(f"depth-2: {fu[:80]} → {len(sub['text'])} chars")
                    await emit(rec, "depth2", parent=url, url=fu,
                               chars=len(sub["text"]), level=sub["level"])
                    text = (text + "\n" + sub["text"]).strip()
        if text and len(text) > 200:
            texts.append(f"[SOURCE: {url}]\n{text[:60000]}")
            excerpts[url] = text[:2500]
            used_sources.append({"url": url, "domain": c.get("domain") or domain_of(url),
                                 "md5": hashes.get(url), "collected_at": now_iso()})
            await emit(rec, "source_used", url=url, domain=c.get("domain"), chars=len(text))
    return texts, hashes, used_sources, excerpts


async def _extract_and_geocode(zone: dict, context: str, used_sources: list[dict], log,
                               rec=None, run=None, catalog_text: str | None = None,
                               settings: dict | None = None) -> list[dict]:
    """Étape 4 — Extraction parallèle comparée (LLM ∥ NER) puis GÉOCODAGE DOUBLE
    (Nominatim ∥ GeoNames, données indépendantes) : l'accord < 2 km devient un
    signal de confiance, le désaccord est arbitré par la validation point-in-EEZ.
    Chaque candidat des deux fournisseurs est journalisé."""
    mrgid = int(zone["mrgid"])
    name = zone.get("name") or zone.get("geoname")
    ports = await extract_ports_llm(context, zone, log, rec=rec,
                                   catalog_text=catalog_text, settings=settings)

    geom = None
    try:
        geom = await asyncio.to_thread(shape, zone["geometry"])
        prepared = prep(geom)
    except Exception:
        prepared = None

    docs = []
    seen_names = set()
    for p in ports:  # pas de plafond par pays (grands États maritimes)
        norm = normalize_name(p["name"])
        if not norm or norm in seen_names:
            continue
        seen_names.add(norm)

        if p.get("lat") is not None and p.get("lon") is not None:
            geo = {"nominatim": None, "geonames": None, "agree": None,
                   "agreement_km": None, "geonames_available": True}
            cands = [{"source": "official_list", "lat": float(p["lat"]),
                      "lon": float(p["lon"]), "validated": False, "dist_km": None}]
            if prepared is not None or geom is not None:
                v, d = point_in_eez(float(p["lat"]), float(p["lon"]), geom, prepared)
                cands[0]["validated"], cands[0]["dist_km"] = v, d
        else:
            geo = await geocode_port_dual(p, zone, log)
            cands = []
        for source in ("nominatim", "geonames"):
            coords = geo.get(source)
            if not coords:
                continue
            if prepared is not None or geom is not None:
                v, d = point_in_eez(coords[0], coords[1], geom, prepared)
            else:
                v, d = False, None
            cands.append({"source": source, "lat": coords[0], "lon": coords[1],
                          "validated": v, "dist_km": d})

        chosen, arbitration = None, None
        valid_cands = [c for c in cands if c["validated"]]
        if len(cands) == 1:
            chosen, arbitration = cands[0], "single"
        elif len(cands) == 2:
            if geo.get("agree"):
                chosen, arbitration = cands[0], "agree"       # accord < 2 km : Nominatim (plus fin)
            elif valid_cands:
                chosen, arbitration = valid_cands[0], "eez"   # désaccord : arbitrage point-in-EEZ
            else:
                chosen, arbitration = cands[0], "first"

        # Rejet des géocodages manifestement aberrants (> 300 km de la ZEE),
        # en basculant sur l'autre fournisseur s'il est plausible.
        if chosen and chosen["dist_km"] is not None and chosen["dist_km"] > 300:
            other = next((c for c in cands if c is not chosen
                          and (c["dist_km"] is None or c["dist_km"] <= 300)), None)
            if other:
                log(f"  ⚠ {p['name']}: {chosen['source']} aberrant ({chosen['dist_km']} km) "
                    f"— bascule sur {other['source']}")
                chosen, arbitration = other, "eez_aberrant_switch"
            else:
                log(f"  ⚠ {p['name']}: géocodage aberrant ({chosen['dist_km']} km de la ZEE) — coordonnées rejetées")
                chosen, arbitration = None, "aberrant_rejected"

        lat = chosen["lat"] if chosen else None
        lon = chosen["lon"] if chosen else None
        source = chosen["source"] if chosen else None
        validated = bool(chosen["validated"]) if chosen else False
        dist_km = chosen["dist_km"] if chosen else None

        await emit(rec, "geocode", port=p["name"],
                   nominatim=geo.get("nominatim"), geonames=geo.get("geonames"),
                   geonames_available=geo.get("geonames_available"),
                   agreement_km=geo.get("agreement_km"), agree=geo.get("agree"),
                   candidates=cands, chosen=source, arbitration=arbitration)

        doc = {
            "_id": str(uuid.uuid4()),
            "mrgid": mrgid,
            "zone_name": name,
            "country_iso2": zone.get("iso2") or zone.get("sov_iso2"),
            "name": p["name"], "city": p.get("city"), "note": p.get("note"),
            "lat": lat, "lon": lon, "geocode_source": source,
            "validated": validated, "distance_km": dist_km,
            "geocode_agree": geo.get("agree"),
            "geocode_agreement_km": geo.get("agreement_km"),
            "geocode_alternates": {"nominatim": geo.get("nominatim"),
                                   "geonames": geo.get("geonames")},
            "geocode_arbitration": arbitration,
            "extraction_engine": p.get("extraction_engine"),
            "extraction_agreement": p.get("extraction_agreement"),
            "source_urls": [s["url"] for s in used_sources],
            "extracted_at": now_iso(),
            "dedup_key": f"{mrgid}:{norm}",
        }
        if run is not None:
            doc["run_id"] = run.run_id
            doc["pipeline_variant"] = getattr(run, "variant", None)
        docs.append(doc)
        agree_note = ""
        if geo.get("agree") is True:
            agree_note = f" ✓ accord géocodeurs ({geo.get('agreement_km')} km)"
        elif geo.get("agree") is False:
            agree_note = f" ⚠ désaccord géocodeurs ({geo.get('agreement_km')} km, arbitrage {arbitration})"
        log(f"  ⚓ {p['name']} → {'%.3f, %.3f' % (lat, lon) if lat is not None else 'non géocodé'}"
            f"{' ✓ ZEE' if validated else (f' ⚠ hors ZEE ({dist_km} km)' if lat is not None else '')}"
            + agree_note)
        await emit(rec, "port", name=p["name"], city=p.get("city"), lat=lat, lon=lon,
                   validated=validated, distance_km=dist_km,
                   extraction_agreement=p.get("extraction_agreement"),
                   geocode_agree=geo.get("agree"))
    return docs


async def _persist_zone_run(db, zone: dict, docs: list[dict], status: str,
                            used_sources: list[dict], hashes: dict, run, rec, log) -> dict:
    """Étape 5 (mode run versionné) — Écriture dans l'ESPACE DU RUN uniquement :
    poe_run_ports / poe_run_zones. Les collections v1 (poe_ports, eez_zones) ne
    sont jamais touchées. Idempotent par (run_id, mrgid) : une re-génération de
    la zone dans le même run remplace ses ports."""
    mrgid = int(zone["mrgid"])
    docs = deduplicate_list(docs, title_key="name") if docs else []
    ports_coll = db[run.ports_coll]
    await ports_coll.delete_many({"run_id": run.run_id, "mrgid": mrgid})
    if docs:
        await ports_coll.insert_many(docs)
    zone_doc = {
        "run_id": run.run_id,
        "mrgid": mrgid,
        "name": zone.get("name"),
        "geoname": zone.get("geoname"),
        "iso2": zone.get("iso2"),
        "sov_iso2": zone.get("sov_iso2"),
        "sovereign": zone.get("sovereign"),
        "status": status if docs else "erreur",
        "poe_count": len(docs),
        "sources": used_sources,
        "source_hashes": hashes,
        "generated_at": now_iso(),
        "last_error": None if docs else "aucun port d'entrée extrait des sources",
        "pipeline_variant": getattr(run, "variant", None),
    }
    await db[run.zones_coll].update_one(
        {"run_id": run.run_id, "mrgid": mrgid}, {"$set": zone_doc}, upsert=True)
    await emit(rec, "persist", inserted=len(docs), status=zone_doc["status"],
               run_id=run.run_id)
    log(f"terminé (run {run.run_id[:8]}): {len(docs)} PoE écrits dans l'espace du run, "
        f"statut {zone_doc['status']}")
    return zone_doc


async def _persist_zone(db, zone: dict, docs: list[dict], status: str,
                        used_sources: list[dict], hashes: dict, excerpts: dict, log) -> dict:
    """Étape 5 — Écriture non-destructive : dédup interne, upsert des ports
    (les enrichissements Bottom-Up sont préservés), statut de la zone."""
    mrgid = int(zone["mrgid"])
    if docs:
        # Déduplication interne (core.dedup: Haversine <500m + fuzzy >60%)
        docs = deduplicate_list(docs, title_key="name")
        # Upsert NON-DESTRUCTIF : les PoE existants sont enrichis, jamais purgés
        # (préserve les champs Bottom-Up: osm_confidence, spatial_anomaly…).
        existing_ports = await db.poe_ports.find({"mrgid": mrgid}).to_list(500)
        inserted = merged = 0
        for d in docs:
            match = next((e for e in existing_ports if e.get("dedup_key") == d["dedup_key"]), None)
            if match is None:
                match = find_duplicate_in_list(d, existing_ports, title_key="name")
            if match:
                updates = merge_docs(match, d)
                updates["note"] = d.get("note") or match.get("note")
                updates["source_urls"] = sorted(set((match.get("source_urls") or []) + (d.get("source_urls") or [])))
                updates["extracted_at"] = d["extracted_at"]
                await db.poe_ports.update_one({"_id": match["_id"]}, {"$set": updates})
                merged += 1
            else:
                await db.poe_ports.insert_one(d)
                existing_ports.append(d)
                inserted += 1
        poe_count = await db.poe_ports.count_documents({"mrgid": mrgid})
        await db.eez_zones.update_one({"mrgid": mrgid}, {"$set": {
            "status": status,
            "poe_count": poe_count,
            "generated_at": now_iso(),
            "sources": used_sources,
            "source_hashes": hashes,
            "source_excerpts": excerpts,
            "last_error": None,
        }, "$unset": {"unclos": ""}})
        log(f"terminé: {inserted} nouveau(x) PoE, {merged} fusionné(s) — total zone {poe_count}, statut {status}")
    elif zone.get("poe_count", 0) > 0:
        # Ré-extraction vide sur une zone déjà peuplée : on PRÉSERVE les ports
        # existants (le pipeline de recherche est non déterministe).
        log(f"0 port extrait — {zone.get('poe_count')} PoE existants préservés (aucune purge)")
        await db.eez_zones.update_one({"mrgid": mrgid}, {"$set": {
            "checked_at": now_iso(),
            "last_error": "ré-extraction vide — ports précédents conservés",
        }})
    else:
        await db.eez_zones.update_one({"mrgid": mrgid}, {"$set": {
            "status": "erreur",
            "poe_count": 0,
            "generated_at": now_iso(),
            "sources": used_sources,
            "source_hashes": hashes,
            "last_error": "aucun port d'entrée extrait des sources",
        }})
        log("terminé: 0 PoE, statut erreur")
    return await db.eez_zones.find_one({"mrgid": mrgid})


async def generate_zone_poe(db, mrgid: int, logger=None, force: bool = False, run=None) -> dict:
    """Orchestrateur : monitoring -> recherche -> collecte -> extraction -> écriture.

    run (RunContext, optionnel) : mode « run versionné from scratch » — le
    monitoring est court-circuité (pipeline complet forcé), chaque micro-étape
    émet un événement structuré, et l'écriture va dans l'espace du run
    (poe_run_ports / poe_run_zones) sans toucher aux collections v1."""
    log = logger or (lambda m: None)
    zone = await db.eez_zones.find_one({"mrgid": int(mrgid)})
    if not zone:
        raise ValueError(f"ZEE mrgid={mrgid} inconnue — construire le référentiel d'abord")
    name = zone.get("name") or zone.get("geoname")
    rec = ZoneRecorder(run.recorder, int(mrgid), name) if run is not None else None
    t0 = time.time()
    settings: dict = {}
    try:
        from app.db import get_settings
        settings = await get_settings()
    except Exception:
        settings = {}
    exceptions = load_exceptions()
    whitelist = build_whitelist(zone.get("iso2"), zone.get("sov_iso2"), exceptions)
    variant = normalize_variant(getattr(run, "variant", None) if run is not None else "tinyfish")
    from app.core.extract import allow_tinyfish_fetch
    _tf_token = allow_tinyfish_fetch.set(variant == "tinyfish")
    log(f"=== {name} (mrgid {mrgid}) — variant={variant} whitelist: {', '.join(whitelist[:8]) or 'vide'}")
    await emit(rec, "zone_start", iso2=zone.get("iso2"), sov_iso2=zone.get("sov_iso2"),
               sovereign=zone.get("sovereign"), pol_type=zone.get("pol_type"),
               whitelist=whitelist, variant=variant)

    try:
        # 1. Monitoring prioritaire des sources connues (jamais en mode run :
        #    un run from scratch refait TOUT le pipeline)
        if run is None:
            unchanged = await _skip_if_unchanged(db, zone, force, log, rec)
            if unchanged is not None:
                return unchanged

        # 2. Recherche + gatekeeper
        official, strictly_official, synthesis = await _find_sources(
            zone, whitelist, exceptions, log, rec, variant=variant)

        # 3. Collecte des textes
        texts, hashes, used_sources, excerpts = await _collect_texts(official, log, rec)

        # Monitoring MD5 post-collecte : skip si contenu strictement identique
        old_hashes = zone.get("source_hashes") or {}
        if (run is None and not force and hashes and old_hashes and hashes == old_hashes
                and zone.get("status") in ("ia", "ia_sans_source") and zone.get("poe_count", 0) > 0):
            log("MD5 inchangés — ré-extraction sautée (contenu source identique)")
            await db.eez_zones.update_one({"mrgid": int(mrgid)}, {"$set": {"checked_at": now_iso()}})
            return await db.eez_zones.find_one({"mrgid": int(mrgid)})

        # Assemblage du contexte (textes + synthèse groundée éventuelle)
        context_parts = list(texts)
        if synthesis:
            # La synthèse provient de la recherche groundée sur les sources officielles ;
            # elle est toujours jointe au contexte (les pages gov listent rarement
            # les ports en HTML brut). Le statut reste piloté par le gatekeeper.
            context_parts.append(f"[SYNTHÈSE DE RECHERCHE (à recouper)]\n{synthesis[:6000]}")
            if not texts:
                strictly_official = False
                log("aucun texte source exploitable — extraction depuis la seule synthèse (ia_sans_source)")
        if not context_parts:
            # Aucun texte exploitable : dernier recours groundé AVANT de déclarer
            # l'erreur (même filet que le retry post-extraction, ici en amont).
            log("aucun texte exploitable — recours à la synthèse groundée")
            _, syn_rescue = await search_grounded(zone, whitelist, log)
            await emit(rec, "search", engine="grounded", lang="en",
                       query="(rescue: aucun texte exploitable)", retry=True,
                       n=0, synthesis_chars=len(syn_rescue or ""))
            if syn_rescue:
                synthesis = syn_rescue
                context_parts.append(f"[SYNTHÈSE DE RECHERCHE (à recouper)]\n{syn_rescue[:6000]}")
                strictly_official = False
                log("synthèse groundée obtenue — extraction depuis la synthèse (ia_sans_source)")
        if not context_parts:
            log("ERREUR: aucun contenu exploitable")
            await emit(rec, "zone_error", error="aucun contenu source exploitable",
                       duration_s=round(time.time() - t0, 1))
            if run is not None:
                return await _persist_zone_run(db, zone, [], "erreur",
                                               used_sources, hashes, run, rec, log)
            await db.eez_zones.update_one({"mrgid": int(mrgid)}, {"$set": {
                "status": "erreur", "last_error": "aucun contenu source exploitable",
                "generated_at": now_iso(), "sources": used_sources, "source_hashes": hashes,
            }})
            return await db.eez_zones.find_one({"mrgid": int(mrgid)})

        # RAG local : le LLM reçoit un extrait ; le parseur de catalogue lit
        # TOUJOURS le texte officiel brut (sinon Alofi / fin de liste SCT disparaissent).
        raw = "\n\n".join(context_parts)
        raw_chars = len(raw)
        raw_catalog = extract_structured_ports(raw)
        if raw_catalog:
            remembered = remember_seed_urls(zone, urls_with_catalog(texts), exceptions)
            if remembered:
                log(f"sources productives mémorisées pour {zone.get('iso2')}: {remembered}")
                await emit(rec, "seed_remembered", iso2=zone.get("iso2"), urls=remembered)
        rag_q = (f"official designated ports of entry customs gazette decree "
                 f"puertos habilitados puertos de entrada port of entry {name}")
        if looks_like_port_catalog(raw) or raw_catalog:
            context = raw[:40000]
            log(f"catalogue / tournure légale ({len(raw_catalog)} nom(s)) — "
                f"texte brut conservé pour le parseur, LLM sur {len(context)} chars")
        elif len(raw) > 15000:
            context = select_context(rag_q, raw, max_chars=20000)
            log(f"RAG: contexte condensé à {len(context)} chars (chunks pertinents par similarité cosinus)")
        else:
            context = raw
        await emit(rec, "context", sources=len(texts), synthesis=bool(synthesis),
                   raw_chars=raw_chars, final_chars=len(context),
                   catalog_n=len(raw_catalog))

        # 4. Extraction + géocodage + validation spatiale
        docs = await _extract_and_geocode(zone, context, used_sources, log, rec, run,
                                          catalog_text=raw, settings=settings)

        # Filet de sécurité : 0 port extrait des pages collectées ET aucune
        # synthèse groundée encore tentée → un (seul) recours à la recherche
        # groundée, dont la synthèse est jointe au contexte puis ré-extraite.
        # (Les pages gov listent rarement les ports en HTML brut ; sans ce
        # filet, les zones à pages minces finissent toutes en erreur.)
        if not docs and synthesis is None:
            log("0 port extrait des pages collectées — recours à la synthèse groundée (retry unique)")
            _, syn_retry = await search_grounded(zone, whitelist, log)
            await emit(rec, "search", engine="grounded", lang="en",
                       query="(retry synthèse après 0 port)", retry=True,
                       n=0, synthesis_chars=len(syn_retry or ""))
            if syn_retry:
                context_retry = f"{context}\n\n[SYNTHÈSE DE RECHERCHE (à recouper)]\n{syn_retry[:6000]}"
                docs = await _extract_and_geocode(zone, context_retry, used_sources, log, rec, run,
                                                  catalog_text=context_retry, settings=settings)
                if docs:
                    strictly_official = False  # ports issus de la synthèse, pas des pages officielles

        # 5. Écriture : espace du run (versionné) ou collections v1 (non-destructif)
        status = "ia" if strictly_official else "ia_sans_source"
        if run is not None:
            result = await _persist_zone_run(db, zone, docs, status,
                                             used_sources, hashes, run, rec, log)
        else:
            result = await _persist_zone(db, zone, docs, status, used_sources, hashes, excerpts, log)
        await emit(rec, "zone_done", status=(result or {}).get("status"),
                   poe_count=(result or {}).get("poe_count", 0),
                   duration_s=round(time.time() - t0, 1),
                   variant=variant)
        return result
    except Exception as e:
        await emit(rec, "zone_error", error=f"{type(e).__name__}: {str(e)[:200]}",
                   duration_s=round(time.time() - t0, 1))
        raise
    finally:
        allow_tinyfish_fetch.reset(_tf_token)


# ---------------------------------------------------------------------------
# Sérialisation
# ---------------------------------------------------------------------------
def zone_to_item(doc: dict) -> dict:
    return {
        "mrgid": doc.get("mrgid"),
        "name": doc.get("name"),
        "geoname": doc.get("geoname"),
        "sovereign": doc.get("sovereign"),
        "iso2": doc.get("iso2"),
        "sov_iso2": doc.get("sov_iso2"),
        "pol_type": doc.get("pol_type"),
        "area_km2": doc.get("area_km2"),
        "bbox": doc.get("bbox"),
        "anchor": doc.get("anchor"),
        "status": doc.get("status", "non_generee"),
        "poe_count": doc.get("poe_count", 0),
        "generated_at": doc.get("generated_at"),
        "stale": is_stale(doc),
        "last_error": doc.get("last_error"),
        "unclos": doc.get("unclos"),
        "sources": [{"url": s.get("url"), "domain": s.get("domain"), "collected_at": s.get("collected_at")}
                    for s in (doc.get("sources") or [])],
        "whitelist": (doc.get("whitelist") or [])[:8],
    }


def ports_to_geojson(docs: list[dict]) -> dict:
    feats = []
    for d in docs:
        if d.get("lat") is None or d.get("lon") is None:
            continue
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [d["lon"], d["lat"]]},
            "properties": {
                "id": d["_id"], "name": d.get("name"), "city": d.get("city"), "note": d.get("note"),
                "mrgid": d.get("mrgid"), "zone_name": d.get("zone_name"),
                "country_iso2": d.get("country_iso2"),
                "validated": bool(d.get("validated")), "distance_km": d.get("distance_km"),
                "geocode_source": d.get("geocode_source"),
                "source_urls": d.get("source_urls") or [],
                "extracted_at": d.get("extracted_at"),
                "osm_confidence": d.get("osm_confidence"),
                "osm_tags": d.get("osm_tags"),
                "spatial_anomaly": d.get("spatial_anomaly"),
            },
        })
    return {
        "type": "FeatureCollection",
        "attribution": f"{EEZ_ATTRIBUTION} · Geocoding © OpenStreetMap/Nominatim (ODbL)",
        "features": feats,
    }
