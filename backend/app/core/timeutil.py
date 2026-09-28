"""Bangladesh time is the platform's display timezone.

Everything is *stored* in UTC - that never changes, and no business logic
below this module should care about local time. But every timestamp a human
reads (an email, a receipt, an eSIM's activation and expiry) is rendered in
Asia/Dhaka, because the customers, the merchants, the agents and the support
desk are all there. A traveller sitting in Bangkok reading "expires 04:00"
needs that to mean 04:00 at home, not 04:00 wherever they happen to have
landed, or they cannot compare it with anything else we have told them.

Asia/Dhaka is UTC+6 with no daylight saving, so the offset is constant - but
it is still resolved through the tz database rather than hardcoded as +6, so
a future rule change is picked up rather than silently wrong.
"""
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

DISPLAY_TZ = ZoneInfo("Asia/Dhaka")

# Spelled out rather than abbreviated: "BST" means Bangladesh Standard Time
# here and British Summer Time to half the world, which is exactly the
# confusion this module exists to remove.
DISPLAY_TZ_SUFFIX = "(GMT+6)"


def now_bd() -> datetime:
    """Now, in Bangladesh time."""
    return datetime.now(timezone.utc).astimezone(DISPLAY_TZ)


def to_bd(value: Optional[datetime]) -> Optional[datetime]:
    """Convert an instant to Bangladesh time.

    A naive datetime is assumed to be UTC, which is what everything in this
    codebase stores - see the column defaults, which are all
    datetime.now(timezone.utc).
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(DISPLAY_TZ)


def fmt_bd(value: Optional[datetime], *, with_time: bool = True, suffix: bool = True) -> str:
    """Render an instant for a human, in Bangladesh time.

    e.g. "28 Sep 2026, 16:07 (GMT+6)"
    """
    local = to_bd(value)
    if local is None:
        return "—"
    text = local.strftime("%d %b %Y, %H:%M") if with_time else local.strftime("%d %b %Y")
    if with_time and suffix:
        text = f"{text} {DISPLAY_TZ_SUFFIX}"
    return text


def bd_datestamp(value: Optional[datetime] = None) -> str:
    """YYYYMMDD in Bangladesh time, for order references.

    An order placed at 02:00 in Dhaka is 20:00 the previous day in UTC. Taking
    the date from UTC would stamp that order with yesterday's date, which is
    the one thing a reference number must never do to the person reading it.
    """
    return (to_bd(value) or now_bd()).strftime("%Y%m%d")
