"""
Signal « fiche Google » sans API Places et sans scrape Maps.

On ne suit pas la redirection JS /search → /place (c'est ce que le navigateur
fait après un laps de temps). On ne garde une URL que si elle est déjà
« /maps/place/ » : tag OSM, ou hit TinyFish Search.
"""
from __future__ import annotations

import re
import time
from typing import Any, Awaitable, Callable, Iterable
from urllib.parse import unquote, urlparse

from app.services.marina_world import osm_website_from_tags

PLACE_PATH_RE = re.compile(r"/maps/place/", re.I)
SEARCH_PATH_RE = re.compile(r"/maps/search/", re.I)
TOKEN_RE = re.compile(r"[a-z0-9]{3,}", re.I)
COORDS_RE = re.compile(r"/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
NON_MARINA_RE = re.compile(
    r"\b(restaurant|hotel|hôtel|pizzeria|café|cafe|brasserie|nightclub|bar)\b",
    re.I,
)
MARINA_HINT_RE = re.compile(
    r"marina|port de plaisance|yacht\s*(club|harbour|harbor)|harbour|harbor",
    re.I,
)
STOPWORDS = frozenset({
    "marina", "port", "ports", "harbour", "harbor", "yacht", "club",
    "bassin", "plaisance", "the", "and", "des", "les", "une", "aux",
    "sur", "mer", "sea", "bay", "du", "de", "la", "le",
})
# Un bassin nommé à côté d'une grande marina ne doit pas hériter de sa fiche.
MAX_PLACE_DISTANCE_M = 8_000

MAPS_PLACE_PURPOSE = (
    "Official Google Maps place page for a named pleasure-craft marina "
    "(maps.google.com/maps/place/...), not a restaurant, hotel or generic pin."
)

SearchFn = Callable[[dict], Awaitable[list[dict]]]


def is_google_place_url(url: str | None) -> bool:
    raw = (url or "").strip()
    if not raw.startswith("http"):
        return False
    if SEARCH_PATH_RE.search(raw):
        return False
    host = (urlparse(raw).hostname or "").lower()
    if "google." not in host:
        return False
    return bool(PLACE_PATH_RE.search(raw))


def canonicalize_place_url(url: str) -> str:
    """Garde le chemin /place/…, coupe les query tracking trop longues."""
    raw = unquote(url.strip())
    parsed = urlparse(raw)
    path = parsed.path or ""
    # /maps/place/Name/@lat,lon,z  → on garde jusqu'au nom + @coords si présent
    cut = path
    if len(cut) > 240:
        cut = cut[:240]
    return f"https://www.google.com{cut}" if cut.startswith("/maps/place/") else raw.split("?")[0][:400]


def name_tokens(name: str | None) -> set[str]:
    raw = (name or "").lower()
    return {t for t in TOKEN_RE.findall(raw) if t not in STOPWORDS}


def _norm_phrase(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", unquote(value or "").lower()).strip()


def hit_blob(hit: dict) -> str:
    parts = [
        hit.get("title"),
        hit.get("url"),
        hit.get("snippet"),
        hit.get("description"),
    ]
    return " ".join(_norm_phrase(str(p)) for p in parts if p)


def place_coords(url: str | None) -> tuple[float, float] | None:
    match = COORDS_RE.search(unquote(url or ""))
    if not match:
        return None
    try:
        return float(match.group(1)), float(match.group(2))
    except (TypeError, ValueError):
        return None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import radians, sin, cos, sqrt, atan2
    rlat1, rlon1, rlat2, rlon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = sin(dlat / 2) ** 2 + cos(rlat1) * cos(rlat2) * sin(dlon / 2) ** 2
    return 2 * 6371000 * atan2(sqrt(a), sqrt(1 - a))


def place_hit_matches(
    name: str,
    hit: dict,
    lat: float | None = None,
    lon: float | None = None,
) -> bool:
    tokens = name_tokens(name)
    if not tokens:
        return False
    blob = hit_blob(hit)
    if not blob:
        return False
    if NON_MARINA_RE.search(blob) and not MARINA_HINT_RE.search(blob):
        return False
    phrase = _norm_phrase(name)
    name_ok = bool(phrase and phrase in blob)
    if not name_ok:
        overlap = sum(1 for t in tokens if t in blob)
        need = 1 if len(tokens) == 1 else min(2, len(tokens))
        name_ok = overlap >= need
    if not name_ok:
        return False
    coords = place_coords(hit.get("url"))
    if coords is not None and lat is not None and lon is not None:
        if haversine_m(float(lat), float(lon), coords[0], coords[1]) > MAX_PLACE_DISTANCE_M:
            return False
    return True


def pick_google_place(
    name: str,
    hits: Iterable[dict],
    lat: float | None = None,
    lon: float | None = None,
) -> str | None:
    for hit in hits or []:
        url = (hit.get("url") or "").strip()
        if not is_google_place_url(url):
            continue
        if place_hit_matches(name, hit, lat=lat, lon=lon):
            return canonicalize_place_url(url)
    return None


def place_url_from_doc(doc: dict) -> str | None:
    for raw in (
        doc.get("maps_place_url"),
        doc.get("website"),
        osm_website_from_tags(doc.get("tags") or {}),
        (doc.get("tags") or {}).get("contact:google"),
    ):
        if is_google_place_url(raw):
            return canonicalize_place_url(raw)
    return None


def google_place_query(marina: dict) -> str:
    name = (marina.get("name") or "").strip()
    lat, lon = marina.get("lat"), marina.get("lon")
    if lat is not None and lon is not None:
        return f'"{name}" marina {float(lat):.4f} {float(lon):.4f}'
    return f'"{name}" marina'


async def default_search(marina: dict) -> list[dict]:
    from app.core.tinyfish import tf_api_key, tf_search
    key = tf_api_key()
    if not key or not (marina.get("name") or "").strip():
        return []
    return await tf_search(
        google_place_query(marina),
        key,
        purpose=MAPS_PLACE_PURPOSE,
        log=None,
    )


async def resolve_google_place(
    marina: dict,
    *,
    search_fn: SearchFn | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """
    Retourne le patch à $set. N'invente pas d'URL /search/.
    unnamed → skipped. Search sans /place/ → none.
    """
    checked = now_iso or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    name = (marina.get("name") or "").strip()
    if not name:
        return {
            "maps_place_url": None,
            "maps_place_status": "skipped_unnamed",
            "maps_place_source": None,
            "maps_place_checked_at": checked,
        }
    tagged = place_url_from_doc({**marina, "maps_place_url": None})
    if tagged:
        return {
            "maps_place_url": tagged,
            "maps_place_status": "found",
            "maps_place_source": "osm_tag",
            "maps_place_checked_at": checked,
        }
    hits = await (search_fn or default_search)(marina)
    picked = pick_google_place(name, hits, lat=marina.get("lat"), lon=marina.get("lon"))
    if picked:
        return {
            "maps_place_url": picked,
            "maps_place_status": "found",
            "maps_place_source": "tinyfish_search",
            "maps_place_checked_at": checked,
        }
    return {
        "maps_place_url": None,
        "maps_place_status": "none",
        "maps_place_source": None,
        "maps_place_checked_at": checked,
    }


async def apply_maps_place(coll, marina: dict, patch: dict) -> None:
    await coll.update_one({"_id": marina["_id"]}, {"$set": patch})


async def resolve_maps_places(
    *,
    marinas_coll,
    state,
    limit: int = 0,
    force: bool = False,
    search_fn: SearchFn | None = None,
) -> dict:
    state.running = True
    state.started_at = time.time()
    state.finished_at = None
    state.error = None
    state.logs = []
    state.summary = None
    state.progress = 0
    state.cancel = False

    q: dict[str, Any] = {"name": {"$nin": ["", None]}}
    if not force:
        q["$or"] = [
            {"maps_place_status": {"$exists": False}},
            {"maps_place_status": None},
        ]

    fetch_n = int(limit) if limit and int(limit) > 0 else 200_000
    cur = marinas_coll.find(q)
    if hasattr(cur, "sort"):
        cur = cur.sort("name", 1)
    if hasattr(cur, "limit"):
        cur = cur.limit(fetch_n)
    if hasattr(cur, "to_list"):
        docs = await cur.to_list(fetch_n)
    else:
        docs = [d async for d in cur]
        docs = docs[:fetch_n]

    state.total = len(docs)
    state.log(f"Fiches Google : {len(docs)} marina(s) nommée(s) à résoudre (force={force})")

    found = none = errors = 0
    try:
        for marina in docs:
            if getattr(state, "cancel", False):
                state.log("Stop demandé")
                break
            try:
                patch = await resolve_google_place(marina, search_fn=search_fn)
                await apply_maps_place(marinas_coll, marina, patch)
                if patch["maps_place_status"] == "found":
                    found += 1
                    state.log(f"✓ {marina.get('name')} → {patch['maps_place_url']}")
                else:
                    none += 1
                    state.log(f"· {marina.get('name')} → pas de /place/")
            except Exception as exc:
                errors += 1
                state.log(f"✗ {marina.get('name')}: {type(exc).__name__}: {str(exc)[:80]}")
            state.progress += 1

        summary = {
            "selected": len(docs),
            "found": found,
            "none": none,
            "errors": errors,
            "force": force,
        }
        state.summary = summary
        state.log(f"Fiches Google terminé: {summary}")
        return summary
    except Exception as exc:
        state.error = f"{type(exc).__name__}: {exc}"
        state.log(f"FATAL: {state.error}")
        raise
    finally:
        state.finished_at = time.time()
        state.running = False
