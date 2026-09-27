"""Signed webhook delivery for Partner Reseller API orders, plus the
retry sweep for deliveries that failed on the first (synchronous,
best-effort) attempt from the order background task."""
import hmac
import hashlib
import json
from datetime import datetime, timedelta, timezone
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.catalog import Country, Product
from app.models.merchant import MerchantProfile
from app.models.order import Order, OrderStatus
from app.models.partner_api import WebhookDeliveryLog
from app.services import esim_telemetry_svc
from app.services.esim_links import esim_install_links
from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_ATTEMPTS = 3


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def serialize_partner_order(order: Order, esim_profile, product: Product | None, country_iso2: str | None) -> dict:
    """The one shape a partner ever sees for an order - the POST/GET
    /partner/orders responses and the webhook body - so polling and
    webhooks can never disagree. Fields are only ever added here, never
    renamed or removed: integrations built against the original payload
    keep working."""
    lpa = esim_profile.lpa_string if esim_profile else None
    return {
        "order_id": order.id,
        "order_no": order.order_no,
        "customer_reference": order.partner_customer_reference,
        "status": order.status.value,
        "amount": str(order.total_amount),
        "currency": order.currency,
        "product": {
            "id": product.id,
            "title": product.title_en,
            "country_iso2": country_iso2,
            "data_amount_gb": float(product.data_amount_gb) if product.data_amount_gb is not None else None,
            "is_unlimited": bool(product.is_unlimited),
            "validity_days": product.validity_days,
        } if product else None,
        "iccid": esim_profile.iccid if esim_profile else None,
        "lpa_string": lpa,
        "qr_code_data": esim_profile.qr_code_data if esim_profile else None,
        "smdp_address": esim_profile.smdp_address if esim_profile else None,
        "matching_id": esim_profile.matching_id if esim_profile else None,
        "install_links": esim_install_links(lpa),
        # The public tracking page, so a partner can forward it to their own
        # customer instead of building a usage view themselves.
        "status_url": esim_telemetry_svc.share_url(esim_profile) if esim_profile else None,
        "is_mock_fallback": esim_profile.is_mock_fallback if esim_profile else None,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }


async def build_partner_order_payload(db: AsyncSession, order: Order, esim_profile) -> dict:
    row = (await db.execute(
        select(Product, Country.iso2).join(Country, Product.country_id == Country.id).where(Product.id == order.product_id)
    )).first()
    product, iso2 = (row[0], row[1]) if row else (None, None)
    return serialize_partner_order(order, esim_profile, product, iso2)


async def deliver_webhook(db: AsyncSession, merchant: MerchantProfile, order: Order, esim_profile, attempt: int = 1) -> None:
    """Sends the order webhook if the merchant has one configured, and
    always records the attempt (success or failure) so the retry sweep
    knows what still needs redelivering. Never raises — a webhook failure
    must not affect order/provisioning state."""
    if not merchant.webhook_url or not merchant.webhook_secret:
        return

    payload = await build_partner_order_payload(db, order, esim_profile)
    body = json.dumps(payload).encode()
    signature = _sign(body, merchant.webhook_secret)

    status_code = None
    success = False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                merchant.webhook_url, content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Signature": signature,
                    "X-Webhook-Event": "order.updated",
                }
            )
            status_code = resp.status_code
            success = 200 <= resp.status_code < 300
    except Exception as e:
        logger.warning("webhook_delivery_failed", order_id=order.id, merchant_id=merchant.id, attempt=attempt, error=str(e))

    db.add(WebhookDeliveryLog(
        merchant_id=merchant.id, order_id=order.id, url=merchant.webhook_url,
        payload=body.decode(), response_status=status_code, attempt=attempt, success=success
    ))
    await db.commit()


async def send_test_webhook(merchant: MerchantProfile) -> dict:
    """A signed ping so a merchant can check their receiver - reachable,
    signature verification wired up - without waiting for a real order.
    Not written to WebhookDeliveryLog: that table tracks order deliveries
    for the retry sweep, and a test must never be retried."""
    payload = {
        "event": "webhook.test",
        "business_name": merchant.business_name,
        "message": "Test delivery from Triptel. Respond with any 2xx status.",
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": _sign(body, merchant.webhook_secret),
        "X-Webhook-Event": "webhook.test",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(merchant.webhook_url, content=body, headers=headers)
        return {"delivered": 200 <= resp.status_code < 300, "status_code": resp.status_code, "error": None}
    except Exception as e:
        logger.info("webhook_test_failed", merchant_id=merchant.id, error=str(e))
        return {"delivered": False, "status_code": None, "error": f"Could not reach the webhook URL ({type(e).__name__})"}


async def retry_failed_webhooks(db: AsyncSession) -> dict:
    """Finds COMPLETED reseller orders from the last 24h whose merchant
    has a webhook configured but has no successful delivery yet and
    hasn't exhausted MAX_ATTEMPTS, and redelivers. Run periodically by
    the scheduler in app/main.py."""
    from sqlalchemy.orm import selectinload

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    orders_res = await db.execute(
        select(Order).options(selectinload(Order.esim_profile)).where(
            Order.is_reseller_order == True,
            # FAILED too: a partner that never hears about a failure keeps
            # waiting on an eSIM that will never come.
            Order.status.in_([OrderStatus.COMPLETED, OrderStatus.FAILED]),
            Order.created_at >= cutoff,
        )
    )
    candidates = orders_res.scalars().all()

    retried = 0
    for order in candidates:
        log_res = await db.execute(
            select(WebhookDeliveryLog).where(WebhookDeliveryLog.order_id == order.id)
        )
        attempts = log_res.scalars().all()
        if not attempts:
            continue  # never attempted (no webhook_url at delivery time) - not this sweep's job
        if any(a.success for a in attempts):
            continue
        if len(attempts) >= MAX_ATTEMPTS:
            continue

        m_res = await db.execute(select(MerchantProfile).where(MerchantProfile.user_id == order.buyer_id))
        merchant = m_res.scalar_one_or_none()
        if not merchant or not merchant.webhook_url:
            continue

        await deliver_webhook(db, merchant, order, order.esim_profile, attempt=len(attempts) + 1)
        retried += 1

    return {"candidates": len(candidates), "retried": retried}
