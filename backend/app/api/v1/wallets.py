from typing import List
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.wallet import Wallet, WalletLedgerEntry
from app.models.payment import ManualPaymentRequest, ManualPaymentStatus
from app.schemas.wallet import WalletResponse, LedgerEntryResponse, ManualDepositRequest, ManualDepositResponse

router = APIRouter(prefix="/wallets", tags=["Wallets & Ledger"])

@router.get("/my-wallets", response_model=List[WalletResponse])
async def get_my_wallets(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Wallet).where(Wallet.user_id == current_user.id))
    return res.scalars().all()

@router.get("/ledger", response_model=List[LedgerEntryResponse])
async def get_my_ledger(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    wallets_res = await db.execute(select(Wallet.id).where(Wallet.user_id == current_user.id))
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
    deposit = ManualPaymentRequest(
        user_id=current_user.id,
        amount=req.amount,
        currency=req.currency,
        bank_name=req.bank_name,
        transaction_id=req.transaction_id,
        receipt_url=req.receipt_url,
        status=ManualPaymentStatus.PENDING
    )
    db.add(deposit)
    await db.commit()
    await db.refresh(deposit)
    return deposit


@router.get("/ledger/{wallet_type}")
async def get_wallet_ledger(wallet_type: WalletType, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.models.wallet import LedgerEntry
    # Get the specific wallet
    w_res = await db.execute(
        select(Wallet).where(Wallet.user_id == current_user.id, Wallet.wallet_type == wallet_type)
    )
    wallet = w_res.scalar_one_or_none()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
        
    # Get ledger entries
    l_res = await db.execute(
        select(LedgerEntry)
        .where(LedgerEntry.wallet_id == wallet.id)
        .order_by(LedgerEntry.created_at.desc())
        .limit(100)
    )
    entries = l_res.scalars().all()
    return [
        {
            "id": e.id,
            "transaction_type": e.transaction_type.value,
            "amount": float(e.amount),
            "balance_after": float(e.balance_after),
            "reference_type": e.reference_type.value if e.reference_type else None,
            "description": e.description,
            "created_at": e.created_at
        }
        for e in entries
    ]
