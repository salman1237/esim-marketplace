"""Background eSIM fulfilment, and recovery of orders it never finished.

Checkout returns as soon as payment is taken; the supplier call (~10-30s)
runs here instead of inside the HTTP request.

That makes a failure mode possible that didn't exist before: a deploy or
crash kills the in-process background task after the customer has paid.
Without recovery such an order would sit in PROCESSING forever, money
taken and nothing delivered. recover_stuck_orders() closes that gap and
must always ship alongside the async checkout.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.catalog import Product
from app.models.merchant import MerchantProfile
from app.models.order import Order, OrderStatus
from app.models.referral import ReferralEvent
from app.models.user import User
from app.services.checkout_svc import (
    provision_esim,
    distribute_commission,
    complete_from_supplier_trx,
    _refund_failed_order,
)
from app.services import esim_telemetry_svc, referral_svc
from app.services.email_svc import EmailService
from app.services.webhook_svc import deliver_webhook

logger = get_logger(__name__)

# Provisioning takes ~10-30s even with a supplier retry, so an order still
# PROCESSING after this long has lost its background task.
STUCK_AFTER = timedelta(minutes=3)
# How long to keep retrying a supplier we can't reach before refunding.
GIVE_UP_AFTER = timedelta(minutes=60)


async def _send_confirmation(db, order: Order, product: Product, profile) -> None:
    email = (await db.execute(select(User.email).where(User.id == order.beneficiary_id))).scalar_one_or_none()
    if not email:
        return
    try:
        await EmailService.send_order_confirmation(
            db, email, order.order_no, product.title_en, profile.iccid, profile.lpa_string,
            validity_days=product.validity_days,
            data_label="Unlimited" if product.is_unlimited else f"{product.data_amount_gb} GB",
            purchase_reference=profile.supplier_reference,
            purchased_at=order.created_at,
            # The customer may have no account at all (a merchant can buy on
            # their behalf), so the tracking link is how they follow their own
            # usage and expiry.
            status_url=esim_telemetry_svc.share_url(profile),
        )
    except Exception as e:
        logger.warning("order_confirmation_email_failed", order_id=order.id, error=str(e))


async def _finish(db, order: Order, product: Product, buyer: User, profile, *, email: bool = True) -> None:
    # Commission and referral rewards only on a sale that actually delivered -
    # a refunded order must not leave the merchant keeping commission, or a
    # referrer keeping promo credit, on it.
    if profile:
        await distribute_commission(db, order, Decimal(str(order.total_amount)), buyer)
        # Paid once per referred buyer: the unique constraint on
        # (referred_id, event) means every later order is a no-op, so this is
        # exactly "their first delivered purchase".
        try:
            await referral_svc.grant(db, buyer, ReferralEvent.FIRST_PURCHASE, order_id=order.id)
        except Exception as e:
            # A referral must never cost a customer their delivered eSIM.
            logger.warning("referral_first_purchase_grant_failed", order_id=order.id, error=str(e))
    await db.commit()
    if profile and email:
        await _send_confirmation(db, order, product, profile)


def _is_partner_order(order: Order) -> bool:
    # Partner API orders (POST /partner/orders) are delivered to the
    # merchant by webhook, not to the end customer by email.
    return order.order_no.startswith("PTR-")


# The event loop only holds weak references to tasks, so a fire-and-forget
# task can be garbage-collected mid-provisioning - after the customer paid.
_running: set[asyncio.Task] = set()


def start_fulfilment(order_id: str) -> None:
    """Runs fulfil_order in the background, keeping the task alive until
    it finishes. Call only after the paid order is committed."""
    task = asyncio.create_task(fulfil_order(order_id))
    _running.add(task)
    task.add_done_callback(_running.discard)


async def fulfil_order(order_id: str) -> None:
    """Provisions a PROCESSING order in its own session. A no-op for any
    other status, so it's safe to call twice for the same order."""
    async with AsyncSessionLocal() as db:
        try:
            order = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
            if not order or order.status != OrderStatus.PROCESSING:
                return
            product = (await db.execute(select(Product).where(Product.id == order.product_id))).scalar_one()
            buyer = (await db.execute(select(User).where(User.id == order.buyer_id))).scalar_one()

            profile = await provision_esim(db, order, product, order.beneficiary_id, buyer.id, buyer.role.value)
            await _finish(db, order, product, buyer, profile)
        except Exception as e:
            logger.error("order_fulfilment_failed", order_id=order_id, error=str(e))


async def recover_stuck_orders() -> dict:
    """Finishes orders whose background task died.

    - external_trx_id set: VivaPe already charged, so fetch that existing
      eSIM - never buy again. If VivaPe can't be reached, retry on later
      runs, refunding only once GIVE_UP_AFTER has passed.
    - no external_trx_id: the task died before or during create-transaction
      and we can't tell whether VivaPe charged. Refund the customer and log
      it for manual review against VivaPe's dashboard.
    """
    now = datetime.now(timezone.utc)
    counts = {"recovered": 0, "refunded": 0, "deferred": 0}

    async with AsyncSessionLocal() as db:
        order_ids = (await db.execute(
            select(Order.id).where(Order.status == OrderStatus.PROCESSING, Order.updated_at < now - STUCK_AFTER)
        )).scalars().all()

    for order_id in order_ids:
        async with AsyncSessionLocal() as db:
            try:
                order = (await db.execute(
                    select(Order).where(Order.id == order_id).with_for_update(skip_locked=True)
                )).scalar_one_or_none()
                if not order or order.status != OrderStatus.PROCESSING:
                    continue
                product = (await db.execute(select(Product).where(Product.id == order.product_id))).scalar_one()
                buyer = (await db.execute(select(User).where(User.id == order.buyer_id))).scalar_one()

                if order.external_trx_id:
                    try:
                        profile = await complete_from_supplier_trx(db, order, product, buyer.id, buyer.role.value)
                    except Exception as e:
                        if now - order.updated_at < GIVE_UP_AFTER:
                            logger.warning("recovery_supplier_unreachable_will_retry", order_id=order.id, error=str(e))
                            await db.rollback()
                            counts["deferred"] += 1
                            continue
                        logger.error(
                            "recovery_gave_up_refunding_needs_admin_review",
                            order_id=order.id, trx_id=order.external_trx_id, error=str(e),
                        )
                        await _refund_failed_order(db, order, buyer.id, buyer.role.value)
                        profile = None
                else:
                    logger.error("recovery_no_supplier_trx_refunding_needs_admin_review", order_id=order.id)
                    await _refund_failed_order(db, order, buyer.id, buyer.role.value)
                    profile = None

                partner = _is_partner_order(order)
                await _finish(db, order, product, buyer, profile, email=not partner)
                if partner:
                    merchant = (await db.execute(
                        select(MerchantProfile).where(MerchantProfile.user_id == order.buyer_id)
                    )).scalar_one_or_none()
                    if merchant:
                        await deliver_webhook(db, merchant, order, profile)
                counts["recovered" if profile else "refunded"] += 1
            except Exception as e:
                logger.error("recovery_order_failed", order_id=order_id, error=str(e))

    return counts
