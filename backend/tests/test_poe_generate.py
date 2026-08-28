"""Slow test — real unitary PoE generation (OpenRouter + Nominatim) on Fiji mrgid=8325."""
from pathlib import Path
import os
import time

import requests
from dotenv import dotenv_values

frontend_env = dotenv_values(Path(__file__).resolve().parent.parent.parent / "frontend" / ".env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or frontend_env["REACT_APP_BACKEND_URL"]).rstrip("/")
MRGID = 8325


def test_generate_fiji_force_and_conflict():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/poe/zones/{MRGID}/generate", params={"force": "true"}, timeout=60)
    assert r.status_code == 202, f"{r.status_code} {r.text[:300]}"
    assert r.json().get("mrgid") == MRGID

    # A second POST while running must return 409
    r2 = s.post(f"{BASE_URL}/api/poe/zones/{MRGID}/generate", params={"force": "true"}, timeout=60)
    assert r2.status_code == 409, f"expected 409 got {r2.status_code} {r2.text[:200]}"

    state, payload = None, None
    deadline = time.time() + 300
    seen_running = False
    while time.time() < deadline:
        st = s.get(f"{BASE_URL}/api/poe/zones/{MRGID}/generate/status", timeout=60)
        assert st.status_code == 200
        payload = st.json()
        state = payload["state"]
        if state == "running":
            seen_running = True
        if state in ("done", "error"):
            break
        time.sleep(8)

    print("LOGS:", (payload or {}).get("logs_tail", [])[-12:])
    assert seen_running, "never observed running state"
    assert state == "done", f"state={state} error={(payload or {}).get('error')}"
    result = payload["result"]
    assert result is not None
    assert result["status"] == "ia", result
    assert result["poe_count"] > 0, result
