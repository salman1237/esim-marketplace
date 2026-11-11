"""Adding data to an already-delivered eSIM - eSIM Access's esim/topup,
a wholly new capability with no VivaPe equivalent (reference doc §4.5).

Deliberately synchronous, unlike checkout_svc.py's order provisioning:
eSIM Access's own docs describe no async step for esim/topup (no orderNo
to poll), so this charges the wallet and calls the supplier within one
request, refunding immediately on a supplier-side failure rather than
leaving anything PROCESSING for a background sweep to find later.
"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Product
from app.models.order import ESIMProfile, EsimTopup, EsimTopupStatus, PaymentMethod
from app.models.wallet import LedgerRefType, WalletType
from app.services.esimaccess_adapter import ESIMAccessAdapter, ESIMAccessError, decimal_to_scaled, scaled_to_decimal
from app.services.ledger_svc import LedgerService
from app.services.pricing_svc import get_selling_profit_pct, retail_price_for


class TopupNotAvailable(Exception):
    """Raised for every "can't do this" case that isn't the customer's
    wallet balance - no supplier support, no iccid yet, a stale/removed
    packageCode. Callers map this to a 400, same as a wallet shortfall."""
    pass


def _parse_topup_option(p: dict) -> dict:
    price_scaled = p.get("price") or 0
    volume_bytes = p.get("volume") or 0
    gb = (Decimal(volume_bytes) / Decimal(1024 ** 3)).quantize(Decimal("0.01"))
    return {
        "package_code": p.get("packageCode"),
        "title": str(p.get("name") or p.get("slug") or "Top-up"),
        "data_amount_gb": gb,
        "validity_days": int(p.get("duration") or 0),
        "price_scaled": price_scaled,
        "cost_price": scaled_to_decimal(price_scaled),
    }


async def get_topup_options(db: AsyncSession, profile: ESIMProfile, product: Product) -> list[dict]:
    """Live options for this specific eSIM - never cached, never derived
    from the base package: supportTopUpType is not a reliable gate (see
    esimaccess_adapter.py's list_topup_packages), so the only trustworthy
    answer is whatever eSIM Access returns for this iccid right now.
    Returns [] (not an error) for a non-eSIM-Access product or a profile
    with no iccid yet - "nothing to offer" is the correct, ordinary answer
    before this eSIM is even provisioned."""
    if product.supplier_reference != "esimaccess" or not profile.iccid:
        return []
    try:
        raw = await ESIMAccessAdapter.list_topup_packages(
            db, package_code=product.supplier_package_code or "", iccid=profile.iccid,
        )
    except ESIMAccessError:
        return []

    profit_pct = await get_selling_profit_pct(db)
    options = []
    for p in raw:
        parsed = _parse_topup_option(p)
        if not parsed["package_code"]:
            continue
        parsed["retail_price"] = retail_price_for(parsed["cost_price"], profit_pct)
        parsed["currency"] = "USD"
        options.append(parsed)
    return options


async def _refund_topup(db: AsyncSession, topup: EsimTopup) -> None:
    total = Decimal(str(topup.retail_price))
    reward_part = min(Decimal(str(topup.reward_amount_used or 0)), total)
    cash_part = total - reward_part

    if reward_part > 0:
        reward_wallet = await LedgerService.ensure_reward_wallet(db, topup.buyer_id)
        await LedgerService.credit(
            db, reward_wallet.id, reward_part, LedgerRefType.REFUND, ref_id=topup.id,
            description=f"Refund: top-up {topup.title} failed",
            idempotency_key=f"topup-refund-{topup.id}-reward",
        )
    if cash_part > 0:
        wallet = await LedgerService.get_wallet(db, topup.buyer_id, WalletType.DEFAULT)
        if wallet:
            await LedgerService.credit(
                db, wallet.id, cash_part, LedgerRefType.REFUND, ref_id=topup.id,
                description=f"Refund: top-up {topup.title} failed",
                idempotency_key=f"topup-refund-{topup.id}",
            )


async def purchase_topup(
    db: AsyncSession, profile: ESIMProfile, product: Product, package_code: str, buyer_id: str,
) -> EsimTopup:
    """Re-fetches the live option by package_code rather than trusting a
    client-supplied price - the same reasoning as every other supplier
    integration in this project: the price a customer is charged must come
    from a just-fetched, authoritative source, never round-tripped from
    the browser."""
    options = await get_topup_options(db, profile, product)
    chosen = next((o for o in options if o["package_code"] == package_code), None)
    if not chosen:
        raise TopupNotAvailable("That top-up option is no longer available for this eSIM.")

    retail_price = chosen["retail_price"]
    funds = await LedgerService.spendable(db, buyer_id)
    if funds["frozen"]:
        raise ValueError("This wallet is frozen. Please contact support.")
    if funds["total"] < retail_price:
        raise ValueError("Insufficient wallet balance. Please top up your wallet.")

    topup = EsimTopup(
        esim_profile_id=profile.id,
        buyer_id=buyer_id,
        package_code=package_code,
        title=chosen["title"],
        data_amount_gb=chosen["data_amount_gb"],
        validity_days=chosen["validity_days"],
        cost_price=chosen["cost_price"],
        retail_price=retail_price,
        currency=chosen["currency"],
        status=EsimTopupStatus.PENDING,
        payment_method=PaymentMethod.WALLET,
    )
    db.add(topup)
    await db.flush()

    topup.reward_amount_used = await LedgerService.spend(
        db, buyer_id, retail_price, LedgerRefType.ESIM_TOPUP_PURCHASE, ref_id=topup.id,
        description=f"Top-up: {topup.title}", idempotency_prefix=f"topup-debit-{topup.id}",
    )
    topup.external_trx_id = topup.id

    try:
        await ESIMAccessAdapter.topup_esim(
            db, iccid=profile.iccid, package_code=package_code,
            amount_scaled=chosen["price_scaled"], transaction_id=topup.id,
        )
    except ESIMAccessError as e:
        await _refund_topup(db, topup)
        topup.status = EsimTopupStatus.FAILED
        await db.commit()
        raise TopupNotAvailable(
            "The network declined this top-up. You have been refunded in full."
        ) from e

    topup.status = EsimTopupStatus.COMPLETED
    topup.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return topup


async def list_my_topups(db: AsyncSession, esim_profile_id: str) -> list[EsimTopup]:
    res = await db.execute(
        select(EsimTopup).where(EsimTopup.esim_profile_id == esim_profile_id)
        .order_by(EsimTopup.created_at.desc())
    )
    return res.scalars().all()


async def create_pending_gateway_topup(
    db: AsyncSession, profile: ESIMProfile, product: Product, package_code: str, buyer_id: str,
) -> EsimTopup:
    """The ShurjoPay half of a top-up purchase - same two-step shape as
    Order's gateway path (payments.py's /shurjopay/order-initiate):
    create PENDING now, charge nothing yet, redirect to checkout, and only
    call the supplier once the gateway callback confirms payment (see
    complete_gateway_topup). Re-fetches the live option the same way
    purchase_topup does - the price a customer is sent to pay at the
    gateway must come from a just-fetched source, never the browser."""
    options = await get_topup_options(db, profile, product)
    chosen = next((o for o in options if o["package_code"] == package_code), None)
    if not chosen:
        raise TopupNotAvailable("That top-up option is no longer available for this eSIM.")

    topup = EsimTopup(
        esim_profile_id=profile.id,
        buyer_id=buyer_id,
        package_code=package_code,
        title=chosen["title"],
        data_amount_gb=chosen["data_amount_gb"],
        validity_days=chosen["validity_days"],
        cost_price=chosen["cost_price"],
        retail_price=chosen["retail_price"],
        currency=chosen["currency"],
        status=EsimTopupStatus.PENDING,
        payment_method=PaymentMethod.SHURJOPAY,
    )
    db.add(topup)
    await db.flush()
    return topup


async def complete_gateway_topup(db: AsyncSession, topup_id: str) -> EsimTopup | None:
    """Completes a ShurjoPay-paid top-up once the gateway callback
    confirms payment - the supplier call happens here, not at initiate
    time, mirroring _complete_gateway_order in payments.py. Row-locked so
    a replayed callback (browser return + IPN both arriving) can't call
    esim/topup twice; returns None for an unknown id or one already past
    PENDING (replay - a no-op, not an error) rather than raising, since
    the caller's job either way is just to redirect the customer."""
    res = await db.execute(select(EsimTopup).where(EsimTopup.id == topup_id).with_for_update())
    topup = res.scalar_one_or_none()
    if not topup or topup.status != EsimTopupStatus.PENDING:
        return topup

    profile = (await db.execute(select(ESIMProfile).where(ESIMProfile.id == topup.esim_profile_id))).scalar_one_or_none()
    if not profile:
        topup.status = EsimTopupStatus.FAILED
        await db.commit()
        return topup

    # The exact amount the customer was quoted and charged at the gateway -
    # derived from the stored cost_price (decimal_to_scaled is the
    # confirmed inverse of scaled_to_decimal, see esimaccess_adapter.py),
    # never re-fetched here: a live re-fetch could return a different
    # price than what was actually paid.
    amount_scaled = decimal_to_scaled(Decimal(str(topup.cost_price)))
    try:
        await ESIMAccessAdapter.topup_esim(
            db, iccid=profile.iccid, package_code=topup.package_code,
            amount_scaled=amount_scaled, transaction_id=topup.id,
        )
    except ESIMAccessError:
        # Payment already happened at the gateway - there's nothing to
        # reverse there (no refund API wired up), so the compensation is
        # a wallet credit, same pattern as a failed gateway-paid Order.
        topup.status = EsimTopupStatus.FAILED
        wallet = await LedgerService.get_wallet(db, topup.buyer_id, WalletType.DEFAULT)
        if wallet:
            await LedgerService.credit(
                db, wallet.id, Decimal(str(topup.retail_price)), LedgerRefType.REFUND, ref_id=topup.id,
                description=f"Refund: top-up {topup.title} failed",
                idempotency_key=f"topup-refund-{topup.id}",
            )
        await db.commit()
        return topup

    topup.status = EsimTopupStatus.COMPLETED
    topup.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return topup
