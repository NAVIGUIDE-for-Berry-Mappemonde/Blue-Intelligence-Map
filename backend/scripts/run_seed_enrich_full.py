"""Enchaîne l'enrichissement seed : name_only puis unverified.

Aucun écriture poe_ports. Reprend si déjà jugé / déjà géocodé.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8001"
LOG = "/opt/cursor/artifacts/seed_enrich_full.log"


def log(msg: str) -> None:
    line = time.strftime("%H:%M:%S") + " " + msg
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def post(path: str, body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.load(r)


def wait_done(label: str) -> dict:
    while True:
        time.sleep(20)
        st = get("/api/poe/seeds/enrich/status?run_id=seed-enrich")
        live = st.get("live") or {}
        enr = st.get("enrich") or {}
        running = bool(live.get("running"))
        counts = enr.get("counts") or (live.get("summary") or {}).get("counts")
        log(
            f"{label} running={running} "
            f"progress={live.get('progress')}/{live.get('total')} "
            f"counts={counts} err={live.get('error')}"
        )
        if enr and not running:
            return st


def main() -> None:
    open(LOG, "w", encoding="utf-8").write("")
    try:
        post("/api/poe/seeds/enrich/cancel?run_id=seed-enrich")
        log("cancel previous enrich")
        time.sleep(2)
    except Exception as e:
        log(f"cancel ignored: {e}")

    phases = [
        ("name_only", {
            "source": "seeds",
            "verdicts": ["name_only"],
            "limit": 2000,
            "do_geocode": True,
            "do_verify": True,
            "use_agent": True,
            "concurrency": 2,
        }),
        ("unverified", {
            "source": "seeds",
            "verdicts": ["unverified"],
            "limit": 2000,
            "do_geocode": False,
            "do_verify": True,
            "use_agent": True,
            "concurrency": 2,
        }),
    ]
    for name, body in phases:
        log(f"START {name} {body}")
        try:
            out = post("/api/poe/seeds/enrich", body)
        except urllib.error.HTTPError as e:
            log(f"POST FAIL {name}: HTTP {e.code} {e.read()[:300]!r}")
            raise
        log(f"accepted {out}")
        st = wait_done(name)
        log(f"DONE {name} enrich={st.get('enrich')}")
    log("COMPLETE RUN FINISHED")


if __name__ == "__main__":
    main()
