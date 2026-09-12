"""MasterSeeds élargis (CDC Projets C5 / §18 / §22).

Union des financeurs v1 + 21 listings curés. Follow the Money écrit dans
la même table : le plafond `max_partner_orgs` ne s'applique qu'aux
organismes *nouveaux*, pas à une fondation déjà vue en v1.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_DIR / "data"
MASTER_SEEDS_PATH = DATA_DIR / "master_seeds.json"

NOISE_NAMES = {"unknown", "n/a", "none", "null", "-", "?"}

SKIP_LISTING_NETLOCS = {
    "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com",
    "youtu.be", "linkedin.com", "google.com", "wikipedia.org", "bit.ly",
    "tinyurl.com", "t.co", "goo.gl", "maps.google.com",
}


def _curated_seeds() -> list[dict]:
    from app.static_data.seeds import CURATED_SEEDS
    return CURATED_SEEDS


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def domain_of(url: str | None) -> str:
    if not url:
        return ""
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def norm_name(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def is_noise_name(name: str) -> bool:
    n = (name or "").strip()
    if not n:
        return True
    if n.lower() in NOISE_NAMES:
        return True
    if n.upper().startswith("TEST_"):
        return True
    return False


def names_match(a: str, b: str, aliases: list | None = None) -> bool:
    if not a or not b:
        return False
    na, nb = norm_name(a), norm_name(b)
    if na and na == nb:
        return True
    for al in aliases or []:
        nal = norm_name(al)
        if nal and nal in (na, nb):
            return True
    return False


def listing_url_from_project_urls(urls: list[str], funder_name: str = "") -> str | None:
    counts: Counter[str] = Counter()
    for u in urls:
        d = domain_of(u)
        if d and d not in SKIP_LISTING_NETLOCS:
            counts[d] += 1
    if not counts:
        return None
    tokens = [t for t in norm_name(funder_name).split() if len(t) >= 4]
    scored = []
    for d, n in counts.items():
        compact = d.replace(".", "")
        bonus = 2 if any(t in compact for t in tokens) else 0
        scored.append((bonus, n, -len(d), d))
    scored.sort(reverse=True)
    return f"https://{scored[0][-1]}/"


def funder_names_from_project(doc: dict) -> list[str]:
    """Noms tels qu'en base. Ne pas re-découper une chaîne déjà jointe."""
    raw = doc.get("funders")
    if isinstance(raw, list) and raw:
        return [str(x).strip() for x in raw if str(x).strip()]
    one = (doc.get("funder") or "").strip()
    return [one] if one else []


def build_v1_seeds(projects: list[dict]) -> list[dict]:
    buckets: dict[str, dict] = defaultdict(lambda: {"urls": [], "count": 0})
    for doc in projects:
        url = (doc.get("url") or "").strip()
        for name in funder_names_from_project(doc):
            if is_noise_name(name):
                continue
            buckets[name]["count"] += 1
            if url:
                buckets[name]["urls"].append(url)
    seeds = []
    for name, bucket in buckets.items():
        listing = listing_url_from_project_urls(bucket["urls"], name)
        seeds.append({
            "name": name,
            "url": listing,
            "listing_kind": "homepage" if listing else "unknown",
            "source": "v1",
            "project_count": bucket["count"],
        })
    return seeds


def merge_curated(v1_seeds: list[dict], curated: list[dict] | None = None) -> list[dict]:
    curated = curated if curated is not None else _curated_seeds()
    out: list[dict] = []
    used = set()

    def _matches_curated(v: dict, c: dict) -> bool:
        aliases = c.get("aliases") or []
        if names_match(c["name"], v.get("name") or "", aliases):
            return True
        cdom = domain_of(c.get("url"))
        return bool(cdom) and cdom == domain_of(v.get("url"))

    for c in curated:
        match = next((v for v in v1_seeds if _matches_curated(v, c)), None)
        item = {
            "name": c["name"],
            "url": c["url"],
            "country": c.get("country"),
            "category": c.get("category"),
            "listing_kind": "projects_index",
            "source": "curated",
            "project_count": int((match or {}).get("project_count") or 0),
            "aliases": list(c.get("aliases") or []),
        }
        out.append(item)
        if match:
            used.add(norm_name(match["name"]))
            cdom = domain_of(c.get("url"))
            if cdom:
                used.add(cdom)

    for v in v1_seeds:
        if norm_name(v.get("name") or "") in used:
            continue
        if domain_of(v.get("url")) and domain_of(v.get("url")) in used:
            continue
        if any(_matches_curated(v, c) for c in curated):
            continue
        out.append({
            "name": v["name"],
            "url": v.get("url"),
            "listing_kind": v.get("listing_kind") or ("homepage" if v.get("url") else "unknown"),
            "source": v.get("source") or "v1",
            "project_count": int(v.get("project_count") or 0),
        })
    return out


def build_master_seeds(projects: list[dict], curated: list[dict] | None = None) -> list[dict]:
    return merge_curated(build_v1_seeds(projects), curated)


def _without_priority(seed: dict) -> dict:
    return {k: v for k, v in seed.items() if k != "priority"}


def seeds_for_run(seeds: list[dict]) -> list[dict]:
    """Tous les listings MasterSeeds avec URL, même rang, ordre stable par nom."""
    ready = [s for s in seeds if (s.get("url") or "").strip()]
    return sorted(ready, key=lambda s: (s.get("name") or "").lower())


def is_known_funder(seeds: list[dict], name: str | None = None, url: str | None = None) -> bool:
    domain = domain_of(url)
    n = norm_name(name or "")
    for s in seeds:
        if domain and domain_of(s.get("url")) == domain:
            return True
        aliases = s.get("aliases") or []
        if n and names_match(s.get("name") or "", name or "", aliases):
            return True
    return False


def listing_url_for_name(seeds: list[dict], name: str) -> str | None:
    for s in seeds:
        if names_match(s.get("name") or "", name, s.get("aliases") or []) and s.get("url"):
            return s["url"]
    return None


def load_master_seeds(path: Path | None = None) -> list[dict]:
    path = path or MASTER_SEEDS_PATH
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        seeds = data.get("seeds") if isinstance(data, dict) else data
        if isinstance(seeds, list) and seeds:
            return [_without_priority(s) if isinstance(s, dict) else s for s in seeds]
    return [
        _without_priority({
            **s, "source": "curated", "listing_kind": "projects_index", "project_count": 0,
        })
        for s in _curated_seeds()
    ]


def dump_master_seeds(seeds: list[dict], path: Path | None = None, source: str = "") -> Path:
    path = path or MASTER_SEEDS_PATH
    payload = {
        "generated_at": now_iso(),
        "source": source,
        "n": len(seeds),
        "n_with_url": sum(1 for s in seeds if s.get("url")),
        "seeds": [_without_priority(s) if isinstance(s, dict) else s for s in seeds],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def projects_from_geojson(fc: dict) -> list[dict]:
    docs = []
    for feat in fc.get("features") or []:
        props = feat.get("properties") or {}
        docs.append({
            "title": props.get("title"),
            "url": props.get("url"),
            "funder": props.get("funder"),
            "funders": props.get("funders"),
        })
    return docs


def fetch_production_projects(base: str = "https://blueintelligence.online") -> list[dict]:
    url = base.rstrip("/") + "/api/projects"
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 Blue-Intelligence-Map/master-seeds"})
    with urlopen(req, timeout=60) as resp:
        fc = json.loads(resp.read().decode("utf-8"))
    return projects_from_geojson(fc)
