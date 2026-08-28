"""app.routers.donations — Dons Stripe (SDK officiel) : checkout, statut, webhook."""
import asyncio
import os
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.db import db
from app.services.swarm_pipeline import now_iso

router = APIRouter(prefix="/api")

# ---------- Donations (Stripe, SDK officiel) ----------
DONATION_PACKAGES = {"don_5": 5.0, "don_10": 10.0, "don_25": 25.0, "don_50": 50.0, "don_100": 100.0}


def _stripe():
    import stripe as stripe_sdk
    stripe_sdk.api_key = os.environ["STRIPE_API_KEY"]
    return stripe_sdk


class DonationCheckoutBody(BaseModel):
    package_id: str
    origin_url: str
    project_id: str | None = None
    project_title: str | None = None


@router.post("/donations/checkout")
async def donation_checkout(body: DonationCheckoutBody, request: Request):
    amount = DONATION_PACKAGES.get(body.package_id)
    if amount is None:
        raise HTTPException(400, "invalid package_id")
    sdk = _stripe()
    session = await asyncio.to_thread(
        sdk.checkout.Session.create,
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "eur",
                "product_data": {"name": "Don Blue Intelligence"},
                "unit_amount": int(amount * 100),
            },
            "quantity": 1,
        }],
        success_url=f"{body.origin_url}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{body.origin_url}/payment/cancel",
        metadata={"project_id": body.project_id or "", "project_title": (body.project_title or "")[:100], "package_id": body.package_id},
    )
    await db.payment_transactions.insert_one({
        "_id": str(uuid.uuid4()), "session_id": session.id,
        "package_id": body.package_id, "amount": amount, "currency": "eur",
        "project_id": body.project_id, "project_title": body.project_title,
        "status": "initiated", "payment_status": "pending",
        "created_at": now_iso(), "updated_at": now_iso(),
    })
    return {"checkout_url": session.url, "session_id": session.id}


@router.get("/payments/status/{session_id}")
async def payment_status(session_id: str, request: Request):
    record = await db.payment_transactions.find_one({"session_id": session_id})
    if not record:
        raise HTTPException(404, "Transaction not found")
    if record.get("payment_status") != "paid":
        try:
            sdk = _stripe()
            st = await asyncio.to_thread(sdk.checkout.Session.retrieve, session_id)
            if st.payment_status == "paid" or st.status == "complete":
                await db.payment_transactions.update_one(
                    {"session_id": session_id, "payment_status": {"$ne": "paid"}},
                    {"$set": {"status": "completed", "payment_status": "paid", "updated_at": now_iso()}},
                )
                record = await db.payment_transactions.find_one({"session_id": session_id})
        except Exception:
            pass
    return {"session_id": record["session_id"], "status": record["status"], "payment_status": record["payment_status"]}


@router.get("/donations/total")
async def donations_total():
    pipeline_agg = [
        {"$match": {"payment_status": "paid"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}, "count": {"$sum": 1}}},
    ]
    rows = await db.payment_transactions.aggregate(pipeline_agg).to_list(1)
    total = rows[0]["total"] if rows else 0.0
    count = rows[0]["count"] if rows else 0
    return {"total_eur": round(total, 2), "count": count}

@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Webhook Stripe — signature vérifiée avec STRIPE_WEBHOOK_SECRET."""
    sdk = _stripe()
    whsec = (os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip()
    if not whsec:
        raise HTTPException(400, "STRIPE_WEBHOOK_SECRET not configured")
    body = await request.body()
    try:
        event = sdk.Webhook.construct_event(body, request.headers.get("Stripe-Signature"), whsec)
    except Exception as e:
        raise HTTPException(400, f"webhook error: {e}")
    if event["type"] in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        session = event["data"]["object"]
        if session.get("payment_status") == "paid":
            await db.payment_transactions.update_one(
                {"session_id": session["id"], "payment_status": {"$ne": "paid"}},
                {"$set": {"status": "completed", "payment_status": "paid", "updated_at": now_iso()}},
            )
    return {"status": "ok"}
