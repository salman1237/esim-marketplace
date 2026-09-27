"""Shared logic between the two checkout paths (wallet, synchronous; and
ShurjoPay gateway, completed later from the payment callback) so
provisioning behavior can't drift between them.
"""
import uuid
import json
import secrets
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.models.merchant import MerchantProfile
from app.models.order import Order, OrderStatus, ESIMProfile, ESIMStatus
from app.models.catalog import Product
from app.models.commission_tier import CommissionTier
from app.models.wallet import Wallet, WalletType, LedgerRefType
from app.services.ledger_svc import LedgerService
from app.services import agent_svc, referral_svc
from app.services.vivape_adapter import VivaPeAdapter
from app.services.audit_svc import AuditService
from app.core.logging import get_logger

logger = get_logger(__name__)

RESELLER_ROLES = {UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.MERCHANT}


def new_share_token() -> str:
    """The token in a customer's public tracking link. 32 hex characters =
    128 bits, so the links cannot be guessed or walked the way VivaPe's
    sequential status ids can."""
    return secrets.token_hex(16)


async def resolve_beneficiary(db: AsyncSession, current_user: User, is_buy_for_user: bool, auto_create_user: bool, beneficiary_username: str | None, beneficiary_email: str | None) -> str:
    if not is_buy_for_user:
        return current_user.id

    if auto_create_user:
        auto_username = f"user_{uuid.uuid4().hex[:8]}"
        auto_email = f"{auto_username}@customer.esim.local"
        new_user = User(
            email=auto_email,
            username=auto_username,
            hashed_password=get_password_hash(uuid.uuid4().hex),
            role=UserRole.USER
        )
        db.add(new_user)
        await db.flush()
        await LedgerService.ensure_wallets_for_user(db, new_user.id, new_user.role)
        return new_user.id

    if beneficiary_username or beneficiary_email:
        u_query = select(User).where(
            (User.username == beneficiary_username) | (User.email == beneficiary_email)
        )
        b_res = await db.execute(u_query)
        target = b_res.scalar_one_or_none()
        if not target:
            raise ValueError("Beneficiary user account not found")
        return target.id

    return current_user.id


def _extract_esim_details(esim_data: dict) -> dict | None:
    """VivaPe proxies multiple underlying eSIM suppliers through the same
    get-esim-by-trx endpoint, and each returns a differently-shaped
    response depending on the product's supplier type - there is no single
    schema. Tries each known shape in turn; returns None if none match.
    Confirmed against real (not mocked) VivaPe responses for both shapes."""
    if not isinstance(esim_data, dict):
        return None

    esim_order = esim_data.get("esim_order")

    # "worldmove"-type products: iccid + the actual LPA activation string
    # under qrcodeContent/qrcode - NOT "lpa"/"qr_code", which don't exist
    # in VivaPe's real response at all (an earlier version of this parser
    # silently fell back to a self-generated fake LPA for every one of
    # these purchases while still marking them is_mock_fallback=False).
    # These fields appear nested under esim_order on real responses, and
    # sometimes also mirrored at the top level - check both, since a
    # top-level-only parser refunded real, successfully-issued eSIMs.
    for candidate in (esim_order, esim_data):
        if isinstance(candidate, dict) and candidate.get("iccid") and candidate.get("qrcodeContent"):
            lpa = candidate["qrcodeContent"]
            # Real values live inside the LPA itself (LPA:1$<smdp>$<id>);
            # parse them out rather than storing fabricated placeholders.
            smdp, matching_id = None, None
            parts = lpa.split("$")
            if len(parts) == 3 and parts[0].upper().startswith("LPA:"):
                smdp, matching_id = parts[1] or None, parts[2] or None
            return {
                "iccid": candidate["iccid"],
                "lpa": lpa,
                "smdp": smdp,
                "matching_id": matching_id,
            }

    # "esimgo"-type products: esim details are nested inside a JSON string
    # (not a nested object) under esim_order.order, e.g.
    # '[{"esims":[{"iccid":"...","matchingId":"...","smdpAddress":"..."}]}]'
    if isinstance(esim_order, dict):
        order_raw = esim_order.get("order")
        if isinstance(order_raw, str):
            try:
                order_items = json.loads(order_raw)
                esims = order_items[0].get("esims") if order_items else None
                if esims:
                    e = esims[0]
                    if e.get("iccid") and e.get("smdpAddress") and e.get("matchingId"):
                        return {
                            "iccid": e["iccid"],
                            "lpa": f"LPA:1${e['smdpAddress']}${e['matchingId']}",
                            "smdp": e["smdpAddress"],
                            "matching_id": e["matchingId"],
                        }
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                pass

    return None


def _attach_profile(db: AsyncSession, order: Order, product: Product, beneficiary_id: str, trx_id, details: dict) -> ESIMProfile:
    """Builds the delivered eSIM from parsed supplier details and marks the
    order COMPLETED. Shared by first-time provisioning and crash recovery
    so the two can't produce differently-shaped profiles."""
    profile = ESIMProfile(
        order_id=order.id,
        beneficiary_id=beneficiary_id,
        iccid=details["iccid"],
        lpa_string=details["lpa"],
        qr_code_data=details["lpa"],
        smdp_address=details["smdp"] or "rsp.truphone.com",
        matching_id=details["matching_id"] or uuid.uuid4().hex[:12].upper(),
        # Shown as "Purchase ID" on the delivery email and the printable
        # eSIM, and what support quotes to VivaPe.
        supplier_reference=str(trx_id),
        status=ESIMStatus.RELEASED,
        is_mock_fallback=False,
        share_token=new_share_token(),
        # activated_at/expires_at are deliberately left unset: the plan's
        # validity starts when the customer installs the profile, not now.
        # esim_telemetry_svc fills both in from VivaPe once that happens.
        # Setting them here dated a 3-day eSIM from the purchase, so anyone
        # who bought before their trip saw it as expired on arrival.
    )
    db.add(profile)
    order.status = OrderStatus.COMPLETED
    return profile


async def complete_from_supplier_trx(db: AsyncSession, order: Order, product: Product, actor_id: str, actor_role: str) -> ESIMProfile | None:
    """Recovery for an order whose supplier purchase already went through
    (external_trx_id is set) but whose delivery never finished - typically
    a deploy that killed the background task mid-provisioning.

    Fetches the existing eSIM by that id and never calls create-transaction,
    so a recovered order cannot be charged twice at the supplier. Refunds
    only on a definitive answer (VivaPe responded but there's no usable
    eSIM); a network error propagates so the caller can retry later rather
    than refunding an eSIM that may well exist."""
    esim_data = await VivaPeAdapter.get_esim_by_trx(db, order.external_trx_id)
    details = _extract_esim_details(esim_data)
    if details:
        return _attach_profile(db, order, product, order.beneficiary_id, order.external_trx_id, details)
    logger.warning("recovery_esim_details_unparseable_refunding_order", order_id=order.id, trx_id=order.external_trx_id)
    await _refund_failed_order(db, order, actor_id, actor_role)
    return None


async def provision_esim(db: AsyncSession, order: Order, product: Product, beneficiary_id: str, actor_id: str, actor_role: str) -> ESIMProfile | None:
    """Creates the ESIMProfile for `order` from a real VivaPe purchase and
    marks the order COMPLETED. If VivaPe is unavailable/fails, or the
    product has no supplier mapping at all, no eSIM is created — the order
    is marked FAILED and the buyer is refunded the full order amount to
    their DEFAULT wallet instead, since a customer must never be charged
    (via wallet debit or gateway payment) for an eSIM that doesn't work.
    Returns None on failure. Caller commits either way."""
    if product.supplier_product_id and product.supplier_receiver_amount is not None:
        try:
            # receiver_amount is NOT the price — confirmed against VivaPe's
            # live catalog it's a supplier-defined quantity whose meaning
            # varies by product type. Must be the exact catalog value,
            # never derived from cost_price.
            trx = await VivaPeAdapter.create_transaction(
                db, product.supplier_product_id, Decimal(str(product.supplier_receiver_amount))
            )
            purchase_trx = trx.get("purchase_trx") if isinstance(trx, dict) else None
            trx_id = purchase_trx.get("id") if isinstance(purchase_trx, dict) else None
            if trx_id:
                # Pin VivaPe's transaction id to the order as soon as we have
                # it - before fetching the eSIM details, which may fail. It's
                # the only handle that ties an order back to a specific
                # supplier transaction; without it, tracing a customer's eSIM
                # (or a failed charge) means scanning supplier logs by
                # timestamp.
                order.external_trx_id = str(trx_id)
                # Durable BEFORE the next supplier call. VivaPe has already
                # charged us at this point; if the process dies now (a deploy
                # mid-purchase), recovery can fetch this already-paid eSIM by
                # id instead of buying a second one.
                await db.commit()
                esim_data = await VivaPeAdapter.get_esim_by_trx(db, trx_id)
                details = _extract_esim_details(esim_data)
                if details:
                    return _attach_profile(db, order, product, beneficiary_id, trx_id, details)
                logger.warning(
                    "vivape_esim_details_unparseable_refunding_order",
                    order_id=order.id, trx_id=trx_id,
                )
            else:
                logger.warning(
                    "vivape_provisioning_failed_refunding_order",
                    order_id=order.id,
                    vivape_error=trx.get("error") if isinstance(trx, dict) else str(trx)
                )
        except Exception as e:
            logger.warning("vivape_provisioning_failed_refunding_order", order_id=order.id, error=str(e))
    else:
        logger.warning("vivape_provisioning_skipped_no_supplier_mapping_refunding_order", order_id=order.id, product_id=product.id)

    await _refund_failed_order(db, order, actor_id, actor_role)
    return None


async def _refund_failed_order(db: AsyncSession, order: Order, actor_id: str, actor_role: str) -> None:
    """Marks `order` FAILED and refunds the full order amount — the same
    compensation regardless of whether the order was originally paid from the
    wallet (reverses the debit) or via ShurjoPay gateway (no prior debit to
    reverse, so this is the customer's only compensation since no
    payment-gateway refund integration exists).

    The refund is split the way the payment was: whatever came out of promo
    credit goes back to promo credit. Returning it all to the main wallet
    would quietly convert non-withdrawable reward credit into cash the
    customer could withdraw."""
    order.status = OrderStatus.FAILED

    total = Decimal(str(order.total_amount))
    reward_part = min(Decimal(str(order.reward_amount_used or 0)), total)
    cash_part = total - reward_part

    if reward_part > 0:
        reward_wallet = await LedgerService.ensure_reward_wallet(db, order.buyer_id)
        await LedgerService.credit(
            db, reward_wallet.id, reward_part,
            LedgerRefType.REFUND,
            ref_id=order.id,
            description=f"Refund to reward credit: order {order.order_no} failed",
            idempotency_key=f"order-refund-{order.id}-reward"
        )

    if cash_part > 0:
        w_res = await db.execute(
            select(Wallet).where(Wallet.user_id == order.buyer_id, Wallet.wallet_type == WalletType.DEFAULT)
        )
        wallet = w_res.scalar_one_or_none()
        if wallet:
            await LedgerService.credit(
                db, wallet.id, cash_part,
                LedgerRefType.REFUND,
                ref_id=order.id,
                description=f"Refund: eSIM provisioning failed for order {order.order_no}",
                idempotency_key=f"order-refund-{order.id}"
            )

    # The single refund funnel, so a first-purchase referral reward tied to
    # this order is clawed back here rather than at each call site.
    await referral_svc.reverse_for_order(db, order.id, f"order {order.order_no} refunded")

    await AuditService.log_action(
        db, actor_id=actor_id, actor_role=actor_role,
        action="ORDER_PROVISIONING_FAILED_REFUNDED",
        after_state={
            "order_id": order.id, "product_id": order.product_id,
            "refund_amount": str(order.total_amount), "refunded_to_reward_credit": str(reward_part),
        }
    )


async def get_effective_commission_rate(db: AsyncSession, merchant_user_id: str, flat_rate_pct: Decimal) -> Decimal:
    """Volume-based tiered commission, falling back to the merchant's own
    flat MerchantProfile.commission_rate_pct - both because that's the
    plan's "default flat %" requirement, and so tiers are fully optional:
    a deployment with none configured behaves exactly as before this
    feature existed."""
    tiers_res = await db.execute(select(CommissionTier).order_by(CommissionTier.min_volume_usd.desc()))
    tiers = tiers_res.scalars().all()
    if not tiers:
        return flat_rate_pct

    volume_res = await db.execute(
        select(func.coalesce(func.sum(Order.total_amount), 0)).where(
            Order.buyer_id == merchant_user_id,
            Order.is_reseller_order == True,
            Order.status == OrderStatus.COMPLETED,
        )
    )
    cumulative_volume = Decimal(str(volume_res.scalar_one()))

    for tier in tiers:  # sorted highest-threshold-first
        if cumulative_volume >= Decimal(str(tier.min_volume_usd)):
            return Decimal(str(tier.rate_pct))

    # Below every configured tier's threshold - the flat rate is the floor.
    return flat_rate_pct


async def distribute_commission(db: AsyncSession, order: Order, total_cost: Decimal, buyer: User) -> None:
    """Credits `buyer`'s COMMISSION wallet for a reseller order, at the
    tiered/flat rate from get_effective_commission_rate, and then the agent
    behind that merchant, if any. Shared between the wallet-checkout path
    (orders.py) and the Partner API order path (partner.py) so the two can't
    drift apart. No-op for non-merchant or non-reseller orders.

    Called only for a delivered order (see order_fulfilment._finish), which is
    what keeps a refunded sale from paying either party. Caller commits."""
    if buyer.role != UserRole.MERCHANT or not order.is_reseller_order:
        return

    m_res = await db.execute(select(MerchantProfile).where(MerchantProfile.user_id == buyer.id))
    merchant_profile = m_res.scalar_one_or_none()
    flat_rate_pct = Decimal(str(merchant_profile.commission_rate_pct)) if merchant_profile else Decimal("5.0")
    gross_rate_pct = await get_effective_commission_rate(db, buyer.id, flat_rate_pct)

    # Resolve the agent FIRST, because the deduction is only legitimate if
    # somebody is actually receiving it. Deducting for a suspended agent would
    # take the slice off the merchant and pay it to nobody - the money would
    # simply vanish - so both sides hang off the same approved-agent check.
    agent_user_id, agent_pct = (
        await agent_svc.commission_rate_for_merchant(db, merchant_profile)
        if merchant_profile else (None, Decimal("0"))
    )
    # Capped at the merchant's own rate, so a generous bonus can zero a
    # merchant out but can never make their commission negative.
    bonus_pct = agent_svc.bonus_pct_for(merchant_profile, gross_rate_pct) if agent_user_id else Decimal("0")
    rate_pct = gross_rate_pct - bonus_pct
    commission_amount = (total_cost * (rate_pct / Decimal("100"))).quantize(Decimal("0.0001"))

    cw_res = await db.execute(
        select(Wallet).where(Wallet.user_id == buyer.id, Wallet.wallet_type == WalletType.COMMISSION)
    )
    comm_wallet = cw_res.scalar_one_or_none()
    if comm_wallet and commission_amount > Decimal("0"):
        await LedgerService.credit(
            db, comm_wallet.id, commission_amount,
            LedgerRefType.COMMISSION_EARNED,
            ref_id=order.id,
            # The NET rate: this line shows up in the merchant's own ledger,
            # and naming the pre-deduction rate here would give the bonus away.
            description=f"Commission for order {order.order_no} ({rate_pct}%)",
            idempotency_key=f"order-commission-{order.id}"
        )
        order.reseller_commission_amount = commission_amount

    if agent_user_id:
        await _pay_agent_commission(db, order, total_cost, agent_user_id, agent_pct, bonus_pct)


async def _pay_agent_commission(
    db: AsyncSession, order: Order, total_cost: Decimal, agent_user_id: str, agent_pct: Decimal, bonus_pct: Decimal
) -> None:
    """The agent earns two separate things on a sale by one of their merchants:

    1. their own percentage of the sale price, which comes out of our margin;
    2. the bonus slice they take from the merchant's commission, which costs
       us nothing because the merchant's share shrinks by the same amount.

    Both are credited to the agent's commission wallet but recorded separately
    on the order, because only the first one affects profit. The agent id is
    snapshotted here so re-pointing the merchant to another agent later can
    never rewrite who was paid for this sale.
    """
    own = (total_cost * (agent_pct / Decimal("100"))).quantize(Decimal("0.0001")) if agent_pct > 0 else Decimal("0")
    bonus = (total_cost * (bonus_pct / Decimal("100"))).quantize(Decimal("0.0001")) if bonus_pct > 0 else Decimal("0")
    if own <= 0 and bonus <= 0:
        return

    wallet = await LedgerService.ensure_commission_wallet(db, agent_user_id)
    if own > 0:
        await LedgerService.credit(
            db, wallet.id, own,
            LedgerRefType.AGENT_COMMISSION_EARNED,
            ref_id=order.id,
            description=f"Agent commission for order {order.order_no} ({agent_pct}%)",
            idempotency_key=f"order-agent-commission-{order.id}",
        )
    if bonus > 0:
        await LedgerService.credit(
            db, wallet.id, bonus,
            LedgerRefType.AGENT_COMMISSION_EARNED,
            ref_id=order.id,
            description=f"Partner bonus for order {order.order_no} ({bonus_pct}%)",
            idempotency_key=f"order-agent-bonus-{order.id}",
        )

    order.agent_id = agent_user_id
    order.agent_commission_amount = own
    order.agent_bonus_amount = bonus
