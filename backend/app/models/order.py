import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Enum, ForeignKey, Numeric, Text
from sqlalchemy.orm import relationship
from app.core.database import Base

class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"

class PaymentMethod(str, enum.Enum):
    WALLET = "WALLET"
    SHURJOPAY = "SHURJOPAY"
    MANUAL = "MANUAL"

class Order(Base):
    __tablename__ = "orders"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_no = Column(String(50), unique=True, index=True, nullable=False)
    buyer_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    beneficiary_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)
    total_amount = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    payment_method = Column(Enum(PaymentMethod), nullable=False)
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING, nullable=False, index=True)
    
    # Reseller / Admin Tracking
    is_reseller_order = Column(Boolean, default=False)
    reseller_commission_amount = Column(Numeric(18, 4), default=0.0000)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    buyer = relationship("User", back_populates="placed_orders", foreign_keys=[buyer_id])
    beneficiary = relationship("User", back_populates="beneficiary_orders", foreign_keys=[beneficiary_id])
    product = relationship("Product", back_populates="orders")
    esim_profile = relationship("ESIMProfile", back_populates="order", uselist=False)

class ESIMStatus(str, enum.Enum):
    PENDING = "PENDING"
    RELEASED = "RELEASED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"

class ESIMProfile(Base):
    __tablename__ = "esim_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String(36), ForeignKey("orders.id", ondelete="CASCADE"), unique=True, nullable=False)
    beneficiary_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    iccid = Column(String(50), index=True, nullable=True)
    lpa_string = Column(Text, nullable=True)
    qr_code_data = Column(Text, nullable=True)
    smdp_address = Column(String(150), nullable=True)
    matching_id = Column(String(100), nullable=True)
    status = Column(Enum(ESIMStatus), default=ESIMStatus.RELEASED, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    order = relationship("Order", back_populates="esim_profile")
