"""
Phase 3.1 async enrichment bug fix – backend test suite.

Runs T1..T10 as described in the review request against the URL declared in
frontend/.env (REACT_APP_BACKEND_URL) + /api. Read-only verification only.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

# ---------- Base URL ----------
def _load_base_url() -> str:
    env_path = Path("/app/frontend/.env")
    for line in env_path.read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("REACT_APP_BACKEND_URL not found in frontend/.env")

BASE = _load_base_url().rstrip("/") + "/api"
print(f"[setup] BASE = {BASE}")

# ---------- helpers ----------
RESULTS: dict[str, dict[str, Any]] = {}

def record(tid: str, ok: bool, detail: str, extra: dict | None = None):
    RESULTS[tid] = {"ok": ok, "detail": detail, **(extra or {})}
    tag = "✅" if ok else "❌"
    print(f"{tag} {tid}: {detail}")

def timed_post(url: str, **kw) -> tuple[requests.Response, float]:
    t0 = time.monotonic()
    r = requests.post(url, timeout=kw.pop("timeout", 30), **kw)
    return r, time.monotonic() - t0

def timed_get(url: str, **kw) -> tuple[requests.Response, float]:
    t0 = time.monotonic()
    r = requests.get(url, timeout=kw.pop("timeout", 30), **kw)
    return r, time.monotonic() - t0

def poll_status(url: str, timeout_s: float, interval: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last = {}
    while time.monotonic() < deadline:
        r, _ = timed_get(url)
        last = r.json()
        if last.get("state") in ("done", "error"):
            return last
        time.sleep(interval)
    return last

# ---------- setup constants ----------
MARINA_PRIMARY = "b75bc928-b5bb-4a54-a433-142c8dffc208"  # Port des Minimes
BAD_ID = "00000000-0000-0000-0000-000000000000"
MAX_HTTP_TIME_OBSERVED = 0.0

def observe_time(t: float):
    global MAX_HTTP_TIME_OBSERVED
    MAX_HTTP_TIME_OBSERVED = max(MAX_HTTP_TIME_OBSERVED, t)

# ================================================================
# T1: Marina POST returns 202 fast
# ================================================================
print("\n--- T1: marina POST returns 202 fast ---")
url_t1 = f"{BASE}/marinas/{MARINA_PRIMARY}/enrich"
r, elapsed = timed_post(url_t1)
observe_time(elapsed)
print(f"  status={r.status_code} elapsed={elapsed:.2f}s body={r.text[:200]}")
t1_ok = False
t1_body = {}
if r.status_code == 202:
    try:
        t1_body = r.json()
    except Exception:
        t1_body = {}
    t1_ok = (
        elapsed < 5.0
        and t1_body.get("status") == "started"
        and t1_body.get("marina_id") == MARINA_PRIMARY
    )
    record("T1", t1_ok, f"HTTP 202 in {elapsed:.2f}s body={t1_body}",
           {"elapsed": elapsed, "body": t1_body})
elif r.status_code == 409:
    # A prior test left a task running — wait it out and retry once
    print("  409 lock hit — waiting up to 180s for prior task to finish, then retry")
    poll_status(f"{BASE}/marinas/{MARINA_PRIMARY}/enrich/status", 180)
    r, elapsed = timed_post(url_t1)
    observe_time(elapsed)
    print(f"  retry status={r.status_code} elapsed={elapsed:.2f}s")
    if r.status_code == 202 and elapsed < 5.0:
        t1_body = r.json()
        t1_ok = t1_body.get("status") == "started"
    record("T1", t1_ok, f"After 409 wait: HTTP {r.status_code} in {elapsed:.2f}s",
           {"elapsed": elapsed, "body": t1_body})
else:
    record("T1", False, f"unexpected HTTP {r.status_code}: {r.text[:200]}")

# ================================================================
# T2: Marina status lifecycle
# ================================================================
print("\n--- T2: marina status endpoint lifecycle ---")
status_url = f"{BASE}/marinas/{MARINA_PRIMARY}/enrich/status"
r, _ = timed_get(status_url)
s0 = r.json()
print(f"  immediate: state={s0.get('state')} started_at={s0.get('started_at')} "
      f"finished_at={s0.get('finished_at')} logs_tail_len={len(s0.get('logs_tail') or [])}")

immediate_running_ok = (
    s0.get("state") == "running"
    and s0.get("started_at") is not None
    and s0.get("finished_at") is None
)
final = poll_status(status_url, timeout_s=200, interval=3.0)
print(f"  final state={final.get('state')} finished_at={final.get('finished_at')}")
result = final.get("result") or {}
err = final.get("error")
enrichment_source = result.get("enrichment_source") if isinstance(result, dict) else None

filled_fields = 0
enrichment_fields = [
    "phone", "email", "website", "vhf_channel", "electricity_amperage",
    "berth_count", "max_length_m",
]
if isinstance(result, dict):
    filled_fields = sum(1 for f in enrichment_fields if result.get(f) not in (None, "", []))

t2_ok = immediate_running_ok and final.get("state") in ("done", "error")
detail = (
    f"immediate running OK={immediate_running_ok}; "
    f"final={final.get('state')} source={enrichment_source} "
    f"fields_filled={filled_fields}/7 error={err}"
)
record("T2", t2_ok, detail,
       {"final_state": final.get("state"),
        "enrichment_source": enrichment_source,
        "fields_filled": filled_fields,
        "logs_tail": final.get("logs_tail", [])})

# ================================================================
# T3: per-id 409 lock
# ================================================================
print("\n--- T3: per-id 409 lock ---")
# Pick a different marina that hasn't been enriched (in this session)
# We'll list marinas and pick one whose id is not MARINA_PRIMARY.
r, _ = timed_get(f"{BASE}/marinas?limit=20")
marinas_list = r.json() if r.status_code == 200 else []
alt_marina_id = None
if isinstance(marinas_list, list):
    for m in marinas_list:
        mid = m.get("_id") or m.get("id")
        if mid and mid != MARINA_PRIMARY:
            alt_marina_id = mid
            break
elif isinstance(marinas_list, dict):
    feats = marinas_list.get("features") or marinas_list.get("items") or []
    for m in feats:
        mid = (m.get("properties") or {}).get("id") or m.get("_id")
        if mid and mid != MARINA_PRIMARY:
            alt_marina_id = mid
            break
print(f"  alt marina picked: {alt_marina_id}")

if alt_marina_id:
    r1, e1 = timed_post(f"{BASE}/marinas/{alt_marina_id}/enrich")
    observe_time(e1)
    print(f"  first POST status={r1.status_code} in {e1:.2f}s")
    # immediate re-post
    r2, e2 = timed_post(f"{BASE}/marinas/{alt_marina_id}/enrich")
    observe_time(e2)
    print(f"  second POST status={r2.status_code} in {e2:.2f}s body={r2.text[:200]}")
    body2 = {}
    try:
        body2 = r2.json()
    except Exception:
        pass
    t3_ok = (
        r1.status_code == 202
        and r2.status_code == 409
        and "already in progress" in (body2.get("detail") or "").lower()
    )
    record("T3", t3_ok,
           f"first={r1.status_code} second={r2.status_code} detail={body2.get('detail')}",
           {"alt_marina_id": alt_marina_id})
else:
    record("T3", False, "could not find an alt marina id to test 409")

# ================================================================
# T4: Project POST returns 202 fast
# ================================================================
print("\n--- T4: project POST returns 202 fast ---")
r, _ = timed_get(f"{BASE}/projects")
projects_payload = r.json() if r.status_code == 200 else {}
project_id = None
project_url_present = False
if isinstance(projects_payload, dict):
    feats = projects_payload.get("features") or []
    for f in feats:
        props = f.get("properties") or {}
        pid = props.get("id")
        if pid:
            # need a URL — projects without URL return 400 per code
            if props.get("url"):
                project_id = pid
                project_url_present = True
                break
            elif project_id is None:
                project_id = pid  # fallback
print(f"  project_id={project_id} url_present={project_url_present}")

t4_ok = False
if project_id:
    r, elapsed = timed_post(f"{BASE}/projects/{project_id}/enrich")
    observe_time(elapsed)
    print(f"  status={r.status_code} elapsed={elapsed:.2f}s body={r.text[:200]}")
    if r.status_code == 202 and elapsed < 5.0:
        b = r.json()
        t4_ok = b.get("status") == "started" and b.get("project_id") == project_id
        record("T4", t4_ok, f"HTTP 202 in {elapsed:.2f}s body={b}",
               {"elapsed": elapsed, "project_id": project_id})
    elif r.status_code == 400:
        # project had no url — try next one
        print("  400: project has no URL, picking another with a URL...")
        picked = None
        for f in projects_payload.get("features", []):
            props = f.get("properties") or {}
            if props.get("url") and props.get("id") != project_id:
                picked = props.get("id")
                break
        if picked:
            project_id = picked
            r, elapsed = timed_post(f"{BASE}/projects/{project_id}/enrich")
            observe_time(elapsed)
            print(f"  retry status={r.status_code} elapsed={elapsed:.2f}s")
            if r.status_code == 202 and elapsed < 5.0:
                b = r.json()
                t4_ok = b.get("status") == "started"
                record("T4", t4_ok, f"HTTP 202 in {elapsed:.2f}s body={b}",
                       {"elapsed": elapsed, "project_id": project_id})
            else:
                record("T4", False, f"retry HTTP {r.status_code} in {elapsed:.2f}s: {r.text[:200]}")
        else:
            record("T4", False, "no project with URL found to test 202")
    else:
        record("T4", False, f"unexpected HTTP {r.status_code} in {elapsed:.2f}s: {r.text[:200]}")
else:
    record("T4", False, "no project id available")

# ================================================================
# T5: Project status lifecycle
# ================================================================
print("\n--- T5: project status lifecycle ---")
if t4_ok and project_id:
    proj_status_url = f"{BASE}/projects/{project_id}/enrich/status"
    r, _ = timed_get(proj_status_url)
    ps0 = r.json()
    print(f"  immediate state={ps0.get('state')}")
    immediate_ok = ps0.get("state") == "running"
    final_p = poll_status(proj_status_url, timeout_s=120, interval=3.0)
    print(f"  final state={final_p.get('state')} error={final_p.get('error')}")
    t5_ok = immediate_ok and final_p.get("state") in ("done", "error")
    detail = f"immediate_running={immediate_ok} final={final_p.get('state')} error={final_p.get('error')}"
    record("T5", t5_ok, detail,
           {"final_state": final_p.get("state"),
            "logs_tail": final_p.get("logs_tail", [])})
else:
    record("T5", False, "skipped due to T4 failure")

# ================================================================
# T6: Idle state before any POST
# ================================================================
print("\n--- T6: idle state before first POST ---")
# find a fresh marina id we have NOT posted against
fresh_id = None
used = {MARINA_PRIMARY, alt_marina_id}
if isinstance(marinas_list, list):
    for m in marinas_list:
        mid = m.get("_id") or m.get("id")
        if mid and mid not in used:
            fresh_id = mid
            break
elif isinstance(marinas_list, dict):
    for feat in marinas_list.get("features") or []:
        props = feat.get("properties") or {}
        mid = props.get("id") or feat.get("_id")
        if mid and mid not in used:
            fresh_id = mid
            break
print(f"  fresh_id={fresh_id}")
if fresh_id:
    r, _ = timed_get(f"{BASE}/marinas/{fresh_id}/enrich/status")
    body = r.json() if r.ok else {}
    print(f"  status={r.status_code} body={body}")
    t6_ok = r.status_code == 200 and body.get("state") == "idle"
    record("T6", t6_ok, f"HTTP {r.status_code} state={body.get('state')}")
else:
    record("T6", False, "no fresh marina id to test idle state")

# ================================================================
# T7: 404 on unknown id
# ================================================================
print("\n--- T7: 404 on unknown id ---")
r1, _ = timed_post(f"{BASE}/marinas/{BAD_ID}/enrich")
r2, _ = timed_post(f"{BASE}/projects/{BAD_ID}/enrich")
b1, b2 = {}, {}
try:
    b1 = r1.json()
except Exception:
    pass
try:
    b2 = r2.json()
except Exception:
    pass
print(f"  marinas: {r1.status_code} {b1}")
print(f"  projects: {r2.status_code} {b2}")
t7_ok = (
    r1.status_code == 404 and "marina not found" in (b1.get("detail") or "").lower()
    and r2.status_code == 404 and "project not found" in (b2.get("detail") or "").lower()
)
record("T7", t7_ok,
       f"marinas: {r1.status_code} '{b1.get('detail')}' | projects: {r2.status_code} '{b2.get('detail')}'")

# ================================================================
# T8: Chain order in logs (using final logs_tail from T2)
# ================================================================
print("\n--- T8: chain order in logs_tail ---")
logs = RESULTS.get("T2", {}).get("logs_tail", []) or []
joined = "\n".join(logs)
print("  logs_tail sample:")
for line in logs[-30:]:
    print(f"    {line}")
# order check
def find_idx(needle: str) -> int:
    for i, line in enumerate(logs):
        if needle.lower() in line.lower():
            return i
    return -1

idx_tiny = find_idx("tinyfish")
idx_kimi = find_idx("kimi")
idx_or = find_idx("openrouter")
idx_fb = find_idx("fallback")
print(f"  idx tinyfish={idx_tiny} kimi={idx_kimi} openrouter={idx_or} fallback={idx_fb}")

# Order: TinyFish first; later tiers must be after if present
present = [(n, i) for n, i in [
    ("tinyfish", idx_tiny), ("kimi", idx_kimi),
    ("openrouter", idx_or), ("fallback", idx_fb)
] if i >= 0]
order_ok = all(present[k][1] < present[k+1][1] for k in range(len(present) - 1))
tinyfish_present = idx_tiny >= 0
t8_ok = tinyfish_present and order_ok
kimi_auth_seen = any(("[kimi]" in ln and ("auth error" in ln.lower() or "401" in ln
                     or "unavailable" in ln.lower() or "no credentials" in ln.lower()))
                     for ln in logs)
detail = (
    f"tinyfish_present={tinyfish_present} order_ok={order_ok} "
    f"kimi_auth_line_seen={kimi_auth_seen} present={present}"
)
record("T8", t8_ok, detail, {"kimi_auth_seen": kimi_auth_seen})

# ================================================================
# T9: No-regression sanity
# ================================================================
print("\n--- T9: no-regression sanity ---")
issues = []

r, _ = timed_get(f"{BASE}/")
observe_time(_)
if r.status_code != 200:
    issues.append(f"GET /api/ => {r.status_code}")

r, _ = timed_get(f"{BASE}/openapi.json")
observe_time(_)
paths = {}
if r.status_code == 200:
    paths = (r.json() or {}).get("paths", {})
else:
    issues.append(f"GET /api/openapi.json => {r.status_code}")
required_paths = [
    "/api/marinas/{marina_id}/enrich",
    "/api/marinas/{marina_id}/enrich/status",
    "/api/projects/{project_id}/enrich",
    "/api/projects/{project_id}/enrich/status",
]
missing_paths = [p for p in required_paths if p not in paths]
if missing_paths:
    issues.append(f"openapi missing: {missing_paths}")

r, _ = timed_get(f"{BASE}/marinas/count")
observe_time(_)
if r.status_code != 200:
    issues.append(f"marinas/count => {r.status_code}")
else:
    total = r.json().get("total")
    if not (isinstance(total, int) and total >= 200):
        issues.append(f"marinas/count total={total} <200")
    else:
        print(f"  marinas/count total={total}")

r, _ = timed_get(f"{BASE}/route")
observe_time(_)
if r.status_code != 200:
    issues.append(f"/route => {r.status_code}")
else:
    j = r.json()
    n_feats = len(j.get("features", []))
    print(f"  route type={j.get('type')} features={n_feats}")
    if j.get("type") != "FeatureCollection":
        issues.append(f"/route type={j.get('type')}")
    if n_feats != 71:
        issues.append(f"/route features={n_feats} (expected 71)")

r, _ = timed_get(f"{BASE}/projects")
observe_time(_)
if r.status_code != 200:
    issues.append(f"/projects => {r.status_code}")
else:
    j = r.json()
    n_feats = len(j.get("features", []))
    print(f"  projects features={n_feats}")
    if n_feats != 4463:
        issues.append(f"/projects features={n_feats} (expected 4463)")

# enrich-batch
r, e = timed_post(f"{BASE}/marinas/enrich-batch", json={"limit": 2})
observe_time(e)
print(f"  enrich-batch: {r.status_code} in {e:.2f}s body={r.text[:200]}")
if r.status_code not in (200, 202, 409):
    issues.append(f"enrich-batch POST => {r.status_code}")
else:
    try:
        bb = r.json()
        if r.status_code in (200, 202) and bb.get("started") is not True:
            # server may return other shape; check for other indicators
            pass
    except Exception:
        pass
r, _ = timed_get(f"{BASE}/marinas/enrich-batch/status")
observe_time(_)
if r.status_code >= 500:
    issues.append(f"enrich-batch/status => {r.status_code}")

t9_ok = not issues
record("T9", t9_ok, f"issues={issues}")

# ================================================================
# T10: Health of the async pattern (no HTTP > 15s)
# ================================================================
print("\n--- T10: async pattern health ---")
t10_ok = MAX_HTTP_TIME_OBSERVED < 15.0
record("T10", t10_ok,
       f"max observed single-request wall-clock = {MAX_HTTP_TIME_OBSERVED:.2f}s (limit 15s)")

# ================================================================
# Final summary
# ================================================================
print("\n\n================ SUMMARY ================")
all_ok = True
for tid in sorted(RESULTS.keys()):
    r = RESULTS[tid]
    tag = "✅" if r["ok"] else "❌"
    print(f"{tag} {tid}: {r['detail']}")
    if not r["ok"]:
        all_ok = False

t2 = RESULTS.get("T2", {})
print(f"\nEnrichment source: {t2.get('enrichment_source')}")
print(f"Fields filled: {t2.get('fields_filled')}/7")
print(f"Max single HTTP wall-clock: {MAX_HTTP_TIME_OBSERVED:.2f}s")

print("\nFinal logs_tail from marina enrichment (T2):")
for ln in (t2.get("logs_tail") or [])[-30:]:
    print(f"  {ln}")

sys.exit(0 if all_ok else 1)
