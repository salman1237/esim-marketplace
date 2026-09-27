"""Live status for a delivered eSIM.

One endpoint serves the customer's status page, the merchant's view of an eSIM
they sold, and admin support - the shape is identical, so nobody is debugging
against different numbers than the customer is looking at.

There is deliberately no public/shareable link. VivaPe's own status page is
unauthenticated on a sequential transaction id and exposes the ICCID, SM-DP+
address, matching id and full LPA string - i.e. everything needed to install
someone else's eSIM. Access here requires being the recipient, the buyer, or
staff.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.rate_limit import limiter
from app.models.catalog import Product
from app.models.order import ESIMProfile, Order
from app.models.user import User, UserRole
from app.services import esim_telemetry_svc

router = APIRouter(prefix="/esims", tags=["eSIM Status"])

STAFF_ROLES = {UserRole.SUPER_ADMIN, UserRole.ADMIN}


async def _load(db: AsyncSession, esim_id: str, current_user: User):
    row = (await db.execute(
        select(ESIMProfile, Order, Product)
        .join(Order, ESIMProfile.order_id == Order.id)
        .join(Product, Order.product_id == Product.id)
        .where(ESIMProfile.id == esim_id)
    )).first()
    if not row:
        raise HTTPException(status_code=404, detail="eSIM not found")

    profile, order, product = row
    allowed = (
        current_user.id in (profile.beneficiary_id, order.buyer_id)
        or current_user.role in STAFF_ROLES
    )
    # Same 404 as a nonexistent id, so eSIM ids can't be probed for existence.
    if not allowed:
        raise HTTPException(status_code=404, detail="eSIM not found")
    return profile, order, product


@router.get("/{esim_id}/status")
async def get_esim_status(
    esim_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Served from cache when fresh (5 minutes), refetched when stale. Never
    fails because the supplier is down - the last snapshot is returned with
    the error alongside it."""
    profile, order, product = await _load(db, esim_id, current_user)
    telemetry = await esim_telemetry_svc.get_telemetry(db, profile, order)
    return esim_telemetry_svc.serialize(telemetry, profile, product, order)


@router.post("/{esim_id}/refresh")
@limiter.limit("20/minute")
async def refresh_esim_status(
    esim_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A human asked for fresh numbers, so VivaPe polls the upstream carrier.
    Rate-limited per caller, and the service itself enforces a short
    per-eSIM cooldown so a held-down button can't become a load test."""
    profile, order, product = await _load(db, esim_id, current_user)
    telemetry = await esim_telemetry_svc.get_telemetry(db, profile, order, force=True)
    return esim_telemetry_svc.serialize(telemetry, profile, product, order)
