"""
poe.py — Pipeline souverain [ZEE / Pays] -> [Ports d'Entrée plaisance].

Architecture (refactor Core mutualisé 2026-08) :
  1. Délimitation ZEE      : VLIZ Marine Regions WFS (World EEZ v12, ~285 zones), simplifié shapely.
  2. Recherche ciblée      : SearXNG -> recherche groundée (llm_core: Gemini grounding ou
                             OpenRouter :online) + Level-2 Retry Query (organisation douanière).
  3. Whitelist automatique : ISO 3166-1 alpha-2 x motifs d'État validés PSL (tldextract)
                             + exceptions.json auto-enrichi + filtrage SERP regex (extract_core).
  4. Collecte & parsing    : cascade hybride extract_core — N1 httpx+trafilatura/PyMuPDF ->
                             N2 Readability/BS4 -> N3 TinyFish (1 seul appel max/zone, dernier recours).
                             Depth=2 sélectif sur liens internes réglementaires.
  5. Extraction structurée : llm_core (cascade Gemini -> Emergent -> OpenRouter, JSON strict)
                             + RAG local (rag_core) sur les contextes longs.
  6. Géocodage             : geo_core (Nominatim -> GeoNames, re-ranking sémantique).
                             Validation spatiale point-in-EEZ (shapely).
  7. Monitoring            : hash MD5 + similarité sémantique (skip si changement mineur).
  8. Stockage              : upsert non-destructif via dedup_core (les enrichissements
                             Bottom-Up osm_confidence / anomalies sont préservés).
"""
import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

import httpx
import pycountry
import tldextract
from shapely.geometry import shape, Point, mapping
from shapely.prepared import prep

from dedup_core import deduplicate_list, find_duplicate_in_list, merge_docs, normalize_name
from extract_core import extract_cascade, internal_followups, serp_filter
from geo_core import geocode_port
from llm_core import extract_ports, grounded_search
from rag_core import content_changed, select_context

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
# 2. Recherche : SearXNG -> recherche groundée (llm_core) + Level-2 Retry
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
    log("SearXNG: aucune instance exploitable — bascule sur recherche groundée")
    return []


async def search_grounded(zone: dict, whitelist: list[str], log, query_override: str | None = None):
    """Recherche groundée via llm_core (Gemini google_search si clé, sinon OpenRouter :online)."""
    name = zone.get("name") or zone.get("geoname")
    hints = ", ".join(whitelist[:6]) if whitelist else "official government domains"
    prompt = query_override or (
        f"Find the OFFICIAL government sources (customs, immigration, maritime/port authority) that list "
        f"the designated ports of entry (clearance ports) for FOREIGN PLEASURE CRAFT / YACHTS in {name} "
        f"({zone.get('sovereign')}). Prefer official domains such as: {hints}. "
        f"List each official port of entry you find with its town, and cite the official URLs used."
    )
    return await grounded_search(prompt, log=log, domain_fn=domain_of)


# ---------------------------------------------------------------------------
# 3. Collecte & parsing — cascade hybride N1/N2/N3 (extract_core)
# ---------------------------------------------------------------------------
async def fetch_and_parse(url: str, log) -> tuple[str | None, str | None]:
    """Retourne (texte, md5). Cascade N1 (trafilatura/PyMuPDF) -> N2 (Readability).
    N3 TinyFish volontairement désactivé ici (monitoring/refresh: pas de crédit)."""
    try:
        res = await extract_cascade(url, min_chars=200, allow_tinyfish=False, log=log)
    except Exception as e:
        log(f"fetch {domain_of(url)}: échec ({type(e).__name__})")
        return None, None
    text = res["text"]
    if text:
        log(f"fetch {domain_of(url)}: {len(text)} chars via {res['level']} (md5 {(res['md5'] or '')[:8]}…)")
    return (text[:10000] if text else None), res["md5"]


# ---------------------------------------------------------------------------
# 4. Extraction JSON stricte — délégué à llm_core (cascade + fallback)
# ---------------------------------------------------------------------------
async def extract_ports_llm(context: str, zone: dict, gemini_key: str | None,
                            emergent_key: str | None, log) -> list[dict]:
    settings = {"gemini_api_key": gemini_key or ""}
    try:
        return await extract_ports(context, zone, settings=settings, log=log)
    except Exception as e:
        log(f"LLM: échec de tous les backends ({type(e).__name__}: {str(e)[:100]})")
        return []


_normalize_name = normalize_name  # rétrocompat


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

    # --- Monitoring MD5 + sémantique prioritaire : re-fetch des sources CONNUES
    # avant toute recherche. Si le contenu n'a pas changé (hash identique OU
    # similarité cosinus >= 0.95), aucune ré-extraction. ---
    known_hashes = zone.get("source_hashes") or {}
    if not force and known_hashes and zone.get("status") in ("ia", "ia_sans_source") and zone.get("poe_count", 0) > 0:
        fresh, fresh_texts = {}, {}
        for url in list(known_hashes.keys())[:3]:
            text, md5 = await fetch_and_parse(url, log)
            if md5:
                fresh[url] = md5
            if text:
                fresh_texts[url] = text
        if fresh and fresh == known_hashes:
            log("MD5 inchangés (sources connues) — ré-extraction sautée")
            await db.eez_zones.update_one({"mrgid": int(mrgid)}, {"$set": {"checked_at": now_iso()}})
            return await db.eez_zones.find_one({"mrgid": int(mrgid)})
        old_excerpts = zone.get("source_excerpts") or {}
        if fresh and old_excerpts and all(
            u in old_excerpts and u in fresh_texts and not content_changed(old_excerpts[u], fresh_texts[u], 0.95)
            for u in fresh
        ):
            log("monitoring sémantique: similarité cosinus >= 0.95 — changement HTML mineur, ré-extraction sautée")
            await db.eez_zones.update_one({"mrgid": int(mrgid)}, {"$set": {
                "checked_at": now_iso(), "source_hashes": {**known_hashes, **fresh},
            }})
            return await db.eez_zones.find_one({"mrgid": int(mrgid)})
        log("contenu source modifié ou source injoignable — pipeline complet relancé")

    # --- Recherche (niveau 1) ---
    query = f"official ports of entry customs clearance foreign yachts pleasure craft {name}"
    candidates = await search_searxng(query, log)
    synthesis = None
    if not candidates:
        candidates, synthesis = await search_grounded(zone, whitelist, log)
    candidates = serp_filter(candidates)

    # --- Gatekeeper + bootstrapping des exceptions ---
    official = [c for c in candidates if url_allowed(c["url"], whitelist)]

    # --- Level-2 Retry Query : recherche ciblée sur l'organisation douanière ---
    if not official:
        log("Level-2 retry: recherche ciblée sur l'organisation douanière nationale")
        q2 = (f"{zone.get('sovereign') or name} customs administration official website "
              f"designated ports of entry clearance pleasure craft {name}")
        extra = await search_searxng(q2, log)
        syn2 = None
        if not extra:
            extra, syn2 = await search_grounded(zone, whitelist, log, query_override=(
                f"Find the OFFICIAL national customs administration / border agency website of "
                f"{zone.get('sovereign') or name} and the page listing designated ports of entry "
                f"(clearance ports) for foreign pleasure craft in {name}. Cite the official URLs."
            ))
        if syn2 and not synthesis:
            synthesis = syn2
        known_domains = {c["domain"] for c in candidates}
        extra = serp_filter([c for c in (extra or []) if c.get("domain") and c["domain"] not in known_domains])
        if extra:
            log(f"Level-2 retry: {len(extra)} source(s) supplémentaires trouvées")
            candidates += extra
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

    # --- Collecte + hash MD5 (cascade N1/N2, depth=2 sélectif) ---
    tf_key = (os.environ.get("TINYFISH_API_KEY") or "").strip() or None
    texts, hashes, used_sources, excerpts = [], {}, [], {}
    for c in official[:3]:
        try:
            res = await extract_cascade(c["url"], min_chars=200, allow_tinyfish=False, log=log)
        except Exception as e:
            log(f"fetch {c['domain']}: échec ({type(e).__name__})")
            continue
        if res["md5"]:
            hashes[c["url"]] = res["md5"]
        text = res["text"]
        log(f"fetch {c['domain']}: {len(text)} chars via {res['level']}")
        # Depth=2 sélectif : liens internes réglementaires (/annuaire, /contacts, /clearance…)
        if len(text) < 400 and res.get("html"):
            for fu in internal_followups(res["html"], c["url"], limit=2):
                try:
                    sub = await extract_cascade(fu, min_chars=200, allow_tinyfish=False, log=log)
                except Exception:
                    continue
                if sub["text"]:
                    log(f"depth-2: {fu[:80]} → {len(sub['text'])} chars")
                    text = (text + "\n" + sub["text"]).strip()
        if text and len(text) > 200:
            texts.append(f"[SOURCE: {c['url']}]\n{text[:10000]}")
            excerpts[c["url"]] = text[:2500]
            used_sources.append({"url": c["url"], "domain": c["domain"],
                                 "md5": hashes.get(c["url"]), "collected_at": now_iso()})

    # --- N3 TinyFish : UN SEUL appel max par zone, uniquement si N1+N2 ont tout raté ---
    if not texts and tf_key and official:
        target = official[0]
        log(f"N1/N2 épuisés sur toutes les sources → N3 TinyFish sur {target['domain']} (dernier recours, cap 120s)")
        try:
            res = await extract_cascade(target["url"], min_chars=200, allow_tinyfish=True,
                                        tinyfish_key=tf_key, log=log)
            if res["text"] and len(res["text"]) > 200:
                hashes[target["url"]] = res["md5"]
                texts.append(f"[SOURCE: {target['url']}]\n{res['text'][:10000]}")
                excerpts[target["url"]] = res["text"][:2500]
                used_sources.append({"url": target["url"], "domain": target["domain"],
                                     "md5": res["md5"], "collected_at": now_iso()})
        except Exception as e:
            log(f"N3 TinyFish: échec ({type(e).__name__})")

    # --- Monitoring MD5 : skip si contenu inchangé ---
    old_hashes = zone.get("source_hashes") or {}
    if (not force and hashes and old_hashes and hashes == old_hashes
            and zone.get("status") in ("ia", "ia_sans_source") and zone.get("poe_count", 0) > 0):
        log("MD5 inchangés — ré-extraction sautée (contenu source identique)")
        await db.eez_zones.update_one({"mrgid": int(mrgid)}, {"$set": {"checked_at": now_iso()}})
        return await db.eez_zones.find_one({"mrgid": int(mrgid)})

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
        await db.eez_zones.update_one({"mrgid": int(mrgid)}, {"$set": {
            "status": "erreur", "last_error": "aucun contenu source exploitable",
            "generated_at": now_iso(), "sources": used_sources, "source_hashes": hashes,
        }})
        log("ERREUR: aucun contenu exploitable")
        return await db.eez_zones.find_one({"mrgid": int(mrgid)})

    # --- RAG local : sur les contextes longs, seuls les chunks pertinents partent au LLM ---
    context = "\n\n".join(context_parts)
    if len(context) > 15000:
        context = select_context(f"official ports of entry customs clearance foreign yachts {name}",
                                 context, max_chars=15000)
        log(f"RAG: contexte condensé à {len(context)} chars (chunks pertinents par similarité cosinus)")

    # --- Extraction LLM (cascade llm_core) ---
    ports = await extract_ports_llm(context, zone, gemini_key, emergent_key, log)

    # --- Géocodage (geo_core) + validation spatiale ---
    geom = None
    try:
        geom = await asyncio.to_thread(shape, zone["geometry"])
        prepared = prep(geom)
    except Exception:
        prepared = None

    docs = []
    seen_names = set()
    for p in ports[:25]:
        norm = normalize_name(p["name"])
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
        # Déduplication interne (dedup_core: Haversine <500m + fuzzy >60%)
        docs = deduplicate_list(docs, title_key="name")
        # Upsert NON-DESTRUCTIF : les PoE existants sont enrichis, jamais purgés
        # (préserve les champs Bottom-Up: osm_confidence, spatial_anomaly…).
        existing_ports = await db.poe_ports.find({"mrgid": int(mrgid)}).to_list(500)
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
        poe_count = await db.poe_ports.count_documents({"mrgid": int(mrgid)})
        await db.eez_zones.update_one({"mrgid": int(mrgid)}, {"$set": {
            "status": status,
            "poe_count": poe_count,
            "generated_at": now_iso(),
            "sources": used_sources,
            "source_hashes": hashes,
            "source_excerpts": excerpts,
            "last_error": None,
        }})
        log(f"terminé: {inserted} nouveau(x) PoE, {merged} fusionné(s) — total zone {poe_count}, statut {status}")
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
