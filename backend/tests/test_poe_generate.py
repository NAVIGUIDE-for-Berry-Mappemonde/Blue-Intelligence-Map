"""generate / generate-batch retirés — 410, sans écrire poe_ports."""
from pathlib import Path
import asyncio
import os
import sys

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.routers.formalities import GENERATE_GONE  # noqa: E402

frontend_env = dotenv_values(Path(__file__).resolve().parent.parent.parent / "frontend" / ".env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
MRGID = 8325


def test_generate_gone_constant():
    assert "poe_ports" in GENERATE_GONE
    assert "/api/poe/runs" in GENERATE_GONE


def test_generate_handlers_raise_410():
    from fastapi import HTTPException
    from app.routers import formalities as f

    async def _all():
        for coro in (
            f.poe_generate(1, force=True),
            f.poe_generate_status(1),
            f.poe_generate_batch(),
            f.poe_generate_batch_status(),
            f.poe_generate_batch_cancel(),
        ):
            with pytest.raises(HTTPException) as ei:
                await coro
            assert ei.value.status_code == 410
            assert "poe_ports" in str(ei.value.detail)

    asyncio.run(_all())


@pytest.mark.skipif(not BASE_URL, reason="REACT_APP_BACKEND_URL missing")
def test_generate_fiji_force_is_gone():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/poe/zones/{MRGID}/generate", params={"force": "true"}, timeout=60)
    assert r.status_code == 410, f"{r.status_code} {r.text[:300]}"
    r2 = s.post(f"{BASE_URL}/api/poe/zones/{MRGID}/generate", params={"force": "true"}, timeout=60)
    assert r2.status_code == 410
    st = s.get(f"{BASE_URL}/api/poe/zones/{MRGID}/generate/status", timeout=60)
    assert st.status_code == 410
