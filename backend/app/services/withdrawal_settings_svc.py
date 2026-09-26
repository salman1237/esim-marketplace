"""Withdrawal limits, fee and payout currency - editable from the admin console.

One PlatformSetting row, same shape as topup_limits_svc. Deliberately NOT
public: payout terms are only shown to a signed-in user on the withdraw
page (GET /withdrawals/config), not on the marketing site.
"""
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import PlatformSetting

WITHDRAWAL_SETTINGS_KEY = "withdrawal_settings"

DEFAULTS = {
    "min_amount": Decimal("5.00"),
    "max_amount": Decimal("1000.00"),
    "fee_type": "flat",          # "flat" (base currency) or "percent"
    "fee_value": Decimal("0.00"),
    "payout_currency": "BDT",
    "processing_time": "1–3 business days",
    "is_enabled": True,
}

ABSOLUTE_MIN = Decimal("0.01")
ABSOLUTE_MAX = Decimal("100000.00")
FEE_TYPES = ("flat", "percent")
# A withdrawal is paid out by hand, so the payout currency has to be one an
# admin can actually send. Kept narrow on purpose rather than accepting any
# three letters the browser posts.
PAYOUT_CURRENCIES = ("BDT", "EUR", "USD")
MAX_PROCESSING_TIME_CHARS = 120


def _money(value) -> Optional[Decimal]:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None


def normalize(value: dict | None) -> dict:
    """Fills in defaults for anything missing or unparseable, so a
    half-written settings row can never break the withdraw page."""
    raw = value if isinstance(value, dict) else {}
    minimum = _money(raw.get("min_amount")) or DEFAULTS["min_amount"]
    maximum = _money(raw.get("max_amount")) or DEFAULTS["max_amount"]
    if minimum < ABSOLUTE_MIN or maximum <= minimum:
        minimum, maximum = DEFAULTS["min_amount"], DEFAULTS["max_amount"]

    fee_type = str(raw.get("fee_type") or DEFAULTS["fee_type"]).lower()
    if fee_type not in FEE_TYPES:
        fee_type = DEFAULTS["fee_type"]
    fee_value = _money(raw.get("fee_value"))
    if fee_value is None or fee_value < 0:
        fee_value = DEFAULTS["fee_value"]

    currency = str(raw.get("payout_currency") or DEFAULTS["payout_currency"]).upper()
    if currency not in PAYOUT_CURRENCIES:
        currency = DEFAULTS["payout_currency"]

    return {
        "min_amount": minimum,
        "max_amount": maximum,
        "fee_type": fee_type,
        "fee_value": fee_value,
        "payout_currency": currency,
        "processing_time": str(raw.get("processing_time") or DEFAULTS["processing_time"])[:MAX_PROCESSING_TIME_CHARS],
        "is_enabled": bool(raw.get("is_enabled", DEFAULTS["is_enabled"])),
    }


def validate(cfg: dict) -> None:
    if cfg["min_amount"] < ABSOLUTE_MIN:
        raise ValueError(f"Minimum must be at least {ABSOLUTE_MIN}")
    if cfg["max_amount"] > ABSOLUTE_MAX:
        raise ValueError(f"Maximum cannot exceed {ABSOLUTE_MAX}")
    if cfg["max_amount"] <= cfg["min_amount"]:
        raise ValueError("Maximum must be greater than the minimum")
    if cfg["fee_type"] == "percent" and cfg["fee_value"] >= 100:
        raise ValueError("A percentage fee must be below 100%")
    # A flat fee at or above the minimum would leave a user withdrawing the
    # smallest allowed amount with nothing (or a negative payout).
    if cfg["fee_type"] == "flat" and cfg["fee_value"] >= cfg["min_amount"]:
        raise ValueError("The flat fee must be smaller than the minimum withdrawal")


async def get_withdrawal_settings(db: AsyncSession) -> dict:
    res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == WITHDRAWAL_SETTINGS_KEY))
    setting = res.scalar_one_or_none()
    return normalize(setting.value if setting else None)


def serialize(cfg: dict) -> dict:
    """JSON-safe form, used both for storage and for the API response."""
    return {
        "min_amount": str(cfg["min_amount"]),
        "max_amount": str(cfg["max_amount"]),
        "fee_type": cfg["fee_type"],
        "fee_value": str(cfg["fee_value"]),
        "payout_currency": cfg["payout_currency"],
        "processing_time": cfg["processing_time"],
        "is_enabled": cfg["is_enabled"],
    }


async def set_withdrawal_settings(db: AsyncSession, incoming: dict, admin_id: str) -> dict:
    """Returns the audit-friendly before/after. Caller commits."""
    cfg = normalize(incoming)
    validate(cfg)
    before = serialize(await get_withdrawal_settings(db))
    after = serialize(cfg)

    res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == WITHDRAWAL_SETTINGS_KEY))
    setting = res.scalar_one_or_none()
    if setting:
        setting.value = after
        setting.is_public = False
        setting.updated_by_id = admin_id
    else:
        db.add(PlatformSetting(key=WITHDRAWAL_SETTINGS_KEY, value=after, is_public=False, updated_by_id=admin_id))
    return {"before": before, "after": after}


def compute_fee(cfg: dict, amount: Decimal) -> Decimal:
    if cfg["fee_type"] == "percent":
        fee = (amount * cfg["fee_value"] / Decimal("100"))
    else:
        fee = cfg["fee_value"]
    fee = Decimal(str(fee)).quantize(Decimal("0.0001"))
    # Never let a fee exceed the amount - the net payout must stay >= 0.
    return min(fee, amount)
