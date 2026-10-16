from typing import Optional
import re
import uuid
import asyncio
import secrets
import hashlib
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.core.config import settings
from app.core.database import get_db, AsyncSessionLocal
from app.core.rate_limit import limiter
from app.core.security import verify_password, get_password_hash, create_access_token
from app.core.deps import get_current_user
from app.core.logging import get_logger
from app.models.user import User, UserRole, UserStatus
from app.models.merchant import MerchantProfile, MerchantStatus
from app.models.referral import ReferralEvent
from app.models.agent import AgentStatus
from app.models.wallet import Wallet, WalletType
from app.models.password_reset import PasswordResetToken
from app.services import currency_svc
from pydantic import BaseModel, Field
from app.schemas.auth import (
    UserRegister, UserLogin, Token, UserResponse, MerchantApplicationRequest,
    ForgotPasswordRequest, ResetPasswordRequest, GoogleLoginRequest,
)
from app.services.google_auth import GoogleTokenError, GoogleUnavailableError, verify_google_id_token
from app.services.ledger_svc import LedgerService
from app.services import agent_svc, notify_svc, referral_svc
from app.services.email_svc import EmailService
from app.services.referral_settings_svc import event_amounts, get_referral_settings

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


async def _send_welcome_email_background(email: str, username: str):
    # Own session, not the request's - that one closes as soon as the
    # response is returned, before this background task gets to run.
    async with AsyncSessionLocal() as bg_db:
        try:
            await EmailService.send_welcome(bg_db, email, username)
        except Exception as e:
            logger.warning("welcome_email_background_task_failed", email=email, error=str(e))


async def _send_password_reset_email_background(email: str, raw_token: str):
    async with AsyncSessionLocal() as bg_db:
        try:
            await EmailService.send_password_reset(bg_db, email, raw_token)
        except Exception as e:
            logger.warning("password_reset_email_background_task_failed", email=email, error=str(e))

@router.post("/register", response_model=Token)
@limiter.limit("5/minute")
async def register(request: Request, req: UserRegister, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(User).where((User.email == req.email) | (User.username == req.username)))
    if res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email or username already exists")

    # An unknown code is ignored rather than refused: it must never be the
    # reason someone can't create an account.
    referrer = await referral_svc.find_referrer(db, req.referral_code)

    user = User(
        email=req.email,
        username=req.username,
        hashed_password=get_password_hash(req.password),
        role=UserRole.USER,
        status=UserStatus.ACTIVE,
        phone=req.phone,
        full_name=req.full_name,
        referred_by_id=referrer.id if referrer else None,
    )
    db.add(user)
    await db.flush()
    await referral_svc.ensure_referral_code(db, user)
    await db.commit()
    await db.refresh(user)

    # Initialize Wallets
    await LedgerService.ensure_wallets_for_user(db, user.id, user.role)

    if referrer:
        try:
            await referral_svc.grant(db, user, ReferralEvent.JOINING)
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.warning("referral_joining_grant_failed", user_id=user.id, error=str(e))

    asyncio.create_task(_send_welcome_email_background(user.email, user.username))
    notify_svc.account_created(
        username=user.username, email=user.email,
        referred_by=referrer.username if referrer else None,
    )
    if referrer:
        cfg = await get_referral_settings(db)
        _, referred_amount = event_amounts(cfg, ReferralEvent.JOINING)
        referrer_amount, _ = event_amounts(cfg, ReferralEvent.JOINING)
        notify_svc.referral_used(
            to=referrer.email, referrer=referrer.username, joined=user.username,
            reward=str(referrer_amount) if referrer_amount > 0 else None,
            currency=settings.BASE_CURRENCY,
        )

    token = create_access_token(subject=user.id, role=user.role.value)
    return Token(access_token=token, token_type="bearer", role=user.role.value, user_id=user.id, username=user.username)

@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
async def login(request: Request, req: UserLogin, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(User).where((User.email == req.email) | (User.username == req.email)))
    user = res.scalar_one_or_none()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email/username or password")

    if user.status == UserStatus.SUSPENDED:
        raise HTTPException(status_code=403, detail="Account suspended")

    token = create_access_token(subject=user.id, role=user.role.value)
    return Token(access_token=token, token_type="bearer", role=user.role.value, user_id=user.id, username=user.username)

@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password(request: Request, req: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    # Always returns the same success response regardless of whether the
    # email exists - a differing response would let an attacker enumerate
    # registered accounts by probing this endpoint.
    generic_response = {"status": "success", "message": "If that email is registered, a reset link has been sent."}

    res = await db.execute(select(User).where(User.email == req.email))
    user = res.scalar_one_or_none()
    if not user:
        return generic_response

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    db.add(PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))
    await db.commit()

    asyncio.create_task(_send_password_reset_email_background(user.email, raw_token))
    return generic_response


@router.post("/reset-password")
@limiter.limit("10/minute")
async def reset_password(request: Request, req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    token_hash = hashlib.sha256(req.token.encode()).hexdigest()
    res = await db.execute(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))
    reset_token = res.scalar_one_or_none()

    if not reset_token or reset_token.used_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or already-used reset link")
    if reset_token.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This reset link has expired")
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    user_res = await db.execute(select(User).where(User.id == reset_token.user_id))
    user = user_res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or already-used reset link")

    user.hashed_password = get_password_hash(req.new_password)
    reset_token.used_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "success", "message": "Password has been reset. You can now log in."}


async def _unique_username(db: AsyncSession, email: str) -> str:
    base = re.sub(r"[^a-z0-9_]", "", email.split("@")[0].lower())[:20] or "user"
    candidate = base
    for _ in range(10):
        if not (await db.execute(select(User.id).where(User.username == candidate))).first():
            return candidate
        candidate = f"{base}_{secrets.token_hex(2)}"
    return f"user_{uuid.uuid4().hex[:10]}"


@router.post("/google", response_model=Token)
@limiter.limit("20/minute")
async def google_login(request: Request, req: GoogleLoginRequest, db: AsyncSession = Depends(get_db)):
    """One-click sign-in (and sign-up) with a Google account.

    Account resolution, in order:
    1. Google account id (`sub`) already linked -> that user.
    2. Otherwise an existing account with the same email is linked - but
       only when Google says it has verified that address, or anyone could
       take over an account by creating a Google login for its email.
    3. Otherwise a new account is created with the Google name, photo and
       verified email.
    """
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google sign-in is not available")
    try:
        claims = await verify_google_id_token(req.credential, settings.GOOGLE_CLIENT_ID)
    except GoogleUnavailableError:
        raise HTTPException(status_code=503, detail="Google sign-in is temporarily unavailable. Please try again.")
    except GoogleTokenError as e:
        logger.info("google_login_rejected", reason=str(e))
        raise HTTPException(status_code=401, detail="Google sign-in could not be verified. Please try again.")

    google_sub = claims["sub"]
    email = claims["email"].strip().lower()
    email_verified = claims.get("email_verified") in (True, "true")

    user = (await db.execute(select(User).where(User.google_sub == google_sub))).scalar_one_or_none()
    created = False
    if not user:
        if not email_verified:
            raise HTTPException(
                status_code=400,
                detail="Your Google account's email address isn't verified. Verify it with Google, or sign up with email.",
            )
        user = (await db.execute(select(User).where(func.lower(User.email) == email))).scalar_one_or_none()
        if user:
            if user.google_sub and user.google_sub != google_sub:
                raise HTTPException(status_code=409, detail="This email is already linked to a different Google account")
            user.google_sub = google_sub
        else:
            user = User(
                email=email,
                username=await _unique_username(db, email),
                # Unusable random password: the account signs in with Google,
                # and can still set a password later via "Forgot password".
                hashed_password=get_password_hash(secrets.token_urlsafe(32)),
                full_name=claims.get("name"),
                role=UserRole.USER,
                status=UserStatus.ACTIVE,
                google_sub=google_sub,
            )
            db.add(user)
            created = True

    if user.status == UserStatus.SUSPENDED:
        raise HTTPException(status_code=403, detail="Account suspended")

    # Refresh from Google on every sign-in: the photo changes, and the email
    # is verified by Google for this address.
    if claims.get("picture"):
        user.avatar_url = claims["picture"][:1024]
    if not user.full_name and claims.get("name"):
        user.full_name = claims["name"]
    if email_verified and user.email.lower() == email:
        user.email_verified = True

    try:
        await db.commit()
    except IntegrityError:
        # Two first-time sign-ins for the same Google account raced.
        await db.rollback()
        user = (await db.execute(select(User).where(User.google_sub == google_sub))).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=409, detail="Couldn't finish Google sign-in. Please try again.")
        created = False
    await db.refresh(user)

    if created:
        await LedgerService.ensure_wallets_for_user(db, user.id, user.role)
        # Google sign-up carries no referral code (nothing in Google's token
        # to put one in), so there is no JOINING reward here - the code can
        # still be added later from the Refer & earn page.
        await referral_svc.ensure_referral_code(db, user)
        await db.commit()
        asyncio.create_task(_send_welcome_email_background(user.email, user.username))
    logger.info("google_login_succeeded", user_id=user.id, created=created)

    token = create_access_token(subject=user.id, role=user.role.value)
    return Token(access_token=token, token_type="bearer", role=user.role.value, user_id=user.id, username=user.username)


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    wallets_res = await db.execute(select(Wallet).where(Wallet.user_id == current_user.id))
    # Unordered from the DB, so the spendable DEFAULT wallet wasn't reliably
    # first - the header showed wallets[0] and read $0.00 whenever the
    # COMMISSION wallet happened to come back ahead of it.
    wallets = sorted(wallets_res.scalars().all(), key=lambda w: w.wallet_type != WalletType.DEFAULT)
    
    merchant_res = await db.execute(select(MerchantProfile).where(MerchantProfile.user_id == current_user.id))
    merchant = merchant_res.scalar_one_or_none()

    return {
        "id": current_user.id,
        "email": current_user.email,
        "username": current_user.username,
        "role": current_user.role.value,
        "status": current_user.status.value,
        "phone": current_user.phone,
        "full_name": current_user.full_name,
        "is_kyc_verified": current_user.is_kyc_verified,
        # The currency this account thinks in. Prices are still held in EUR;
        # this is what the customer types and reads, including when topping up.
        "preferred_currency": current_user.preferred_currency or settings.BASE_CURRENCY,
        "avatar_url": current_user.avatar_url,
        "email_verified": bool(current_user.email_verified),
        "has_google": bool(current_user.google_sub),
        # wallet_type matches /wallets/my-wallets; the reseller portal reads
        # that key. "type" is kept for existing clients.
        "wallets": [
            {"type": w.wallet_type.value, "wallet_type": w.wallet_type.value, "balance": float(w.balance), "currency": w.currency}
            for w in wallets
        ],
        "merchant_profile": {
            "business_name": merchant.business_name,
            "status": merchant.status.value,
            "rejection_reason": merchant.rejection_reason,
            "commission_rate_pct": float(merchant.commission_rate_pct)
        } if merchant else None
    }

@router.post("/apply-merchant")
async def apply_merchant(
    req: MerchantApplicationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(MerchantProfile).where(MerchantProfile.user_id == current_user.id))
    if res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Merchant application already submitted")

    # An agent's code on the application is how an agent gets credited for the
    # partner they brought in. An unknown or unapproved code is ignored rather
    # than refused - it must never block a partner application.
    agent_profile = await agent_svc.find_by_code(db, req.agent_code)
    agent_id = None
    if agent_profile and agent_profile.status == AgentStatus.APPROVED and agent_profile.user_id != current_user.id:
        agent_id = agent_profile.user_id

    profile = MerchantProfile(
        user_id=current_user.id,
        business_name=req.business_name,
        trade_license=req.trade_license,
        contact_phone=req.contact_phone,
        website=req.website,
        agent_id=agent_id,
        status=MerchantStatus.PENDING
    )
    db.add(profile)
    await db.commit()

    notify_svc.merchant_applied(
        to=current_user.email, business_name=profile.business_name,
        username=current_user.username,
        agent=agent_profile.company_name if agent_id else None,
    )
    if agent_id:
        # The agent hears that their code was used, which is the whole point
        # of giving them one.
        agent_user = (await db.execute(select(User).where(User.id == agent_id))).scalar_one_or_none()
        if agent_user:
            notify_svc.agent_code_used(
                to=agent_user.email, agent=agent_user.username,
                business_name=profile.business_name, applicant=current_user.username,
            )

    return {
        "status": "success",
        "message": "Application submitted for review",
        "agent": agent_profile.company_name if agent_id else None,
    }


class PreferencesRequest(BaseModel):
    # Both optional so this one endpoint can carry either, and so clearing a
    # phone number is expressible: omitted leaves it alone, "" removes it.
    preferred_currency: Optional[str] = Field(None, min_length=3, max_length=10)
    phone: Optional[str] = Field(None, max_length=50)


@router.put("/me/preferences")
async def update_preferences(
    req: PreferencesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Persists the currency this account thinks in, and its contact number.

    Currency was previously only in browser storage, so a customer who
    switched to BDT on their phone still saw euros on their laptop - and the
    top-up box had no idea what they wanted to type in.

    The phone number is optional at every point it is asked for, here
    included: plenty of customers buy an eSIM precisely because they are
    about to stop being reachable on their usual number.
    """
    if req.preferred_currency is not None:
        code = req.preferred_currency.strip().upper()
        if not currency_svc.is_supported(code):
            raise HTTPException(status_code=400, detail=f"{code} isn't a currency we hold a rate for")
        current_user.preferred_currency = code

    if req.phone is not None:
        phone = req.phone.strip()
        current_user.phone = phone or None

    await db.commit()
    return {
        "status": "success",
        "preferred_currency": current_user.preferred_currency,
        "phone": current_user.phone,
    }
