import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Enum, ForeignKey, Numeric, Text
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum

class ManualPaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

PaymentRequestStatus = ManualPaymentStatus
class _OldPaymentRequestStatus(str, enum.Enum):
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
    deposit_slip_url = Column(String(500), nullable=True)
    status = Column(Enum(PaymentRequestStatus), default=PaymentRequestStatus.PENDING, nullable=False)
    admin_notes = Column(Text, nullable=True)
    approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])
    approver = relationship("User", foreign_keys=[approved_by])

class PaymentLog(Base):
    __tablename__ = "payment_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    gateway = Column(String(50), nullable=False)
    transaction_id = Column(String(100), nullable=True, index=True)
    order_id = Column(String(36), nullable=True, index=True)
    status = Column(String(50), nullable=False)
    amount = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(10), nullable=False)
    raw_callback_payload = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
