"""
poe.py — Pipeline souverain [ZEE / Pays] -> [Ports d'Entrée plaisance].

Architecture (plan de développement 2026-06) :
  1. Délimitation ZEE      : VLIZ Marine Regions WFS (World EEZ v12, ~285 zones), simplifié shapely.
  2. Recherche ciblée      : SearXNG (1ère intention) -> Gemini Google Search grounding (fallback).
  3. Whitelist automatique : ISO 3166-1 alpha-2 x motifs d'extensions d'État (gov/gouv/gob/...)
                             validés contre la Public Suffix List (tldextract) + exceptions.json
                             enrichi par auto-découverte (bootstrapping).
  4. Collecte & parsing    : httpx + trafilatura (HTML) + PyMuPDF (PDF). Pas d'agent navigateur lourd.
  5. Extraction structurée : LLM léger (Gemini flash) en mode JSON strict -> liste de noms de PoE.
  6. Géocodage             : Nominatim (OSM) -> GeoNames. Validation spatiale point-in-EEZ (shapely).
  7. Monitoring            : hash MD5 des contenus sources — ré-extraction uniquement si modifiés.
"""
import asyncio
import hashlib
import json
import os
import re
import time
import unicodedata
import uuid
from pathlib import Path

import httpx
import pycountry
import tldextract
from shapely.geometry import shape, Point, mapping
from shapely.prepared import prep

ROOT = Path(__file__).parent
DATA = ROOT / "data"
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

SEARX_INSTANCES = [
    "https://searx.be",
    "https://search.inetol.net",
    "https://priv.au",
]

_geocode_lock = asyncio.Lock()
_last_nominatim = 0.0


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
def load_exceptions() -> dict:
    try:
        return json.loads(EXCEPTIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"manual": {}, "auto": {}}


def save_exceptions(exc: dict):
    try:
        EXCEPTIONS_FILE.write_text(json.dumps(exc, indent=2, ensure_ascii=False), encoding="utf-8")
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
# 2. Recherche : SearXNG -> Gemini grounding
# ---------------------------------------------------------------------------
async def search_searxng(query: str, log) -> list[dict]:
    for inst in SEARX_INSTANCES:
        try:
            async with httpx.AsyncClient(timeout=8, headers={"User-Agent": UA}) as client:
                r = await client.get(f"{inst}/search", params={"q": query, "format": "json"})
                if r.status_code != 200 or "json" not in (r.headers.get("content-type") or ""):
                    continue
                results = (r.json().get("results") or [])[:10]
                if results:
                    log(f"SearXNG {inst}: {len(results)} résultats")
                    return [{"url": x.get("url"), "domain": domain_of(x.get("url") or "")} for x in results if x.get("url")]
        except Exception:
            continue
    log("SearXNG: aucune instance exploitable — bascule sur Gemini grounding")
    return []


async def search_gemini_grounding(zone: dict, whitelist: list[str], gemini_key: str, log):
    """Gemini + google_search tool. Retourne (candidats [{url, domain}], texte de synthèse)."""
    name = zone.get("name") or zone.get("geoname")
    hints = ", ".join(whitelist[:6]) if whitelist else "official government domains"
    prompt = (
        f"Find the OFFICIAL government sources (customs, immigration, maritime/port authority) that list "
        f"the designated ports of entry (clearance ports) for FOREIGN PLEASURE CRAFT / YACHTS in {name} "
        f"({zone.get('sovereign')}). Prefer official domains such as: {hints}. "
        f"List each official port of entry you find with its town, and cite the official URLs used."
    )
    body = {"contents": [{"parts": [{"text": prompt}]}], "tools": [{"google_search": {}}]}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={gemini_key}",
                json=body,
            )
            r.raise_for_status()
            d = r.json()
    except Exception as e:
        log(f"Gemini grounding: échec ({type(e).__name__}: {e})")
        return [], None
    cand = (d.get("candidates") or [{}])[0]
    synthesis = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
    chunks = (cand.get("groundingMetadata") or {}).get("groundingChunks") or []
    raw = []
    for c in chunks:
        w = c.get("web") or {}
        if w.get("uri"):
            raw.append({"redirect": w["uri"], "title": (w.get("title") or "").strip().lower()})
    log(f"Gemini grounding: {len(raw)} sources candidates, synthèse {len(synthesis)} chars")

    # Résolution des redirections vertexaisearch -> URL réelle
    async def _resolve(item):
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": UA}) as client:
                async with client.stream("GET", item["redirect"]) as r:
                    return {"url": str(r.url), "domain": domain_of(str(r.url))}
        except Exception:
            t = item["title"]
            if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", t or ""):
                return {"url": f"https://{t}/", "domain": t}
            return None

    resolved = await asyncio.gather(*(_resolve(x) for x in raw[:10]))
    seen, out = set(), []
    for x in resolved:
        if x and x["domain"] and x["domain"] not in seen:
            seen.add(x["domain"])
            out.append(x)
    return out, synthesis


# ---------------------------------------------------------------------------
# 3. Collecte & parsing (httpx + trafilatura / PyMuPDF)
# ---------------------------------------------------------------------------
async def fetch_and_parse(url: str, log) -> tuple[str | None, str | None]:
    """Retourne (texte, md5 du contenu brut)."""
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers={"User-Agent": UA}) as client:
            r = await client.get(url)
            r.raise_for_status()
            content = r.content
    except Exception as e:
        log(f"fetch {domain_of(url)}: échec ({type(e).__name__})")
        return None, None
    md5 = hashlib.md5(content).hexdigest()
    ctype = (r.headers.get("content-type") or "").lower()

    def _parse():
        if content[:5] == b"%PDF-" or "pdf" in ctype or url.lower().endswith(".pdf"):
            import fitz
            with fitz.open(stream=content, filetype="pdf") as pdf:
                return "\n".join(page.get_text() for page in pdf[:20])
        import trafilatura
        return trafilatura.extract(content.decode("utf-8", errors="replace")) or ""

    try:
        text = await asyncio.to_thread(_parse)
    except Exception as e:
        log(f"parse {domain_of(url)}: échec ({type(e).__name__})")
        return None, md5
    text = (text or "").strip()
    log(f"fetch {domain_of(url)}: {len(text)} chars (md5 {md5[:8]}…)")
    return (text[:10000] if text else None), md5


# ---------------------------------------------------------------------------
# 4. Extraction JSON stricte (LLM léger)
# ---------------------------------------------------------------------------
EXTRACT_PROMPT = """Tu extrais les PORTS D'ENTRÉE OFFICIELS (ports de clearance douanière) pour les navires de PLAISANCE étrangers dans : {name} ({sovereign}).

Réponds UNIQUEMENT avec un JSON strict de la forme:
{{"ports": [{{"name": "...", "city": "... ou null", "note": "précision courte ou null"}}]}}

Règles absolues:
- Uniquement les ports d'entrée / de clearance OFFICIELS pour la plaisance mentionnés dans les extraits.
- Ne JAMAIS inventer. Si les extraits ne désignent aucun port d'entrée: {{"ports": []}}.
- "name" = nom du port/marina/quai tel qu'écrit. "note" en français, max 120 caractères.

EXTRAITS DES SOURCES OFFICIELLES:
{context}"""


def _parse_ports_json(txt: str) -> list[dict]:
    txt = re.sub(r"^```(json)?|```$", "", (txt or "").strip(), flags=re.M).strip()
    try:
        d = json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return []
        try:
            d = json.loads(m.group(0))
        except Exception:
            return []
    ports = d.get("ports") if isinstance(d, dict) else None
    out = []
    for p in ports or []:
        if isinstance(p, dict) and (p.get("name") or "").strip():
            out.append({
                "name": str(p["name"]).strip()[:120],
                "city": (str(p["city"]).strip()[:80] if p.get("city") else None),
                "note": (str(p["note"]).strip()[:200] if p.get("note") else None),
            })
    return out[:40]


async def extract_ports_llm(context: str, zone: dict, gemini_key: str | None, emergent_key: str | None, log) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(
        name=zone.get("name") or zone.get("geoname"),
        sovereign=zone.get("sovereign") or "",
        context=context[:20000],
    )
    # Primaire : Gemini REST, mode JSON strict
    if gemini_key:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={gemini_key}",
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
                    },
                )
                r.raise_for_status()
                txt = "".join(
                    p.get("text", "")
                    for p in ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts", [])
                )
            ports = _parse_ports_json(txt)
            log(f"LLM Gemini flash: {len(ports)} port(s) extraits")
            return ports
        except Exception as e:
            log(f"LLM Gemini: échec ({type(e).__name__}) — fallback clé universelle")
    # Fallback : Emergent LLM key via emergentintegrations
    if emergent_key:
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            chat = LlmChat(
                api_key=emergent_key,
                session_id=f"poe-{zone.get('mrgid')}-{int(time.time())}",
                system_message="Tu réponds uniquement en JSON strict.",
            ).with_model("gemini", "gemini-2.5-flash")
            resp = await chat.send_message(UserMessage(text=prompt))
            ports = _parse_ports_json(str(resp))
            log(f"LLM Emergent (gemini-2.5-flash): {len(ports)} port(s) extraits")
            return ports
        except Exception as e:
            log(f"LLM Emergent: échec ({type(e).__name__}: {e})")
    return []


# ---------------------------------------------------------------------------
# 5. Géocodage (Nominatim -> GeoNames) + validation spatiale
# ---------------------------------------------------------------------------
async def geocode_port(port: dict, zone: dict, log) -> tuple[float, float, str] | None:
    global _last_nominatim
    name = port["name"]
    territory = zone.get("name") or ""
    variants = [name]
    stripped = re.sub(r"^(port|puerto|porto|harbour|harbor)\s+(of|de|du|di|da|d')\s*", "", name, flags=re.I).strip()
    if stripped and stripped.lower() != name.lower():
        variants.append(stripped)
    stripped2 = re.sub(r"\s+(port|harbour|harbor|marina|wharf|jetty|terminal)$", "", name, flags=re.I).strip()
    if stripped2 and stripped2.lower() not in {v.lower() for v in variants}:
        variants.append(stripped2)
    queries = []
    if port.get("city"):
        queries.append(f"{name}, {port['city']}, {territory}")
    for v in variants:
        queries.append(f"{v}, {territory}")
    if port.get("city"):
        queries.append(f"{port['city']}, {territory}")
    queries.append(f"{name} port, {zone.get('sovereign') or territory}")

    cc = (zone.get("iso2") or "").lower()
    for q in queries:
        async with _geocode_lock:
            wait = 1.1 - (time.time() - _last_nominatim)
            if wait > 0:
                await asyncio.sleep(wait)
            _last_nominatim = time.time()
        try:
            params = {"q": q, "format": "json", "limit": 1}
            if cc:
                params["countrycodes"] = cc
            async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA}) as client:
                r = await client.get("https://nominatim.openstreetmap.org/search", params=params)
                rows = r.json() if r.status_code == 200 else []
            if rows:
                return float(rows[0]["lat"]), float(rows[0]["lon"]), "nominatim"
        except Exception:
            continue
    # Fallback GeoNames
    gn_user = (os.environ.get("GEONAMES_USERNAME") or "").strip()
    if gn_user:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    "http://api.geonames.org/searchJSON",
                    params={"q": f"{name} {territory}", "maxRows": 1, "username": gn_user},
                )
                rows = (r.json().get("geonames") or []) if r.status_code == 200 else []
            if rows:
                return float(rows[0]["lat"]), float(rows[0]["lng"]), "geonames"
        except Exception:
            pass
    log(f"géocodage: aucun résultat pour « {name} »")
    return None


def _normalize_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", s)[:40]


# ---------------------------------------------------------------------------
# Pipeline complet pour UNE zone
# ---------------------------------------------------------------------------
async def generate_zone_poe(db, mrgid: int, gemini_key: str | None, emergent_key: str | None,
                            logger=None, force: bool = False) -> dict:
    log = logger or (lambda m: None)
    zone = await db.eez_zones.find_one({"mrgid": int(mrgid)})
    if not zone:
        raise ValueError(f"ZEE mrgid={mrgid} inconnue — construire le référentiel d'abord")
    name = zone.get("name") or zone.get("geoname")
    exceptions = load_exceptions()
    whitelist = build_whitelist(zone.get("iso2"), zone.get("sov_iso2"), exceptions)
    log(f"=== {name} (mrgid {mrgid}) — whitelist: {', '.join(whitelist[:8]) or 'vide'}")

    # --- Recherche ---
    query = f"official ports of entry customs clearance foreign yachts pleasure craft {name}"
    candidates = await search_searxng(query, log)
    synthesis = None
    if not candidates:
        if not gemini_key:
            raise RuntimeError("Aucun moteur de recherche disponible (SearXNG bloqué, pas de clé Gemini)")
        candidates, synthesis = await search_gemini_grounding(zone, whitelist, gemini_key, log)

    # --- Gatekeeper + bootstrapping des exceptions ---
    official = [c for c in candidates if url_allowed(c["url"], whitelist)]
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
            official = boot
    strictly_official = bool(official)
    if not official:
        # dernier recours : domaines du pays même non gouvernementaux (statut ia_sans_source)
        official = [c for c in rejected if cc_low and c["domain"].endswith("." + cc_low)][:2] or rejected[:2]
        log(f"gatekeeper: 0 domaine whitelisté — {len(official)} source(s) non officielles retenues (ia_sans_source)")
    else:
        log(f"gatekeeper: {len(official)} source(s) officielles retenues, {len(rejected)} rejetées")

    # --- Collecte + hash MD5 ---
    texts, hashes, used_sources = [], {}, []
    for c in official[:3]:
        text, md5 = await fetch_and_parse(c["url"], log)
        if md5:
            hashes[c["url"]] = md5
        if text and len(text) > 200:
            texts.append(f"[SOURCE: {c['url']}]\n{text}")
            used_sources.append({"url": c["url"], "domain": c["domain"], "md5": md5, "collected_at": now_iso()})

    # --- Monitoring MD5 : skip si contenu inchangé ---
    old_hashes = zone.get("source_hashes") or {}
    if (not force and hashes and old_hashes and hashes == old_hashes
            and zone.get("status") in ("ia", "ia_sans_source") and zone.get("poe_count", 0) > 0):
        log("MD5 inchangés — ré-extraction sautée (contenu source identique)")
        await db.eez_zones.update_one({"mrgid": int(mrgid)}, {"$set": {"checked_at": now_iso()}})
        return await db.eez_zones.find_one({"mrgid": int(mrgid)})

    context_parts = list(texts)
    if synthesis:
        # La synthèse provient du grounding Google sur les sources officielles ;
        # elle est toujours jointe au contexte (les pages gov listent rarement
        # les ports en HTML brut). Le statut reste piloté par le gatekeeper.
        context_parts.append(f"[SYNTHÈSE DE RECHERCHE (à recouper)]\n{synthesis[:6000]}")
        if not texts:
            strictly_official = False
            log("aucun texte source exploitable — extraction depuis la seule synthèse (ia_sans_source)")
    if not context_parts:
        await db.eez_zones.update_one({"mrgid": int(mrgid)}, {"$set": {
            "status": "erreur", "last_error": "aucun contenu source exploitable",
            "generated_at": now_iso(), "sources": used_sources, "source_hashes": hashes,
        }})
        log("ERREUR: aucun contenu exploitable")
        return await db.eez_zones.find_one({"mrgid": int(mrgid)})

    # --- Extraction LLM ---
    ports = await extract_ports_llm("\n\n".join(context_parts), zone, gemini_key, emergent_key, log)

    # --- Géocodage + validation spatiale ---
    geom = None
    try:
        geom = await asyncio.to_thread(shape, zone["geometry"])
        prepared = prep(geom)
    except Exception:
        prepared = None

    docs = []
    seen_names = set()
    for p in ports[:25]:
        norm = _normalize_name(p["name"])
        if not norm or norm in seen_names:
            continue
        seen_names.add(norm)
        geo = await geocode_port(p, zone, log)
        lat = lon = None
        source = None
        validated = False
        dist_km = None
        if geo:
            lat, lon, source = geo
            if prepared is not None:
                pt = Point(lon, lat)
                if prepared.contains(pt):
                    validated, dist_km = True, 0.0
                else:
                    d = geom.distance(pt)
                    dist_km = round(d * 111.0, 1)
                    validated = d <= 0.5  # tolérance côtière ~55 km (les PoE sont à terre)
                    if dist_km > 300:
                        # Géocodage manifestement aberrant — coordonnées rejetées.
                        log(f"  ⚠ {p['name']}: géocodage aberrant ({dist_km} km de la ZEE) — coordonnées rejetées")
                        lat = lon = source = None
                        dist_km = None
        docs.append({
            "_id": str(uuid.uuid4()),
            "mrgid": int(mrgid),
            "zone_name": name,
            "country_iso2": zone.get("iso2"),
            "name": p["name"], "city": p.get("city"), "note": p.get("note"),
            "lat": lat, "lon": lon, "geocode_source": source,
            "validated": validated, "distance_km": dist_km,
            "source_urls": [s["url"] for s in used_sources],
            "extracted_at": now_iso(),
            "dedup_key": f"{mrgid}:{norm}",
        })
        log(f"  ⚓ {p['name']} → {'%.3f, %.3f' % (lat, lon) if lat is not None else 'non géocodé'}"
            f"{' ✓ ZEE' if validated else (f' ⚠ hors ZEE ({dist_km} km)' if lat is not None else '')}")

    status = "ia" if strictly_official else "ia_sans_source"
    if docs:
        # Remplacement atomique uniquement quand la nouvelle extraction est non vide.
        await db.poe_ports.delete_many({"mrgid": int(mrgid)})
        await db.poe_ports.insert_many(docs)
        await db.eez_zones.update_one({"mrgid": int(mrgid)}, {"$set": {
            "status": status,
            "poe_count": len(docs),
            "generated_at": now_iso(),
            "sources": used_sources,
            "source_hashes": hashes,
            "last_error": None,
        }})
        log(f"terminé: {len(docs)} PoE, statut {status}")
    elif zone.get("poe_count", 0) > 0:
        # Ré-extraction vide sur une zone déjà peuplée : on PRÉSERVE les ports
        # existants (le pipeline de recherche est non déterministe).
        log(f"0 port extrait — {zone.get('poe_count')} PoE existants préservés (aucune purge)")
        await db.eez_zones.update_one({"mrgid": int(mrgid)}, {"$set": {
            "checked_at": now_iso(),
            "last_error": "ré-extraction vide — ports précédents conservés",
        }})
    else:
        await db.eez_zones.update_one({"mrgid": int(mrgid)}, {"$set": {
            "status": "erreur",
            "poe_count": 0,
            "generated_at": now_iso(),
            "sources": used_sources,
            "source_hashes": hashes,
            "last_error": "aucun port d'entrée extrait des sources",
        }})
        log("terminé: 0 PoE, statut erreur")
    return await db.eez_zones.find_one({"mrgid": int(mrgid)})


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
            },
        })
    return {
        "type": "FeatureCollection",
        "attribution": f"{EEZ_ATTRIBUTION} · Geocoding © OpenStreetMap/Nominatim (ODbL)",
        "features": feats,
    }
