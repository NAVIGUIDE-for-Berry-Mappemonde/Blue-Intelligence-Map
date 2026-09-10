"""Mode Science — moissonnage des catalogues océanographiques ouverts.

Contrat :
  * objet = jeu de données scientifique localisé (fiche catalogue) ou
    flotteur Argo (dernière position de profil) — jamais une mesure brute
  * identité = ``{source}:{id natif}`` (uuid GeoNetwork, n° EDMED, WMO Argo)
  * chaque fiche porte l'URL de sa page portail (+ DOI quand présent)
  * pas de purge (upsert non destructif), pas de LLM, pas de scraping :
    uniquement des API structurées (Elasticsearch GeoNetwork, SPARQL, ERDDAP)
  * fiches sans emprise exploitable (globales ou sans géométrie) : conservées
    en base mais jamais posées sur la carte

Sources :
  * ``sextant`` — catalogue Sextant (Ifremer / SISMER), API JSON GeoNetwork 4
  * ``odatis``  — sous-portail ODATIS (pôle océan Data Terra) du même GeoNetwork
  * ``edmed``   — répertoire EDMED de SeaDataNet, endpoint SPARQL (WKT)
  * ``argo``    — index des profils Argo (ERDDAP Ifremer / Coriolis),
    dernière position par flotteur sur une fenêtre glissante
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Iterable

import httpx

from app.services.marina_build import USER_AGENT

SCHEMA = "science_v1"

GN_ES_PAGE_SIZE = 200
GN_ES_HARD_CAP = 10_000  # au-delà, l'API Elasticsearch exige search_after
DEFAULT_CATALOG_MAX = 2000
DEFAULT_ARGO_DAYS = 30
EDMED_PAGE_SIZE = 400

GN_PORTALS: dict[str, dict[str, str]] = {
    "sextant": {
        "es_url": "https://sextant.ifremer.fr/geonetwork/srv/api/search/records/_search",
        "record_url": "https://sextant.ifremer.fr/geonetwork/srv/fre/catalog.search#/metadata/{uuid}",
    },
    "odatis": {
        "es_url": "https://sextant.ifremer.fr/geonetwork/ODATIS/api/search/records/_search",
        "record_url": "https://sextant.ifremer.fr/geonetwork/ODATIS/fre/catalog.search#/metadata/{uuid}",
    },
}
GN_SOURCE_FIELDS = [
    "resourceTitleObject", "resourceAbstractObject", "geom", "uuid",
    "link", "OrgForResource", "resourceDate", "changeDate",
]

EDMED_SPARQL = "https://edmed.seadatanet.org/sparql/sparql"
EDMED_QUERY = (
    "PREFIX dct: <http://purl.org/dc/terms/> "
    "PREFIX dcat: <http://www.w3.org/ns/dcat#> "
    "PREFIX locn: <http://www.w3.org/ns/locn#> "
    "SELECT ?s ?title ?desc ?geom WHERE { "
    "?s a dcat:Dataset ; dct:title ?title . "
    "OPTIONAL { ?s dct:description ?desc } "
    "OPTIONAL { ?s dct:spatial ?sp . ?sp locn:geometry ?geom } "
    "} ORDER BY ?s LIMIT {limit} OFFSET {offset}"
)

ARGO_ERDDAP_INDEX = "https://erddap.ifremer.fr/erddap/tabledap/ArgoFloats-index.json"
ARGO_FLOAT_URL = "https://fleetmonitoring.euro-argo.eu/float/{wmo}"

SOURCES = ("sextant", "odatis", "edmed", "argo")

SOURCE_LABELS = {
    "sextant": "Sextant · Ifremer / SISMER",
    "odatis": "ODATIS · Data Terra",
    "edmed": "EDMED · SeaDataNet",
    "argo": "Argo · Coriolis",
}

# Codes DAC de l'index Argo (colonne institution) — jamais inventés.
ARGO_INSTITUTIONS = {
    "AO": "AOML (USA)",
    "BO": "BODC (UK)",
    "CS": "CSIRO (Australia)",
    "GE": "BSH (Germany)",
    "HZ": "CSIO (China)",
    "IF": "Ifremer (France)",
    "IN": "INCOIS (India)",
    "JA": "JMA (Japan)",
    "KM": "KMA (Korea)",
    "KO": "KIOST (Korea)",
    "ME": "MEDS (Canada)",
    "NM": "NMDIS (China)",
}
ARGO_OCEANS = {"A": "Atlantic", "P": "Pacific", "I": "Indian"}

# Emprise « globale » : la fiche couvre (presque) tout le globe — la poser
# au centre (0, 0) n'aurait aucun sens de localisation.
GLOBAL_MIN_WIDTH_DEG = 350.0
GLOBAL_MIN_HEIGHT_DEG = 160.0

SLIM_PROJECTION = {
    "_id": 1,
    "kind": 1,
    "source": 1,
    "name": 1,
    "provider": 1,
    "abstract": 1,
    "url": 1,
    "doi": 1,
    "lat": 1,
    "lon": 1,
    "bbox": 1,
    "date": 1,
    "profile_date": 1,
    "cycle": 1,
    "ocean": 1,
    "wmo": 1,
    "fetched_at": 1,
}

_WKT_PAIR_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)")
_ARGO_CYCLE_RE = re.compile(r"_(\d+)D?\.nc$", re.I)

FetchGn = Callable[[httpx.AsyncClient, str, int, int], Awaitable[list[dict]]]
FetchEdmed = Callable[[httpx.AsyncClient, int, int], Awaitable[list[dict]]]
FetchArgo = Callable[[httpx.AsyncClient, int], Awaitable[dict]]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Emprises : GeoJSON (GeoNetwork) et WKT (EDMED) → bbox (w, s, e, n) → centre
# ---------------------------------------------------------------------------

def _iter_positions(coords: Any):
    """Descend récursivement une structure de coordonnées GeoJSON."""
    if not isinstance(coords, (list, tuple)) or not coords:
        return
    head = coords[0]
    if isinstance(head, (int, float)):
        if len(coords) >= 2:
            yield float(coords[0]), float(coords[1])
        return
    for sub in coords:
        yield from _iter_positions(sub)


def _bbox_of_pairs(pairs: list[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    pts = [
        (lon, lat) for lon, lat in pairs
        if -180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0
    ]
    if not pts:
        return None
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    w, e = min(lons), max(lons)
    s, n = min(lats), max(lats)
    # Antiméridien : si l'étendue naïve dépasse 180°, retenter en 0–360.
    # Garde-fou : une emprise mondiale [-180, 180] dégénère en largeur ~0
    # après le modulo — on la laisse alors telle quelle (fiche « globale »).
    if e - w > 180.0:
        shifted = [lon % 360.0 for lon in lons]
        w2, e2 = min(shifted), max(shifted)
        if 1e-6 < e2 - w2 < e - w:
            w, e = w2 - 360.0 if w2 > 180.0 else w2, e2 - 360.0 if e2 > 180.0 else e2
            if e < w:
                w, e = w, e + 360.0
    return (w, s, e, n)


def bbox_from_geom(geom: Any) -> tuple[float, float, float, float] | None:
    """bbox (w, s, e, n) d'une géométrie GeoJSON (ou d'une liste de géométries)."""
    geoms = geom if isinstance(geom, list) else [geom]
    pairs: list[tuple[float, float]] = []
    for g in geoms:
        if not isinstance(g, dict):
            continue
        pairs.extend(_iter_positions(g.get("coordinates")))
    return _bbox_of_pairs(pairs)


def bbox_from_wkt(wkt: str | None) -> tuple[float, float, float, float] | None:
    """bbox d'un WKT EDMED (POLYGON / MULTIPOLYGON / POINT, ordre lon lat)."""
    if not wkt or not str(wkt).strip():
        return None
    pairs = [(float(a), float(b)) for a, b in _WKT_PAIR_RE.findall(str(wkt))]
    return _bbox_of_pairs(pairs)


def is_global_bbox(bbox: tuple[float, float, float, float] | None) -> bool:
    if not bbox:
        return False
    w, s, e, n = bbox
    return (e - w) >= GLOBAL_MIN_WIDTH_DEG and (n - s) >= GLOBAL_MIN_HEIGHT_DEG


def bbox_center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    w, s, e, n = bbox
    lat = (s + n) / 2.0
    lon = (w + e) / 2.0
    if lon > 180.0:
        lon -= 360.0
    elif lon < -180.0:
        lon += 360.0
    return (lat, lon)


# ---------------------------------------------------------------------------
# GeoNetwork (Sextant / ODATIS) — hit Elasticsearch → fiche
# ---------------------------------------------------------------------------

def _first_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list):
        for item in value:
            got = _first_str(item)
            if got:
                return got
    if isinstance(value, dict):
        return _first_str(value.get("default"))
    return None


def _gn_link_url(link: dict) -> str | None:
    url = link.get("url")
    if isinstance(url, dict):
        url = url.get("default")
    if isinstance(url, str) and url.strip():
        return url.strip()
    obj = link.get("urlObject")
    if isinstance(obj, dict):
        got = obj.get("default")
        if isinstance(got, str) and got.strip():
            return got.strip()
    return None


def _gn_doi(links: Any) -> str | None:
    if not isinstance(links, list):
        return None
    for link in links:
        if not isinstance(link, dict):
            continue
        url = _gn_link_url(link)
        if not url:
            continue
        protocol = str(link.get("protocol") or "")
        if "doi.org/" in url or protocol.upper() == "DOI":
            return url
    return None


def _gn_date(src: dict) -> str | None:
    dates = src.get("resourceDate")
    if isinstance(dates, list):
        by_type = {str(d.get("type")): str(d.get("date") or "") for d in dates if isinstance(d, dict)}
        for key in ("publication", "revision", "creation"):
            if by_type.get(key):
                return by_type[key][:10]
    change = src.get("changeDate")
    if isinstance(change, str) and change:
        return change[:10]
    return None


def dataset_from_gn_hit(hit: dict, source: str) -> dict | None:
    """Fiche Science depuis un hit de l'API de recherche GeoNetwork 4."""
    src = hit.get("_source") or {}
    uuid = str(src.get("uuid") or hit.get("_id") or "").strip()
    title = _first_str(src.get("resourceTitleObject"))
    if not uuid or not title:
        return None
    bbox = bbox_from_geom(src.get("geom"))
    lat = lon = None
    if bbox and not is_global_bbox(bbox):
        lat, lon = bbox_center(bbox)
    portal = GN_PORTALS.get(source) or GN_PORTALS["sextant"]
    abstract = _first_str(src.get("resourceAbstractObject")) or ""
    return {
        "_id": f"{source}:{uuid}",
        "kind": "dataset",
        "source": source,
        "native_id": uuid,
        "name": title[:240],
        "abstract": abstract[:600],
        "url": portal["record_url"].format(uuid=uuid),
        "doi": _gn_doi(src.get("link")),
        "provider": _first_str(src.get("OrgForResource")),
        "date": _gn_date(src),
        "lat": lat,
        "lon": lon,
        "bbox": list(bbox) if bbox else None,
        "global": is_global_bbox(bbox),
    }


# ---------------------------------------------------------------------------
# EDMED (SeaDataNet) — binding SPARQL → fiche
# ---------------------------------------------------------------------------

def _binding_value(binding: dict, key: str) -> str | None:
    cell = binding.get(key)
    if isinstance(cell, dict):
        val = cell.get("value")
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def dataset_from_edmed_binding(binding: dict) -> dict | None:
    """Fiche Science depuis une ligne SPARQL EDMED (une ligne par géométrie)."""
    subject = _binding_value(binding, "s")
    title = _binding_value(binding, "title")
    if not subject or not title:
        return None
    native = subject.rstrip("/").rsplit("/", 1)[-1]
    if not native:
        return None
    bbox = bbox_from_wkt(_binding_value(binding, "geom"))
    lat = lon = None
    if bbox and not is_global_bbox(bbox):
        lat, lon = bbox_center(bbox)
    desc = _binding_value(binding, "desc") or ""
    return {
        "_id": f"edmed:{native}",
        "kind": "dataset",
        "source": "edmed",
        "native_id": native,
        "name": title[:240],
        "abstract": desc[:600],
        "url": subject if subject.endswith("/") else subject + "/",
        "doi": None,
        "provider": "SeaDataNet EDMED",
        "date": None,
        "lat": lat,
        "lon": lon,
        "bbox": list(bbox) if bbox else None,
        "global": is_global_bbox(bbox),
    }


# ---------------------------------------------------------------------------
# Argo (Coriolis / ERDDAP) — index des profils → dernière position par flotteur
# ---------------------------------------------------------------------------

def wmo_from_file(path: str | None) -> tuple[str | None, str | None, int | None]:
    """(wmo, dac, cycle) depuis un chemin d'index ``aoml/1901514/profiles/R1901514_538.nc``."""
    if not path:
        return None, None, None
    parts = str(path).split("/")
    if len(parts) < 2 or not parts[1].isdigit():
        return None, None, None
    dac = parts[0] or None
    wmo = parts[1]
    cycle = None
    m = _ARGO_CYCLE_RE.search(parts[-1])
    if m:
        cycle = int(m.group(1))
    return wmo, dac, cycle


def argo_docs_from_index(table: dict) -> list[dict]:
    """Docs flotteurs (dernière position par WMO) depuis la table ERDDAP."""
    cols = table.get("columnNames") or []
    rows = table.get("rows") or []
    idx = {name: i for i, name in enumerate(cols)}
    required = ("file", "date", "latitude", "longitude")
    if any(k not in idx for k in required):
        return []
    latest: dict[str, dict] = {}
    for row in rows:
        try:
            path = row[idx["file"]]
            date = str(row[idx["date"]] or "")
            lat = float(row[idx["latitude"]])
            lon = float(row[idx["longitude"]])
        except (TypeError, ValueError, IndexError):
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        wmo, dac, cycle = wmo_from_file(path)
        if not wmo or not date:
            continue
        current = latest.get(wmo)
        if current and current["profile_date"] >= date:
            continue
        ocean = str(row[idx["ocean"]] or "") if "ocean" in idx else ""
        inst = str(row[idx["institution"]] or "") if "institution" in idx else ""
        latest[wmo] = {
            "_id": f"argo:{wmo}",
            "kind": "argo_float",
            "source": "argo",
            "native_id": wmo,
            "wmo": wmo,
            "dac": dac,
            "cycle": cycle,
            "name": f"Argo {wmo}",
            "abstract": "",
            "url": ARGO_FLOAT_URL.format(wmo=wmo),
            "doi": None,
            "provider": ARGO_INSTITUTIONS.get(inst, inst or None),
            "ocean": ARGO_OCEANS.get(ocean, ocean or None),
            "profile_date": date,
            "date": date[:10],
            "lat": lat,
            "lon": lon,
            "bbox": None,
            "global": False,
        }
    return sorted(latest.values(), key=lambda d: d["wmo"])


# ---------------------------------------------------------------------------
# Persistance (upsert non destructif) et GeoJSON maigre
# ---------------------------------------------------------------------------

async def upsert_science(coll, cand: dict, fetched_at: str) -> str:
    doc = {**cand, "fetched_at": fetched_at, "schema": SCHEMA}
    existing = await coll.find_one({"_id": doc["_id"]})
    if existing:
        await coll.update_one({"_id": doc["_id"]}, {"$set": {k: v for k, v in doc.items() if k != "_id"}})
        return "updated"
    await coll.insert_one(doc)
    return "inserted"


def slim_feature(doc: dict) -> dict:
    lat = float(doc["lat"])
    lon = float(doc["lon"])
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "id": doc.get("_id"),
            "kind": doc.get("kind") or "dataset",
            "source": doc.get("source"),
            "name": doc.get("name") or "",
            "provider": doc.get("provider"),
            "abstract": doc.get("abstract"),
            "url": doc.get("url"),
            "doi": doc.get("doi"),
            "bbox": doc.get("bbox"),
            "date": doc.get("date"),
            "profile_date": doc.get("profile_date"),
            "cycle": doc.get("cycle"),
            "ocean": doc.get("ocean"),
            "wmo": doc.get("wmo"),
            "fetched_at": doc.get("fetched_at"),
        },
    }


def to_slim_geojson(docs: Iterable[dict]) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            slim_feature(d) for d in docs
            if d.get("lat") is not None and d.get("lon") is not None
        ],
        "attribution": (
            "Sextant © Ifremer/SISMER · ODATIS (Data Terra) · EDMED © SeaDataNet "
            "· Argo (Coriolis ERDDAP) — métadonnées ouvertes, liens vers les portails"
        ),
    }


async def ensure_indexes(coll) -> None:
    try:
        await coll.create_index("source")
        await coll.create_index("kind")
        await coll.create_index("name")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Fetchers réseau (injectables pour les tests)
# ---------------------------------------------------------------------------

async def fetch_gn_page(client: httpx.AsyncClient, es_url: str, frm: int, size: int) -> list[dict]:
    body = {
        "query": {"match_all": {}},
        "from": frm,
        "size": size,
        "sort": [{"changeDate": "desc"}],
        "_source": GN_SOURCE_FIELDS,
    }
    r = await client.post(
        es_url, json=body,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    return ((data.get("hits") or {}).get("hits")) or []


async def fetch_edmed_page(client: httpx.AsyncClient, limit: int, offset: int) -> list[dict]:
    query = EDMED_QUERY.replace("{limit}", str(int(limit))).replace("{offset}", str(int(offset)))
    r = await client.get(
        EDMED_SPARQL,
        params={"query": query, "output": "json"},
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
        timeout=90,
    )
    r.raise_for_status()
    data = r.json()
    return ((data.get("results") or {}).get("bindings")) or []


async def fetch_argo_index(client: httpx.AsyncClient, days: int) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=int(days))).strftime("%Y-%m-%dT00:00:00Z")
    url = (
        f"{ARGO_ERDDAP_INDEX}"
        f"?file,date,latitude,longitude,ocean,profiler_type,institution,date_update"
        f"&date%3E={since}"
    )
    r = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=180)
    if r.status_code == 404:
        # ERDDAP répond 404 quand la contrainte ne matche aucune ligne.
        return {"columnNames": [], "rows": []}
    r.raise_for_status()
    data = r.json()
    return data.get("table") or {"columnNames": [], "rows": []}


# ---------------------------------------------------------------------------
# Orchestrateur
# ---------------------------------------------------------------------------

def _rule(rule_id: str, fallback):
    try:
        from app.core.run_rules import get_rule
        return get_rule(rule_id, fallback)
    except Exception:
        return fallback


def _empty_source_summary() -> dict:
    return {"fetched": 0, "inserted": 0, "updated": 0, "unlocated": 0, "error": None}


async def _harvest_docs(coll, docs: Iterable[dict], summary: dict, fetched_at: str) -> None:
    for cand in docs:
        result = await upsert_science(coll, cand, fetched_at)
        if result == "inserted":
            summary["inserted"] += 1
        else:
            summary["updated"] += 1
        if cand.get("lat") is None:
            summary["unlocated"] += 1


async def build_science(
    *,
    coll,
    state,
    sources: tuple[str, ...] | list[str] | None = None,
    client: httpx.AsyncClient | None = None,
    max_records: int | None = None,
    argo_days: int | None = None,
    fetch_gn: FetchGn | None = None,
    fetch_edmed: FetchEdmed | None = None,
    fetch_argo: FetchArgo | None = None,
    run_id: str | None = None,
) -> dict:
    """Moissonne les sources demandées vers la collection live (upsert, no purge)."""
    state.running = True
    state.started_at = time.time()
    state.finished_at = None
    state.error = None
    state.logs = []
    state.summary = None
    state.cancel = False
    state.run_id = run_id

    enabled = [s for s in (sources or SOURCES) if s in SOURCES]
    if not enabled:
        enabled = list(SOURCES)
    cap = int(max_records if max_records is not None else _rule("science.catalog_max_records", DEFAULT_CATALOG_MAX))
    cap = max(1, min(cap, GN_ES_HARD_CAP))
    days = int(argo_days if argo_days is not None else _rule("science.argo_window_days", DEFAULT_ARGO_DAYS))
    fetched_at = now_iso()

    state.total = len(enabled)
    state.progress = 0
    state.log(
        f"Moisson Science : sources={','.join(enabled)} · cap catalogue={cap} · fenêtre Argo={days} j"
    )

    per_source: dict[str, dict] = {}
    own_client = client is None
    http = client or httpx.AsyncClient(headers={"User-Agent": USER_AGENT})
    try:
        await ensure_indexes(coll)
        for source in enabled:
            if state.cancel:
                state.log("Stop demandé — moisson interrompue")
                break
            summary = _empty_source_summary()
            per_source[source] = summary
            state.log(f"[{source}] {SOURCE_LABELS.get(source, source)}")
            try:
                if source in GN_PORTALS:
                    es_url = GN_PORTALS[source]["es_url"]
                    frm = 0
                    while frm < cap and not state.cancel:
                        size = min(GN_ES_PAGE_SIZE, cap - frm)
                        hits = await (fetch_gn or fetch_gn_page)(http, es_url, frm, size)
                        if not hits:
                            break
                        docs = [d for d in (dataset_from_gn_hit(h, source) for h in hits) if d]
                        summary["fetched"] += len(hits)
                        await _harvest_docs(coll, docs, summary, fetched_at)
                        state.log(
                            f"[{source}] page {frm}-{frm + len(hits)} : "
                            f"+{summary['inserted']} / ~{summary['updated']}"
                        )
                        if len(hits) < size:
                            break
                        frm += size
                elif source == "edmed":
                    offset = 0
                    while offset < cap and not state.cancel:
                        limit = min(EDMED_PAGE_SIZE, cap - offset)
                        bindings = await (fetch_edmed or fetch_edmed_page)(http, limit, offset)
                        if not bindings:
                            break
                        # Une ligne SPARQL par géométrie : on garde une fiche
                        # par identifiant, de préférence localisée.
                        page_docs: dict[str, dict] = {}
                        for b in bindings:
                            doc = dataset_from_edmed_binding(b)
                            if not doc:
                                continue
                            cur = page_docs.get(doc["_id"])
                            if cur is None or (cur.get("lat") is None and doc.get("lat") is not None):
                                page_docs[doc["_id"]] = doc
                        summary["fetched"] += len(bindings)
                        await _harvest_docs(coll, page_docs.values(), summary, fetched_at)
                        state.log(
                            f"[edmed] offset {offset} : +{summary['inserted']} / ~{summary['updated']}"
                        )
                        if len(bindings) < limit:
                            break
                        offset += limit
                elif source == "argo":
                    table = await (fetch_argo or fetch_argo_index)(http, days)
                    docs = argo_docs_from_index(table)
                    summary["fetched"] = len(table.get("rows") or [])
                    await _harvest_docs(coll, docs, summary, fetched_at)
                    state.log(
                        f"[argo] {summary['fetched']} profils → {len(docs)} flotteurs actifs "
                        f"(+{summary['inserted']} / ~{summary['updated']})"
                    )
            except Exception as exc:
                summary["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
                state.log(f"[{source}] ERREUR {summary['error']}")
            state.progress += 1
    finally:
        if own_client:
            await http.aclose()

    result = {
        "schema": SCHEMA,
        "sources": per_source,
        "inserted": sum(s["inserted"] for s in per_source.values()),
        "updated": sum(s["updated"] for s in per_source.values()),
        "unlocated": sum(s["unlocated"] for s in per_source.values()),
        "cancelled": state.cancel,
        "catalog_max_records": cap,
        "argo_window_days": days,
    }
    state.summary = result
    state.log(f"Moisson Science terminée : +{result['inserted']} / ~{result['updated']}")
    state.finished_at = time.time()
    state.running = False
    return result
