import uuid
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import verify_password, get_password_hash, create_access_token
from app.core.deps import get_current_user
from app.models.user import User, UserRole, UserStatus
from app.models.merchant import MerchantProfile, MerchantStatus
from app.models.wallet import Wallet
from app.schemas.auth import UserRegister, UserLogin, Token, UserResponse, MerchantApplicationRequest
from app.services.ledger_svc import LedgerService

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=Token)
async def register(req: UserRegister, db: AsyncSession = Depends(get_db)):
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

    token = create_access_token(subject=user.id, role=user.role.value)
    return Token(access_token=token, token_type="bearer", role=user.role.value, user_id=user.id, username=user.username)

@router.post("/login", response_model=Token)
async def login(req: UserLogin, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(User).where((User.email == req.email) | (User.username == req.email)))
    user = res.scalar_one_or_none()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email/username or password")

    if user.status == UserStatus.SUSPENDED:
        raise HTTPException(status_code=403, detail="Account suspended")

    token = create_access_token(subject=user.id, role=user.role.value)
    return Token(access_token=token, token_type="bearer", role=user.role.value, user_id=user.id, username=user.username)

@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    wallets_res = await db.execute(select(Wallet).where(Wallet.user_id == current_user.id))
    wallets = wallets_res.scalars().all()
    
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
        "wallets": [{"type": w.wallet_type.value, "balance": float(w.balance), "currency": w.currency} for w in wallets],
        "merchant_profile": {
            "business_name": merchant.business_name,
            "status": merchant.status.value,
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
