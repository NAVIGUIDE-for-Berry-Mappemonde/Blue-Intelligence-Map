"""Mode AMP — Aires Marines Protégées (ProtectedSeas Navigator).

Deux URL distinctes par site :

* ``manager_url`` — champ ProtectedSeas ``url`` (alias Website), page
  institutionnelle / gestionnaire.
* ``visit_url`` — procédures de visite ou d'entrée (permis, mouillage,
  formalités). **Jamais** une copie du site gestionnaire.

La couche polygones est servie par bbox ; l'enrichissement visite est
stocké dans ``amp_sites`` (pas l'ancienne ``mpa_cache``).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Any, Iterable

import httpx

from app.core.run_rules import catalog_default

ARCGIS_AMP_URL = (
    "https://services9.arcgis.com/lm7wE8a9YA9rKfzy/arcgis/rest/services/"
    "Navigator_AllSites_010925_attributes/FeatureServer/0/query"
)

AMP_OUT_FIELDS = (
    "SITE_ID,site_name,url,country,state,managing_authority,designation,"
    "category_name,wdpa_id,iucn_cat,purpose,lfp,other_helpful_links,"
    "gov_level,year_est"
)
ATTR_OUT_FIELDS = "SITE_ID,site_name,url,other_helpful_links,purpose"
ATTR_REFRESH_BATCH = 80

VISIT_STATUSES = (
    "none",
    "found",
    "rejected_same_as_manager",
    "not_found",
)

_URL_RE = re.compile(r"https?://[^\s,;|<>\"']+", re.I)
_VISIT_HINT = (
    r"visite|visits?|visiter|plaisance|mouillage|anchor(?:ing)?|moorings?|"
    r"permits?|permis|autorisation|r[eé]glement(?:ation)?s?|"
    r"entr[eé]e|entrer|entry|formalit\w*|pleasure.?craft|yachts?|"
    r"recreational|clearance|access|acceso|fondeo|amarr\w*|navegac\w*|"
    r"div(?:e|ing)|plonge(?:e|r)?|rules?|normativa|visitors?|"
    r"turismo|tourisme|nautism\w*|zoning|regulat\w*"
)
VISIT_HINT_RE = re.compile(rf"(?:^|[\W_])(?:{_VISIT_HINT})(?:$|[\W_])", re.I)
_NAME_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9]{4,}")
_NAME_STOP = frozenset({
    "area", "aire", "amp", "mpa", "zone", "zona", "park", "parc", "marine",
    "marin", "natural", "naturel", "naturelle", "national", "nacional",
    "reserve", "reserva", "protected", "site", "sites", "gulf", "golfe",
    "golf", "port", "ports", "isla", "isle", "illes", "islas", "cape",
    "cabo", "west", "east", "north", "south", "nord", "sud", "ouest",
    "france", "french", "spain", "spanish", "italia", "italy", "waters",
    "mediterranean", "mediterranee", "special", "integral", "partial",
    "partiale", "protection", "protegida", "this", "that", "with", "from",
})

SLIM_PROJECTION = {
    "_id": 1,
    "site_id": 1,
    "name": 1,
    "country": 1,
    "state": 1,
    "designation": 1,
    "category_name": 1,
    "iucn_cat": 1,
    "purpose": 1,
    "lfp": 1,
    "managing_authority": 1,
    "gov_level": 1,
    "wdpa_id": 1,
    "year_est": 1,
    "manager_url": 1,
    "other_helpful_links": 1,
    "visit_url": 1,
    "visit_url_status": 1,
    "visit_url_source": 1,
    "lat": 1,
    "lon": 1,
    "fetched_at": 1,
    "enriched_at": 1,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_bbox(raw: str, *, max_w: float = 180.0,
               max_h: float = 90.0) -> tuple[float, float, float, float]:
    """Caps par défaut adaptés au rafraîchissement ProtectedSeas ; la lecture
    du cache (GET /amp) passe des caps monde entier (360×180)."""
    parts = [p.strip() for p in (raw or "").split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be minx,miny,maxx,maxy")
    minx, miny, maxx, maxy = (float(p) for p in parts)
    if minx >= maxx or miny >= maxy:
        raise ValueError("bbox min must be < max")
    if abs(maxx - minx) > max_w or abs(maxy - miny) > max_h:
        raise ValueError("bbox too large")
    return minx, miny, maxx, maxy


def bbox_span_deg(bbox: tuple[float, float, float, float]) -> float:
    return max(bbox[2] - bbox[0], bbox[3] - bbox[1])


def bbox_polygon(bbox: tuple[float, float, float, float]) -> dict:
    minx, miny, maxx, maxy = bbox
    ring = [[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]
    return {"type": "Polygon", "coordinates": [ring]}


def normalize_url(url: str | None) -> str | None:
    raw = (url or "").strip()
    if not raw or raw.lower() in ("null", "none", "n/a", "-"):
        return None
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    host = (parsed.netloc or "").lower()
    if not host:
        return None
    if host.startswith("www."):
        host = host[4:]
    path = (parsed.path or "").rstrip("/")
    return f"{(parsed.scheme or 'https').lower()}://{host}{path}"


def urls_equivalent(a: str | None, b: str | None) -> bool:
    na, nb = normalize_url(a), normalize_url(b)
    return bool(na and nb and na == nb)


def extract_urls(blob: str | None) -> list[str]:
    if not blob:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _URL_RE.findall(str(blob)):
        cleaned = match.rstrip(").,;]")
        norm = normalize_url(cleaned)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(cleaned.strip().rstrip(").,;]"))
    return out


def url_host(url: str | None) -> str | None:
    nu = normalize_url(url)
    if not nu:
        return None
    host = (urlparse(nu).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def is_manager_suburl(url: str | None, manager_url: str | None) -> bool:
    """Même hôte que le gestionnaire, chemin distinct — cas le plus fréquent."""
    if urls_equivalent(url, manager_url):
        return False
    hu, hm = url_host(url), url_host(manager_url)
    return bool(hu and hm and hu == hm)


def fold_text(value: str | None) -> str:
    raw = unicodedata.normalize("NFD", value or "")
    return "".join(ch for ch in raw if unicodedata.category(ch) != "Mn").lower()


def name_tokens(name: str | None) -> set[str]:
    return {
        tok for tok in _NAME_TOKEN_RE.findall(fold_text(name))
        if tok not in _NAME_STOP
    }


def name_matches(name: str | None, blob: str | None) -> bool:
    """Le nom du site doit apparaître dans l'URL / le titre (recherche hors hôte)."""
    toks = name_tokens(name)
    if not toks:
        return False
    hay = fold_text(blob)
    long_toks = {tok for tok in toks if len(tok) >= 5}
    if long_toks:
        return any(tok in hay for tok in long_toks)
    if len(toks) >= 2:
        return sum(1 for tok in toks if tok in hay) >= 2
    return next(iter(toks)) in hay


def split_protectedseas_website(raw: str | None) -> tuple[str | None, list[str]]:
    """Champ Website PS : parfois ``Label|https://a; Autre|https://b``."""
    urls = extract_urls(raw)
    if not urls:
        return normalize_url(raw), []
    return normalize_url(urls[0]), urls[1:]


def protectedseas_visit_blobs(doc: dict) -> list[str]:
    """Textes PS où une sous-URL de visite est souvent déjà écrite."""
    return [
        doc.get("other_helpful_links") or "",
        doc.get("ps_website_raw") or "",
        doc.get("purpose") or "",
    ]


def rank_visit_candidate(
    url: str | None,
    manager_url: str | None,
    *,
    curated: bool = False,
    title: str = "",
    snippet: str = "",
    name: str = "",
    require_name: bool = False,
) -> int:
    """Score > 0 = candidat. 0 = homepage, pub, ou hors sujet."""
    if not normalize_url(url) or urls_equivalent(url, manager_url):
        return 0
    path = urlparse(normalize_url(url) or "").path or ""
    blob = f"{url} {title} {snippet}"
    hint_path = bool(VISIT_HINT_RE.search(path))
    hint_blob = bool(VISIT_HINT_RE.search(blob))
    same = is_manager_suburl(url, manager_url)
    if require_name and not same and not name_matches(name, blob):
        return 0
    if require_name and not same and not path.strip("/"):
        return 0
    score = 0
    if hint_path:
        score += 4
    if hint_blob:
        score += 2
    if same and (hint_path or hint_blob or curated):
        score += 3
    if curated and same:
        score += 3
    if curated and not same and (hint_path or hint_blob):
        score += 2
    if curated and not same and not hint_path and not hint_blob:
        # Lien extra PS hors hôte, sans mot-clé : brochure / dive-map souvent utile.
        score += 2
    if not same and name_matches(name, blob):
        score += 2
    return score


def pick_visit_url(
    manager_url: str | None,
    other_helpful_links: str | None = None,
    discovered: str | None = None,
    extra_blobs: list[str] | None = None,
) -> tuple[str | None, str]:
    """Choisit une URL de visite distincte du gestionnaire.

    Privilegie une sous-URL du même hôte si elle existe, mais accepte
    un autre domaine déjà présent dans ProtectedSeas ou découvert.
    Retourne ``(url, status)``. ``status`` ∈ VISIT_STATUSES.
    """
    if discovered:
        if urls_equivalent(discovered, manager_url):
            return None, "rejected_same_as_manager"
        if normalize_url(discovered):
            return discovered.strip(), "found"

    ranked: list[tuple[int, str]] = []
    seen: set[str] = set()
    had_manager_copy = False
    had_distinct = False

    def _consider(raw: str, *, curated: bool, count_manager_copy: bool) -> None:
        nonlocal had_manager_copy, had_distinct
        if not normalize_url(raw):
            return
        if urls_equivalent(raw, manager_url):
            if count_manager_copy:
                had_manager_copy = True
            return
        had_distinct = True
        key = normalize_url(raw)
        if not key or key in seen:
            return
        score = rank_visit_candidate(raw, manager_url, curated=curated)
        if score <= 0:
            return
        seen.add(key)
        ranked.append((score, raw.strip()))

    for raw in extract_urls(other_helpful_links):
        _consider(raw, curated=True, count_manager_copy=True)
    for blob in extra_blobs or []:
        for raw in extract_urls(blob):
            # Tout lien distinct déjà écrit par ProtectedSeas compte, même hors hôte.
            _consider(raw, curated=True, count_manager_copy=False)

    if ranked:
        ranked.sort(key=lambda item: (-item[0], -len(urlparse(item[1]).path or "")))
        return ranked[0][1], "found"
    if had_manager_copy and not had_distinct:
        return None, "rejected_same_as_manager"
    blobs = [other_helpful_links or "", *(extra_blobs or [])]
    return None, "none" if not manager_url and not any(blobs) else "not_found"


def apply_visit_choice(doc: dict, *, discovered: str | None = None,
                       source: str | None = None) -> dict:
    """Écrit visit_url / status. N'écrase jamais visit_url avec manager_url."""
    raw_web = doc.get("ps_website_raw") or ""
    if not raw_web and "|" in str(doc.get("manager_url") or ""):
        raw_web = doc.get("manager_url") or ""
        doc["ps_website_raw"] = raw_web
    if raw_web:
        parsed, _ = split_protectedseas_website(raw_web)
        if parsed:
            doc["manager_url"] = parsed
    manager = doc.get("manager_url")
    extras = [b for b in protectedseas_visit_blobs(doc) if b]
    url, status = pick_visit_url(
        manager,
        doc.get("other_helpful_links"),
        discovered=discovered,
        extra_blobs=extras,
    )
    if url and urls_equivalent(url, manager):
        url, status = None, "rejected_same_as_manager"
    if url:
        doc["visit_url"] = url
        doc["visit_url_status"] = "found"
        helpful = extract_urls(doc.get("other_helpful_links"))
        default_src = "other_helpful_links" if any(
            urls_equivalent(url, h) for h in helpful) else "protectedseas"
        doc["visit_url_source"] = source or doc.get("visit_url_source") or default_src
        doc["enriched_at"] = now_iso()
    else:
        if not doc.get("visit_url") or urls_equivalent(doc.get("visit_url"), manager):
            doc["visit_url"] = None
        doc["visit_url_status"] = status
        if status != "found":
            doc.setdefault("visit_url_source", None)
    return doc


def _as_lfp(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if 0 <= n <= 5 else 0


def _ring_ok(ring) -> bool:
    """Mongo 2dsphere exige ≥ 3 sommets distincts (anneau fermé ≥ 4 positions)."""
    if not isinstance(ring, (list, tuple)) or len(ring) < 4:
        return False
    uniq: list[tuple[float, float]] = []
    for pt in ring:
        if not isinstance(pt, (list, tuple)) or len(pt) < 2:
            continue
        try:
            pair = (float(pt[0]), float(pt[1]))
        except (TypeError, ValueError):
            continue
        if not uniq or pair != uniq[-1]:
            uniq.append(pair)
    if len(uniq) >= 2 and uniq[0] == uniq[-1]:
        uniq = uniq[:-1]
    return len(uniq) >= 3


def sanitize_geometry(geom: dict | None) -> dict | None:
    """Retire les anneaux dégénérés (simplification ArcGIS) avant index 2dsphere."""
    if not geom or not isinstance(geom, dict):
        return None
    kind = geom.get("type")
    coords = geom.get("coordinates")
    if kind == "Polygon":
        rings = [r for r in (coords or []) if _ring_ok(r)]
        return {"type": "Polygon", "coordinates": rings} if rings else None
    if kind == "MultiPolygon":
        polys = []
        for poly in coords or []:
            rings = [r for r in (poly or []) if _ring_ok(r)]
            if rings:
                polys.append(rings)
        if not polys:
            return None
        if len(polys) == 1:
            return {"type": "Polygon", "coordinates": polys[0]}
        return {"type": "MultiPolygon", "coordinates": polys}
    if kind == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
        try:
            return {"type": "Point", "coordinates": [float(coords[0]), float(coords[1])]}
        except (TypeError, ValueError):
            return None
    return None


def _point_geom(lat: float | None, lon: float | None) -> dict | None:
    if lat is None or lon is None:
        return None
    return {"type": "Point", "coordinates": [float(lon), float(lat)]}


def _centroid(geom: dict | None) -> tuple[float | None, float | None]:
    if not geom:
        return None, None
    coords: list[list[float]] = []

    def walk(node):
        if not node:
            return
        if isinstance(node[0], (int, float)) and len(node) >= 2:
            coords.append([float(node[0]), float(node[1])])
            return
        for child in node:
            walk(child)

    walk(geom.get("coordinates"))
    if not coords:
        return None, None
    lon = sum(c[0] for c in coords) / len(coords)
    lat = sum(c[1] for c in coords) / len(coords)
    return lat, lon


def attrs_from_feature(feat: dict) -> dict:
    props = feat.get("properties") or {}
    site_id = str(props.get("SITE_ID") or props.get("site_id") or "").strip()
    website_raw = props.get("url") or ""
    manager, _ps_extras = split_protectedseas_website(website_raw)
    raw_geom = feat.get("geometry")
    lat, lon = _centroid(raw_geom)
    geom = sanitize_geometry(raw_geom) or _point_geom(lat, lon)
    doc = {
        "_id": site_id,
        "site_id": site_id,
        "name": (props.get("site_name") or "").strip() or site_id or "—",
        "country": props.get("country") or "",
        "state": props.get("state") or "",
        "designation": props.get("designation") or "",
        "category_name": props.get("category_name") or "",
        "iucn_cat": props.get("iucn_cat") or "",
        "purpose": props.get("purpose") or "",
        "lfp": _as_lfp(props.get("lfp")),
        "managing_authority": props.get("managing_authority") or "",
        "gov_level": props.get("gov_level") or "",
        "wdpa_id": props.get("wdpa_id") or "",
        "year_est": props.get("year_est"),
        "manager_url": manager,
        "ps_website_raw": website_raw,
        "other_helpful_links": props.get("other_helpful_links") or "",
        "geometry": geom,
        "lat": lat,
        "lon": lon,
        "fetched_at": now_iso(),
    }
    apply_visit_choice(doc, source="other_helpful_links")
    return doc


def merge_cached(existing: dict | None, incoming: dict) -> dict:
    """Garde l'URL de visite déjà validée ; ne la remplace pas par le gestionnaire."""
    if not existing:
        return incoming
    out = dict(incoming)
    prev = existing.get("visit_url")
    prev_status = existing.get("visit_url_status")
    if prev and not urls_equivalent(prev, incoming.get("manager_url")):
        out["visit_url"] = prev
        out["visit_url_status"] = prev_status or "found"
        out["visit_url_source"] = existing.get("visit_url_source")
        out["enriched_at"] = existing.get("enriched_at")
    elif not out.get("visit_url"):
        apply_visit_choice(out, source="other_helpful_links")
    return out


def public_properties(doc: dict, *, include_geometry_meta: bool = True) -> dict:
    manager = doc.get("manager_url")
    visit = doc.get("visit_url")
    if urls_equivalent(visit, manager):
        visit = None
    props = {
        "id": doc.get("site_id") or doc.get("_id"),
        "site_id": doc.get("site_id") or doc.get("_id"),
        "name": doc.get("name"),
        "country": doc.get("country"),
        "state": doc.get("state"),
        "designation": doc.get("designation"),
        "category_name": doc.get("category_name"),
        "iucn_cat": doc.get("iucn_cat"),
        "purpose": doc.get("purpose"),
        "lfp": _as_lfp(doc.get("lfp")),
        "managing_authority": doc.get("managing_authority"),
        "gov_level": doc.get("gov_level"),
        "wdpa_id": doc.get("wdpa_id"),
        "year_est": doc.get("year_est"),
        "manager_url": manager,
        "visit_url": visit,
        "visit_url_status": "none" if not visit else (doc.get("visit_url_status") or "found"),
        "visit_url_source": doc.get("visit_url_source") if visit else None,
        "lat": doc.get("lat"),
        "lon": doc.get("lon"),
    }
    if include_geometry_meta:
        props["fetched_at"] = doc.get("fetched_at")
        props["enriched_at"] = doc.get("enriched_at")
    return props


def to_feature(doc: dict, *, geometry: bool = True) -> dict:
    geom = doc.get("geometry") if geometry else None
    if not geom and doc.get("lon") is not None and doc.get("lat") is not None:
        geom = {"type": "Point", "coordinates": [doc["lon"], doc["lat"]]}
    return {
        "type": "Feature",
        "id": doc.get("site_id") or doc.get("_id"),
        "geometry": geom,
        "properties": public_properties(doc),
    }


def to_feature_collection(docs: Iterable[dict], *, geometry: bool = True,
                          extra: dict | None = None) -> dict:
    fc = {
        "type": "FeatureCollection",
        "features": [to_feature(d, geometry=geometry) for d in docs if d.get("site_id") or d.get("_id")],
    }
    if extra:
        fc.update(extra)
    return fc


def _offset_for_span(span: float) -> float:
    if span >= 8:
        return 0.05
    if span >= 4:
        return 0.02
    if span >= 2:
        return 0.008
    if span >= 1:
        return 0.003
    return 0.0008


async def fetch_arcgis(bbox: tuple[float, float, float, float], *,
                       max_features: int = 400) -> list[dict]:
    minx, miny, maxx, maxy = bbox
    span = bbox_span_deg(bbox)
    params = {
        "geometry": f"{minx},{miny},{maxx},{maxy}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": AMP_OUT_FIELDS,
        "outSR": 4326,
        "f": "geojson",
        "returnGeometry": "true",
        "maxAllowableOffset": _offset_for_span(span),
        "resultRecordCount": min(int(max_features), 2000),
    }
    async with httpx.AsyncClient(timeout=35.0) as client:
        r = await client.get(ARCGIS_AMP_URL, params=params)
        r.raise_for_status()
        data = r.json()
    feats = data.get("features") or []
    docs = []
    for feat in feats:
        doc = attrs_from_feature(feat)
        if not doc.get("site_id"):
            continue
        docs.append(doc)
    return docs


def _sql_site_ids(site_ids: list[str]) -> str:
    parts = []
    for sid in site_ids:
        safe = str(sid).replace("'", "''")
        if safe:
            parts.append(f"'{safe}'")
    return f"SITE_ID IN ({','.join(parts)})"


async def fetch_arcgis_attrs(site_ids: list[str]) -> dict[str, dict]:
    """Attributs ProtectedSeas sans géométrie — extras Website / Other Helpful Links."""
    out: dict[str, dict] = {}
    ids = [str(s).strip() for s in site_ids if str(s).strip()]
    if not ids:
        return out
    async with httpx.AsyncClient(timeout=35.0) as client:
        for i in range(0, len(ids), ATTR_REFRESH_BATCH):
            chunk = ids[i:i + ATTR_REFRESH_BATCH]
            params = {
                "where": _sql_site_ids(chunk),
                "outFields": ATTR_OUT_FIELDS,
                "returnGeometry": "false",
                "f": "json",
            }
            r = await client.get(ARCGIS_AMP_URL, params=params)
            r.raise_for_status()
            data = r.json()
            for feat in data.get("features") or []:
                attrs = feat.get("attributes") or feat.get("properties") or {}
                sid = str(attrs.get("SITE_ID") or attrs.get("site_id") or "").strip()
                if sid:
                    out[sid] = attrs
    return out


def apply_protectedseas_attrs(doc: dict, attrs: dict | None) -> dict:
    """Réécrit manager_url / extras depuis une fiche ArcGIS (sans polygone)."""
    if not attrs:
        return doc
    website_raw = attrs.get("url") or ""
    helpful = attrs.get("other_helpful_links")
    purpose = attrs.get("purpose")
    if website_raw:
        doc["ps_website_raw"] = website_raw
        manager, _extras = split_protectedseas_website(website_raw)
        if manager:
            doc["manager_url"] = manager
    if helpful is not None:
        doc["other_helpful_links"] = helpful
    if purpose:
        doc["purpose"] = purpose
    return doc


async def refresh_protectedseas_attrs(
    db, docs: list[dict], *, fetch_fn=None, log=None,
) -> int:
    """Recharge les extras ProtectedSeas du cache (comme les tags OSM Capitaineries)."""
    ids = [str(d.get("site_id") or d.get("_id") or "").strip() for d in docs]
    ids = [i for i in ids if i]
    if not ids:
        return 0
    fetch = fetch_fn or fetch_arcgis_attrs
    try:
        remote = await fetch(ids)
    except Exception as exc:
        if log:
            log(f"ProtectedSeas attributs : {type(exc).__name__}: {str(exc)[:80]}")
        return 0
    n = 0
    for doc in docs:
        sid = str(doc.get("site_id") or doc.get("_id") or "").strip()
        attrs = remote.get(sid)
        if not attrs:
            continue
        apply_protectedseas_attrs(doc, attrs)
        if doc.get("visit_url") and urls_equivalent(doc.get("visit_url"), doc.get("manager_url")):
            doc["visit_url"] = None
            doc["visit_url_status"] = "not_found"
            doc["visit_url_source"] = None
            doc["visit_url_judge"] = None
        n += 1
        from app.services.isolated_runs import current_run_id
        if db is not None and doc.get("_id") is not None and not current_run_id():
            await db.amp_sites.update_one(
                {"_id": doc["_id"]},
                {"$set": {
                    "manager_url": doc.get("manager_url"),
                    "ps_website_raw": doc.get("ps_website_raw"),
                    "other_helpful_links": doc.get("other_helpful_links"),
                    "purpose": doc.get("purpose"),
                    "visit_url": doc.get("visit_url"),
                    "visit_url_status": doc.get("visit_url_status"),
                    "visit_url_source": doc.get("visit_url_source"),
                    "visit_url_judge": doc.get("visit_url_judge"),
                }},
            )
    if log:
        log(f"ProtectedSeas attributs : {n}/{len(ids)} fiche(s) mises à jour")
    return n


async def ensure_amp_indexes(db) -> None:
    try:
        await db.amp_sites.create_index("site_id", unique=True)
        await db.amp_sites.create_index("name")
        await db.amp_sites.create_index("lfp")
        await db.amp_sites.create_index([("geometry", "2dsphere")])
        await db.amp_tiles.create_index("fetched_at")
    except Exception:
        pass


def tile_key(bbox: tuple[float, float, float, float]) -> str:
    minx, miny, maxx, maxy = bbox
    return f"{minx:.3f},{miny:.3f},{maxx:.3f},{maxy:.3f}"


def cache_covers_tile(cached: list[dict], tile_doc: dict | None,
                      ttl_days: int, *, force: bool) -> bool:
    """Un site isolé d'un upsert raté ne compte pas pour une tuile."""
    if force or not cached or not tile_doc:
        return False
    return _is_fresh(tile_doc, ttl_days)


def _is_fresh(doc: dict, ttl_days: int) -> bool:
    raw = doc.get("fetched_at") or ""
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    age = datetime.now(timezone.utc) - ts.astimezone(timezone.utc)
    return age.total_seconds() < ttl_days * 86400


async def query_cache(db, bbox: tuple[float, float, float, float],
                      limit: int = 400) -> list[dict]:
    q = {"geometry": {"$geoIntersects": {"$geometry": bbox_polygon(bbox)}}}
    try:
        return await db.amp_sites.find(q).limit(int(limit)).to_list(int(limit))
    except Exception:
        return []


async def upsert_sites(db, docs: list[dict]) -> int:
    n = 0
    for incoming in docs:
        sid = incoming.get("site_id")
        if not sid:
            continue
        existing = await db.amp_sites.find_one({"_id": sid})
        merged = merge_cached(existing, incoming)
        try:
            await db.amp_sites.update_one({"_id": sid}, {"$set": merged}, upsert=True)
        except Exception:
            merged["geometry"] = _point_geom(merged.get("lat"), merged.get("lon"))
            if not merged.get("geometry"):
                continue
            try:
                await db.amp_sites.update_one({"_id": sid}, {"$set": merged}, upsert=True)
            except Exception:
                continue
        n += 1
    return n


async def sites_in_bbox(db, bbox: tuple[float, float, float, float], *,
                        force: bool = False, max_features: int | None = None,
                        ttl_days: int | None = None) -> tuple[list[dict], dict]:
    max_features = int(max_features or catalog_default("amp.max_features", 400))
    ttl_days = int(ttl_days or catalog_default("amp.cache_ttl_days", 30))
    cached = await query_cache(db, bbox, limit=max_features)
    tile = None
    try:
        tile = await db.amp_tiles.find_one({"_id": tile_key(bbox)})
    except Exception:
        tile = None
    meta = {"source": "cache", "truncated": False, "fetched": 0}
    if cache_covers_tile(cached, tile, ttl_days, force=force):
        meta["truncated"] = len(cached) >= max_features
        return cached, meta
    try:
        remote = await fetch_arcgis(bbox, max_features=max_features)
    except Exception as exc:
        meta["error"] = str(exc)[:180]
        return cached, meta
    if remote:
        try:
            meta["fetched"] = await upsert_sites(db, remote)
            meta["source"] = "arcgis"
            cached = await query_cache(db, bbox, limit=max_features) or remote
            try:
                await db.amp_tiles.update_one(
                    {"_id": tile_key(bbox)},
                    {"$set": {
                        "fetched_at": now_iso(),
                        "count": len(cached),
                        "bbox": list(bbox),
                    }},
                    upsert=True,
                )
            except Exception:
                pass
        except Exception as exc:
            meta["error"] = str(exc)[:180]
            cached = remote or cached
    meta["truncated"] = len(cached) >= max_features
    return cached, meta


async def resolve_visit_urls(db, *, limit: int = 500) -> dict:
    """Applique l'heuristique other_helpful_links sur le cache (sans TinyFish)."""
    docs = await db.amp_sites.find({
        "$or": [
            {"visit_url": {"$in": [None, ""]}},
            {"visit_url_status": {"$in": ["none", "not_found", None]}},
        ],
    }).to_list(int(limit))
    found = rejected = unchanged = 0
    for doc in docs:
        before = doc.get("visit_url")
        apply_visit_choice(doc, source="other_helpful_links")
        after = doc.get("visit_url")
        if after and not urls_equivalent(after, doc.get("manager_url")):
            found += 1
        elif doc.get("visit_url_status") == "rejected_same_as_manager":
            rejected += 1
        else:
            unchanged += 1
        if after != before or doc.get("visit_url_status"):
            await db.amp_sites.update_one(
                {"_id": doc["_id"]},
                {"$set": {
                    "visit_url": doc.get("visit_url"),
                    "visit_url_status": doc.get("visit_url_status"),
                    "visit_url_source": doc.get("visit_url_source"),
                    "enriched_at": doc.get("enriched_at"),
                }},
            )
    return {
        "scanned": len(docs),
        "found": found,
        "rejected_same_as_manager": rejected,
        "unchanged": unchanged,
    }


async def set_visit_url(db, site_id: str, url: str | None) -> dict | None:
    doc = await db.amp_sites.find_one({"_id": site_id})
    if not doc:
        doc = await db.amp_sites.find_one({"site_id": site_id})
    if not doc:
        return None
    apply_visit_choice(doc, discovered=url, source="manual" if url else "other_helpful_links")
    await db.amp_sites.update_one(
        {"_id": doc["_id"]},
        {"$set": {
            "visit_url": doc.get("visit_url"),
            "visit_url_status": doc.get("visit_url_status"),
            "visit_url_source": doc.get("visit_url_source"),
            "enriched_at": doc.get("enriched_at"),
        }},
    )
    return doc


async def amp_stats(db) -> dict:
    total = await db.amp_sites.count_documents({})
    with_manager = await db.amp_sites.count_documents(
        {"manager_url": {"$nin": [None, ""]}})
    with_visit = await db.amp_sites.count_documents(
        {"visit_url": {"$nin": [None, ""]}})
    return {
        "mode": "amp",
        "total": total,
        "with_manager_url": with_manager,
        "with_visit_url": with_visit,
        "visit_coverage": round(with_visit / total * 100, 1) if total else 0.0,
        "items_mapped": total,
    }


def slim_export_feature(doc: dict) -> dict:
    """Export léger : centroïde + les deux URL, pas le polygone."""
    return to_feature(doc, geometry=False)
