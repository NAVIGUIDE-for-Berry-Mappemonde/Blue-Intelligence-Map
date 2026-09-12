"""Home → catalogue (CDC Projets C5 « listing à découvrir »).

Les 21 curés donnent les motifs d'une page qui *liste* les projets.
Les MasterSeeds v1 n'ont souvent que la home (`https://domaine/`).
Cette étape trouve l'URL catalogue avant la découverte des fiches.
"""
from __future__ import annotations

from urllib.parse import urlparse

from app.services.master_seeds import SKIP_LISTING_NETLOCS, domain_of
from app.static_data.seeds import CRAWL_BLACKLIST, CURATED_SEEDS, URL_PATTERNS

LANG_PREFIXES = {
    "en", "fr", "de", "es", "it", "pt", "nl", "int", "uk", "us", "eu",
}

# Segments « index » appris des 21 listings curés + URL_PATTERNS.
_LISTING_LEAVES: frozenset[str] | None = None

# Préfixes de chemins à ne jamais prendre pour un catalogue (PDF, CMS, actu).
_NOT_LISTING_PREFIXES = (
    "/wp-content", "/wp-admin", "/uploads", "/feed", "/tag/", "/tags/",
    "/category/", "/author/", "/cdn-cgi",
)


def _norm_seg(seg: str) -> str:
    return (seg or "").strip().strip("/").lower()


def listing_leaves() -> frozenset[str]:
    """Derniers segments des 21 curés + motifs URL_PATTERNS (sans slash)."""
    global _LISTING_LEAVES
    if _LISTING_LEAVES is not None:
        return _LISTING_LEAVES
    leaves: set[str] = set()
    for pat in URL_PATTERNS:
        tok = _norm_seg(pat.replace("/where-we-work/", "where-we-work"))
        if tok:
            leaves.add(tok)
            if tok.endswith("s") and len(tok) > 4:
                leaves.add(tok[:-1])
            else:
                leaves.add(tok + "s")
    for seed in CURATED_SEEDS:
        parts = [p for p in urlparse(seed.get("url") or "").path.split("/") if p]
        for p in parts:
            n = _norm_seg(p)
            if n and n not in LANG_PREFIXES:
                leaves.add(n)
    # Variantes fréquentes non couvertes par un curé isolé.
    leaves.update({
        "projects", "project", "projets", "projet",
        "campaigns", "campaign", "initiatives", "initiative",
        "programs", "program", "programmes", "programme",
        "grants", "grant", "actions", "missions", "expeditions",
        "hope-spots", "hope-spot", "our-work", "our-work",
        "where-we-work", "nos-actions", "fondation",
    })
    _LISTING_LEAVES = frozenset(leaves)
    return _LISTING_LEAVES


def path_parts(path: str) -> list[str]:
    return [p for p in (path or "").strip("/").split("/") if p]


def is_homepage_url(url: str | None) -> bool:
    """Racine du site (éventuellement /fr, /en). Pas un catalogue."""
    if not (url or "").strip():
        return True
    parts = path_parts(urlparse(url).path)
    if not parts:
        return True
    if len(parts) == 1 and parts[0].lower() in LANG_PREFIXES:
        return True
    return False


def is_listing_path(path: str, *, apply_blacklist: bool = True) -> bool:
    """Page qui liste des projets : 1–3 segments, feuille dans les motifs curés.

    `/projects/` et `/hope-spots/` passent (1 segment).
    `/en/where-we-work/` passe (feuille = motif).
    `/projects/coral-restore` est une fiche, pas un catalogue.
    """
    raw = path or ""
    low = raw.lower()
    if apply_blacklist and any(b in low for b in CRAWL_BLACKLIST):
        return False
    if any(low.startswith(p) or p in low for p in _NOT_LISTING_PREFIXES):
        return False
    parts = path_parts(raw)
    if not parts or len(parts) > 3:
        return False
    leaves = listing_leaves()
    meaningful = [_norm_seg(p) for p in parts if _norm_seg(p) not in LANG_PREFIXES]
    if not meaningful:
        return False
    last = meaningful[-1]
    if last not in leaves:
        return False
    # Une fiche a souvent un slug après le motif (4e segment déjà exclu).
    # 2+ meaningful dont le dernier n'est PAS seulement le motif? last IS a leaf
    # `/projects/coral-restore` → meaningful=[projects, coral-restore], last not leaf → False. OK.
    return True


def is_listing_url(url: str | None, *, home_ok: bool = False) -> bool:
    if not (url or "").strip().startswith("http"):
        return False
    if is_homepage_url(url):
        return bool(home_ok)
    return is_listing_path(urlparse(url).path)


def is_curated_listing_url(url: str | None) -> bool:
    """Les 21 curés sont déjà le catalogue, même si le chemin sort du filtre feuille."""
    key = (url or "").rstrip("/")
    if not key:
        return False
    return any((s.get("url") or "").rstrip("/") == key for s in CURATED_SEEDS)


def needs_listing_hop(seed: dict | None) -> bool:
    """True si on n'a pas encore une URL catalogue qualifiée."""
    seed = seed or {}
    kind = (seed.get("listing_kind") or "").strip().lower()
    if kind == "projects_index":
        return False
    url = (seed.get("url") or "").strip()
    if not url:
        return True
    if is_listing_url(url) or is_curated_listing_url(url):
        return False
    return True


def pick_listing_url(urls: list[str] | None) -> str | None:
    """Un seul catalogue : chemin le plus court parmi les candidats valides."""
    ok = [u for u in (urls or []) if is_listing_url(u)]
    if not ok:
        return None
    ok.sort(key=lambda u: (len(path_parts(urlparse(u).path)), len(u)))
    return ok[0]


def apply_learned_listings(seeds: list[dict], extras: list[dict] | None) -> list[dict]:
    """Recolle les catalogues mémorisés (Mongo) sur les MasterSeeds v1."""
    by_domain: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for extra in extras or []:
        if (extra.get("listing_kind") or "").strip().lower() != "projects_index":
            continue
        u = (extra.get("url") or "").strip()
        if not u or not (is_listing_url(u) or is_curated_listing_url(u)):
            continue
        d = domain_of(u) or domain_of(extra.get("domain") or "")
        if d:
            by_domain[d] = u
        n = (extra.get("name") or "").strip().lower()
        if n:
            by_name[n] = u
    out = []
    for seed in seeds or []:
        item = dict(seed)
        d = domain_of(item.get("url"))
        n = (item.get("name") or "").strip().lower()
        learned = by_domain.get(d) or by_name.get(n)
        if learned:
            item["url"] = learned
            item["listing_kind"] = "projects_index"
        out.append(item)
    return out


def listing_search_query(seed: dict) -> str:
    """Un shot : site:{domaine} … listing. Pas de 2e langue."""
    name = (seed.get("name") or "").strip() if isinstance(seed, dict) else ""
    url = (seed.get("url") or "").strip() if isinstance(seed, dict) else ""
    host = domain_of(url)
    if host:
        return f"site:{host} projects OR projets OR campaigns OR programs listing"
    if name:
        return f'"{name}" marine projects listing'
    return "marine conservation projects listing"


def listing_search_retry_query(seed: dict) -> str:
    """2e shot si le filtre a tout jeté : chemins d'index, hors news."""
    url = (seed.get("url") or "").strip() if isinstance(seed, dict) else ""
    host = domain_of(url)
    if host:
        return (
            f"site:{host} inurl:projects OR inurl:projets OR inurl:campaigns "
            f"OR inurl:hope-spots OR inurl:programs -news -donate -about"
        )
    name = (seed.get("name") or "").strip() if isinstance(seed, dict) else ""
    if name:
        return f'"{name}" inurl:projects marine -news'
    return listing_search_query(seed or {})


def fiche_search_retry_query(seed: dict) -> str:
    """2e shot fiches : pages profondes, hors URLs déjà éliminées."""
    name = (seed.get("name") or "").strip() if isinstance(seed, dict) else ""
    url = (seed.get("url") or "").strip() if isinstance(seed, dict) else ""
    host = domain_of(url)
    if host:
        q = f"site:{host} inurl:project OR inurl:projet OR inurl:campaign -news -donate"
        if name:
            return f"{q} {name}"
        return q
    if name:
        return f'"{name}" marine project page -news'
    return "marine conservation project page -news"


def infer_listing_from_project_urls(urls: list[str], funder_name: str = "") -> str | None:
    """Indice : préfixe commun des fiches v1 s'il ressemble à un catalogue.

    Save Our Seas `/project/…` → `https://saveourseas.com/project/`.
    `/wp-content/uploads` → ignoré.
    """
    by_host: dict[str, list[list[str]]] = {}
    for u in urls or []:
        if not (u or "").startswith("http"):
            continue
        pr = urlparse(u)
        host = domain_of(u)
        if not host or host in SKIP_LISTING_NETLOCS:
            continue
        by_host.setdefault(host, []).append(path_parts(pr.path))
    if not by_host:
        return None
    tokens = [t for t in (funder_name or "").lower().split() if len(t) >= 4]
    ranked = []
    for host, groups in by_host.items():
        name_hit = any(t in host.replace(".", "") for t in tokens)
        if len(groups) < 2 and not name_hit:
            continue
        prefix = _common_prefix(groups)
        if not prefix:
            continue
        path = "/" + "/".join(prefix) + "/"
        if not is_listing_path(path):
            continue
        bonus = 2 if name_hit else 0
        ranked.append((bonus, len(groups), -len(host), host, path))
    if not ranked:
        return None
    ranked.sort(reverse=True)
    _, _, _, host, path = ranked[0]
    return f"https://{host}{path}"


def _common_prefix(groups: list[list[str]]) -> list[str]:
    if not groups:
        return []
    prefix: list[str] = []
    for segs in zip(*groups):
        normed = {_norm_seg(s) for s in segs}
        if len(normed) != 1:
            break
        prefix.append(next(iter(normed)))
    return prefix


def _hit_url(hit) -> str:
    if isinstance(hit, str):
        return hit.strip()
    if isinstance(hit, dict):
        return (hit.get("url") or hit.get("link") or hit.get("href") or "").strip()
    return ""


def filter_listing_urls(hits, seed, max_urls=3, *, exclude_urls=None) -> list[str]:
    """Même hôte, page catalogue, hors home, hors URLs déjà éliminées."""
    try:
        cap = max(0, int(max_urls or 0))
    except (TypeError, ValueError):
        cap = 0
    excluded = {u.rstrip("/") for u in (exclude_urls or []) if u}
    host = domain_of((seed or {}).get("url") or "") if isinstance(seed, dict) else ""
    seed_url = ""
    if isinstance(seed, dict):
        seed_url = (seed.get("url") or "").rstrip("/")
    urls, seen = [], set()
    for hit in hits or []:
        raw = _hit_url(hit)
        if not raw.startswith("http"):
            continue
        href = raw.split("#")[0].split("?")[0]
        if not href.startswith("http"):
            continue
        key = href.rstrip("/")
        if key in excluded or key in seen:
            continue
        if seed_url and key == seed_url:
            continue
        d = domain_of(href)
        if host and d != host:
            continue
        if not host and (not d or d in SKIP_LISTING_NETLOCS):
            continue
        if not is_listing_url(href):
            continue
        seen.add(key)
        urls.append(href)
        if cap and len(urls) >= cap:
            break
    return urls[:cap] if cap else urls
