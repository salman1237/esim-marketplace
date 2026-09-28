"""Withdrawal requests: eligibility, the balance hold, approval and reversal.

The money leaves the user's DEFAULT wallet when the request is CREATED, not
when it is paid. Holding it any later would let someone request a payout and
then spend the same balance on eSIMs before an admin reviews it - the admin
would approve a payout the wallet can no longer cover.

Only the DEFAULT wallet is ever touched. Merchants move earned commission
into it first (POST /merchant/commission/transfer), and the REWARD wallet -
which Phase 3 will fill with referral promo credit - is deliberately out of
reach here, because reward credit is spendable but never withdrawable.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.timeutil import fmt_bd
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.kyc import KYCStatus, KYCSubmission
from app.models.user import User
from app.models.wallet import LedgerRefType, Wallet, WalletType
from app.models.withdrawal import (
    BankAccount,
    WithdrawalRequest,
    WithdrawalStatus,
    new_reference_no,
)
from app.services.currency_svc import CurrencyService
from app.services.email_svc import EmailService
from app.services.ledger_svc import LedgerService
from app.services.withdrawal_settings_svc import compute_fee, get_withdrawal_settings

logger = get_logger(__name__)

# What the money is for. Free text would make the finance report useless, so
# the reason is a fixed list the user picks from, with `note` for the detail.
NOTE_CATEGORIES = ("withdrawal", "commission", "refund", "renew", "business", "other")


class WithdrawalError(Exception):
    """A rule the user broke - surfaced as a 400 with this message."""


async def default_wallet(db: AsyncSession, user_id: str) -> Optional[Wallet]:
    res = await db.execute(
        select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.DEFAULT)
    )
    return res.scalar_one_or_none()


async def eligibility(db: AsyncSession, user: User) -> dict:
    """Why the user can or cannot withdraw. The withdraw page shows these
    reasons instead of a button that fails on submit."""
    cfg = await get_withdrawal_settings(db)

    kyc_res = await db.execute(select(KYCSubmission).where(KYCSubmission.user_id == user.id))
    kyc = kyc_res.scalar_one_or_none()
    kyc_status = kyc.status.value if kyc else None
    kyc_ok = bool(user.is_kyc_verified) or (kyc is not None and kyc.status == KYCStatus.APPROVED)

    acc_res = await db.execute(
        select(func.count(BankAccount.id)).where(
            BankAccount.user_id == user.id, BankAccount.is_deleted == False  # noqa: E712
        )
    )
    account_count = acc_res.scalar() or 0

    wallet = await default_wallet(db, user.id)
    balance = Decimal(str(wallet.balance)) if wallet else Decimal("0")

    blockers = []
    if not cfg["is_enabled"]:
        blockers.append("Withdrawals are temporarily unavailable.")
    if not kyc_ok:
        blockers.append(
            "Your KYC verification is still pending review." if kyc_status == "PENDING"
            else "Complete KYC verification first."
        )
    if account_count == 0:
        blockers.append("Add a bank or mobile wallet account to receive the payout.")
    if balance < cfg["min_amount"]:
        blockers.append(f"Your balance is below the minimum withdrawal of {cfg['min_amount']}.")

    return {
        "can_withdraw": not blockers,
        "blockers": blockers,
        "kyc_verified": kyc_ok,
        "kyc_status": kyc_status,
        "account_count": account_count,
        "balance": balance,
    }


def quote(cfg: dict, amount: Decimal) -> dict:
    fee = compute_fee(cfg, amount)
    return {"amount": amount, "fee_amount": fee, "net_amount": amount - fee}


async def create_withdrawal(
    db: AsyncSession,
    user: User,
    amount: Decimal,
    bank_account: BankAccount,
    note_category: Optional[str],
    note: Optional[str],
) -> WithdrawalRequest:
    """Validates, holds the balance and records the request. Caller commits."""
    cfg = await get_withdrawal_settings(db)
    if not cfg["is_enabled"]:
        raise WithdrawalError("Withdrawals are temporarily unavailable.")

    amount = Decimal(str(amount)).quantize(Decimal("0.0001"))
    if amount <= 0:
        raise WithdrawalError("Enter an amount greater than zero.")
    if amount < cfg["min_amount"]:
        raise WithdrawalError(f"The minimum withdrawal is {cfg['min_amount']}.")
    if amount > cfg["max_amount"]:
        raise WithdrawalError(f"The maximum withdrawal is {cfg['max_amount']}.")

    status = await eligibility(db, user)
    if not status["kyc_verified"]:
        raise WithdrawalError("Complete KYC verification before withdrawing.")

    category = (note_category or "withdrawal").lower()
    if category not in NOTE_CATEGORIES:
        raise WithdrawalError("Choose one of the listed reasons.")

    wallet = await default_wallet(db, user.id)
    if not wallet:
        raise WithdrawalError("No wallet found for this account.")
    if wallet.is_frozen:
        raise WithdrawalError("This wallet is frozen. Please contact support.")

    figures = quote(cfg, amount)
    request = WithdrawalRequest(
        reference_no=new_reference_no(),
        user_id=user.id,
        amount=figures["amount"],
        fee_amount=figures["fee_amount"],
        net_amount=figures["net_amount"],
        note_category=category,
        note=(note or None),
        bank_account_id=bank_account.id,
        account_snapshot=bank_account.snapshot(),
        status=WithdrawalStatus.PENDING,
        payout_currency=cfg["payout_currency"],
    )
    db.add(request)
    await db.flush()

    # The hold. LedgerService.debit itself refuses to overdraw (and locks the
    # wallet row FOR UPDATE), so two requests racing for the same balance
    # cannot both succeed.
    try:
        await LedgerService.debit(
            db,
            wallet.id,
            figures["amount"],
            LedgerRefType.WITHDRAWAL_HOLD,
            ref_id=request.id,
            description=f"Withdrawal requested ({request.reference_no})",
            idempotency_key=f"withdrawal-hold-{request.id}",
        )
    except ValueError:
        raise WithdrawalError("Your balance is lower than the amount requested.")

    return request


async def approve_withdrawal(
    db: AsyncSession,
    request: WithdrawalRequest,
    admin: User,
    payment_reference: str,
    proof_filename: Optional[str],
) -> WithdrawalRequest:
    """Marks a request paid and freezes the conversion used. No ledger entry:
    the balance already left the wallet when the request was created."""
    if request.status != WithdrawalStatus.PENDING:
        raise WithdrawalError(f"This request is already {request.status.value.lower()}.")
    if not payment_reference.strip():
        raise WithdrawalError("A payment reference is required.")

    rate = await CurrencyService.get_effective_rate(db, request.payout_currency)
    net = Decimal(str(request.net_amount))

    request.status = WithdrawalStatus.PAID
    request.conversion_rate = Decimal(str(rate)).quantize(Decimal("0.000001"))
    request.payout_amount = (net * Decimal(str(rate))).quantize(Decimal("0.0001"))
    request.payment_reference = payment_reference.strip()
    request.proof_filename = proof_filename
    request.reviewed_by_id = admin.id
    request.reviewed_at = datetime.now(timezone.utc)
    return request


async def _return_held_balance(db: AsyncSession, request: WithdrawalRequest, reason: str) -> None:
    wallet = await default_wallet(db, request.user_id)
    if not wallet:
        # Can only happen if the account was deleted; nothing to credit back.
        return
    await LedgerService.credit(
        db,
        wallet.id,
        Decimal(str(request.amount)),
        LedgerRefType.WITHDRAWAL_REVERSED,
        ref_id=request.id,
        description=f"{reason} ({request.reference_no})",
        idempotency_key=f"withdrawal-reversed-{request.id}",
    )


async def reject_withdrawal(
    db: AsyncSession, request: WithdrawalRequest, admin: User, reason: Optional[str]
) -> WithdrawalRequest:
    if request.status != WithdrawalStatus.PENDING:
        raise WithdrawalError(f"This request is already {request.status.value.lower()}.")
    request.status = WithdrawalStatus.REJECTED
    request.rejection_reason = reason
    request.reviewed_by_id = admin.id
    request.reviewed_at = datetime.now(timezone.utc)
    await _return_held_balance(db, request, "Withdrawal rejected")
    return request


async def cancel_withdrawal(db: AsyncSession, request: WithdrawalRequest) -> WithdrawalRequest:
    if request.status != WithdrawalStatus.PENDING:
        raise WithdrawalError(f"This request is already {request.status.value.lower()}.")
    request.status = WithdrawalStatus.CANCELLED
    await _return_held_balance(db, request, "Withdrawal cancelled")
    return request


async def send_email_background(kind: str, to_email: str, payload: dict, extra: dict) -> None:
    """Fire-and-forget notification, used via asyncio.create_task by both the
    user router and the admin review endpoints. Its own DB session: the
    request's is closed by the time this runs, and the payload is already
    plain values so no ORM object is touched here."""
    async with AsyncSessionLocal() as bg_db:
        try:
            if kind == "requested":
                await EmailService.send_withdrawal_requested(bg_db, to_email, payload, extra["processing_time"])
            elif kind == "paid":
                await EmailService.send_withdrawal_paid(
                    bg_db, to_email, payload, extra["processing_time"], for_admin=extra.get("for_admin", False)
                )
            elif kind == "rejected":
                await EmailService.send_withdrawal_rejected(bg_db, to_email, payload, extra.get("reason"))
        except Exception as e:
            logger.warning("withdrawal_email_background_task_failed", kind=kind, to=to_email, error=str(e))


def account_line(snapshot: dict | None) -> str:
    """"bKash · 01712345678 (Rahim Uddin)" - one readable line for the
    receipt, the email and the admin queue."""
    snap = snapshot or {}
    parts = [p for p in (snap.get("bank_name"), snap.get("account_number")) if p]
    line = " · ".join(parts) or "Saved account"
    holder = snap.get("holder_name")
    return f"{line} ({holder})" if holder else line


def email_payload(request: WithdrawalRequest, user: User) -> dict:
    """Plain values for the email templates - built before the response is
    returned, because the background sender uses its own DB session and must
    not touch these ORM objects."""
    def when(value):
        return fmt_bd(value)

    return {
        "id": request.id,
        "reference_no": request.reference_no,
        "amount": str(request.amount),
        "fee_amount": str(request.fee_amount),
        "net_amount": str(request.net_amount),
        "base_currency": settings.BASE_CURRENCY,
        "payout_currency": request.payout_currency,
        "conversion_rate": str(request.conversion_rate) if request.conversion_rate is not None else None,
        "payout_amount": str(request.payout_amount) if request.payout_amount is not None else None,
        "payment_reference": request.payment_reference,
        "account_line": account_line(request.account_snapshot),
        "created_display": when(request.created_at),
        "paid_display": when(request.reviewed_at),
        "username": user.username,
        "user_email": user.email,
    }


def serialize(request: WithdrawalRequest, include_user: Optional[User] = None) -> dict:
    data = {
        "id": request.id,
        "reference_no": request.reference_no,
        "amount": str(request.amount),
        "fee_amount": str(request.fee_amount),
        "net_amount": str(request.net_amount),
        "note_category": request.note_category,
        "note": request.note,
        "account": request.account_snapshot or {},
        "account_line": account_line(request.account_snapshot),
        "status": request.status.value,
        "payout_currency": request.payout_currency,
        "conversion_rate": str(request.conversion_rate) if request.conversion_rate is not None else None,
        "payout_amount": str(request.payout_amount) if request.payout_amount is not None else None,
        "payment_reference": request.payment_reference,
        "has_proof": bool(request.proof_filename),
        "rejection_reason": request.rejection_reason,
        "reviewed_at": request.reviewed_at,
        "created_at": request.created_at,
    }
    if include_user is not None:
        data["user"] = {
            "id": include_user.id,
            "username": include_user.username,
            "email": include_user.email,
            "role": include_user.role.value,
        }
    return data
