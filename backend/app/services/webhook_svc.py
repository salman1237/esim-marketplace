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
from app.models.merchant import MerchantProfile
from app.models.order import Order, OrderStatus
from app.models.partner_api import WebhookDeliveryLog
from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_ATTEMPTS = 3


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _build_payload(order: Order, esim_profile) -> dict:
    return {
        "order_id": order.id,
        "customer_reference": order.partner_customer_reference,
        "status": order.status.value,
        "iccid": esim_profile.iccid if esim_profile else None,
        "lpa_string": esim_profile.lpa_string if esim_profile else None,
        "qr_code_data": esim_profile.qr_code_data if esim_profile else None,
        "is_mock_fallback": esim_profile.is_mock_fallback if esim_profile else None,
    }


async def deliver_webhook(db: AsyncSession, merchant: MerchantProfile, order: Order, esim_profile, attempt: int = 1) -> None:
    """Sends the order webhook if the merchant has one configured, and
    always records the attempt (success or failure) so the retry sweep
    knows what still needs redelivering. Never raises — a webhook failure
    must not affect order/provisioning state."""
    if not merchant.webhook_url or not merchant.webhook_secret:
        return

    payload = _build_payload(order, esim_profile)
    body = json.dumps(payload).encode()
    signature = _sign(body, merchant.webhook_secret)

    status_code = None
    success = False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                merchant.webhook_url, content=body,
                headers={"Content-Type": "application/json", "X-Webhook-Signature": signature}
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
            Order.status == OrderStatus.COMPLETED,
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
