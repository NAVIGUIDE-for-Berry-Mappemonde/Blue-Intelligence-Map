"""Home → catalogue (CDC Projets C5 « listing à découvrir »).

Les 21 curés donnent les motifs d'une page qui *liste* les projets.
Les MasterSeeds v1 n'ont souvent que la home (`https://domaine/`).
Cette étape trouve l'URL catalogue avant la découverte des fiches.

Hop 1 : hygiène SERP (même hôte, pas home / news / donate / wp-content) →
raccourci feuille curée (`/projects/`) → sinon juge LLM de 3–5 URLs →
Agent listing. Le filtre feuille n'est plus un veto sur la SERP.
"""
from __future__ import annotations

from urllib.parse import urlparse

from app.services.master_seeds import SKIP_LISTING_NETLOCS, domain_of
from app.static_data.seeds import CRAWL_BLACKLIST, CURATED_SEEDS, URL_PATTERNS

LISTING_JUDGE_CAP = 5
_FILE_EXTS = frozenset({
    "pdf", "jpg", "jpeg", "png", "gif", "zip", "svg", "mp4", "webp", "css", "js",
})

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


_BLOCKED_SEGS = frozenset(_norm_seg(s) for s in CRAWL_BLACKLIST)


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
        if not u or is_homepage_url(u):
            continue
        if not (
            is_listing_url(u)
            or is_curated_listing_url(u)
            or listing_hygiene_ok(u)
        ):
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


def _looks_like_fiche_parts(parts: list[str]) -> bool:
    """`/projects/coral-restore` : feuille + slug. Pas un catalogue."""
    meaningful = [_norm_seg(p) for p in parts if _norm_seg(p) not in LANG_PREFIXES]
    if len(meaningful) < 2:
        return False
    leaves = listing_leaves()
    return meaningful[0] in leaves and meaningful[-1] not in leaves


def listing_hygiene_ok(url: str | None) -> bool:
    """Même contrainte légère pour SERP, Agent et mémoire. Pas un veto feuille."""
    if not (url or "").startswith("http"):
        return False
    if is_homepage_url(url):
        return False
    path = urlparse(url).path or ""
    low = path.lower()
    if any(low.startswith(p) or p in low for p in _NOT_LISTING_PREFIXES):
        return False
    parts = path_parts(path)
    if not parts or len(parts) > 3:
        return False
    segs = [_norm_seg(p) for p in parts]
    if any(s in _BLOCKED_SEGS for s in segs):
        return False
    last = segs[-1]
    if "." in last and last.rsplit(".", 1)[-1] in _FILE_EXTS:
        return False
    if _looks_like_fiche_parts(parts):
        return False
    return True


def _collect_same_host_hits(hits, seed, *, exclude_urls=None) -> list[str]:
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
        seen.add(key)
        urls.append(href)
    return urls


def hygiene_listing_urls(hits, seed, max_urls=LISTING_JUDGE_CAP, *, exclude_urls=None) -> list[str]:
    """3–5 candidats juge : même hôte, pas home / news / donate / fiche / wp-content.

    Les feuilles curées (`/projects/`) passent en tête pour le raccourci, sans
    plafonner avant : un `/projects/` en 6e hit SERP n'est pas perdu.
    """
    try:
        cap = max(0, int(max_urls or 0))
    except (TypeError, ValueError):
        cap = 0
    same = _collect_same_host_hits(hits, seed, exclude_urls=exclude_urls)
    ok = [u for u in same if listing_hygiene_ok(u)]
    leaves = [u for u in ok if is_listing_url(u)]
    rest = [u for u in ok if not is_listing_url(u)]
    ordered = leaves + rest
    return ordered[:cap] if cap else ordered


def merge_listing_candidates(*groups, cap=LISTING_JUDGE_CAP) -> list[str]:
    """Union crawl + Fetch + Search, feuilles d'abord, plafond juge."""
    seen: set[str] = set()
    leaves, rest = [], []
    for group in groups:
        for u in group or []:
            if not u:
                continue
            key = u.rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            if is_listing_url(u):
                leaves.append(u)
            elif listing_hygiene_ok(u):
                rest.append(u)
    ordered = leaves + rest
    try:
        limit = max(0, int(cap or 0))
    except (TypeError, ValueError):
        limit = LISTING_JUDGE_CAP
    return ordered[:limit] if limit else ordered


def accept_listing_url(url: str | None, seed: dict | None = None) -> str | None:
    """Sortie Agent listing : hygiène, pas le veto feuille `/projects/`."""
    raw = (url or "").strip()
    if not raw.startswith("http"):
        return None
    href = raw.split("#")[0].split("?")[0]
    if not listing_hygiene_ok(href):
        return None
    if isinstance(seed, dict):
        host = domain_of(seed.get("url") or "")
        if host and domain_of(href) != host:
            return None
        seed_url = (seed.get("url") or "").rstrip("/")
        if seed_url and href.rstrip("/") == seed_url:
            return None
    return href


def filter_listing_urls(hits, seed, max_urls=3, *, exclude_urls=None) -> list[str]:
    """Raccourci feuille curée uniquement (`/projects/`, `/hope-spots/`)."""
    try:
        cap = max(0, int(max_urls or 0))
    except (TypeError, ValueError):
        cap = 0
    urls, seen = [], set()
    for href in _collect_same_host_hits(hits, seed, exclude_urls=exclude_urls):
        if not is_listing_url(href):
            continue
        key = href.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        urls.append(href)
        if cap and len(urls) >= cap:
            break
    return urls[:cap] if cap else urls


LISTING_JUDGE_SYSTEM = (
    "Tu juges des URL de catalogue de projets d'une organisation marine. "
    "Réponds uniquement en JSON strict : "
    '{"url": "https://example.org/projects/", "accept": true, "reason": ""} '
    "url doit être l'une des candidates, ou null. "
    "accept=true seulement si la page LISTE plusieurs projets, campagnes, "
    "programmes ou hope spots DE CETTE organisation (index, directory, "
    "where we work, our work, our programmes). "
    "accept=false pour une homepage, une fiche projet unique, une actualité, "
    "un don, une page about/contact, un PDF ou /wp-content. "
    "N'invente aucune URL."
)


def listing_judge_prompt(seed: dict, candidates: list) -> str:
    lines = []
    for i, cand in enumerate(candidates[:LISTING_JUDGE_CAP], 1):
        if isinstance(cand, dict):
            url = cand.get("url") or ""
            title = (cand.get("title") or "").strip()
        else:
            url, title = str(cand), ""
        extra = f" | {title}" if title else ""
        lines.append(f"{i}. {url}{extra}")
    home = ((seed or {}).get("url") or "").strip()
    name = ((seed or {}).get("name") or "").strip()
    return (
        f"Organisation : {name}\n"
        f"Homepage (interdite comme listing) : {home}\n"
        f"Candidats :\n" + "\n".join(lines)
    )


def parse_listing_judge(data: dict | None, candidates: list, home: str | None) -> str | None:
    from app.core.judge import parse_yes_no
    yes = parse_yes_no(
        data,
        allowed_urls=candidates,
        forbidden_urls=[home] if home else None,
    )
    return yes.url if yes.accepted else None


async def llm_judge_listing(
    seed: dict,
    candidates: list,
    *,
    settings: dict | None = None,
    log=None,
) -> str | None:
    """NVIDIA (chaîne json) → OpenRouter → Claude. Une URL parmi 3–5, jamais hors liste."""
    packed = []
    for cand in candidates or []:
        if isinstance(cand, dict):
            url = (cand.get("url") or cand.get("link") or "").strip()
            title = cand.get("title") or ""
        else:
            url, title = str(cand).strip(), ""
        if url.startswith("http"):
            packed.append({"url": url, "title": title})
        if len(packed) >= LISTING_JUDGE_CAP:
            break
    if not packed:
        return None
    from app.core.judge import ask_yes_no

    home = (seed or {}).get("url")
    yes = await ask_yes_no(
        LISTING_JUDGE_SYSTEM,
        listing_judge_prompt(seed or {}, packed),
        settings=settings,
        log=log,
        role="json",
        max_tokens=400,
        allowed_urls=packed,
        forbidden_urls=[home] if home else None,
        on_empty="inconclusive",
    )
    if yes.accepted and yes.url:
        return yes.url
    return None
