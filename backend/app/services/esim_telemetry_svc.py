"""Live eSIM telemetry: data used, install state, and the real validity window.

For a VivaPe eSIM, this comes from two calls - esim/usage and
esim/device-info - merged into one cached snapshot. For an eSIM Access
eSIM, esim/query returns everything in one call (iccid, LPA, esimStatus/
smdpStatus, and - per the reference doc's confirmed response shape -
totalVolume/orderUsage/totalDuration/expiredTime), so there is no
separate "device info" call to make; see _fetch_esimaccess below.

The important correction this service makes: an eSIM's validity runs from
FIRST ACTIVATION, not from purchase. VivaPe reports `start_date` as the moment
the profile first attached and `end_date` as validity days after that, and
returns a long coupon window for a profile nobody has installed yet. So
ESIMProfile.activated_at/expires_at are filled in from here once the customer
installs, and stay NULL until then. The same principle is applied to eSIM
Access's response even though it has no separate start_date field: an
expiredTime is only trusted once esimStatus confirms the eSIM is actually
in use, never for a freshly-issued, uninstalled profile.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.catalog import Product
from app.models.esim_telemetry import ESIMTelemetry
from app.models.order import ESIMProfile, Order
from app.services.esimaccess_adapter import ESIMAccessAdapter
from app.services.vivape_adapter import VivaPeAdapter

logger = get_logger(__name__)

# How long a snapshot is served before a page view refetches it.
TTL = timedelta(minutes=5)
# Floor between forced refreshes of the same eSIM. A forced refresh makes
# VivaPe poll the upstream carrier, so the button can't be a load generator.
FORCE_COOLDOWN = timedelta(seconds=45)

# VivaPe is inconsistent about timestamps across its endpoints: user/profile
# returns an ISO string with a real offset ("...T13:31:32+01:00"), their
# published collection shows a UTC "Z", and the eSIM diagnostics endpoints
# hand back the upstream carrier's own naive strings ("2026-09-26 18:47:19").
#
# The previous version of this function sliced every value to [:19], which
# threw away the offset when there was one and stamped the result UTC. An
# activation an hour or eight hours out is not a rounding detail: it is what a
# customer compares against their landing time, so it is read as the system
# being wrong about their eSIM.
#
# So: honour whatever offset the string carries, and only fall back to an
# assumed zone when it genuinely has none. That assumption is configurable
# because it belongs to whoever is upstream of VivaPe, not to us.
_NAIVE_TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


def _supplier_tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.SUPPLIER_TIMEZONE)
    except Exception:
        logger.warning("unknown_supplier_timezone", configured=settings.SUPPLIER_TIMEZONE)
        return ZoneInfo("UTC")


def _parse_ts(value) -> Optional[datetime]:
    """Parse a supplier timestamp into an aware UTC datetime.

    Returns None for anything unparseable rather than guessing, so a bad value
    surfaces as a missing activation date instead of a plausible wrong one.
    """
    if not value or not isinstance(value, str):
        return None

    text = value.strip()
    parsed: Optional[datetime] = None

    # fromisoformat handles "Z", "+01:00" and fractional seconds on 3.11.
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in _NAIVE_TS_FORMATS:
            try:
                parsed = datetime.strptime(text[:19], fmt)
                break
            except ValueError:
                continue

    if parsed is None:
        return None

    if parsed.tzinfo is None:
        # No offset: the string is local time somewhere upstream of us.
        parsed = parsed.replace(tzinfo=_supplier_tz())

    return parsed.astimezone(timezone.utc)


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


def _merge_esimaccess(entry: dict | None) -> dict:
    """One entry from eSIM Access's esim/query obj.esimList[] (see
    checkout_svc.py's _extract_esimaccess_details for the same `ac`/LPA
    parsing already proven against a real purchase). Confirmed live
    fields are iccid/ac/esimStatus/smdpStatus (reference doc §4.2); the
    usage fields (totalVolume, orderUsage, totalDuration, durationUnit,
    expiredTime) are the shape the reference doc's own worked FAQ example
    shows for this same envelope (§3) and documents as expected to carry
    over to esim/query (§4.3) - not yet independently re-confirmed
    against a real query_esim call, so read defensively and never assumed
    present.

    No device-info equivalent exists for eSIM Access (no handset model,
    no EID, no event history) - those fields are simply always empty
    here, not a bug to fix later."""
    entry = entry if isinstance(entry, dict) else {}

    order_usage = entry.get("orderUsage")
    used_bytes = _as_int(order_usage) if order_usage is not None else 0

    esim_status = entry.get("esimStatus") or None
    # Only "IN_USE" is a confirmed-live signal (reference doc §5's
    # ESIM_STATUS webhook example) that the eSIM is genuinely installed
    # and active. Any other or unknown esimStatus value is NOT assumed to
    # mean installed - the same "confirmed, not guessed" discipline every
    # other eSIM Access field in this project follows. This means a
    # customer's status briefly shows "Not installed yet" for esimStatus
    # values this project hasn't seen live yet, which is the safe
    # direction to be wrong in - never the reverse.
    is_installed = esim_status == "IN_USE"

    expires_at = _parse_ts(entry.get("expiredTime")) if is_installed else None
    activated_at = None
    total_duration = entry.get("totalDuration")
    duration_unit = entry.get("durationUnit")
    if is_installed and expires_at and total_duration and duration_unit == "DAY":
        # eSIM Access gives only the absolute expiry, never a start date -
        # unlike VivaPe's explicit start_date, so activation time is
        # derived by walking the known validity length back from it.
        activated_at = expires_at - timedelta(days=_as_int(total_duration))

    return {
        "data_used_bytes": used_bytes,
        "data_used_mb": _as_decimal(Decimal(used_bytes) / Decimal(1024 * 1024)) if used_bytes else Decimal("0"),
        "status_code": 1 if is_installed else 0,
        "status_text": esim_status,
        "is_installed": is_installed,
        "device_model": None,
        "eid": None,
        "activated_at": activated_at,
        "expires_at": expires_at,
        "history": [],
        "daily_breakdown": [],
    }


def _is_activated(merged: dict) -> bool:
    """Only an installed profile has a real validity window. VivaPe reports a
    long coupon window and status 0/"Unknown" for one nobody has installed,
    so its end_date must not be mistaken for the plan's expiry."""
    return bool(merged["is_installed"]) or bool(merged["status_code"])


async def _fetch(db: AsyncSession, profile: ESIMProfile, product: Product, trx_id, refresh: bool) -> dict:
    if product.supplier_reference == "esimaccess":
        # One call carries everything (reference doc §4.3) - no separate
        # "refresh" concept the way VivaPe's usage call has one, since
        # esim/query has no cache of its own to bypass.
        result = await ESIMAccessAdapter.query_esim(db, order_no=profile.supplier_reference, iccid=profile.iccid)
        esim_list = (result or {}).get("esimList") or []
        return _merge_esimaccess(esim_list[0] if esim_list else None)

    usage = await VivaPeAdapter.get_esim_usage(db, trx_id=trx_id, iccid=profile.iccid, refresh=refresh)
    device = await VivaPeAdapter.get_esim_device_info(db, trx_id=trx_id, iccid=profile.iccid)
    return _merge(usage, device)


async def get_telemetry(
    db: AsyncSession, profile: ESIMProfile, product: Product, order: Optional[Order] = None, *, force: bool = False
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
        merged = await _fetch(db, profile, product, trx_id, refresh=force)
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


def share_url(profile: ESIMProfile) -> Optional[str]:
    """The public tracking link sent in the delivery email."""
    if not profile.share_token:
        return None
    return f"{settings.FRONTEND_BASE_URL}/track/{profile.share_token}"


def serialize(
    row: Optional[ESIMTelemetry], profile: ESIMProfile, product: Product, order: Order, *, public: bool = False
) -> dict:
    """One shape for the customer page, the public tracking link, the merchant
    view and admin support.

    `public` strips the handset's hardware id (EID) from the carrier history
    and withholds the share link itself. Everything else is identical: the
    install details are the point of the link, and the delivery email carrying
    it already contains the QR code and the LPA string.
    """
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
        "share_url": None if public else share_url(profile),
        "history": _history(row, public),
        "daily_breakdown": (row.daily_breakdown or []) if row else [],
        "telemetry": {
            "fetched_at": row.fetched_at if row else None,
            "error": row.fetch_error if row else None,
            "available": row is not None and not (row.fetch_error and not row.fetched_at),
        },
    }


def _history(row: Optional[ESIMTelemetry], public: bool) -> list:
    events = (row.history or []) if row else []
    if not public:
        return events
    # The EID identifies the customer's physical handset and tells them
    # nothing useful, so it doesn't travel on a link that can be forwarded.
    return [{k: v for k, v in e.items() if k != "eid"} for e in events if isinstance(e, dict)]


def _row_activated(row: ESIMTelemetry) -> bool:
    return bool(row.is_installed) or bool(row.status_code)


def _format_data(mb: Optional[Decimal]) -> Optional[str]:
    if mb is None:
        return None
    mb = Decimal(str(mb))
    if mb >= Decimal("1024"):
        return f"{(mb / Decimal('1024')).quantize(Decimal('0.01'))} GB"
    return f"{mb.quantize(Decimal('0.01'))} MB"
