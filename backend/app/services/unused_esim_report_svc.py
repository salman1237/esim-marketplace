"""The paid-but-never-delivered eSIM report.

An order that reached VivaPe's create-transaction was BILLED TO US even if
the customer never received anything. Until 28 Oct 2026 a supplier that
issues eSIMs asynchronously (WorldMove answers "Transaction Pending" for
the first seconds) made that routine: the order was refunded to the
customer and the eSIM abandoned, paid for and unclaimed. That bug is
fixed, but the eSIMs it already bought still exist on VivaPe's side and
are what this report exists to reclaim.

The ICCID is the part VivaPe actually reconciles on, and it is NOT in our
database for these orders - no ESIMProfile was ever created, so the only
copy lives at VivaPe, reachable by the transaction id we did record.
Hence the live lookup: a report without ICCIDs is not a claim, it is a
list of complaints.
"""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.timeutil import fmt_bd
from app.models.catalog import Country, Product
from app.models.esim_telemetry import ESIMTelemetry
from app.models.order import ESIMProfile, Order, OrderStatus
from app.models.settings import PlatformSetting
from app.models.user import User
from app.services.vivape_adapter import VivaPeAdapter

logger = get_logger(__name__)

# Emails and ICCIDs the business has told us were their own testing, kept
# as a setting rather than hardcoded so it can be corrected without a
# deploy - VivaPe asked for real and test separated, and only the business
# knows which of their own accounts were which.
TEST_IDENTIFIERS_KEY = "test_esim_identifiers"

# A courtesy to a supplier that rate-limits at 60/min, and a guard against
# one slow report tying up a worker for minutes.
_LOOKUP_CONCURRENCY = 4


async def get_test_identifiers(db: AsyncSession) -> set[str]:
    res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == TEST_IDENTIFIERS_KEY))
    row = res.scalar_one_or_none()
    value = row.value if row else None
    if isinstance(value, list):
        return {str(v).strip().lower() for v in value if str(v).strip()}
    return set()


async def set_test_identifiers(db: AsyncSession, identifiers: list[str], admin_id: str) -> list[str]:
    cleaned = sorted({str(v).strip().lower() for v in identifiers if str(v).strip()})
    res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == TEST_IDENTIFIERS_KEY))
    row = res.scalar_one_or_none()
    if row:
        row.value = cleaned
        row.updated_by_id = admin_id
    else:
        db.add(PlatformSetting(key=TEST_IDENTIFIERS_KEY, value=cleaned, is_public=False, updated_by_id=admin_id))
    await db.flush()
    return cleaned


def _iccid_from(payload) -> Optional[str]:
    """VivaPe returns the eSIM under different shapes per wholesaler, so
    take the ICCID from wherever it actually is rather than assuming one."""
    if not isinstance(payload, dict):
        return None
    for candidate in (payload, payload.get("esim_order"), payload.get("esim"), payload.get("data")):
        if isinstance(candidate, dict) and candidate.get("iccid"):
            return str(candidate["iccid"])
    return None


def _supplier_status_from(payload) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    order = payload.get("esim_order") if isinstance(payload.get("esim_order"), dict) else payload
    if not isinstance(order, dict):
        return None
    return order.get("resultmsg") or order.get("note") or order.get("msg")


async def _lookup(trx_id: str, semaphore: asyncio.Semaphore) -> dict:
    """Never raises: a lookup that fails must leave a row in the report
    saying so, not remove an order we were charged for from the claim.

    Runs on its OWN session, never the caller's. The adapter records every
    supplier call in supplier_transaction_logs, and an AsyncSession cannot
    be used from several tasks at once - sharing the request session made
    those writes interleave, one flush failed, and the whole session was
    left in "current transaction is aborted" for the rest of the request
    (production 500s, 29 Oct 2026). A session per lookup also means one
    bad call cannot poison the others.
    """
    async with semaphore:
        try:
            async with AsyncSessionLocal() as lookup_db:
                payload = await VivaPeAdapter.get_esim_by_trx(lookup_db, trx_id)
            return {
                "iccid": _iccid_from(payload),
                "supplier_status": _supplier_status_from(payload),
                "lookup_error": None,
            }
        except Exception as e:
            logger.warning("unused_esim_iccid_lookup_failed", trx_id=trx_id, error=str(e))
            return {"iccid": None, "supplier_status": None, "lookup_error": str(e)}


async def build_unused_esim_report(
    db: AsyncSession,
    *,
    search: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    include_type: Optional[str] = None,
    resolve_iccids: bool = True,
) -> dict:
    """Every eSIM VivaPe billed us for that the business should not be
    paying for, in two kinds:

    - NEVER_DELIVERED: charged, but the customer received nothing.
    - TEST_PURCHASE: the business testing its own platform. Delivered or
      not, VivaPe still charged for it, so it belongs in the same
      reconciliation - which is why a test account is included here even
      when its orders completed perfectly.

    `include_type` filters to "real" or "test"; anything else returns both.
    `resolve_iccids=False` skips the supplier lookups, for a fast on-screen
    list where the ICCID is not needed yet.
    """
    test_ids = await get_test_identifiers(db)

    # A delivered order keeps its ICCID in our own database; only the
    # abandoned ones have to be looked up at VivaPe.
    stmt = (
        select(Order, User, Product, Country, ESIMProfile, ESIMTelemetry)
        .join(User, Order.buyer_id == User.id)
        .join(Product, Order.product_id == Product.id)
        .join(Country, Product.country_id == Country.id)
        .outerjoin(ESIMProfile, ESIMProfile.order_id == Order.id)
        .outerjoin(ESIMTelemetry, ESIMTelemetry.esim_profile_id == ESIMProfile.id)
        .where(Order.external_trx_id.isnot(None))
        .order_by(Order.created_at.desc())
    )
    test_emails = [t for t in test_ids if "@" in t]
    stmt = stmt.where(
        or_(
            Order.status == OrderStatus.FAILED,
            func.lower(User.email).in_(test_emails) if test_emails else False,
        )
    )
    if date_from is not None:
        stmt = stmt.where(Order.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Order.created_at <= date_to)

    rows = (await db.execute(stmt)).all()

    # Only ask VivaPe about the ones we cannot answer ourselves.
    semaphore = asyncio.Semaphore(_LOOKUP_CONCURRENCY)

    async def _resolve(order, profile):
        if profile is not None and profile.iccid:
            return {"iccid": profile.iccid, "supplier_status": "Delivered", "lookup_error": None}
        if not resolve_iccids:
            return {"iccid": None, "supplier_status": None, "lookup_error": None}
        return await _lookup(order.external_trx_id, semaphore)

    lookups = await asyncio.gather(*[_resolve(o, prof) for o, _, _, _, prof, _ in rows]) if rows else []

    items = []
    for (order, user, product, country, profile, telemetry), extra in zip(rows, lookups):
        iccid = extra["iccid"]
        is_test = (user.email or "").lower() in test_ids or (iccid or "").lower() in test_ids
        cost = Decimal(str(order.cost_amount if order.cost_amount is not None else product.cost_price))
        item = {
            "order_no": order.order_no,
            "purchased_at": fmt_bd(order.created_at),
            "purchased_at_iso": order.created_at.isoformat() if order.created_at else None,
            "customer_name": user.full_name or user.username,
            "customer_email": user.email,
            "customer_phone": user.phone,
            "product": product.title_en,
            "country": country.name_en,
            "vivape_trx_id": order.external_trx_id,
            "iccid": iccid,
            "supplier_status": extra["supplier_status"],
            "lookup_error": extra["lookup_error"],
            "reason": "NEVER_DELIVERED" if order.status == OrderStatus.FAILED else "TEST_PURCHASE",
            "order_status": order.status.value,
            "data_used_mb": str(telemetry.data_used_mb) if telemetry is not None and telemetry.data_used_mb is not None else None,
            "supplier_cost_eur": str(cost.quantize(Decimal("0.01"))),
            "customer_refunded_eur": str(Decimal(str(order.total_amount)).quantize(Decimal("0.01"))),
            "type": "TEST" if is_test else "REAL",
        }
        if include_type in ("real", "test") and item["type"].lower() != include_type:
            continue
        if search:
            needle = search.strip().lower()
            haystack = " ".join(
                str(v or "") for v in (
                    item["order_no"], item["customer_name"], item["customer_email"],
                    item["customer_phone"], item["iccid"], item["vivape_trx_id"], item["product"],
                )
            ).lower()
            if needle not in haystack:
                continue
        items.append(item)

    total_cost = sum(Decimal(i["supplier_cost_eur"]) for i in items) if items else Decimal("0")
    real = [i for i in items if i["type"] == "REAL"]
    test = [i for i in items if i["type"] == "TEST"]
    return {
        "items": items,
        "summary": {
            "count": len(items),
            "real_count": len(real),
            "test_count": len(test),
            "supplier_cost_eur": str(total_cost.quantize(Decimal("0.01"))),
            "real_cost_eur": str(sum(Decimal(i["supplier_cost_eur"]) for i in real).quantize(Decimal("0.01")) if real else Decimal("0.00")),
            "test_cost_eur": str(sum(Decimal(i["supplier_cost_eur"]) for i in test).quantize(Decimal("0.01")) if test else Decimal("0.00")),
            "iccids_resolved": sum(1 for i in items if i["iccid"]),
            "generated_at": fmt_bd(datetime.now(timezone.utc)),
        },
    }
