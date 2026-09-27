"""Live eSIM telemetry: data used, install state, and the real validity window.

Everything here comes from two VivaPe calls - esim/usage and
esim/device-info - merged into one cached snapshot per eSIM.

The important correction this service makes: an eSIM's validity runs from
FIRST ACTIVATION, not from purchase. VivaPe reports `start_date` as the moment
the profile first attached and `end_date` as validity days after that, and
returns a long coupon window for a profile nobody has installed yet. So
ESIMProfile.activated_at/expires_at are filled in from here once the customer
installs, and stay NULL until then.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.catalog import Product
from app.models.esim_telemetry import ESIMTelemetry
from app.models.order import ESIMProfile, Order
from app.services.vivape_adapter import VivaPeAdapter

logger = get_logger(__name__)

# How long a snapshot is served before a page view refetches it.
TTL = timedelta(minutes=5)
# Floor between forced refreshes of the same eSIM. A forced refresh makes
# VivaPe poll the upstream carrier, so the button can't be a load generator.
FORCE_COOLDOWN = timedelta(seconds=45)

# VivaPe returns naive local-looking timestamps ("2026-09-26 18:47:19") in
# their account timezone. Parsed as UTC: an hour's drift on a 3-day validity
# is immaterial next to showing the wrong month, which is what computing from
# the purchase date did.
_TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


def _parse_ts(value) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(value.strip()[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _as_int(value) -> int:
    try:
        return int(Decimal(str(value)))
    except Exception:
        return 0


def _as_decimal(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0")


def _merge(usage: dict | None, device: dict | None) -> dict:
    """The two responses reduced to the fields the UI and support actually use."""
    usage = usage if isinstance(usage, dict) else {}
    device = device if isinstance(device, dict) else {}

    history = device.get("history")
    daily = usage.get("daily_breakdown")

    return {
        "data_used_bytes": _as_int(usage.get("total_bytes")),
        "data_used_mb": _as_decimal(usage.get("total_mb")),
        "status_code": usage.get("esim_status_code") if isinstance(usage.get("esim_status_code"), int) else None,
        "status_text": (usage.get("esim_status_text") or None),
        "is_installed": bool(device.get("is_installed")),
        "device_model": device.get("device_model") or None,
        "eid": device.get("eid") or None,
        "activated_at": _parse_ts(usage.get("start_date")),
        "expires_at": _parse_ts(usage.get("end_date")),
        "history": history if isinstance(history, list) else [],
        "daily_breakdown": daily if isinstance(daily, list) else [],
    }


def _is_activated(merged: dict) -> bool:
    """Only an installed profile has a real validity window. VivaPe reports a
    long coupon window and status 0/"Unknown" for one nobody has installed,
    so its end_date must not be mistaken for the plan's expiry."""
    return bool(merged["is_installed"]) or bool(merged["status_code"])


async def _fetch(db: AsyncSession, profile: ESIMProfile, trx_id, refresh: bool) -> dict:
    usage = await VivaPeAdapter.get_esim_usage(db, trx_id=trx_id, iccid=profile.iccid, refresh=refresh)
    device = await VivaPeAdapter.get_esim_device_info(db, trx_id=trx_id, iccid=profile.iccid)
    return _merge(usage, device)


async def get_telemetry(
    db: AsyncSession, profile: ESIMProfile, order: Optional[Order] = None, *, force: bool = False
) -> Optional[ESIMTelemetry]:
    """The cached snapshot, refreshed when stale or when a human asked.

    Never raises for a supplier problem: a failed fetch keeps the previous
    snapshot and records `fetch_error`, because the moment VivaPe is down is
    exactly when someone is trying to look at an eSIM. Caller need not commit;
    this commits its own write.
    """
    row = (await db.execute(
        select(ESIMTelemetry).where(ESIMTelemetry.esim_profile_id == profile.id)
    )).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if row is not None:
        age = now - row.fetched_at if row.fetched_at else TTL
        if force:
            # Only a previous FORCED poll throttles this one, so pressing
            # Refresh right after opening the page still works.
            since_forced = now - row.last_forced_at if row.last_forced_at else None
            if since_forced is not None and since_forced < FORCE_COOLDOWN:
                return row
        elif age < TTL and not row.fetch_error:
            return row

    trx_id = profile.supplier_reference or (order.external_trx_id if order else None)
    if not trx_id and not profile.iccid:
        return row

    try:
        merged = await _fetch(db, profile, trx_id, refresh=force)
    except Exception as e:
        logger.warning("esim_telemetry_fetch_failed", esim_profile_id=profile.id, error=str(e))
        if row is None:
            row = ESIMTelemetry(esim_profile_id=profile.id)
            db.add(row)
        row.fetched_at = now
        if force:
            row.last_forced_at = now
        row.fetch_error = str(e)[:500]
        await db.commit()
        await db.refresh(row)
        return row

    if row is None:
        row = ESIMTelemetry(esim_profile_id=profile.id)
        db.add(row)

    for field, value in merged.items():
        setattr(row, field, value)
    row.fetched_at = now
    if force:
        row.last_forced_at = now
    row.fetch_error = None

    # Promote the real validity window onto the profile once the customer has
    # actually installed it - that is the only point at which these are known.
    if _is_activated(merged):
        if merged["activated_at"]:
            profile.activated_at = merged["activated_at"]
        if merged["expires_at"]:
            profile.expires_at = merged["expires_at"]

    await db.commit()
    await db.refresh(row)
    return row


def data_allowance_mb(product: Product) -> Optional[Decimal]:
    """The plan's size in MB, or None for unlimited - which has no remaining
    figure to show and must not be rendered as a full progress bar."""
    if product.is_unlimited or product.data_amount_gb is None:
        return None
    return (Decimal(str(product.data_amount_gb)) * Decimal("1024")).quantize(Decimal("0.01"))


# Only 0 (never installed) and 1 (Active) have been observed from VivaPe. The
# label is taken from their response; this only supplies wording for the case
# where they send nothing at all.
def status_label(row: Optional[ESIMTelemetry], profile: ESIMProfile) -> str:
    if row is None:
        return "Not checked yet"
    if row.is_installed or (row.status_code or 0) > 0:
        return row.status_text or "Active"
    return "Not installed yet"


def serialize(row: Optional[ESIMTelemetry], profile: ESIMProfile, product: Product, order: Order) -> dict:
    """One shape for the customer page, the merchant view and admin support."""
    allowance = data_allowance_mb(product)
    used_mb = Decimal(str(row.data_used_mb)) if row and row.data_used_mb is not None else Decimal("0")
    remaining = None
    used_pct = None
    if allowance is not None and allowance > 0:
        remaining = max(Decimal("0"), allowance - used_mb)
        used_pct = float(min(Decimal("100"), (used_mb / allowance * Decimal("100")).quantize(Decimal("0.1"))))

    # Activation is decided by the profile being installed, never by the
    # presence of VivaPe's timestamps: for an uninstalled eSIM those describe
    # the long coupon window, and treating them as the plan's dates is exactly
    # the mistake this whole change exists to fix.
    row_activated = bool(row and _row_activated(row))
    activated = row_activated or bool(profile.activated_at)
    activated_at = profile.activated_at or (row.activated_at if row_activated else None)
    expires_at = profile.expires_at or (row.expires_at if row_activated else None)

    return {
        "esim_id": profile.id,
        "order_no": order.order_no,
        "purchased_at": order.created_at,
        "product": {
            "title": product.title_en,
            "validity_days": product.validity_days,
            "is_unlimited": bool(product.is_unlimited),
            "data_amount_gb": str(product.data_amount_gb) if product.data_amount_gb is not None else None,
        },
        "iccid": profile.iccid,
        "lpa_string": profile.lpa_string,
        "qr_code_data": profile.qr_code_data,
        "smdp_address": profile.smdp_address,
        "matching_id": profile.matching_id,
        "supplier_reference": profile.supplier_reference,
        "status": {
            "label": status_label(row, profile),
            "code": row.status_code if row else None,
            "is_installed": bool(row.is_installed) if row else False,
            "is_activated": activated,
            "device_model": row.device_model if row else None,
        },
        "usage": {
            "used_mb": str(used_mb),
            "used_bytes": int(row.data_used_bytes) if row and row.data_used_bytes else 0,
            "formatted": _format_data(used_mb),
            "allowance_mb": str(allowance) if allowance is not None else None,
            "remaining_mb": str(remaining) if remaining is not None else None,
            "remaining_formatted": _format_data(remaining) if remaining is not None else None,
            "used_pct": used_pct,
            "is_unlimited": bool(product.is_unlimited),
        },
        "validity": {
            "days": product.validity_days,
            "activated_at": activated_at,
            "expires_at": expires_at,
            # Said plainly, because it is the thing customers get wrong: the
            # clock starts on install, not at purchase.
            "note": (
                None if activated
                else f"Validity starts when you install this eSIM — {product.validity_days} days from then."
            ),
        },
        "history": (row.history or []) if row else [],
        "daily_breakdown": (row.daily_breakdown or []) if row else [],
        "telemetry": {
            "fetched_at": row.fetched_at if row else None,
            "error": row.fetch_error if row else None,
            "available": row is not None and not (row.fetch_error and not row.fetched_at),
        },
    }


def _row_activated(row: ESIMTelemetry) -> bool:
    return bool(row.is_installed) or bool(row.status_code)


def _format_data(mb: Optional[Decimal]) -> Optional[str]:
    if mb is None:
        return None
    mb = Decimal(str(mb))
    if mb >= Decimal("1024"):
        return f"{(mb / Decimal('1024')).quantize(Decimal('0.01'))} GB"
    return f"{mb.quantize(Decimal('0.01'))} MB"
