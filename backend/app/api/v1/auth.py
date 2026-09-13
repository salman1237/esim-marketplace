import uuid
import asyncio
import secrets
import hashlib
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db, AsyncSessionLocal
from app.core.rate_limit import limiter
from app.core.security import verify_password, get_password_hash, create_access_token
from app.core.deps import get_current_user
from app.core.logging import get_logger
from app.models.user import User, UserRole, UserStatus
from app.models.merchant import MerchantProfile, MerchantStatus
from app.models.wallet import Wallet, WalletType
from app.models.password_reset import PasswordResetToken
from app.schemas.auth import (
    UserRegister, UserLogin, Token, UserResponse, MerchantApplicationRequest,
    ForgotPasswordRequest, ResetPasswordRequest,
)
from app.services.ledger_svc import LedgerService
from app.services.email_svc import EmailService

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

    user = User(
        email=req.email,
        username=req.username,
        hashed_password=get_password_hash(req.password),
        role=UserRole.USER,
        status=UserStatus.ACTIVE,
        phone=req.phone,
        full_name=req.full_name
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Initialize Wallets
    await LedgerService.ensure_wallets_for_user(db, user.id, user.role)

    asyncio.create_task(_send_welcome_email_background(user.email, user.username))

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

    profile = MerchantProfile(
        user_id=current_user.id,
        business_name=req.business_name,
        trade_license=req.trade_license,
        contact_phone=req.contact_phone,
        website=req.website,
        status=MerchantStatus.PENDING
    )
    db.add(profile)
    await db.commit()
    return {"status": "success", "message": "Application submitted for review"}
