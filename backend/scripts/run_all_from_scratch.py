#!/usr/bin/env python3
"""Enchaîne un run Complet from scratch de chaque mode (sauf Science).

N'écrit jamais dans Atlas. À lancer contre l'API locale du VPS
(http://127.0.0.1:8001) dont MONGO_URL pointe vers Mongo local.

Usage :
  python scripts/run_all_from_scratch.py
  BASE_URL=http://127.0.0.1:8001 ADMIN_KEY=… python scripts/run_all_from_scratch.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8001").rstrip("/")
ADMIN = (os.environ.get("ADMIN_KEY") or "").strip()
POLL_S = float(os.environ.get("FROM_SCRATCH_POLL_S") or 15)
MODES = ("projects", "marinas", "capitaineries", "formalities", "amp")


def _req(method: str, path: str, body: dict | None = None, timeout: int = 60) -> dict:
    url = f"{BASE}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if ADMIN:
        headers["X-Admin-Key"] = ADMIN
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise SystemExit(f"{method} {path} → HTTP {exc.code}: {detail}") from exc


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"[{ts}] {msg}", flush=True)


def any_running(paths: list[str]) -> bool:
    for path in paths:
        try:
            data = _req("GET", path)
        except SystemExit:
            return False
        if data.get("running") or data.get("cycle_running"):
            return True
        if data.get("active_run_ids"):
            return True
        if data.get("active_run_id"):
            return True
        live = data.get("live") or {}
        if isinstance(live, dict) and live.get("running"):
            return True
        run = data.get("run") or {}
        if isinstance(run, dict) and run.get("state") in ("running", "started"):
            return True
        task = data.get("task") or {}
        if isinstance(task, dict) and task.get("running"):
            return True
    return False


def wait_idle(label: str, paths: list[str], *, must_have_started: bool = True) -> None:
    seen = False
    idle = 0
    while True:
        running = any_running(paths)
        if running:
            seen = True
            idle = 0
            log(f"{label}: en cours…")
        else:
            idle += 1
            if seen and idle >= 2:
                log(f"{label}: terminé")
                return
            if not must_have_started and idle >= 2:
                log(f"{label}: déjà idle")
                return
        time.sleep(POLL_S)


def start_projects() -> str:
    data = _req("POST", "/api/projects/runs", {
        "mode": "full", "from_scratch": True, "force_rescan": True,
        "label": "from-scratch-all",
    })
    rid = data.get("run_id") or ""
    log(f"Projets démarré run_id={rid} from_scratch={data.get('from_scratch')}")
    return rid


def start_marinas() -> str:
    data = _req("POST", "/api/marinas/build", {
        "scope": "full", "from_scratch": True, "resume": False,
        "maps_place_after": True, "clear_before": False,
        "label": "from-scratch-all",
    })
    rid = data.get("run_id") or ""
    log(f"Marinas démarré run_id={rid} from_scratch={data.get('from_scratch')}")
    return rid


def start_capitaineries() -> str:
    data = _req("POST", "/api/capitaineries/build", {
        "scope": "full", "from_scratch": True, "resume": False,
        "clear_before": False, "label": "from-scratch-all",
    })
    rid = data.get("run_id") or ""
    log(f"Capitaineries démarré run_id={rid} from_scratch={data.get('from_scratch')}")
    return rid


def start_formalities() -> str:
    data = _req("POST", "/api/poe/runs", {
        "variant": "tinyfish", "from_scratch": True,
        "label": "from-scratch-all",
    })
    rid = data.get("run_id") or ""
    log(f"Formalités démarré run_id={rid}")
    return rid


def start_amp() -> str:
    data = _req("POST", "/api/amp/discover-visit-urls", {
        "scope": "full", "from_scratch": True, "harvest_polygons": True,
        "limit": 0, "skip_search": False, "label": "from-scratch-all",
    })
    rid = data.get("run_id") or ""
    log(f"AMP démarré run_id={rid} from_scratch={data.get('from_scratch')}")
    return rid


def main() -> int:
    health = _req("GET", "/api/")
    mongo = str(health.get("mongo") or "")
    log(f"API {BASE} mongo={mongo} status={health.get('status')}")
    if "atlas" in mongo.lower() or "mongodb.net" in mongo.lower():
        log("REFUS : Mongo Atlas (figé). Lancer ce script sur le VPS (mongo=local).")
        return 2

    wanted = [m.strip() for m in os.environ.get("MODES", ",".join(MODES)).split(",") if m.strip()]
    for mode in wanted:
        if mode == "science":
            log("Science ignoré (demande explicite)")
            continue
        if mode == "projects":
            rid = start_projects()
            wait_idle("Projets", [
                "/api/swarm/status",
                f"/api/projects/runs/{rid}/status" if rid else "/api/swarm/status",
            ])
        elif mode == "marinas":
            start_marinas()
            wait_idle("Marinas", [
                "/api/marinas/build/status",
                "/api/marinas/enrich-batch/status",
                "/api/marinas/maps-place/status",
                "/api/anchorages/build/status",
            ])
        elif mode == "capitaineries":
            start_capitaineries()
            wait_idle("Capitaineries", [
                "/api/capitaineries/build/status",
                "/api/capitaineries/enrich-batch/status",
            ])
        elif mode == "formalities":
            rid = start_formalities()
            wait_idle("Formalités", [
                "/api/poe/runs",
                f"/api/poe/runs/{rid}/status" if rid else "/api/poe/runs",
            ])
        elif mode == "amp":
            start_amp()
            wait_idle("AMP", ["/api/amp/discover-visit-urls/status"])
        else:
            log(f"mode inconnu ignoré: {mode}")
    log("Tous les modes demandés sont terminés (sauf Science).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
