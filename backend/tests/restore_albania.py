"""Utility: re-run generation for Albania (mrgid=5670) to restore data lost during regression test."""
from pathlib import Path
import time

import requests
from dotenv import dotenv_values

BASE_URL = dotenv_values(Path(__file__).resolve().parent.parent.parent / "frontend" / ".env")["REACT_APP_BACKEND_URL"].rstrip("/")

r = requests.post(f"{BASE_URL}/api/poe/zones/5670/generate", params={"force": "true"}, timeout=60)
print("POST", r.status_code, r.text[:200])
for _ in range(40):
    time.sleep(6)
    st = requests.get(f"{BASE_URL}/api/poe/zones/5670/generate/status", timeout=60).json()
    if st["state"] in ("done", "error"):
        print("STATE", st["state"], "RESULT", st.get("result"), "ERR", st.get("error"))
        print("LOGS", st.get("logs_tail", [])[-8:])
        break
    print("...", st["state"])
