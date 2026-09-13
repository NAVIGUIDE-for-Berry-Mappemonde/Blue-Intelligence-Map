"""Catalogue MasterSeeds : audit hors Complet + homes / listes / file.

Ne touche pas `projects`. Enrichit seulement la liste d'entrée (CDC C5 / §18).
"""
from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

from app.services.master_seeds import (
    DATA_DIR, NOISE_NAMES, SKIP_LISTING_NETLOCS, domain_of, domain_matches_org,
    funder_names_from_project, is_noise_name, is_publisher_host,
    is_shared_hub, listing_url_from_project_urls, name_owns_hub,
    names_soft_match, now_iso, norm_name,
)
from app.services.project_listing import (
    infer_listing_from_project_urls, is_homepage_url, is_listing_url,
)

HOME_STATUS_OFFICIAL = "official"
HOME_STATUS_BORROWED = "borrowed_hub"
HOME_STATUS_PUBLISHER = "publisher"
HOME_STATUS_SOCIAL = "social"
HOME_STATUS_EMPTY = "empty"
HOME_STATUS_UNKNOWN = "unknown"

NAME_OK = "ok"
NAME_COMPOUND = "compound"
NAME_EXCLUDE = "exclude"

QUEUE_CRAWL = "crawl"
QUEUE_RESOLVE = "resolve"
QUEUE_SKIP = "skip"

SEARCH_JOURNAL_PATH = DATA_DIR / "official_homes_search.jsonl"
SEARCH_PROGRESS_PATH = DATA_DIR / "official_homes_search.progress.json"
AUDIT_PATH = DATA_DIR / "master_seeds_audit.json"
HOME_SOURCE_SEARCH = "search"

SEARCH_HOME_STATUSES = {
    HOME_STATUS_BORROWED,
    HOME_STATUS_UNKNOWN,
    HOME_STATUS_EMPTY,
    HOME_STATUS_PUBLISHER,
}

_SEARCH_OVERLAY_FIELDS = (
    "home_url", "url", "home_status", "home_source", "queue", "listing_kind",
    "listing_url",
)

_EXCLUDE_EXACT = NOISE_NAMES | {
    "in-kind", "in kind", "inkind",
    "individual supporters and business partners",
    "shippers, tankers and large vessels",
    "donor funded, manta trust affiliate, barefoot manta resort, conservation international",
}

_KEEP_AND = (
    "gordon and betty",
    "david and lucile",
    "jeremy and hannelore",
    "parks and recreation",
    "land and natural",
    "science and technology",
    "science and engineering",
    "climate and environment",
    "food and agriculture",
    "disease control and prevention",
    "city and county",
    "fish and wildlife",
    "ocean and atmospheric",
    "oceanic and atmospheric",
    "marine and environmental",
    "marine and coastal",
    "data and information",
    "education and research",
    "nature and people",
    "arts and ",
    "research and production",
    "research and innovation",
    "management and exploitation",
    "fisheries and oceans",
    "science and research",
)

_ORG_HINT = re.compile(
    r"\b(foundation|fondation|fund|trust|institut|institute|university|"
    r"universit|conservancy|alliance|commission|council|agency|society|"
    r"association|ministry|ministere|centre|center|laboratory|lab)\b",
    re.I,
)

def classify_name(name: str) -> str:
    """ok / compound / exclude — avant tout Search « official site »."""
    raw = (name or "").strip()
    if is_noise_name(raw):
        return NAME_EXCLUDE
    n = norm_name(raw)
    if n in _EXCLUDE_EXACT:
        return NAME_EXCLUDE
    if n.startswith("in kind") or n.startswith("in-kind") or n.startswith("inkind"):
        return NAME_EXCLUDE
    if raw.lower().startswith("multiple ("):
        return NAME_EXCLUDE
    display = re.sub(r"\s*\(partner\)\s*$", "", raw, flags=re.I).strip()
    n = norm_name(display)
    if display.count(",") >= 2:
        return NAME_COMPOUND
    if "," in display:
        if re.search(
            r",\s*(ministry|universit|helmholtz|department of|"
            r"far eastern|mnr\b|gmbh|inc\.?|ltd\.?)\b",
            display,
            re.I,
        ) and display.count(",") == 1:
            pass
        else:
            parts = [p.strip() for p in display.split(",")]
            if any(_ORG_HINT.search(p) for p in parts if p):
                return NAME_COMPOUND
    if re.search(r"\band\b", display, re.I):
        low = n
        if any(k in low for k in _KEEP_AND):
            return NAME_OK
        return NAME_COMPOUND
    return NAME_OK


def _best_own_domain(name: str, urls: list[str]) -> tuple[str, str]:
    """(domaine propriétaire, raison) ou ('', '')."""
    counts: Counter[str] = Counter()
    social = 0
    for u in urls or []:
        d = domain_of(u)
        if not d:
            continue
        if d in SKIP_LISTING_NETLOCS:
            social += 1
            continue
        counts[d] += 1
    if not counts and social:
        return "", HOME_STATUS_SOCIAL
    if not counts:
        return "", HOME_STATUS_EMPTY
    own = []
    for d, n in counts.items():
        if is_publisher_host(d):
            continue
        if domain_matches_org(d, name) or name_owns_hub(name, d):
            own.append((n, -len(d), d))
    if own:
        own.sort(reverse=True)
        return own[0][-1], HOME_STATUS_OFFICIAL
    if all(is_publisher_host(d) for d in counts):
        return "", HOME_STATUS_PUBLISHER
    if all(is_shared_hub(d) for d in counts):
        return "", HOME_STATUS_BORROWED
    if any(is_shared_hub(d) for d in counts) and not own:
        return "", HOME_STATUS_BORROWED
    return "", HOME_STATUS_UNKNOWN


def classify_home(name: str, urls: list[str]) -> dict:
    """Classe la home sans écrire de catalogue emprunté."""
    own, status = _best_own_domain(name, urls)
    borrowed = ""
    hubs = [
        domain_of(u) for u in (urls or [])
        if is_shared_hub(u) and domain_of(u)
    ]
    if hubs:
        borrowed = Counter(hubs).most_common(1)[0][0]
    home_url = f"https://{own}/" if own else None
    if not home_url and status == HOME_STATUS_OFFICIAL:
        status = HOME_STATUS_UNKNOWN
    return {
        "home_status": status,
        "home_url": home_url,
        "borrowed_domain": borrowed or None,
        "home_source": "v1_url" if home_url else "",
    }


def infer_own_listing(name: str, urls: list[str], home_url: str | None) -> str | None:
    """Préfixe commun des fiches *sur le domaine propriétaire*."""
    host = domain_of(home_url)
    if not host:
        return None
    if not domain_matches_org(home_url or host, name) and not name_owns_hub(name, host):
        return None
    own = [u for u in (urls or []) if domain_of(u) == host]
    if len(own) < 2:
        return None
    # La home est déjà officielle : on ne refiltre pas via les hubs fréquents
    # (fondationdelamer.org porterait sinon trop de noms v1).
    inferred = infer_listing_from_project_urls(own, name, allow_shared_hub=True)
    if not inferred:
        return None
    if domain_of(inferred) != host:
        return None
    if not is_listing_url(inferred):
        return None
    return inferred


def _curated_listing_kind(c: dict) -> str:
    kind = (c.get("listing_kind") or "").strip().lower()
    if kind in {"projects_index", "home_only", "homepage", "unknown"}:
        return kind
    url = (c.get("url") or "").strip()
    if url and is_listing_url(url) and not is_homepage_url(url):
        return "projects_index"
    return "homepage"


def enrich_v1_seed(name: str, urls: list[str], project_count: int) -> dict:
    name_status = classify_name(name)
    home = classify_home(name, urls)
    listing = None
    if home["home_status"] == HOME_STATUS_OFFICIAL:
        listing = infer_own_listing(name, urls, home["home_url"])
        if not listing:
            # Racine du domaine propriétaire (pas un hub).
            listing = listing_url_from_project_urls(urls, name)
            if listing and domain_of(listing) != domain_of(home["home_url"]):
                listing = None
            if listing and is_listing_url(listing):
                pass
            elif listing:
                listing = None
    if listing:
        listing_kind = "projects_index"
        url = listing
    elif home["home_url"]:
        listing_kind = "homepage"
        url = home["home_url"]
    else:
        listing_kind = "unknown"
        url = None
    if name_status == NAME_EXCLUDE:
        queue = QUEUE_SKIP
    elif name_status == NAME_COMPOUND:
        queue = QUEUE_RESOLVE
    elif home["home_status"] == HOME_STATUS_OFFICIAL and url:
        queue = QUEUE_CRAWL
    else:
        queue = QUEUE_RESOLVE
    return {
        "name": name,
        "url": url,
        "listing_kind": listing_kind,
        "source": "v1",
        "project_count": int(project_count or 0),
        "home_url": home["home_url"],
        "listing_url": listing,
        "home_status": home["home_status"],
        "name_status": name_status,
        "queue": queue,
        "borrowed_domain": home["borrowed_domain"],
        "home_source": home["home_source"] or ("inferred" if listing else ""),
    }


def build_v1_catalog(projects: list[dict]) -> list[dict]:
    buckets: dict[str, dict] = defaultdict(lambda: {"urls": [], "count": 0})
    for doc in projects:
        url = (doc.get("url") or "").strip()
        for name in funder_names_from_project(doc):
            if is_noise_name(name):
                continue
            buckets[name]["count"] += 1
            if url:
                buckets[name]["urls"].append(url)
    return [
        enrich_v1_seed(name, bucket["urls"], bucket["count"])
        for name, bucket in buckets.items()
    ]


def merge_curated_catalog(v1_seeds: list[dict], curated: list[dict] | None = None) -> list[dict]:
    """Union nom/alias seulement : un hébergé CORDIS n'est plus jeté."""
    if curated is None:
        from app.static_data.seeds import CURATED_SEEDS
        curated = CURATED_SEEDS
    out: list[dict] = []
    used = set()

    def _matches(v: dict, c: dict) -> bool:
        return names_soft_match(c["name"], v.get("name") or "", c.get("aliases") or [])

    for c in curated:
        matches = [v for v in v1_seeds if _matches(v, c)]
        kind = _curated_listing_kind(c)
        listing_url = c["url"] if kind == "projects_index" else None
        if kind == "projects_index" and is_homepage_url(c.get("url")):
            kind = "homepage"
            listing_url = None
        home_url = None
        d = domain_of(c.get("url"))
        if d:
            home_url = f"https://{d}/"
        crawl_url = listing_url or c.get("url")
        item = {
            "name": c["name"],
            "url": crawl_url,
            "country": c.get("country"),
            "category": c.get("category"),
            "listing_kind": kind,
            "source": "curated",
            "project_count": sum(int(m.get("project_count") or 0) for m in matches),
            "aliases": list(c.get("aliases") or []),
            "home_url": home_url,
            "listing_url": listing_url,
            "home_status": HOME_STATUS_OFFICIAL,
            "name_status": NAME_OK,
            "queue": QUEUE_CRAWL if crawl_url else QUEUE_RESOLVE,
            "borrowed_domain": None,
            "home_source": "curated",
        }
        out.append(item)
        for m in matches:
            used.add(norm_name(m.get("name") or ""))

    for v in v1_seeds:
        if norm_name(v.get("name") or "") in used:
            continue
        if any(_matches(v, c) for c in curated):
            continue
        out.append({k: val for k, val in v.items() if k != "priority"})
    return out


def build_enriched_master_seeds(projects: list[dict], curated: list[dict] | None = None) -> list[dict]:
    from app.services.master_seeds import set_frequent_hubs_from_projects
    set_frequent_hubs_from_projects(projects)
    return merge_curated_catalog(build_v1_catalog(projects), curated)


def is_crawl_ready(seed: dict | None) -> bool:
    """File Complet : home officielle ou page-liste. Pas de hub à résoudre."""
    seed = seed or {}
    name = (seed.get("name") or "").strip()
    if not name:
        return False
    q = (seed.get("queue") or "").strip().lower()
    if q in {QUEUE_RESOLVE, QUEUE_SKIP}:
        return False
    if (seed.get("name_status") or "") in {NAME_COMPOUND, NAME_EXCLUDE}:
        return False
    status = (seed.get("home_status") or "").strip().lower()
    if status in {
        HOME_STATUS_BORROWED, HOME_STATUS_PUBLISHER, HOME_STATUS_SOCIAL,
        HOME_STATUS_EMPTY, HOME_STATUS_UNKNOWN,
    }:
        return False
    url = (
        (seed.get("listing_url") or "").strip()
        or (seed.get("url") or "").strip()
        or (seed.get("home_url") or "").strip()
    )
    if q == QUEUE_CRAWL:
        return bool(url)
    if status == HOME_STATUS_OFFICIAL:
        return bool(url)
    # Partenaire Follow the Money / graine legacy : URL propre, pas un hub.
    if not url:
        return False
    from app.services.master_seeds import is_shared_hub_home, needs_official_home
    if is_shared_hub_home(seed) or needs_official_home(seed):
        return False
    return True


def catalog_summary(seeds: list[dict]) -> dict:
    def _count(key, value):
        return sum(1 for s in seeds if (s.get(key) or "") == value)

    return {
        "n": len(seeds),
        "n_with_url": sum(1 for s in seeds if s.get("url")),
        "n_crawl": sum(1 for s in seeds if is_crawl_ready(s)),
        "n_resolve": _count("queue", QUEUE_RESOLVE),
        "n_skip": _count("queue", QUEUE_SKIP),
        "n_official": _count("home_status", HOME_STATUS_OFFICIAL),
        "n_borrowed": _count("home_status", HOME_STATUS_BORROWED),
        "n_unknown_home": _count("home_status", HOME_STATUS_UNKNOWN),
        "n_compound": _count("name_status", NAME_COMPOUND),
        "n_projects_index": _count("listing_kind", "projects_index"),
        "n_home_only": _count("listing_kind", "home_only"),
    }


def audit_rows(seeds: list[dict]) -> list[dict]:
    rows = []
    for s in seeds:
        rows.append({
            "name": s.get("name"),
            "project_count": s.get("project_count") or 0,
            "source": s.get("source"),
            "name_status": s.get("name_status") or "",
            "home_status": s.get("home_status") or "",
            "listing_kind": s.get("listing_kind") or "",
            "queue": s.get("queue") or "",
            "home_url": s.get("home_url") or "",
            "listing_url": s.get("listing_url") or "",
            "url": s.get("url") or "",
            "borrowed_domain": s.get("borrowed_domain") or "",
            "home_source": s.get("home_source") or "",
        })
    rows.sort(key=lambda r: (-int(r["project_count"] or 0), (r["name"] or "").lower()))
    return rows


def _atomic_write_text(path: Path, text: str) -> Path:
    """Écriture tmp + fsync + replace : un crash laisse l'ancien fichier intact."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)
    return path


def apply_official_site_result(seed: dict, site: str | None) -> dict:
    """Applique un hit Search B. Conserve `borrowed_domain` pour l'audit."""
    site = (site or "").strip()
    if site:
        listing = (seed.get("listing_url") or "").strip() or None
        if listing and domain_of(listing) != domain_of(site):
            listing = None
            seed["listing_url"] = None
        seed["home_url"] = site
        seed["url"] = listing or site
        seed["home_status"] = HOME_STATUS_OFFICIAL
        seed["home_source"] = HOME_SOURCE_SEARCH
        seed["queue"] = QUEUE_CRAWL
        if not seed.get("listing_kind") or seed["listing_kind"] == "unknown":
            seed["listing_kind"] = "homepage"
        return seed
    seed["home_status"] = HOME_STATUS_UNKNOWN
    seed["queue"] = QUEUE_RESOLVE
    seed["home_source"] = HOME_SOURCE_SEARCH
    return seed


def append_search_journal(path: Path, record: dict) -> Path:
    """Append + fsync : chaque résultat B est consigné avant le checkpoint."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
    return path


def load_search_journal(path: Path) -> dict[str, dict]:
    """Dernier enregistrement par nom (journal append-only)."""
    out: dict[str, dict] = {}
    path = Path(path)
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = (rec.get("name") or "").strip()
        if name:
            out[name] = rec
    return out


def journal_done_names(records: dict[str, dict], *, retry_unknown: bool = False) -> set[str]:
    """Noms déjà Search-és. Les erreurs réseau ne sont pas « done » (reprise)."""
    done: set[str] = set()
    for name, rec in (records or {}).items():
        if rec.get("error") and not rec.get("site"):
            continue
        if rec.get("site"):
            done.add(norm_name(name))
        elif not retry_unknown:
            done.add(norm_name(name))
    return done


def search_candidates(
    seeds: list[dict],
    *,
    done_names: set[str] | None = None,
    retry_unknown: bool = False,
) -> list[dict]:
    """Graines B : nom ok, home empruntée/inconnue, pas déjà consignées Search."""
    done = {norm_name(n) for n in (done_names or set()) if n}
    out = []
    for s in seeds:
        name = (s.get("name") or "").strip()
        if not name:
            continue
        if (s.get("name_status") or NAME_OK) != NAME_OK:
            continue
        if (s.get("queue") or "") == QUEUE_SKIP:
            continue
        key = norm_name(name)
        if key in done:
            continue
        source = (s.get("home_source") or "").strip()
        status = (s.get("home_status") or "").strip()
        if source == HOME_SOURCE_SEARCH:
            if retry_unknown and status == HOME_STATUS_UNKNOWN:
                pass
            else:
                continue
        if status not in SEARCH_HOME_STATUSES:
            continue
        out.append(s)
    return out


def overlay_search_results(
    seeds: list[dict],
    *,
    previous: list[dict] | None = None,
    journal: Path | dict | None = None,
) -> int:
    """Réapplique les homes Search (catalogue précédent + journal). Le journal gagne."""
    by = {norm_name(s.get("name") or ""): s for s in seeds}
    touched: set[str] = set()
    for old in previous or []:
        if (old.get("home_source") or "") != HOME_SOURCE_SEARCH:
            continue
        key = norm_name(old.get("name") or "")
        cur = by.get(key)
        if not cur:
            continue
        for field in _SEARCH_OVERLAY_FIELDS:
            if field in old:
                cur[field] = old[field]
        if old.get("borrowed_domain") and not cur.get("borrowed_domain"):
            cur["borrowed_domain"] = old["borrowed_domain"]
        touched.add(key)
    records: dict[str, dict]
    if isinstance(journal, dict):
        records = journal
    elif journal is not None:
        records = load_search_journal(Path(journal))
    else:
        records = {}
    for rec in records.values():
        key = norm_name(rec.get("name") or "")
        cur = by.get(key)
        if not cur:
            continue
        if rec.get("error") and not rec.get("site"):
            continue
        apply_official_site_result(cur, rec.get("site") or "")
        touched.add(key)
    return len(touched)


def write_search_progress(path: Path, payload: dict) -> Path:
    body = {"updated_at": now_iso(), **payload}
    return _atomic_write_text(Path(path), json.dumps(body, ensure_ascii=False, indent=2) + "\n")


def persist_catalog(
    seeds: list[dict],
    catalog_path: Path,
    audit_path: Path | None = None,
    source: str = "",
) -> Path:
    """Checkpoint catalogue + audit (atomiques)."""
    path = dump_catalog(seeds, catalog_path, source=source)
    if audit_path is not None:
        write_audit(seeds, audit_path, source=source)
    return path


def write_audit(seeds: list[dict], path: Path, source: str = "") -> Path:
    path = Path(path)
    payload = {
        "generated_at": now_iso(),
        "source": source,
        "summary": catalog_summary(seeds),
        "rows": audit_rows(seeds),
    }
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    csv_path = path.with_suffix(".csv")
    rows = payload["rows"]
    if rows:
        tmp = csv_path.with_name(csv_path.name + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(csv_path)
    return path


def dump_catalog(seeds: list[dict], path: Path | None = None, source: str = "") -> Path:
    from app.services.master_seeds import MASTER_SEEDS_PATH
    path = Path(path or MASTER_SEEDS_PATH)
    extra = catalog_summary(seeds)
    payload = {
        "generated_at": now_iso(),
        "source": source,
        **extra,
        "seeds": [{k: v for k, v in s.items() if k != "priority"} for s in seeds],
    }
    return _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
