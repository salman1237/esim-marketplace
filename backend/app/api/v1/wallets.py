from typing import List, Optional
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services import currency_svc
from app.models.wallet import Wallet, WalletLedgerEntry, WalletType
from app.models.payment import ManualPaymentRequest, ManualPaymentStatus
from app.services.payment_methods_svc import get_payment_methods
from app.schemas.wallet import WalletResponse, LedgerEntryResponse, ManualDepositRequest, ManualDepositResponse

router = APIRouter(prefix="/wallets", tags=["Wallets & Ledger"])

@router.get("/my-wallets", response_model=List[WalletResponse])
async def get_my_wallets(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Wallet).where(Wallet.user_id == current_user.id))
    return res.scalars().all()

@router.get("/ledger", response_model=List[LedgerEntryResponse])
async def get_my_ledger(
    limit: int = 50,
    wallet_type: Optional[WalletType] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    wallet_query = select(Wallet.id).where(Wallet.user_id == current_user.id)
    if wallet_type is not None:
        wallet_query = wallet_query.where(Wallet.wallet_type == wallet_type)
    wallets_res = await db.execute(wallet_query)
    wallet_ids = wallets_res.scalars().all()
    if not wallet_ids:
        return []

    entries_res = await db.execute(
        select(WalletLedgerEntry)
        .where(WalletLedgerEntry.wallet_id.in_(wallet_ids))
        .order_by(WalletLedgerEntry.created_at.desc())
        .limit(limit)
    )
    return entries_res.scalars().all()

@router.post("/manual-deposit", response_model=ManualDepositResponse)
async def submit_manual_deposit(
    req: ManualDepositRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Deposit amount must be greater than zero")
    if not req.transaction_id.strip():
        raise HTTPException(status_code=400, detail="Transaction ID is required")

    # The customer deposits in whatever currency they hold; approval converts
    # it to the base currency at that day's rate. Validated here so an
    # unknown code can't reach the approval screen and be credited at a
    # fallback rate nobody chose.
    currency = (req.currency or "BDT").strip().upper()
    if not currency_svc.is_supported(currency):
        raise HTTPException(status_code=400, detail=f"{currency} isn't a currency we hold a rate for")

    # Once the Super Admin has configured deposit accounts, a deposit must
    # name one of the active ones - otherwise an admin could be asked to
    # approve money sent to an account that was retired or never existed.
    bank_name = req.bank_name.strip()
    active = await get_payment_methods(db, active_only=True)
    if active:
        match = next((m for m in active if m.name.lower() == bank_name.lower()), None)
        if not match:
            raise HTTPException(status_code=400, detail="Please choose one of the listed payment methods")
        bank_name = match.name

    deposit = ManualPaymentRequest(
        user_id=current_user.id,
        amount=req.amount,
        currency=currency,
        bank_name=bank_name,
        transaction_id=req.transaction_id.strip(),
        receipt_url=req.receipt_url,
        status=ManualPaymentStatus.PENDING
    )
    db.add(deposit)
    await db.commit()
    await db.refresh(deposit)
    return deposit
