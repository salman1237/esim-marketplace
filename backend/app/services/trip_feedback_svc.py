"""The "how was your trip" reminder, sent once an eSIM's validity has ended.

Runs on a schedule (see app/main.py) rather than being tied to any one
order event, because the trigger is time passing, not something a customer
or admin does. A profile is only ever swept once it already has an
expires_at (set from real telemetry on first activation - see
ESIMProfile.expires_at), so an eSIM that was bought but never installed is
correctly never reminded about a trip that never started.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.catalog import Country, Product
from app.models.order import ESIMProfile, Order
from app.models.settings import PlatformSetting
from app.models.user import User
from app.services.email_svc import EmailService

logger = get_logger(__name__)

# The sweep runs every few hours (see main.py); this window just needs to be
# wider than the gap between runs plus a safety margin, since
# trip_feedback_sent_at (never cleared once set) is what actually prevents
# a duplicate send - not tight bounds on the window itself.
REMINDER_WINDOW = timedelta(hours=36)
# Give a trip a little room to actually be over, rather than emailing
# someone mid-flight the moment the validity clock ticks past zero.
REMINDER_DELAY = timedelta(hours=2)


async def _contact_rows(db: AsyncSession) -> list[tuple[str, str]]:
    res = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key.in_(["support_email", "support_whatsapp", "support_phone"]))
    )
    by_key = {row.key: row.value for row in res.scalars().all()}
    rows = []
    if by_key.get("support_email"):
        rows.append(("Email", by_key["support_email"]))
    if by_key.get("support_whatsapp"):
        rows.append(("WhatsApp", by_key["support_whatsapp"]))
    if by_key.get("support_phone"):
        rows.append(("Phone", by_key["support_phone"]))
    return rows


async def send_due_trip_feedback_reminders(db: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    window_start = now - REMINDER_WINDOW
    window_end = now - REMINDER_DELAY

    res = await db.execute(
        select(ESIMProfile, Order, Product, Country, User.email)
        .join(Order, Order.id == ESIMProfile.order_id)
        .join(Product, Product.id == Order.product_id)
        .join(Country, Country.id == Product.country_id)
        .join(User, User.id == ESIMProfile.beneficiary_id)
        .where(
            ESIMProfile.expires_at.isnot(None),
            ESIMProfile.expires_at >= window_start,
            ESIMProfile.expires_at <= window_end,
            ESIMProfile.trip_feedback_sent_at.is_(None),
        )
    )
    rows = res.all()
    contact_rows = await _contact_rows(db)
    sent = 0
    failed = 0
    for profile, order, product, country, email in rows:
        if not email:
            # No account email to reach (e.g. a merchant bought on this
            # beneficiary's behalf without one) - mark done so the sweep
            # doesn't keep retrying something it can never send.
            profile.trip_feedback_sent_at = now
            continue
        try:
            ok = await EmailService.send_notice(
                db, email,
                subject="How was your eSIM in " + country.name_en + "?",
                title="Dear valued customer",
                intro=(
                    f"We hope your {country.name_en} trip went smoothly on the eSIM you bought from us. "
                    "We'd love to hear how it went, or help if anything didn't work as expected."
                ),
                rows=contact_rows,
                cta_label="Buy your next destination",
                cta_url=f"{settings.FRONTEND_BASE_URL}/destinations",
                footnote="Questions, a problem with this eSIM, or ready for your next trip? We're here.",
            )
            if ok:
                sent += 1
            else:
                failed += 1
        except Exception as e:
            logger.warning("trip_feedback_email_failed", profile_id=profile.id, error=str(e))
            failed += 1
        # Marked sent either way (once attempted) - a permanently
        # unconfigured/unreachable SMTP server must not make this sweep
        # retry the same row forever.
        profile.trip_feedback_sent_at = now

    await db.commit()
    return {"candidates": len(rows), "sent": sent, "failed": failed}
