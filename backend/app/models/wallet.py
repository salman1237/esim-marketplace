import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Enum, ForeignKey, Numeric, Text, Index
from sqlalchemy.orm import relationship
from app.core.database import Base

class WalletType(str, enum.Enum):
    DEFAULT = "DEFAULT"
    REWARD = "REWARD"
    COMMISSION = "COMMISSION"

class LedgerTxType(str, enum.Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"

class LedgerRefType(str, enum.Enum):
    DEPOSIT_GATEWAY = "DEPOSIT_GATEWAY"
    DEPOSIT_MANUAL = "DEPOSIT_MANUAL"
    ORDER_PURCHASE = "ORDER_PURCHASE"
    COMMISSION_EARNED = "COMMISSION_EARNED"
    ADMIN_ADJUSTMENT = "ADMIN_ADJUSTMENT"
    REFUND = "REFUND"
    # A merchant moving earned commission into their main wallet (both legs).
    COMMISSION_TRANSFER = "COMMISSION_TRANSFER"
    # The balance leaves the wallet the moment a withdrawal is REQUESTED, not
    # when it is paid - otherwise a user can request a payout and spend the
    # same money on eSIMs before an admin gets to it. REVERSED puts it back
    # when a request is rejected or cancelled.
    WITHDRAWAL_HOLD = "WITHDRAWAL_HOLD"
    WITHDRAWAL_REVERSED = "WITHDRAWAL_REVERSED"
    # Referral promo credit, which only ever lands in the REWARD wallet:
    # spendable on eSIMs, never withdrawable. REVERSED claws it back when the
    # purchase that earned it is refunded.
    REWARD_EARNED = "REWARD_EARNED"
    REWARD_REVERSED = "REWARD_REVERSED"
    # An agent's cut of a sale made by one of their merchants, paid on top of
    # that merchant's own commission.
    AGENT_COMMISSION_EARNED = "AGENT_COMMISSION_EARNED"

class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    wallet_type = Column(Enum(WalletType), default=WalletType.DEFAULT, nullable=False)
    balance = Column(Numeric(18, 4), default=0.0000, nullable=False)
    currency = Column(String(3), default="EUR", nullable=False)
    is_frozen = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="wallets")
    ledger_entries = relationship("WalletLedgerEntry", back_populates="wallet", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_user_wallet_type", "user_id", "wallet_type", unique=True),
    )

class WalletLedgerEntry(Base):
    __tablename__ = "wallet_ledger_entries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    wallet_id = Column(String(36), ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False, index=True)
    tx_type = Column(Enum(LedgerTxType), nullable=False)
    amount = Column(Numeric(18, 4), nullable=False)
    balance_before = Column(Numeric(18, 4), nullable=False)
    balance_after = Column(Numeric(18, 4), nullable=False)
    reference_type = Column(Enum(LedgerRefType), nullable=False)
    reference_id = Column(String(100), nullable=True, index=True)
    idempotency_key = Column(String(100), unique=True, index=True, nullable=True)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    wallet = relationship("Wallet", back_populates="ledger_entries")
