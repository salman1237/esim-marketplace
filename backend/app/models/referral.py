"""Referral rewards.

One row per (referred user, event), enforced by a unique constraint, so an
event can only ever pay once no matter how many times its trigger fires -
registration retried, an order re-fulfilled, a merchant re-approved.

Both sides of a reward live on the same row (referrer_amount and
referred_amount) because they are granted and reversed together: they are one
decision by the admin, not two independent payments.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base


class ReferralEvent(str, enum.Enum):
    JOINING = "JOINING"              # the referred user signed up
    FIRST_PURCHASE = "FIRST_PURCHASE"  # their first order was delivered
    NEW_MERCHANT = "NEW_MERCHANT"    # they were approved as a partner


class ReferralRewardStatus(str, enum.Enum):
    GRANTED = "GRANTED"
    REVERSED = "REVERSED"


class ReferralReward(Base):
    __tablename__ = "referral_rewards"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    referrer_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    referred_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    event = Column(Enum(ReferralEvent), nullable=False)

    # Both in the base currency, as promo credit. Either can be zero if the
    # admin only rewards one side of this event.
    referrer_amount = Column(Numeric(18, 4), default=0, nullable=False)
    referred_amount = Column(Numeric(18, 4), default=0, nullable=False)

    # Set for FIRST_PURCHASE, so the reward can be found and reversed if that
    # order is refunded.
    order_id = Column(String(36), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)

    status = Column(Enum(ReferralRewardStatus), default=ReferralRewardStatus.GRANTED, nullable=False, index=True)
    reversal_reason = Column(Text, nullable=True)
    reversed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    referrer = relationship("User", foreign_keys=[referrer_id])
    referred = relationship("User", foreign_keys=[referred_id])

    __table_args__ = (
        UniqueConstraint("referred_id", "event", name="uq_referral_reward_once_per_event"),
    )
