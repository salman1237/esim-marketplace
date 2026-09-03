import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Enum, ForeignKey, Numeric, Text
from sqlalchemy.orm import relationship
from app.core.database import Base

class MerchantStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"

class MerchantProfile(Base):
    __tablename__ = "merchant_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    business_name = Column(String(150), nullable=False)
    trade_license = Column(String(100), nullable=True)
    contact_phone = Column(String(50), nullable=False)
    website = Column(String(255), nullable=True)
    status = Column(Enum(MerchantStatus), default=MerchantStatus.PENDING, nullable=False)
    commission_rate_pct = Column(Numeric(5, 2), default=5.00)  # e.g. 5.00%
    
    reviewed_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    review_notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="merchant_profile", foreign_keys=[user_id])
