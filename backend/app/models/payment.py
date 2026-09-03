import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Enum, ForeignKey, Numeric, Text, Integer, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum

class ManualPaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

class ManualPaymentRequest(Base):
    __tablename__ = "manual_payment_requests"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    amount = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(10), default="BDT")
    bank_name = Column(String(100), nullable=False)
    transaction_id = Column(String(100), unique=True, nullable=False)
    receipt_url = Column(String(500), nullable=True)
    status = Column(Enum(ManualPaymentStatus), default=ManualPaymentStatus.PENDING, nullable=False)
    admin_notes = Column(Text, nullable=True)
    reviewed_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by_id])

class PaymentLog(Base):
    __tablename__ = "payment_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    gateway = Column(String(50), nullable=False)
    order_id = Column(String(100), nullable=True, index=True)
    endpoint = Column(String(255), nullable=False)
    request_payload = Column(JSON, nullable=True)
    response_payload = Column(JSON, nullable=True)
    status_code = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
