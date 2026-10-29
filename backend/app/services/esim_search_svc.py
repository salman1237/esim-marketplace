"""Finding one customer's eSIM fast, from whatever the customer told you.

Support gets given an ICCID, an order number, a phone number, an email or
just a name - whichever the person on the other end happens to have. One
search box over all of them beats making an admin guess which field they
are holding, which is what the dashboard widget this backs is for.

Deliberately read-only and deliberately NOT paginated beyond a cap: this
is a lookup tool, not a browsing tool, and an admin who needs the whole
list has the orders tab and the exports.
"""
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import fmt_bd
from app.models.catalog import Country, Product
from app.models.esim_telemetry import ESIMTelemetry
from app.models.order import ESIMProfile, Order, OrderStatus
from app.models.user import User

MAX_RESULTS = 50


async def search_esims(
    db: AsyncSession,
    *,
    query: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = MAX_RESULTS,
) -> dict:
    """Matches an ICCID, order number, email, phone or name.

    Partial matches are allowed on every field: an admin reading an ICCID
    off a customer's screen usually has the last few digits, not all 20.
    """
    limit = max(1, min(limit, MAX_RESULTS))
    stmt = (
        select(Order, User, Product, Country, ESIMProfile, ESIMTelemetry)
        .join(User, Order.beneficiary_id == User.id)
        .join(Product, Order.product_id == Product.id)
        .join(Country, Product.country_id == Country.id)
        .outerjoin(ESIMProfile, ESIMProfile.order_id == Order.id)
        .outerjoin(ESIMTelemetry, ESIMTelemetry.esim_profile_id == ESIMProfile.id)
        .order_by(Order.created_at.desc())
        .limit(limit)
    )

    if query and query.strip():
        term = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(
                ESIMProfile.iccid.ilike(term),
                Order.order_no.ilike(term),
                Order.external_trx_id.ilike(term),
                User.email.ilike(term),
                User.phone.ilike(term),
                User.full_name.ilike(term),
                User.username.ilike(term),
            )
        )
    if status:
        try:
            stmt = stmt.where(Order.status == OrderStatus(status.upper()))
        except ValueError:
            pass

    rows = (await db.execute(stmt)).all()
    items = []
    for order, user, product, country, profile, telemetry in rows:
        items.append({
            "order_id": order.id,
            "order_no": order.order_no,
            "order_status": order.status.value,
            "purchased_at": fmt_bd(order.created_at),
            "customer_name": user.full_name or user.username,
            "customer_email": user.email,
            "customer_phone": user.phone,
            "country": country.name_en,
            "product": product.title_en,
            "validity_days": product.validity_days,
            "esim_id": profile.id if profile else None,
            "iccid": profile.iccid if profile else None,
            "esim_status": profile.status.value if profile else None,
            "lpa_string": profile.lpa_string if profile else None,
            "qr_code_data": profile.qr_code_data if profile else None,
            "is_mock_fallback": profile.is_mock_fallback if profile else None,
            # Cached telemetry only - this is a list view, and asking the
            # carrier for 50 live readings would make the search unusable.
            # The per-eSIM panel is where a forced refresh belongs.
            "data_used_mb": str(telemetry.data_used_mb) if telemetry and telemetry.data_used_mb is not None else None,
            "is_installed": telemetry.is_installed if telemetry else None,
            "activated_at": fmt_bd(telemetry.activated_at) if telemetry and telemetry.activated_at else None,
            "expires_at": fmt_bd(telemetry.expires_at) if telemetry and telemetry.expires_at else None,
            "usage_fetched_at": fmt_bd(telemetry.fetched_at) if telemetry and telemetry.fetched_at else None,
        })

    return {"items": items, "count": len(items), "capped_at": limit}


async def esim_counts(db: AsyncSession) -> dict:
    """The headline numbers for the dashboard widget."""
    total = (await db.execute(
        select(func.count()).select_from(ESIMProfile)
    )).scalar_one()
    installed = (await db.execute(
        select(func.count()).select_from(ESIMTelemetry).where(ESIMTelemetry.is_installed.is_(True))
    )).scalar_one()
    never_installed = (await db.execute(
        select(func.count()).select_from(ESIMProfile)
        .outerjoin(ESIMTelemetry, ESIMTelemetry.esim_profile_id == ESIMProfile.id)
        .where(or_(ESIMTelemetry.id.is_(None), ESIMTelemetry.is_installed.is_(False)))
    )).scalar_one()
    return {"total_esims": total, "installed": installed, "never_installed": never_installed}
