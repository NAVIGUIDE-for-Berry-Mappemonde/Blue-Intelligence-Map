"""
Libellé d'affichage d'une ZEE : un polygone VLIZ = une fiche.

Un État (France, UK, US…) a souvent plusieurs polygones : hexagone / métropole,
outre-mer, régime conjoint, revendication. On n'agrège jamais ces polygones.
Le libellé distingue chaque `mrgid` : « France (hexagone) » ≠ « France (Mayotte) ».
"""
from __future__ import annotations

from collections import Counter, defaultdict

_JOINT_FR = "régime conjoint"
_OVERLAP_FR = "revendication croisée"
_HEX_FR = "hexagone"
_METRO_FR = "métropole"

_GEO_PREFIXES = (
    "Joint regime area Torres Strait Treaty: ",
    "Joint regime area: ",
    "Overlapping claim: ",
    "Overlapping claim ",
)


def _is_200nm(pol: str | None) -> bool:
    return (pol or "").replace(" ", "").upper() == "200NM"


def _fold(s: str | None) -> str:
    return (s or "").strip().casefold()


def geoname_tail(geoname: str | None) -> str:
    """Retire le préfixe VLIZ, garde les partenaires / le lieu."""
    g = (geoname or "").strip()
    gl = g.casefold()
    for prefix in _GEO_PREFIXES:
        if gl.startswith(prefix.casefold()):
            return g[len(prefix):].strip(" :")
    return g


def partners_without_self(tail: str, sovereign: str) -> str:
    """« Spain / France » + souverain France → « Spain »."""
    raw = (tail or "").strip()
    if not raw:
        return ""
    sov = _fold(sovereign)
    parts = [p.strip() for p in raw.split("/") if p.strip()]
    if len(parts) <= 1:
        return raw
    kept = []
    for p in parts:
        pf = p.casefold()
        if pf == sov or pf.startswith(sov + " ") or pf.startswith(sov + " ("):
            continue
        kept.append(p)
    return " / ".join(kept) if kept else raw


def zone_qualifier(zone: dict) -> tuple[str, str]:
    """Retourne (qualifier_key, texte)."""
    name = (zone.get("name") or "").strip()
    sov = (zone.get("sovereign") or "").strip()
    pol = (zone.get("pol_type") or "").strip()
    geo = (zone.get("geoname") or "").strip()
    pol_l = pol.casefold()

    if name and sov and _fold(name) != _fold(sov):
        return "territory", name

    tail = partners_without_self(geoname_tail(geo), sov)
    if "joint" in pol_l:
        return "joint", tail or pol
    if "overlap" in pol_l:
        return "overlap", tail or pol

    iso2 = (zone.get("iso2") or "").upper()
    if iso2 == "FR" or _fold(sov) == "france":
        return "hexagone", _HEX_FR
    return "metropole", _METRO_FR


def compose_zone_label(sovereign: str, key: str, qualifier: str) -> str:
    sov = (sovereign or "").strip()
    q = (qualifier or "").strip()
    if key == "hexagone":
        inner = _HEX_FR
    elif key == "metropole":
        inner = _METRO_FR
    elif key == "joint":
        inner = f"{_JOINT_FR} · {q}" if q else _JOINT_FR
    elif key == "overlap":
        inner = f"{_OVERLAP_FR} · {q}" if q else _OVERLAP_FR
    else:
        inner = q or sov
    return f"{sov} ({inner})" if sov else inner


def _stamp(zone: dict, *, disambiguated: bool, key: str | None,
           qualifier: str | None, label: str) -> None:
    zone["disambiguated"] = disambiguated
    zone["qualifier_key"] = key
    zone["qualifier"] = qualifier
    zone["label"] = label


def _apply_one(zone: dict, sibling_count: int) -> None:
    name = (zone.get("name") or "").strip()
    sov = (zone.get("sovereign") or "").strip()
    fallback = name or (zone.get("geoname") or "").strip() or sov
    if sibling_count <= 1 or not sov:
        _stamp(zone, disambiguated=False, key=None, qualifier=None, label=fallback)
        return
    key, qual = zone_qualifier(zone)
    _stamp(
        zone, disambiguated=True, key=key, qualifier=qual,
        label=compose_zone_label(sov, key, qual),
    )


def _refine_collisions(zones: list[dict]) -> None:
    """Deux polygones du même souverain ne doivent pas partager le même libellé."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for z in zones:
        if not z.get("disambiguated"):
            continue
        groups[(_fold(z.get("sovereign")), _fold(z.get("label")))].append(z)
    for _key, group in groups.items():
        if len(group) < 2:
            continue
        for z in group:
            pol = (z.get("pol_type") or "").strip()
            if _is_200nm(pol):
                continue
            extra = partners_without_self(
                geoname_tail(z.get("geoname")), z.get("sovereign") or "") or pol
            qual = (z.get("qualifier") or "").strip()
            if extra and extra.casefold() not in qual.casefold():
                qual = f"{qual} — {extra}" if qual else extra
            elif pol:
                qual = f"{qual} · {pol}" if qual else pol
            else:
                qual = f"{qual} · {z.get('mrgid')}"
            z["qualifier"] = qual
            z["label"] = compose_zone_label(
                z.get("sovereign") or "", z.get("qualifier_key") or "territory", qual)


def attach_zone_labels(zones: list[dict]) -> list[dict]:
    """Pose `label` / `qualifier` / `qualifier_key` / `disambiguated` sur chaque dict."""
    counts: Counter[str] = Counter()
    for z in zones:
        s = (z.get("sovereign") or "").strip()
        if s:
            counts[s] += 1
    for z in zones:
        sov = (z.get("sovereign") or "").strip()
        _apply_one(z, counts.get(sov, 1) if sov else 1)
    _refine_collisions(zones)
    return zones


def zone_sort_key(zone: dict) -> tuple:
    """Groupe par souverain, métropole/hexagone en tête du groupe."""
    sov = (zone.get("sovereign") or zone.get("name") or "").strip().casefold()
    label = (zone.get("label") or zone.get("name") or "").strip().casefold()
    primary = 0 if zone.get("qualifier_key") in ("hexagone", "metropole") else 1
    return (sov, primary, label)


def sovereign_polygon_count(sovereign: str, zones: list[dict] | None = None) -> int:
    """Combien de polygones VLIZ pour ce souverain (eez_index si zones omis)."""
    sov = (sovereign or "").strip()
    if not sov:
        return 0
    if zones is None:
        from app.services.listing_ref import load_eez_index
        zones = load_eez_index()
    fold = _fold(sov)
    return sum(1 for z in zones if _fold(z.get("sovereign")) == fold)


def search_polygon_name(zone: dict, zones: list[dict] | None = None) -> str:
    """Nom SERP / extraction = ce polygone VLIZ, pas l'agrégat pays.

    Mayotte → « Mayotte ». France hexagone (23 polygones) → « France hexagone ».
    Belgique (un seul polygone) → « Belgium ». Jamais un nom de port.
    """
    name = (zone.get("name") or zone.get("geoname") or "").strip()
    sov = (zone.get("sovereign") or "").strip()
    if not name and not sov:
        return ""
    if not sov or _fold(name) != _fold(sov):
        return name or sov
    if sovereign_polygon_count(sov, zones) <= 1:
        return name
    key, qual = zone_qualifier(zone)
    label = compose_zone_label(sov, key, qual)
    return " ".join(label.replace("(", " ").replace(")", " ").replace("·", " ").split())


def zone_search_lang_iso(zone: dict) -> str | None:
    """ISO2 pour la langue des requêtes : polygone d'abord, sinon souverain."""
    for cc in (zone.get("iso2"), zone.get("sov_iso2")):
        val = (cc or "").strip().upper()
        if val:
            return val
    return None


def zone_search_location(zone: dict) -> str | None:
    """ISO2 TinyFish / géocode : le polygone (YT), pas le souverain (FR)."""
    return zone_search_lang_iso(zone)


def keep_extracted_in_zone(arbitration: str | None) -> bool:
    """Un GPS hors de CE polygone n'est pas écrit sur cette fiche."""
    return arbitration != "spatial_rejected"
