"""An agent's request to change the bonus they take from a merchant.

The live value is MerchantProfile.agent_bonus_pct; this table is the approval
queue in front of it. Nothing an agent submits changes a commission rate until
an admin approves it, which is the client's rule - so the request carries both
the current and the requested percentage, and approval is the only thing that
writes to the merchant profile.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base

# The client's range. A deduction is also capped at the merchant's own rate at
# payout time, so a bonus can never push a merchant's commission negative.
MAX_AGENT_BONUS_PCT = "10.00"


class AgentBonusStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AgentBonusRequest(Base):
    __tablename__ = "agent_bonus_requests"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    merchant_profile_id = Column(
        String(36), ForeignKey("merchant_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Snapshotted so the queue shows what was actually being asked for, even if
    # the live value moves while the request is waiting.
    current_pct = Column(Numeric(5, 2), nullable=False)
    requested_pct = Column(Numeric(5, 2), nullable=False)
    # The merchant's commission rate at request time, so an admin can see the
    # resulting net without recomputing it.
    merchant_rate_pct = Column(Numeric(5, 2), nullable=True)

    reason = Column(Text, nullable=True)
    status = Column(Enum(AgentBonusStatus), default=AgentBonusStatus.PENDING, nullable=False, index=True)
    decision_note = Column(Text, nullable=True)
    reviewed_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    agent = relationship("User", foreign_keys=[agent_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by_id])
    merchant = relationship("MerchantProfile", foreign_keys=[merchant_profile_id])
