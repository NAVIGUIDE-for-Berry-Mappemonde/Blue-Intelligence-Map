"""Inspirations seamap : exports versionnés, snapshots immuables, badges services, audit."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND.parent / "scripts"))

from app.core.export_meta import (
    DISCLAIMER_EN,
    content_fingerprint,
    versioned_fc,
)
from app.routers.exports import write_snapshot_files
from app.services.marina_world import marina_services, slim_feature


# ------------------------------------------------------------ export_meta

FEATURES = [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
     "properties": {"name": "A"}},
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [3.0, 4.0]},
     "properties": {"name": "B"}},
]


def test_versioned_fc_metadata_complete_et_features_intactes():
    fc = {"type": "FeatureCollection", "features": list(FEATURES),
          "attribution": "© OpenStreetMap contributors"}
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    out = versioned_fc(fc, "marinas", license_note="ODbL", now=now)
    meta = out["metadata"]
    assert meta["dataset"] == "marinas"
    assert meta["count"] == 2
    assert meta["version"] == f"2026-09-10.{meta['content_sha256']}"
    assert len(meta["content_sha256"]) == 12
    assert meta["generated_at"] == "2026-09-10T12:00:00Z"
    assert meta["license"] == "ODbL"
    assert meta["disclaimer"] == DISCLAIMER_EN
    assert "navigation" in meta["disclaimer_fr"].lower()
    # features et clés existantes intactes
    assert out["features"] == FEATURES
    assert out["attribution"] == "© OpenStreetMap contributors"
    assert "metadata" not in fc  # l'original n'est pas muté


def test_fingerprint_stable_et_sensible_au_contenu():
    a = content_fingerprint(FEATURES)
    assert a == content_fingerprint(json.loads(json.dumps(FEATURES)))
    changed = json.loads(json.dumps(FEATURES))
    changed[0]["properties"]["name"] = "Z"
    assert content_fingerprint(changed) != a
    # même contenu deux jours différents → même empreinte, versions datées distinctes
    v1 = versioned_fc({"features": FEATURES}, "d",
                      now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    v2 = versioned_fc({"features": FEATURES}, "d",
                      now=datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert v1["metadata"]["content_sha256"] == v2["metadata"]["content_sha256"]
    assert v1["metadata"]["version"] != v2["metadata"]["version"]


# ------------------------------------------------------------ snapshots

def test_snapshot_ecrit_manifest_et_reste_immuable(tmp_path):
    fc = versioned_fc({"type": "FeatureCollection", "features": FEATURES}, "route")
    manifest = write_snapshot_files(tmp_path, "2026-09-10", {"route": fc})
    target = tmp_path / "2026-09-10"
    assert (target / "route.geojson").exists()
    assert manifest["immutable"] is True
    entry = manifest["files"]["route.geojson"]
    assert entry["count"] == 2
    assert entry["version"] == fc["metadata"]["version"]
    assert entry["bytes"] > 0
    on_disk = json.loads((target / "MANIFEST.json").read_text(encoding="utf-8"))
    assert on_disk["files"]["route.geojson"]["content_sha256"] == entry["content_sha256"]
    # immuable : même date → refus, contenu intact
    before = (target / "route.geojson").read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_snapshot_files(tmp_path, "2026-09-10", {"route": fc})
    assert (target / "route.geojson").read_text(encoding="utf-8") == before


# ------------------------------------------------------------ badges services

def test_marina_services_mappe_les_questions():
    svc = marina_services({
        "fuel": "yes", "drinking_water": "yes",          # supply
        "shower": "yes", "toilets": "customers",         # shore
        "pumpout": "yes",                                # tech
        "capacity": "120", "seamark:harbour:draught": "3.5",  # berth
        "website": "https://example.org",                # hors badges
    })
    assert set(svc) == {"berth", "supply", "tech", "shore"}
    assert list(svc) == ["berth", "supply", "tech", "shore"]  # ordre canonique
    assert "capacity=120" in svc["berth"]
    assert "fuel=yes" in svc["supply"]
    assert "pumpout=yes" in svc["tech"]
    assert "toilets=customers" in svc["shore"]


def test_marina_services_ignore_les_negatifs_et_vides():
    assert marina_services({"fuel": "no", "toilets": "none", "shower": ""}) == {}
    assert marina_services({}) == {}
    assert marina_services(None) == {}


def test_marina_services_small_craft_facility_multi_valeurs():
    svc = marina_services({
        "seamark:small_craft_facility:category": "slipway;fuel",
        "seamark:small_craft_facility:2:category": "laundrette",
    })
    assert "seamark:small_craft_facility:category=slipway" in svc["tech"]
    assert "seamark:small_craft_facility:category=fuel" in svc["supply"]
    assert any(e.endswith("=laundrette") for e in svc["shore"])


def test_slim_feature_expose_svc_seulement_si_present():
    base = {"_id": "m1", "lat": 46.15, "lon": -1.17, "name": "Port Test"}
    without = slim_feature(dict(base, tags={"website": "https://x.org"}))
    assert "svc" not in without["properties"]
    with_svc = slim_feature(dict(base, tags={"fuel": "yes"}))
    assert with_svc["properties"]["svc"] == {"supply": ["fuel=yes"]}


# ------------------------------------------------------------ audit des tags

def test_audit_collect_tag_stats():
    from audit_tags import collect_tag_stats
    stats = collect_tag_stats([
        {"seamark:type": "harbour", "seamark:harbour:category": "marina",
         "fuel": "yes"},
        {"seamark:type": "anchorage", "seamark:light:1:colour": "red"},
        {},
    ])
    assert stats["docs"] == 3
    assert stats["docs_with_tags"] == 2
    assert stats["seamark_types"]["harbour"] == 1
    assert stats["seamark_types"]["anchorage"] == 1
    # sous-clé extraite en sautant le segment numérique
    assert stats["seamark_subkeys"]["colour"] == {"light"}
    assert stats["key_counts"]["fuel"] == 1


def test_audit_geojson_rapporte_couverture(tmp_path):
    from audit_tags import audit_geojson
    fc = versioned_fc({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": None,
         "properties": {"name": "A", "website": "https://x", "svc": {"supply": ["fuel=yes"]}}},
        {"type": "Feature", "geometry": None,
         "properties": {"name": "B", "website": None}},
    ]}, "marinas")
    path = tmp_path / "marinas.geojson"
    path.write_text(json.dumps(fc), encoding="utf-8")
    lines = "\n".join(audit_geojson([str(path)]))
    assert "2 features" in lines
    assert fc["metadata"]["version"] in lines
    assert "| `name` | 2 | 100.0 |" in lines
    assert "supply=1" in lines
