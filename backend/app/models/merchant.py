import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Enum, ForeignKey, Numeric, Text
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum

class MerchantStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"

class MerchantProfile(Base):
    __tablename__ = "merchant_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    business_name = Column(String(255), nullable=False)
    trade_license = Column(String(100), nullable=True)
    tax_id = Column(String(100), nullable=True)
    nid_passport_no = Column(String(100), nullable=True)
    document_urls = Column(Text, nullable=True)
    contact_phone = Column(String(50), nullable=False)
    website = Column(String(255), nullable=True)
    commission_rate_pct = Column(Numeric(5, 2), default=5.00, nullable=False)
    # Partner Reseller API (see app/models/partner_api.py) - null until the
    # merchant/admin configures a webhook receiver for async order events.
    webhook_url = Column(String(500), nullable=True)
    webhook_secret = Column(String(64), nullable=True)
    status = Column(Enum(MerchantStatus), default=MerchantStatus.PENDING, nullable=False)
    rejection_reason = Column(Text, nullable=True)
    reviewed_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="merchant_profile", foreign_keys=[user_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by_id])
