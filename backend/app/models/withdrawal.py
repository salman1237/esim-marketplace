"""Payout destinations and withdrawal requests.

Two rules are encoded in the columns rather than left to the API:

1. The bank details are SNAPSHOTTED onto each request (`account_snapshot`).
   A payout receipt has to keep saying where the money actually went, even
   after the user edits or deletes that account afterwards.
2. The conversion rate and the payout amount are stored on the request,
   filled in when an admin approves it. The client's rule is "converted at
   approval time", so the rate can't be recomputed later - the receipt, the
   email and the finance report all have to agree forever.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, JSON, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class PayoutAccountType(str, enum.Enum):
    BANK = "BANK"
    MOBILE = "MOBILE"  # bKash / Nagad / Rocket


class WithdrawalStatus(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"  # withdrawn by the user while still pending


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    account_type = Column(Enum(PayoutAccountType), default=PayoutAccountType.BANK, nullable=False)
    # For MOBILE this is the wallet brand ("bKash"), for BANK the bank's name.
    bank_name = Column(String(120), nullable=False)
    holder_name = Column(String(160), nullable=False)
    account_number = Column(String(64), nullable=False)
    branch_name = Column(String(160), nullable=True)
    routing_number = Column(String(64), nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)
    # Soft delete: a paid withdrawal still points at the row it was sent to.
    is_deleted = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", foreign_keys=[user_id])

    def snapshot(self) -> dict:
        return {
            "account_type": self.account_type.value,
            "bank_name": self.bank_name,
            "holder_name": self.holder_name,
            "account_number": self.account_number,
            "branch_name": self.branch_name,
            "routing_number": self.routing_number,
        }


class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_requests"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Human-readable and quotable in an email or a bank memo.
    reference_no = Column(String(32), unique=True, nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # All three in the base currency (EUR). net = amount - fee is what the
    # user actually receives; `amount` is what left their wallet.
    amount = Column(Numeric(18, 4), nullable=False)
    fee_amount = Column(Numeric(18, 4), default=0, nullable=False)
    net_amount = Column(Numeric(18, 4), nullable=False)

    # Why the user is withdrawing - the client asked for this on the request
    # so finance can tell a commission payout from a refund.
    note_category = Column(String(40), nullable=True)
    note = Column(Text, nullable=True)

    bank_account_id = Column(String(36), ForeignKey("bank_accounts.id", ondelete="SET NULL"), nullable=True)
    account_snapshot = Column(JSON, nullable=False)

    status = Column(Enum(WithdrawalStatus), default=WithdrawalStatus.PENDING, nullable=False, index=True)

    payout_currency = Column(String(3), default="BDT", nullable=False)
    # Both filled at approval, never before - see the module docstring.
    conversion_rate = Column(Numeric(18, 6), nullable=True)
    payout_amount = Column(Numeric(18, 4), nullable=True)

    payment_reference = Column(String(120), nullable=True)
    # Filename only, resolved against settings.WITHDRAWAL_UPLOADS_DIR and
    # served through an authenticated admin endpoint - same treatment as KYC
    # documents, since a payout screenshot shows account details.
    proof_filename = Column(String(255), nullable=True)

    rejection_reason = Column(Text, nullable=True)
    reviewed_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", foreign_keys=[user_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by_id])
    bank_account = relationship("BankAccount", foreign_keys=[bank_account_id])


def new_reference_no() -> str:
    return f"WDR-{datetime.now(timezone.utc).strftime('%y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
