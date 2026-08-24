"""
Formalities — Phase 4A.

Territory-level customs/immigration reference for the Berry-Mappemonde route.

This module ONLY handles the schema, seeding and reading of the `formalities`
collection. The actual generation pipeline (LLM + TinyFish sourcing) is
scheduled for Phase 4B — every field here defaults to null / empty so the
Phase 4B generator can just fill them in-place.

Schema per doc (1 doc per territory_code):
    _id                str  (uuid)
    territory_code     str  (matches territories.json entry)
    status             "non_generee" | "ia" | "ia_sans_source" | "verifiee"
    entree             {preavis, pavillon_q, demarches_arrivee, ou_s_amarrer,
                        vhf, douanes_clearance, admission_temporaire,
                        franchises, biosecurite, frais, horaires}  (each str|null)
    sortie             {clearance, delais, documents, ou_obtenir}
    cas_particuliers   {animaux, drones, armes}
    contacts           [{type, label, value}]
    liens_officiels    [{label, url}]
    immigration        {fr, ca, us, gb}  — sub-object per nationality
                        {visa, duree_sejour, equivalent_esta, notes}
                        `fr` will be generated first in Phase 4B; ca/us/gb on demand.
    sources            [{url, domain, collected_at}]  — empty pre-4B
    generated_at       ISO-8601 str | null
    verified_at        ISO-8601 str | null
    stale              bool  (computed against generated_at, 180 days)
    escale_overlays    [{escale_name, is_port_of_entry: bool, note: str}]

`is_stale()` uses a 180-day threshold (Phase 4A decision — half of the
365-day threshold used for marinas since regulations shift more often).
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional


FORMALITIES_STALE_DAYS = 180


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Territory reference loader
# ---------------------------------------------------------------------------

def load_territories(path: Path) -> dict:
    """Read the curated territories.json reference file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if "territories" not in data:
        raise ValueError("territories.json missing 'territories' key")
    return data


# ---------------------------------------------------------------------------
# Empty schema factory (called at seed time)
# ---------------------------------------------------------------------------

def _empty_entree() -> dict:
    return {
        "preavis": None,
        "pavillon_q": None,
        "demarches_arrivee": None,
        "ou_s_amarrer": None,
        "vhf": None,
        "douanes_clearance": None,
        "admission_temporaire": None,
        "franchises": None,
        "biosecurite": None,
        "frais": None,
        "horaires": None,
    }


def _empty_sortie() -> dict:
    return {
        "clearance": None,
        "delais": None,
        "documents": None,
        "ou_obtenir": None,
    }


def _empty_cas_particuliers() -> dict:
    return {
        "animaux": None,
        "drones": None,
        "armes": None,
    }


def _empty_immigration_slot() -> None:
    """A nationality slot before generation is None (per Phase 4A spec:
    `fr` will be filled by default in 4B, others on-demand)."""
    return None


def _default_overlays(territory: dict) -> list[dict]:
    """
    Auto-build sensible escale_overlays defaults:
      - For every escale_name in the territory, is_port_of_entry defaults
        to whether a matching entry exists in ports_of_entry (loose match
        on the leading token of the port name vs the escale name).
      - Special overrides for TAAF (no ports of entry) and Saint-Maur
        (overland departure).
    Phase 4B or a human curator can overwrite each entry.
    """
    poes = [p.get("name", "") for p in (territory.get("ports_of_entry") or [])]
    overlays: list[dict] = []
    for name in territory.get("escale_names", []):
        note: Optional[str] = None
        # ---- Saint-Maur is the overland start of the route.
        if name.startswith("Saint-Maur"):
            overlays.append({
                "escale_name": name,
                "is_port_of_entry": False,
                "note": "Départ terrestre — aucune formalité maritime.",
            })
            continue
        # ---- TAAF Îles Éparses: landing subject to prior TAAF Prefect authorisation.
        if territory.get("regime") == "taaf":
            overlays.append({
                "escale_name": name,
                "is_port_of_entry": False,
                "note": "Débarquement soumis à autorisation préalable du Préfet des TAAF.",
            })
            continue
        # ---- La Réunion: Saint-Gilles is a secondary marina, NOT an entry port.
        if name.startswith("Saint-Gilles"):
            overlays.append({
                "escale_name": name,
                "is_port_of_entry": False,
                "note": "Port de plaisance secondaire — l'entrée officielle se fait à la Pointe des Galets.",
            })
            continue
        # ---- Default: infer from ports_of_entry list.
        is_poe = False
        for p in poes:
            token = (name.split("(")[0] or "").strip().lower()
            if token and (token in p.lower() or p.lower().split()[0] in name.lower()):
                is_poe = True
                break
        overlays.append({
            "escale_name": name,
            "is_port_of_entry": is_poe,
            "note": None,
        })
    return overlays


def build_seed_doc(territory: dict) -> dict:
    """Create a blank formalities document for the given territory entry."""
    return {
        "_id": str(uuid.uuid4()),
        "territory_code": territory["code"],
        "status": "non_generee",
        "entree": _empty_entree(),
        "sortie": _empty_sortie(),
        "cas_particuliers": _empty_cas_particuliers(),
        "contacts": [],
        "liens_officiels": [],
        "immigration": {
            "fr": _empty_immigration_slot(),
            "ca": _empty_immigration_slot(),
            "us": _empty_immigration_slot(),
            "gb": _empty_immigration_slot(),
        },
        "sources": [],
        "generated_at": None,
        "verified_at": None,
        "stale": False,
        "escale_overlays": _default_overlays(territory),
        "created_at": _now_iso(),
    }


async def seed_formalities(db, territories_data: dict) -> dict:
    """
    Idempotent seed. For every territory in territories.json, insert a blank
    `formalities` doc if none exists yet for that territory_code.
    Returns a summary with inserted/existing counts.
    """
    inserted = 0
    existing = 0
    for terr in territories_data.get("territories", []):
        code = terr.get("code")
        if not code:
            continue
        found = await db.formalities.find_one({"territory_code": code})
        if found:
            existing += 1
            # Backfill escale_overlays if the doc predates a route edit and is
            # missing them entirely (never overrides existing overlays).
            if not found.get("escale_overlays"):
                await db.formalities.update_one(
                    {"_id": found["_id"]},
                    {"$set": {"escale_overlays": _default_overlays(terr)}},
                )
            continue
        doc = build_seed_doc(terr)
        await db.formalities.insert_one(doc)
        inserted += 1
    return {"inserted": inserted, "existing": existing, "total": inserted + existing}


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def is_stale(doc: dict, max_age_days: int = FORMALITIES_STALE_DAYS) -> bool:
    ga = doc.get("generated_at")
    if not ga:
        return False
    try:
        t = time.strptime(ga, "%Y-%m-%dT%H:%M:%SZ")
        return (time.time() - time.mktime(t)) > max_age_days * 86400
    except (ValueError, TypeError):
        return False


def serialise_doc(doc: dict) -> dict:
    """Strip Mongo `_id` prefix, expose `id`, compute `stale`."""
    out = {k: v for k, v in doc.items() if k != "_id"}
    out["id"] = doc.get("_id")
    out["stale"] = is_stale(doc)
    return out


def serialise_list(docs: Iterable[dict]) -> list[dict]:
    return [serialise_doc(d) for d in docs]
