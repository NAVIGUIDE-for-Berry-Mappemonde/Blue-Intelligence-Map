"""Iteration 3: Donations / Stripe sandbox tests.

Covers:
- POST /api/donations/checkout with valid + invalid package_id
- Mongo payment_transactions record created with status initiated / pending
- GET /api/payments/status/{session_id} for pending + unknown
- GET /api/donations/total counts only payment_status=paid records
  (insert fake paid record, verify increment, then remove)
"""
import os
import uuid
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


@pytest.fixture(scope="module")
def s():
    return requests.Session()


@pytest.fixture(scope="module")
def coll():
    c = MongoClient(MONGO_URL)[DB_NAME]["payment_transactions"]
    return c


def test_checkout_invalid_package(s):
    r = s.post(f"{API}/donations/checkout", json={
        "package_id": "don_bogus",
        "origin_url": BASE_URL,
    })
    assert r.status_code == 400, r.text


def test_checkout_valid_creates_session_and_record(s, coll):
    r = s.post(f"{API}/donations/checkout", json={
        "package_id": "don_10",
        "origin_url": BASE_URL,
        "project_id": "TEST_proj",
        "project_title": "Test Project",
    }, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "session_id" in d and d["session_id"]
    assert d["checkout_url"].startswith("https://checkout.stripe.com"), d["checkout_url"]

    # Verify Mongo record
    rec = coll.find_one({"session_id": d["session_id"]})
    assert rec is not None
    assert rec["amount"] == 10.0
    assert rec["currency"] == "eur"
    assert rec["payment_status"] == "pending"
    assert rec["status"] == "initiated"
    assert rec["project_id"] == "TEST_proj"

    # Save session for status test
    pytest.session_id_pending = d["session_id"]


def test_payment_status_pending(s):
    sid = getattr(pytest, "session_id_pending", None)
    assert sid, "no session id from prior test"
    r = s.get(f"{API}/payments/status/{sid}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["session_id"] == sid
    # Should be pending (unpaid stripe session)
    assert d["payment_status"] in ("pending", "unpaid")


def test_payment_status_unknown_404(s):
    r = s.get(f"{API}/payments/status/cs_test_unknown_bogus_{uuid.uuid4().hex}")
    assert r.status_code == 404


def test_donations_total_shape_and_counts_only_paid(s, coll):
    # Baseline
    r0 = s.get(f"{API}/donations/total")
    assert r0.status_code == 200
    base = r0.json()
    assert "total_eur" in base and "count" in base
    base_total = float(base["total_eur"])
    base_count = int(base["count"])

    # Insert a fake paid record directly
    fake_id = f"TEST_paid_{uuid.uuid4().hex}"
    coll.insert_one({
        "_id": fake_id,
        "session_id": fake_id,
        "package_id": "don_10",
        "amount": 10.0,
        "currency": "eur",
        "status": "completed",
        "payment_status": "paid",
        "project_id": "TEST",
        "project_title": "TEST",
    })
    try:
        r1 = s.get(f"{API}/donations/total")
        assert r1.status_code == 200
        after = r1.json()
        assert round(float(after["total_eur"]) - base_total, 2) == 10.00, (base, after)
        assert int(after["count"]) == base_count + 1
    finally:
        coll.delete_one({"_id": fake_id})

    # Baseline restored
    r2 = s.get(f"{API}/donations/total").json()
    assert round(float(r2["total_eur"]), 2) == round(base_total, 2)
    assert int(r2["count"]) == base_count
