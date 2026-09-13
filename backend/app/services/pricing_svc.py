"""Triptel's selling price for every eSIM: the supplier (VivaPe) cost plus one
global selling profit %, set by a super admin.

    selling price = cost x (1 + selling_profit_pct / 100), rounded to the cent

e.g. a EUR 1.00 VivaPe package at 80% profit sells for EUR 1.80.

Merchant commission is a separate thing: a % of the selling price paid to a
reseller, which comes out of this profit - it never changes the price the
customer pays.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Product
from app.models.settings import PlatformSetting

SELLING_PROFIT_KEY = "selling_profit_pct"
# The markup the catalog sync hardcoded before this became configurable, so
# prices don't move until an admin actually sets a new value.
DEFAULT_SELLING_PROFIT_PCT = Decimal("25")
MAX_SELLING_PROFIT_PCT = Decimal("1000")
CENT = Decimal("0.01")


def retail_price_for(cost, profit_pct) -> Decimal:
    cost = Decimal(str(cost))
    multiplier = Decimal("1") + Decimal(str(profit_pct)) / Decimal("100")
    return (cost * multiplier).quantize(CENT, rounding=ROUND_HALF_UP)


async def get_selling_profit_pct(db: AsyncSession) -> Decimal:
    row = (await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == SELLING_PROFIT_KEY)
    )).scalar_one_or_none()
    if row is None or row.value in (None, ""):
        return DEFAULT_SELLING_PROFIT_PCT
    try:
        return Decimal(str(row.value))
    except (InvalidOperation, ValueError):
        return DEFAULT_SELLING_PROFIT_PCT


async def reprice_catalog(db: AsyncSession, profit_pct: Decimal) -> int:
    """Sets every product's selling price from its cost. Doesn't commit."""
    products = (await db.execute(select(Product))).scalars().all()
    for product in products:
        product.retail_price = retail_price_for(product.cost_price, profit_pct)
    await db.flush()
    return len(products)


async def set_selling_profit_pct(db: AsyncSession, profit_pct: Decimal, admin_user_id: str) -> int:
    """Stores the new % and reprices the whole catalog in the same
    transaction, so prices and the setting can never disagree. Returns how
    many products were repriced. Doesn't commit."""
    row = (await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == SELLING_PROFIT_KEY)
    )).scalar_one_or_none()
    # Stored as a string so the JSON column never turns it into a float.
    value = str(profit_pct)
    if row:
        row.value = value
        row.updated_by_id = admin_user_id
    else:
        db.add(PlatformSetting(
            key=SELLING_PROFIT_KEY,
            value=value,
            description="Global selling profit % added to the supplier cost",
            # Margin is internal - never exposed through /settings/public.
            is_public=False,
            updated_by_id=admin_user_id,
        ))
    await db.flush()
    return await reprice_catalog(db, profit_pct)
