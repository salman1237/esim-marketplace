"""Live status for a delivered eSIM.

One serializer feeds the customer's status page, the public tracking link sent
in the delivery email, the merchant's view of an eSIM they sold, and admin
support - so nobody is ever debugging against different numbers than the
customer is looking at.

The public link is keyed on a 128-bit random share_token, never on the profile
id. VivaPe's own status page is unauthenticated on a *sequential* transaction
id, which means anyone can count upwards and read other customers' eSIMs; a
random token cannot be walked. The link is no more sensitive than the delivery
email that carries it, which already contains the QR code and the LPA string -
but the public view still omits the handset's hardware id, which the customer
has no use for.
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
from app.services import esim_telemetry_svc, esim_topup_svc
from app.services.checkout_svc import new_share_token
from app.schemas.esim_topup import EsimTopupResponse, TopupOptionResponse, TopupPurchaseRequest

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


@router.get("/public/{token}")
@limiter.limit("60/minute")
async def public_esim_status(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """The tracking link from the delivery email. No login: the customer who
    received the eSIM may not have an account at all (a merchant can buy on
    their behalf), which is exactly why this exists.

    Declared before /{esim_id}/status so "public" is never read as an id.
    """
    if len(token) < 16:
        raise HTTPException(status_code=404, detail="Not found")

    row = (await db.execute(
        select(ESIMProfile, Order, Product)
        .join(Order, ESIMProfile.order_id == Order.id)
        .join(Product, Order.product_id == Product.id)
        .where(ESIMProfile.share_token == token)
    )).first()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")

    profile, order, product = row
    telemetry = await esim_telemetry_svc.get_telemetry(db, profile, order)
    return esim_telemetry_svc.serialize(telemetry, profile, product, order, public=True)


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
    # eSIMs delivered before tracking links existed get one the first time
    # their owner opens this page - cheaper and safer than a bulk backfill.
    if not profile.share_token:
        profile.share_token = new_share_token()
        await db.commit()
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


@router.get("/{esim_id}/topup-options", response_model=list[TopupOptionResponse])
async def get_topup_options(
    esim_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Live, just-fetched options - empty for anything but a delivered
    eSIM Access eSIM. See esim_topup_svc.py for why nothing is cached."""
    profile, _order, product = await _load(db, esim_id, current_user)
    return await esim_topup_svc.get_topup_options(db, profile, product)


@router.post("/{esim_id}/topup", response_model=EsimTopupResponse)
@limiter.limit("10/minute")
async def purchase_topup(
    esim_id: str,
    req: TopupPurchaseRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile, _order, product = await _load(db, esim_id, current_user)
    try:
        topup = await esim_topup_svc.purchase_topup(db, profile, product, req.package_code, current_user.id)
    except esim_topup_svc.TopupNotAvailable as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return topup
