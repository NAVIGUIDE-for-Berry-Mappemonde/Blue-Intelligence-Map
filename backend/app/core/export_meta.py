"""
app.core.export_meta — Exports GeoJSON versionnés (inspiration Open Waters: Seamap).

Chaque FeatureCollection exportée porte un bloc ``metadata`` auto-descriptif :
nom du jeu de données, horodatage UTC, comptage, empreinte de contenu
(sha256 tronqué à 12 hex) et avertissement légal. La version
``AAAA-MM-JJ.<hash12>`` identifie le contenu de façon stable : deux exports au
contenu identique portent la même empreinte, deux contenus différents ne
peuvent pas la partager.

La discipline de l'avertissement (« pas pour la navigation ») suit le README
de seamap : les données sont participatives / extraites automatiquement, aucune
autorité hydrographique ou douanière ne les vérifie.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from fastapi.responses import JSONResponse

GENERATOR = "Blue Intelligence — blueintelligence.online"

DISCLAIMER_EN = (
    "Not for navigation. Crowd-sourced / automatically extracted data, provided "
    "as-is: always verify against official sources (nautical charts, government "
    "publications) before any use at sea."
)
DISCLAIMER_FR = (
    "Ne convient pas à la navigation. Données participatives / extraites "
    "automatiquement, fournies telles quelles : vérifiez toujours les sources "
    "officielles (cartes marines, publications gouvernementales) avant toute "
    "utilisation en mer."
)


def content_fingerprint(features: list) -> str:
    """Empreinte stable du contenu : sha256 des features canonisées, 12 hex."""
    canon = json.dumps(features, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]


def versioned_fc(fc: dict, dataset: str, *, license_note: str | None = None,
                 now: datetime | None = None,
                 period: str | None = None,
                 month: int | None = None,
                 source_ids: list | None = None,
                 doi: str | None = None,
                 extra_metadata: dict | None = None) -> dict:
    """Retourne une copie superficielle de ``fc`` avec le bloc ``metadata``.

    Les features ne sont jamais modifiées ; les clés existantes de la
    FeatureCollection (``attribution``…) sont préservées.
    """
    now = now or datetime.now(timezone.utc)
    features = fc.get("features") or []
    fingerprint = content_fingerprint(features)
    out = dict(fc)
    out["metadata"] = {
        "dataset": dataset,
        "version": f"{now.strftime('%Y-%m-%d')}.{fingerprint}",
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(features),
        "content_sha256": fingerprint,
        "generator": GENERATOR,
        "disclaimer": DISCLAIMER_EN,
        "disclaimer_fr": DISCLAIMER_FR,
    }
    if license_note:
        out["metadata"]["license"] = license_note
    if period:
        out["metadata"]["period"] = period
    if month is not None:
        out["metadata"]["month"] = month
    if source_ids:
        out["metadata"]["source_ids"] = list(source_ids)
    if doi:
        out["metadata"]["doi"] = doi
    if extra_metadata:
        for key, value in extra_metadata.items():
            out["metadata"].setdefault(key, value)
    return out


def export_response(fc: dict, dataset: str, filename: str, *,
                    license_note: str | None = None) -> JSONResponse:
    """Réponse d'export uniformisée : metadata + Content-Disposition + version HTTP."""
    out = versioned_fc(fc, dataset, license_note=license_note)
    return JSONResponse(out, headers={
        "Content-Disposition": f"attachment; filename={filename}",
        "X-Dataset-Version": out["metadata"]["version"],
    })
