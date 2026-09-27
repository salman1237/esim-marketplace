"""Discount code validation, pricing and usage counting.

Every rule a code can carry is checked here, once, so the two checkout paths
(wallet and gateway) and the preview endpoint can never disagree about
whether a code applies or what it is worth.

Usage is counted from redemptions joined to their orders rather than from a
counter on the code. A failed or cancelled order therefore gives its use
back automatically, with no compensating write to remember on a refund path.
An unpaid gateway checkout holds its use for PENDING_HOLD and then releases
it, so an abandoned browser tab can't permanently consume a limited code.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Product
from app.models.discount import DiscountCode, DiscountRedemption, DiscountScope, DiscountType
from app.models.order import Order, OrderStatus
from app.models.user import User

# How long an unpaid gateway checkout keeps its claim on a limited code.
PENDING_HOLD = timedelta(minutes=30)

# Statuses that definitely consumed a use. PENDING is handled separately by
# the hold window above; FAILED and CANCELLED never count.
CONSUMING_STATUSES = (OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.COMPLETED)

MAX_CODE_LENGTH = 40


class DiscountError(Exception):
    """A reason the code can't be used, phrased for the customer."""


def normalize_code(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    code = raw.strip().upper()
    return code[:MAX_CODE_LENGTH] or None


def _counted_orders_clause(now: datetime):
    """Redemptions whose order still counts against the code's limits."""
    return or_(
        Order.status.in_(CONSUMING_STATUSES),
        # Awaiting payment on the gateway, recently enough to still be live.
        (Order.status == OrderStatus.PENDING) & (Order.created_at >= now - PENDING_HOLD),
    )


async def usage_counts(db: AsyncSession, code_id: str, user_id: Optional[str] = None, now: Optional[datetime] = None) -> Tuple[int, int]:
    """(total uses, uses by this user) - both under the counting rule above."""
    now = now or datetime.now(timezone.utc)
    base = (
        select(func.count(DiscountRedemption.id))
        .join(Order, DiscountRedemption.order_id == Order.id)
        .where(DiscountRedemption.discount_code_id == code_id, _counted_orders_clause(now))
    )
    total = (await db.execute(base)).scalar() or 0
    mine = 0
    if user_id:
        mine = (await db.execute(base.where(DiscountRedemption.user_id == user_id))).scalar() or 0
    return total, mine


def discount_for(code: DiscountCode, price: Decimal) -> Decimal:
    """What comes off `price`. Never more than the price itself - a code can
    make an eSIM free but can never make an order negative."""
    if code.discount_type == DiscountType.PERCENT:
        amount = price * Decimal(str(code.value)) / Decimal("100")
        if code.max_discount_amount is not None:
            amount = min(amount, Decimal(str(code.max_discount_amount)))
    else:
        amount = Decimal(str(code.value))
    amount = Decimal(str(amount)).quantize(Decimal("0.0001"))
    return max(Decimal("0"), min(amount, price))


async def _has_completed_order(db: AsyncSession, user_id: str) -> bool:
    res = await db.execute(
        select(Order.id).where(
            Order.buyer_id == user_id,
            Order.status.in_((OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.COMPLETED)),
        ).limit(1)
    )
    return res.scalar_one_or_none() is not None


async def find_code(db: AsyncSession, raw_code: str, *, lock: bool = False) -> Optional[DiscountCode]:
    """`lock` takes a row lock, used on the checkout path so two orders
    racing for the last use of a limited code can't both win."""
    code = normalize_code(raw_code)
    if not code:
        return None
    stmt = select(DiscountCode).where(func.upper(DiscountCode.code) == code)
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def validate(
    db: AsyncSession,
    raw_code: str,
    user: User,
    product: Product,
    price: Decimal,
    *,
    lock: bool = False,
    now: Optional[datetime] = None,
) -> Tuple[DiscountCode, Decimal]:
    """The code and what it takes off, or DiscountError explaining why not."""
    now = now or datetime.now(timezone.utc)
    code = await find_code(db, raw_code, lock=lock)
    if not code or not code.is_active:
        raise DiscountError("That discount code isn't valid.")

    if code.starts_at and now < code.starts_at:
        raise DiscountError("That code isn't active yet.")
    if code.ends_at and now >= code.ends_at:
        raise DiscountError("That code has expired.")

    if code.scope == DiscountScope.PRODUCT and code.product_id != product.id:
        raise DiscountError("That code doesn't apply to this package.")
    if code.scope == DiscountScope.COUNTRY and code.country_id != product.country_id:
        raise DiscountError("That code doesn't apply to this destination.")

    if code.min_order_amount is not None and price < Decimal(str(code.min_order_amount)):
        raise DiscountError(f"That code needs an order of at least {Decimal(str(code.min_order_amount)):.2f}.")

    if code.first_order_only and await _has_completed_order(db, user.id):
        raise DiscountError("That code is for a first purchase only.")

    total_uses, my_uses = await usage_counts(db, code.id, user.id, now=now)
    if code.max_uses is not None and total_uses >= code.max_uses:
        raise DiscountError("That code has reached its usage limit.")
    if code.max_uses_per_user is not None and my_uses >= code.max_uses_per_user:
        raise DiscountError("You've already used that code.")

    amount = discount_for(code, price)
    if amount <= 0:
        raise DiscountError("That code doesn't reduce this order.")
    return code, amount


async def apply_to_order(db: AsyncSession, order: Order, code: DiscountCode, user_id: str, amount: Decimal) -> None:
    """Records the discount on the order and its redemption. Caller commits.
    The unique constraint on redemptions.order_id is what enforces one code
    per order at the database level."""
    order.discount_code_id = code.id
    order.discount_amount = amount
    db.add(DiscountRedemption(
        discount_code_id=code.id,
        user_id=user_id,
        order_id=order.id,
        discount_amount=amount,
    ))


async def resolve_for_checkout(
    db: AsyncSession, raw_code: Optional[str], user: User, product: Product, price: Decimal
) -> Tuple[Optional[DiscountCode], Decimal]:
    """Convenience for the checkout paths: no code means no discount, and a
    bad code raises DiscountError rather than being silently ignored - a
    customer who typed a code must not be charged full price without being
    told why."""
    code_str = normalize_code(raw_code)
    if not code_str:
        return None, Decimal("0")
    code, amount = await validate(db, code_str, user, product, price, lock=True)
    return code, amount


def serialize(code: DiscountCode, *, total_uses: int = 0, revenue: Decimal | None = None, given: Decimal | None = None) -> dict:
    return {
        "id": code.id,
        "code": code.code,
        "description": code.description,
        "discount_type": code.discount_type.value,
        "value": str(code.value),
        "max_discount_amount": str(code.max_discount_amount) if code.max_discount_amount is not None else None,
        "min_order_amount": str(code.min_order_amount) if code.min_order_amount is not None else None,
        "starts_at": code.starts_at,
        "ends_at": code.ends_at,
        "max_uses": code.max_uses,
        "max_uses_per_user": code.max_uses_per_user,
        "first_order_only": code.first_order_only,
        "scope": code.scope.value,
        "country_id": code.country_id,
        "product_id": code.product_id,
        "is_active": code.is_active,
        "created_at": code.created_at,
        "times_used": total_uses,
        "discount_given": str(given) if given is not None else "0.00",
        "revenue": str(revenue) if revenue is not None else "0.00",
    }
