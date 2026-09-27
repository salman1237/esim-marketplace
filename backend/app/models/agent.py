"""Agents: people who recruit merchants and earn on what those merchants sell.

Agent capability lives on this profile, not on User.role. The client's rule is
that an agent can also be a merchant, and a single role column can't express
both - so the agent portal is gated on having an APPROVED AgentProfile, which
a MERCHANT-role account can hold just as easily as an AGENT-role one. The
AGENT role exists for accounts that are only agents, so admin listings and
navigation can tell them apart.
"""
import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base

# The client's default: 2% of the price of everything their merchants sell.
DEFAULT_AGENT_COMMISSION_PCT = "2.00"


class AgentStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class AgentProfile(Base):
    __tablename__ = "agent_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    company_name = Column(String(255), nullable=False)
    contact_phone = Column(String(50), nullable=False)
    # Shared with merchants, who enter it on their B2B application.
    agent_code = Column(String(16), unique=True, index=True, nullable=False)
    # Percentage of the product PRICE, not of our margin - the client chose
    # price, and it is paid on top of the merchant's own commission.
    commission_rate_pct = Column(Numeric(5, 2), default=Decimal(DEFAULT_AGENT_COMMISSION_PCT), nullable=False)
    status = Column(Enum(AgentStatus), default=AgentStatus.PENDING, nullable=False, index=True)
    rejection_reason = Column(Text, nullable=True)
    reviewed_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", foreign_keys=[user_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by_id])
