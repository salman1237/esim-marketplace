"""Payout accounts and withdrawal requests for the signed-in user.

Any user can withdraw (the client's rule), but only with KYC approved and a
saved payout account - both enforced in withdrawal_svc, and both reported by
GET /withdrawals/config so the page can explain itself before the user fills
anything in.
"""
import asyncio
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.withdrawal import BankAccount, PayoutAccountType, WithdrawalRequest, WithdrawalStatus
from app.services import withdrawal_svc
from app.services.withdrawal_settings_svc import get_withdrawal_settings

router = APIRouter(prefix="/withdrawals", tags=["Withdrawals"])

MAX_ACCOUNTS_PER_USER = 5


class BankAccountRequest(BaseModel):
    account_type: PayoutAccountType = PayoutAccountType.BANK
    bank_name: str = Field(..., min_length=2, max_length=120)
    holder_name: str = Field(..., min_length=2, max_length=160)
    account_number: str = Field(..., min_length=4, max_length=64)
    branch_name: Optional[str] = Field(None, max_length=160)
    routing_number: Optional[str] = Field(None, max_length=64)
    is_default: bool = False

    @field_validator("bank_name", "holder_name", "account_number", "branch_name", "routing_number")
    @classmethod
    def _trim(cls, v):
        return v.strip() if isinstance(v, str) else v


class WithdrawalCreateRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    bank_account_id: str
    note_category: Optional[str] = None
    note: Optional[str] = Field(None, max_length=500)


def _account_json(account: BankAccount) -> dict:
    return {
        "id": account.id,
        "account_type": account.account_type.value,
        "bank_name": account.bank_name,
        "holder_name": account.holder_name,
        "account_number": account.account_number,
        "branch_name": account.branch_name,
        "routing_number": account.routing_number,
        "is_default": account.is_default,
    }


async def _my_accounts(db: AsyncSession, user_id: str) -> List[BankAccount]:
    res = await db.execute(
        select(BankAccount)
        .where(BankAccount.user_id == user_id, BankAccount.is_deleted == False)  # noqa: E712
        .order_by(BankAccount.is_default.desc(), BankAccount.created_at.asc())
    )
    return list(res.scalars().all())


# --- Configuration & eligibility ---

@router.get("/config")
async def withdrawal_config(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cfg = await get_withdrawal_settings(db)
    status = await withdrawal_svc.eligibility(db, current_user)
    return {
        "min_amount": str(cfg["min_amount"]),
        "max_amount": str(cfg["max_amount"]),
        "fee_type": cfg["fee_type"],
        "fee_value": str(cfg["fee_value"]),
        "payout_currency": cfg["payout_currency"],
        "processing_time": cfg["processing_time"],
        "is_enabled": cfg["is_enabled"],
        "base_currency": app_settings.BASE_CURRENCY,
        "note_categories": list(withdrawal_svc.NOTE_CATEGORIES),
        "balance": str(status["balance"]),
        "can_withdraw": status["can_withdraw"],
        "blockers": status["blockers"],
        "kyc_verified": status["kyc_verified"],
        "kyc_status": status["kyc_status"],
        "account_count": status["account_count"],
    }


# --- Payout accounts ---

@router.get("/accounts")
async def list_accounts(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return [_account_json(a) for a in await _my_accounts(db, current_user.id)]


@router.post("/accounts")
async def add_account(
    req: BankAccountRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await _my_accounts(db, current_user.id)
    if len(existing) >= MAX_ACCOUNTS_PER_USER:
        raise HTTPException(status_code=400, detail=f"You can save up to {MAX_ACCOUNTS_PER_USER} payout accounts.")
    # Same number twice is a mistake, not a second account.
    if any(a.account_number == req.account_number and a.bank_name.lower() == req.bank_name.lower() for a in existing):
        raise HTTPException(status_code=400, detail="That account is already saved.")

    account = BankAccount(
        user_id=current_user.id,
        account_type=req.account_type,
        bank_name=req.bank_name,
        holder_name=req.holder_name,
        account_number=req.account_number,
        branch_name=req.branch_name or None,
        routing_number=req.routing_number or None,
        # The first account saved is the default whether or not it was asked for.
        is_default=req.is_default or not existing,
    )
    if account.is_default:
        for other in existing:
            other.is_default = False
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return _account_json(account)


@router.post("/accounts/{account_id}/default")
async def set_default_account(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    accounts = await _my_accounts(db, current_user.id)
    target = next((a for a in accounts if a.id == account_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Account not found")
    for account in accounts:
        account.is_default = account.id == account_id
    await db.commit()
    return {"status": "success"}


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    accounts = await _my_accounts(db, current_user.id)
    target = next((a for a in accounts if a.id == account_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Account not found")

    # A pending request is about to be paid to this account - removing it now
    # would leave an admin sending money to details nobody can re-check.
    pending = await db.execute(
        select(WithdrawalRequest).where(
            WithdrawalRequest.bank_account_id == account_id,
            WithdrawalRequest.status == WithdrawalStatus.PENDING,
        )
    )
    if pending.scalars().first():
        raise HTTPException(status_code=400, detail="This account has a withdrawal awaiting review. Cancel it first.")

    # Soft delete - paid withdrawals keep pointing at the row they were sent to.
    target.is_deleted = True
    target.is_default = False
    remaining = [a for a in accounts if a.id != account_id]
    if remaining and not any(a.is_default for a in remaining):
        remaining[0].is_default = True
    await db.commit()
    return {"status": "success"}


# --- Requests ---

@router.get("")
async def my_withdrawals(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(WithdrawalRequest)
        .where(WithdrawalRequest.user_id == current_user.id)
        .order_by(WithdrawalRequest.created_at.desc())
        .limit(limit)
    )
    return [withdrawal_svc.serialize(w) for w in res.scalars().all()]


@router.post("")
async def create_withdrawal(
    req: WithdrawalCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    accounts = await _my_accounts(db, current_user.id)
    account = next((a for a in accounts if a.id == req.bank_account_id), None)
    if not account:
        raise HTTPException(status_code=400, detail="Choose one of your saved payout accounts.")

    try:
        request = await withdrawal_svc.create_withdrawal(
            db, current_user, req.amount, account, req.note_category, req.note
        )
    except withdrawal_svc.WithdrawalError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    await db.commit()
    await db.refresh(request)

    cfg = await get_withdrawal_settings(db)
    asyncio.create_task(withdrawal_svc.send_email_background(
        "requested", current_user.email,
        withdrawal_svc.email_payload(request, current_user),
        {"processing_time": cfg["processing_time"]},
    ))
    return withdrawal_svc.serialize(request)


@router.get("/{withdrawal_id}")
async def get_withdrawal(
    withdrawal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(WithdrawalRequest).where(
            WithdrawalRequest.id == withdrawal_id, WithdrawalRequest.user_id == current_user.id
        )
    )
    request = res.scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Withdrawal not found")
    return withdrawal_svc.serialize(request)


@router.post("/{withdrawal_id}/cancel")
async def cancel_withdrawal(
    withdrawal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(WithdrawalRequest).where(
            WithdrawalRequest.id == withdrawal_id, WithdrawalRequest.user_id == current_user.id
        )
    )
    request = res.scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Withdrawal not found")
    try:
        await withdrawal_svc.cancel_withdrawal(db, request)
    except withdrawal_svc.WithdrawalError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(request)
    return withdrawal_svc.serialize(request)
