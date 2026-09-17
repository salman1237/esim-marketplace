"""Wallet top-up minimum and maximum, editable from the admin console.

They were fixed constants in payments.py, which made a small live-gateway
test impossible: the minimum of 1 EUR is about 140 BDT, so a 10 BDT test
payment was rejected before it ever reached ShurjoPay. Stored as one
public PlatformSetting (amounts in the base currency) so the wallet page
can show the same limits the API enforces."""
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import PlatformSetting

TOPUP_LIMITS_KEY = "topup_limits"
DEFAULT_MIN = Decimal("1.00")
DEFAULT_MAX = Decimal("2000.00")
# A floor below this is meaningless once converted, and gateways reject 0.
ABSOLUTE_MIN = Decimal("0.01")
ABSOLUTE_MAX = Decimal("100000.00")


def _money(value) -> Optional[Decimal]:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None


async def get_topup_limits(db: AsyncSession) -> Tuple[Decimal, Decimal]:
    res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == TOPUP_LIMITS_KEY))
    setting = res.scalar_one_or_none()
    value = setting.value if setting and isinstance(setting.value, dict) else {}
    minimum = _money(value.get("min")) or DEFAULT_MIN
    maximum = _money(value.get("max")) or DEFAULT_MAX
    if minimum <= 0 or maximum <= minimum:
        return DEFAULT_MIN, DEFAULT_MAX
    return minimum, maximum


def validate_limits(minimum: Decimal, maximum: Decimal) -> None:
    if minimum < ABSOLUTE_MIN:
        raise ValueError(f"Minimum must be at least {ABSOLUTE_MIN}")
    if maximum > ABSOLUTE_MAX:
        raise ValueError(f"Maximum cannot exceed {ABSOLUTE_MAX}")
    if maximum <= minimum:
        raise ValueError("Maximum must be greater than the minimum")


async def set_topup_limits(db: AsyncSession, minimum: Decimal, maximum: Decimal, admin_id: str) -> dict:
    """Returns the audit-friendly before/after. Caller commits."""
    validate_limits(minimum, maximum)
    before_min, before_max = await get_topup_limits(db)
    value = {"min": str(minimum.quantize(Decimal("0.01"))), "max": str(maximum.quantize(Decimal("0.01")))}

    res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == TOPUP_LIMITS_KEY))
    setting = res.scalar_one_or_none()
    if setting:
        setting.value = value
        setting.is_public = True
        setting.updated_by_id = admin_id
    else:
        db.add(PlatformSetting(key=TOPUP_LIMITS_KEY, value=value, is_public=True, updated_by_id=admin_id))
    return {"before": {"min": str(before_min), "max": str(before_max)}, "after": value}
