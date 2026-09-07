"""
Score de confiance d'un Port d'Entrée (0–100), lisible et composable.

Ce n'est pas une vérité officielle : chaque brique (source, lecture, carte,
contrôles extérieurs) ajoute des points. Un port vu seulement dans une
synthèse web reste bas ; un décret d'État + deux géocodeurs + OSM monte.

Les poids suivent l'audit PoE :
  source   ≤ 30  (domaine d'État, gazette, repli national)
  lecture  ≤ 25  (catalogue, LLM, NER, second lecteur Claude)
  carte    ≤ 25  (ZEE / bord terrestre, accord des géocodeurs)
  externe  ≤ 20  (listing communautaire, OSM, multi-run)
"""
from __future__ import annotations

from app.core.dedup import normalize_name, text_similarity


def listing_role(name: str, listing_ports: list[dict] | None) -> str | None:
    """'poe' | 'other' | None — le listing n'est pas une source de vérité."""
    if not name or not listing_ports:
        return None
    best, role = 0.0, None
    for p in listing_ports:
        other = (p.get("name") or "").strip()
        if not other:
            continue
        if normalize_name(name) == normalize_name(other):
            return p.get("role") or "poe"
        sim = text_similarity(name, other)
        if sim > best:
            best, role = sim, p.get("role")
    from app.core.run_rules import get_rule
    return role if best >= float(get_rule("formalities.listing_role_sim", 0.72)) else None


def score_port(port: dict, *,
               official_source: bool = False,
               listing_ports: list[dict] | None = None,
               multi_run: bool = False) -> dict:
    """Retourne {confidence, parts, reasons, listing_role}."""
    from app.core.run_rules import get_rule
    reasons: list[str] = []
    parts = {"source": 0, "reading": 0, "map": 0, "external": 0}
    src_max = int(get_rule("formalities.confidence_source_max", 30))
    read_max = int(get_rule("formalities.confidence_reading_max", 25))
    map_max = int(get_rule("formalities.confidence_map_max", 25))
    ext_max = int(get_rule("formalities.confidence_external_max", 20))
    osm_hi = float(get_rule("formalities.osm_confidence_hi", 0.5))

    engine = (port.get("extraction_engine") or "").lower()
    note = port.get("note") or ""
    urls = port.get("source_urls") or []
    synthesis_only = bool(port.get("from_synthesis")) or (
        not urls and "synthèse" in note.lower()
    )

    if official_source:
        parts["source"] = src_max
        reasons.append("source d'État")
    elif synthesis_only:
        parts["source"] = 8
        reasons.append("synthèse web sans page")
    elif urls:
        parts["source"] = 14
        reasons.append("source nationale non whitelistée")
    else:
        parts["source"] = 4
        reasons.append("source indéterminée")

    catalog = engine == "catalog" or "catalogue officiel" in note
    llm_ner = port.get("extraction_agreement") is True
    claude_or = port.get("claude_agreement") is True
    readers = 0
    if catalog:
        readers += 1
    if engine in ("llm", "openrouter", "claude") or port.get("extraction_engine"):
        if engine != "catalog":
            readers += 1
    if llm_ner:
        readers += 1
    if claude_or:
        readers += 1
        reasons.append("Claude et OpenRouter d'accord")
    if catalog and llm_ner:
        parts["reading"] = read_max
        reasons.append("catalogue + LLM + NER")
    elif catalog:
        parts["reading"] = 20
        reasons.append("catalogue officiel")
    elif llm_ner and claude_or:
        parts["reading"] = 24
        reasons.append("LLM ∩ NER ∩ Claude")
    elif llm_ner:
        parts["reading"] = 18
        reasons.append("LLM et NER d'accord")
    elif claude_or:
        parts["reading"] = 16
        reasons.append("deux lecteurs LLM")
    elif engine == "ner":
        parts["reading"] = 8
        reasons.append("NER seul")
    elif "tournure légale" in note:
        parts["reading"] = 6
        reasons.append("tournure légale")
    else:
        parts["reading"] = 12
        reasons.append("un seul extracteur")

    kind = port.get("spatial_kind") or (
        "in_eez" if port.get("validated") else None
    )
    agree = port.get("geocode_agree")
    has_geo = port.get("lat") is not None and port.get("lon") is not None
    if not has_geo:
        parts["map"] = 0
        reasons.append("non géocodé")
    elif kind == "rejected" or (port.get("validated") is False and kind not in (
            "in_eez", "coastal_land", "inland_river")):
        parts["map"] = 0
        reasons.append("hors ZEE et hors bord terrestre")
    elif kind == "in_eez" and agree is True:
        parts["map"] = map_max
        reasons.append("dans la ZEE, géocodeurs d'accord")
    elif kind == "coastal_land" and agree is True:
        parts["map"] = 22
        reasons.append("bord terrestre de la ZEE, géocodeurs d'accord")
    elif kind == "inland_river" and agree is True:
        parts["map"] = 18
        reasons.append("port fluvial du pays, géocodeurs d'accord")
    elif kind == "in_eez":
        parts["map"] = 18
        reasons.append("dans la ZEE")
    elif kind == "coastal_land":
        parts["map"] = 16
        reasons.append("bord terrestre de la ZEE")
    elif kind == "inland_river":
        parts["map"] = 14
        reasons.append("port fluvial hors ZEE (exception)")
    elif port.get("validated"):
        parts["map"] = 16
        reasons.append("point accepté dans la zone")
    else:
        parts["map"] = 4
        reasons.append("position incertaine")

    role = listing_role(port.get("name") or "", listing_ports)
    osm = port.get("osm_confidence")
    ext = 0
    if role == "poe":
        ext += 8
        reasons.append("connu du listing communautaire (PoE)")
    elif role == "other":
        ext += 2
        reasons.append("listing : autre port (pas un PoE)")
    if osm is not None:
        if osm >= osm_hi:
            ext += 8
            reasons.append("OSM : infrastructure portuaire / douane")
        elif osm > 0:
            ext += 4
            reasons.append("OSM : correspondance faible")
        else:
            reasons.append("OSM : aucun tag proche")
    if multi_run or port.get("multi_run"):
        ext += 4
        reasons.append("vu dans plusieurs runs")
    if port.get("wpi_commercial"):
        reasons.append("WPI commerce (contre-liste, pas une preuve PoE)")
    parts["external"] = min(ext_max, ext)

    total = min(100, sum(parts.values()))
    return {
        "confidence": total,
        "parts": parts,
        "reasons": reasons,
        "listing_role": role,
    }


def apply_score(port: dict, scored: dict) -> dict:
    port["confidence"] = scored["confidence"]
    port["confidence_parts"] = scored["parts"]
    port["confidence_reasons"] = scored["reasons"]
    if scored.get("listing_role"):
        port["listing_role"] = scored["listing_role"]
    return port


def zone_confidence_avg(ports: list[dict]) -> int | None:
    vals = [p.get("confidence") for p in ports if p.get("confidence") is not None]
    if not vals:
        return None
    return int(round(sum(vals) / len(vals)))
