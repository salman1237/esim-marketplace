import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Enum, ForeignKey, Numeric, Text, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base

class ManualPaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

class ManualPaymentRequest(Base):
    __tablename__ = "manual_payment_requests"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(3), default="BDT", nullable=False)
    bank_name = Column(String(100), nullable=False)
    transaction_id = Column(String(100), nullable=False, index=True)
    receipt_url = Column(String(255), nullable=True)
    status = Column(Enum(ManualPaymentStatus), default=ManualPaymentStatus.PENDING, nullable=False)
    reviewed_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    review_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class PaymentLog(Base):
    __tablename__ = "payment_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    gateway = Column(String(50), nullable=False, index=True)
    order_id = Column(String(36), nullable=True, index=True)
    tx_id = Column(String(100), nullable=True, index=True)
    endpoint = Column(String(255), nullable=True)
    request_payload = Column(JSON, nullable=True)
    response_payload = Column(JSON, nullable=True)
    status_code = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
