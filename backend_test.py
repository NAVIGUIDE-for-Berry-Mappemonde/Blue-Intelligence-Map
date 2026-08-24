"""Backend tests for 4-bug fix phase (2026-08-24).

Covers:
  T1 — GET /api/export/formalities.geojson ships FULL content
  T2 — round-trip export → import
  T3 — GET /api/stats?mode=... returns mode-scoped counter
  T4 — GET /api/stats?mode=unknown defaults to projects
  T5 — non-regression sanity endpoints

Run: python /app/backend_test.py
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8001")
API = f"{BASE_URL}/api"

TMP_EXPORT = Path("/tmp/formalities_export_roundtrip.geojson")

results: list[tuple[str, bool, str]] = []


def _record(tag: str, ok: bool, msg: str = ""):
    results.append((tag, ok, msg))
    prefix = "PASS" if ok else "FAIL"
    print(f"[{prefix}] {tag} — {msg}")


def _assert(tag: str, cond: bool, msg: str):
    if cond:
        _record(tag, True, msg)
    else:
        _record(tag, False, msg)
    return cond


# ---------------------------------------------------------------------------
# T1 — export ships full content
# ---------------------------------------------------------------------------
def test_T1_export_full_content() -> dict:
    print("\n=== T1 — /api/export/formalities.geojson ships full content ===")
    r = requests.get(f"{API}/export/formalities.geojson", timeout=30)
    _assert("T1.http", r.status_code == 200, f"status={r.status_code}")
    if r.status_code != 200:
        return {}
    body_bytes = r.content
    size = len(body_bytes)
    _assert("T1.size>20KB", size > 20 * 1024, f"size={size} bytes ({size/1024:.1f} KB)")
    fc = r.json()
    _assert("T1.type", fc.get("type") == "FeatureCollection",
            f"type={fc.get('type')!r}")
    feats = fc.get("features") or []
    _assert("T1.count==17", len(feats) == 17, f"features={len(feats)}")

    # Save for T2 round-trip
    TMP_EXPORT.write_bytes(body_bytes)

    # Find Martinique feature
    mart = next(
        (f for f in feats if (f.get("properties") or {}).get("territory_code") == "martinique"),
        None,
    )
    _assert("T1.mart.present", mart is not None, f"found={mart is not None}")
    if not mart:
        return {"export": fc}

    props = mart.get("properties") or {}
    required = [
        "escale_name", "leg", "territory_code", "status", "is_port_of_entry",
        "stale", "generated_at", "verified_at",
        "entree", "sortie", "cas_particuliers", "immigration",
        "contacts", "liens_officiels", "sources", "escale_overlay",
    ]
    missing = [k for k in required if k not in props]
    _assert("T1.mart.all_keys", not missing,
            f"missing_keys={missing} present_keys={sorted(props.keys())}")

    entree = props.get("entree")
    _assert("T1.mart.entree_dict", isinstance(entree, dict),
            f"type(entree)={type(entree).__name__}")
    if isinstance(entree, dict):
        dem = entree.get("demarches_arrivee")
        any_nonnull = any(v not in (None, "", [], {}) for v in entree.values())
        _assert(
            "T1.mart.entree_content_populated",
            (isinstance(dem, str) and len(dem) > 0) or any_nonnull,
            f"demarches_arrivee_len={len(dem) if isinstance(dem, str) else None} "
            f"any_nonnull={any_nonnull} keys={sorted(entree.keys())}",
        )

    sortie = props.get("sortie")
    _assert("T1.mart.sortie_dict", isinstance(sortie, dict),
            f"type(sortie)={type(sortie).__name__}")

    contacts = props.get("contacts")
    _assert("T1.mart.contacts_list", isinstance(contacts, list),
            f"type(contacts)={type(contacts).__name__} len={len(contacts) if isinstance(contacts, list) else 'n/a'}")

    sources = props.get("sources")
    _assert("T1.mart.sources_list", isinstance(sources, list),
            f"type(sources)={type(sources).__name__} len={len(sources) if isinstance(sources, list) else 'n/a'}")

    return {"export": fc, "mart_props": props}


# ---------------------------------------------------------------------------
# T2 — round-trip export → import
# ---------------------------------------------------------------------------
def test_T2_round_trip(t1_data: dict):
    print("\n=== T2 — round-trip export → import ===")
    if not TMP_EXPORT.exists():
        _record("T2", False, "no export file saved from T1")
        return
    export_fc = json.loads(TMP_EXPORT.read_text(encoding="utf-8"))
    r = requests.post(
        f"{API}/import/formalities.geojson",
        json=export_fc,
        timeout=30,
    )
    _assert("T2.http", r.status_code == 200,
            f"status={r.status_code} body={r.text[:200]}")
    if r.status_code != 200:
        return
    resp = r.json()
    _assert("T2.total_formalities==13",
            resp.get("total_formalities") == 13,
            f"total_formalities={resp.get('total_formalities')} resp={resp}")
    _assert("T2.territories_touched==13",
            resp.get("territories_touched") == 13,
            f"territories_touched={resp.get('territories_touched')}")
    _assert("T2.invalid==0",
            resp.get("invalid") == 0,
            f"invalid={resp.get('invalid')}")

    # Fetch /api/formalities and compare martinique fields
    r2 = requests.get(f"{API}/formalities", timeout=30)
    _assert("T2.formalities.http", r2.status_code == 200,
            f"status={r2.status_code}")
    if r2.status_code != 200:
        return
    body = r2.json()
    items = body.get("items") or []
    mart_item = next(
        (it for it in items if it.get("territory_code") == "martinique"),
        None,
    )
    _assert("T2.mart_item.present", mart_item is not None,
            f"found={mart_item is not None}")
    if not mart_item:
        return

    exported_mart = t1_data.get("mart_props") or {}
    # entree.demarches_arrivee identical
    exported_entree = exported_mart.get("entree") or {}
    imported_entree = mart_item.get("entree") or {}
    exp_dem = exported_entree.get("demarches_arrivee") if isinstance(exported_entree, dict) else None
    imp_dem = imported_entree.get("demarches_arrivee") if isinstance(imported_entree, dict) else None
    _assert(
        "T2.entree.demarches_arrivee.identical",
        exp_dem == imp_dem,
        f"exp_len={len(exp_dem) if isinstance(exp_dem, str) else None} "
        f"imp_len={len(imp_dem) if isinstance(imp_dem, str) else None} "
        f"equal={exp_dem == imp_dem}",
    )

    # sortie.clearance preserved
    exported_sortie = exported_mart.get("sortie") or {}
    imported_sortie = mart_item.get("sortie") or {}
    exp_cl = exported_sortie.get("clearance") if isinstance(exported_sortie, dict) else None
    imp_cl = imported_sortie.get("clearance") if isinstance(imported_sortie, dict) else None
    _assert(
        "T2.sortie.clearance.preserved",
        exp_cl == imp_cl,
        f"exp={str(exp_cl)[:80]!r} imp={str(imp_cl)[:80]!r} equal={exp_cl == imp_cl}",
    )

    overlays = mart_item.get("escale_overlays") or []
    _assert(
        "T2.escale_overlays.len==1",
        isinstance(overlays, list) and len(overlays) == 1,
        f"len={len(overlays) if isinstance(overlays, list) else 'n/a'} overlays={overlays}",
    )


# ---------------------------------------------------------------------------
# T3 — /api/stats?mode=... returns mode-scoped counter
# ---------------------------------------------------------------------------
def test_T3_stats_mode_scoped():
    print("\n=== T3 — /api/stats?mode=... ===")
    cases = [
        ("projects", 4463),
        ("marinas", 212),
        ("formalities", 17),
    ]
    for mode, expected in cases:
        r = requests.get(f"{API}/stats", params={"mode": mode}, timeout=15)
        _assert(f"T3.{mode}.http", r.status_code == 200, f"status={r.status_code}")
        if r.status_code != 200:
            continue
        body = r.json()
        _assert(
            f"T3.{mode}.items_mapped=={expected}",
            body.get("items_mapped") == expected,
            f"items_mapped={body.get('items_mapped')} body={body}",
        )
        _assert(
            f"T3.{mode}.mode",
            body.get("mode") == mode,
            f"mode={body.get('mode')!r}",
        )
        if mode == "projects":
            _assert(
                "T3.projects.projects_mapped==4463(bw-compat)",
                body.get("projects_mapped") == 4463,
                f"projects_mapped={body.get('projects_mapped')}",
            )

    # Default (no query) should equal projects
    r = requests.get(f"{API}/stats", timeout=15)
    _assert("T3.default.http", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        body = r.json()
        _assert(
            "T3.default.items_mapped==4463",
            body.get("items_mapped") == 4463,
            f"items_mapped={body.get('items_mapped')} body={body}",
        )


# ---------------------------------------------------------------------------
# T4 — unknown mode defaults to projects
# ---------------------------------------------------------------------------
def test_T4_unknown_mode():
    print("\n=== T4 — /api/stats?mode=unknown ===")
    r = requests.get(f"{API}/stats", params={"mode": "xxx_unknown"}, timeout=15)
    _assert("T4.http", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    if r.status_code != 200:
        return
    body = r.json()
    _assert("T4.has_items_mapped", "items_mapped" in body,
            f"keys={sorted(body.keys())}")
    _assert("T4.no_crash", isinstance(body.get("items_mapped"), int),
            f"items_mapped={body.get('items_mapped')!r} type={type(body.get('items_mapped')).__name__}")


# ---------------------------------------------------------------------------
# T5 — non-regression sanity endpoints
# ---------------------------------------------------------------------------
def test_T5_sanity():
    print("\n=== T5 — non-regression sanity ===")

    r = requests.get(f"{API}/", timeout=15)
    _assert("T5./api/", r.status_code == 200, f"status={r.status_code}")

    r = requests.get(f"{API}/route", timeout=15)
    _assert("T5./api/route.http", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        body = r.json()
        feats = body.get("features") or []
        _assert("T5./api/route.type",
                body.get("type") == "FeatureCollection",
                f"type={body.get('type')!r}")
        _assert("T5./api/route.features>=60",
                len(feats) >= 60,
                f"features={len(feats)}")

    r = requests.get(f"{API}/projects", timeout=30)
    _assert("T5./api/projects.http", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        body = r.json()
        feats = body.get("features") or []
        _assert("T5./api/projects.count==4463",
                len(feats) == 4463,
                f"features={len(feats)}")

    r = requests.get(f"{API}/marinas", timeout=30)
    _assert("T5./api/marinas.http", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        body = r.json()
        feats = body.get("features") or []
        _assert("T5./api/marinas.count==212",
                len(feats) == 212,
                f"features={len(feats)}")

    r = requests.get(f"{API}/formalities", timeout=15)
    _assert("T5./api/formalities.http", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        body = r.json()
        _assert("T5./api/formalities.count==13",
                body.get("count") == 13,
                f"count={body.get('count')}")

    r = requests.get(f"{API}/territories", timeout=15)
    _assert("T5./api/territories.http", r.status_code == 200, f"status={r.status_code}")

    r = requests.get(f"{API}/openapi.json", timeout=15)
    _assert("T5./api/openapi.json.http", r.status_code == 200,
            f"status={r.status_code}")
    if r.status_code == 200:
        body = r.json()
        paths = body.get("paths") or {}
        required_paths = [
            "/api/import/geojson",
            "/api/import/marinas.geojson",
            "/api/import/formalities.geojson",
            "/api/export/formalities.geojson",
            "/api/stats",
        ]
        missing = [p for p in required_paths if p not in paths]
        _assert("T5./api/openapi.json.paths",
                not missing,
                f"missing_paths={missing}")


def main():
    print(f"BASE_URL = {BASE_URL}")
    t1 = test_T1_export_full_content()
    test_T2_round_trip(t1)
    test_T3_stats_mode_scoped()
    test_T4_unknown_mode()
    test_T5_sanity()

    print("\n" + "=" * 72)
    ok = sum(1 for _, o, _ in results if o)
    ko = sum(1 for _, o, _ in results if not o)
    print(f"SUMMARY: {ok} PASS · {ko} FAIL · total={len(results)}")
    if ko:
        print("\nFailures:")
        for tag, o, msg in results:
            if not o:
                print(f"  - {tag}: {msg}")
    return 0 if ko == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
