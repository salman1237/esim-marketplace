"""The customer's side of the referral programme.

Reward credit lands in the REWARD wallet: spendable on eSIMs, never
withdrawable. That isn't enforced here - it follows from withdrawal_svc only
ever touching the DEFAULT wallet - but it is what the copy on this page
promises, so the two must stay in step.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.order import Order, OrderStatus
from app.models.referral import ReferralEvent
from app.models.user import User
from app.services import referral_svc
from app.services.referral_settings_svc import get_referral_settings

router = APIRouter(prefix="/referrals", tags=["Referrals"])


class ClaimReferralRequest(BaseModel):
    code: str = Field(..., min_length=3, max_length=16)


@router.get("/validate")
async def validate_referral_code(code: str = Query(..., min_length=1, max_length=16), db: AsyncSession = Depends(get_db)):
    """Used by the registration form. Public, and deliberately thin: it
    confirms only that a code belongs to someone and shows that person's
    username, so a stranger's code can't be used to enumerate accounts."""
    cfg = await get_referral_settings(db)
    if not cfg["is_enabled"]:
        return {"valid": False}
    referrer = await referral_svc.find_referrer(db, code)
    if not referrer:
        return {"valid": False}
    _, referred_amount = (cfg["events"][ReferralEvent.JOINING.value]["referrer"],
                          cfg["events"][ReferralEvent.JOINING.value]["referred"])
    return {
        "valid": True,
        "referrer_username": referrer.username,
        "joining_reward": str(referred_amount),
        "currency": settings.BASE_CURRENCY,
    }


@router.get("/me")
async def my_referrals(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # An account created before this feature existed has no code yet; issue
    # one the first time they open the page rather than in a migration.
    if not current_user.referral_code:
        await referral_svc.ensure_referral_code(db, current_user)
        await db.commit()
        await db.refresh(current_user)

    summary = await referral_svc.my_summary(db, current_user)
    summary["currency"] = settings.BASE_CURRENCY
    summary["share_url"] = (
        f"{settings.FRONTEND_BASE_URL}/auth/register?ref={current_user.referral_code}"
        if current_user.referral_code else None
    )
    # Whether this account can still name a referrer (Google sign-up has no
    # place to enter one, so it is offered here instead).
    summary["can_claim"] = current_user.referred_by_id is None
    summary["referred_by"] = None
    if current_user.referred_by_id:
        referrer = (await db.execute(select(User.username).where(User.id == current_user.referred_by_id))).scalar_one_or_none()
        summary["referred_by"] = referrer
    return summary


@router.post("/claim")
async def claim_referral(
    req: ClaimReferralRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Names who referred you, after the fact. Needed because Google sign-up
    has nowhere to type a code.

    Guarded so it can't be used to attribute an established account: only
    before any eSIM has been delivered, only once, and never to yourself."""
    if current_user.referred_by_id:
        raise HTTPException(status_code=400, detail="Your account already has a referrer.")

    referrer = await referral_svc.find_referrer(db, req.code)
    if not referrer:
        raise HTTPException(status_code=400, detail="That referral code isn't valid.")
    if referrer.id == current_user.id:
        raise HTTPException(status_code=400, detail="You can't refer yourself.")

    delivered = (await db.execute(
        select(Order.id).where(Order.buyer_id == current_user.id, Order.status == OrderStatus.COMPLETED).limit(1)
    )).scalar_one_or_none()
    if delivered:
        raise HTTPException(
            status_code=400,
            detail="A referral code can only be added before your first eSIM purchase.",
        )

    current_user.referred_by_id = referrer.id
    await referral_svc.grant(db, current_user, ReferralEvent.JOINING)
    await db.commit()

    summary = await referral_svc.my_summary(db, current_user)
    summary["referred_by"] = referrer.username
    summary["can_claim"] = False
    summary["currency"] = settings.BASE_CURRENCY
    return summary
