"""Referral reward amounts, editable from the admin console.

The client's rule: the admin sets a flat amount in the system default
currency, separately for the referrer and the referred person, for each
event. Nothing is percentage-based and nothing is hard-coded here beyond
zeroes - a deployment that never configures this pays nothing.
"""
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.referral import ReferralEvent
from app.models.settings import PlatformSetting

REFERRAL_SETTINGS_KEY = "referral_settings"

# Deliberately zero by default: money only moves once someone decides it does.
DEFAULT_EVENT = {"referrer": Decimal("0.00"), "referred": Decimal("0.00"), "enabled": False}
ABSOLUTE_MAX_REWARD = Decimal("1000.00")

EVENT_LABELS = {
    ReferralEvent.JOINING.value: "Signs up",
    ReferralEvent.FIRST_PURCHASE.value: "First eSIM delivered",
    ReferralEvent.NEW_MERCHANT.value: "Approved as a partner",
}


def _money(value) -> Optional[Decimal]:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None


def normalize(value: dict | None) -> dict:
    raw = value if isinstance(value, dict) else {}
    raw_events = raw.get("events") if isinstance(raw.get("events"), dict) else {}

    events = {}
    for event in ReferralEvent:
        incoming = raw_events.get(event.value) if isinstance(raw_events.get(event.value), dict) else {}
        referrer = _money(incoming.get("referrer"))
        referred = _money(incoming.get("referred"))
        referrer = DEFAULT_EVENT["referrer"] if referrer is None or referrer < 0 else referrer
        referred = DEFAULT_EVENT["referred"] if referred is None or referred < 0 else referred
        events[event.value] = {
            "referrer": referrer,
            "referred": referred,
            # An event with both amounts at zero is off whatever the flag says,
            # so the admin screen and the granting code agree.
            "enabled": bool(incoming.get("enabled", DEFAULT_EVENT["enabled"])) and (referrer > 0 or referred > 0),
        }

    cap = raw.get("max_rewarded_referrals")
    try:
        cap = int(cap) if cap not in (None, "", "0") else None
    except (TypeError, ValueError):
        cap = None
    if cap is not None and cap < 1:
        cap = None

    return {
        "is_enabled": bool(raw.get("is_enabled", False)),
        "events": events,
        # A ceiling on how many referrals one person can be paid for. Without
        # it, a flat per-signup reward is an invitation to farm accounts.
        "max_rewarded_referrals": cap,
    }


def validate(cfg: dict) -> None:
    for event, amounts in cfg["events"].items():
        for side in ("referrer", "referred"):
            if amounts[side] > ABSOLUTE_MAX_REWARD:
                raise ValueError(f"{event} {side} reward cannot exceed {ABSOLUTE_MAX_REWARD}")


def serialize(cfg: dict) -> dict:
    return {
        "is_enabled": cfg["is_enabled"],
        "events": {
            event: {"referrer": str(a["referrer"]), "referred": str(a["referred"]), "enabled": a["enabled"]}
            for event, a in cfg["events"].items()
        },
        "max_rewarded_referrals": cfg["max_rewarded_referrals"],
    }


async def get_referral_settings(db: AsyncSession) -> dict:
    res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == REFERRAL_SETTINGS_KEY))
    setting = res.scalar_one_or_none()
    return normalize(setting.value if setting else None)


async def set_referral_settings(db: AsyncSession, incoming: dict, admin_id: str) -> dict:
    """Returns the audit-friendly before/after. Caller commits."""
    cfg = normalize(incoming)
    validate(cfg)
    before = serialize(await get_referral_settings(db))
    after = serialize(cfg)

    res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == REFERRAL_SETTINGS_KEY))
    setting = res.scalar_one_or_none()
    if setting:
        setting.value = after
        setting.is_public = False
        setting.updated_by_id = admin_id
    else:
        db.add(PlatformSetting(key=REFERRAL_SETTINGS_KEY, value=after, is_public=False, updated_by_id=admin_id))
    return {"before": before, "after": after}


def event_amounts(cfg: dict, event: ReferralEvent) -> tuple[Decimal, Decimal]:
    """(referrer, referred) - both zero when the event or the whole programme
    is switched off, so callers never need to check the flags themselves."""
    if not cfg["is_enabled"]:
        return Decimal("0"), Decimal("0")
    amounts = cfg["events"].get(event.value)
    if not amounts or not amounts["enabled"]:
        return Decimal("0"), Decimal("0")
    return amounts["referrer"], amounts["referred"]
