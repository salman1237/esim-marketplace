import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Enum, ForeignKey, Numeric, Text
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum

class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class PaymentMethod(str, enum.Enum):
    WALLET = "WALLET"
    SHURJOPAY = "SHURJOPAY"
    MANUAL_BANK = "MANUAL_BANK"

class Order(Base):
    __tablename__ = "orders"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_no = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)
    country_iso2 = Column(String(2), nullable=False)
    quantity = Column(Numeric(10, 0), default=1)
    unit_price = Column(Numeric(18, 4), nullable=False)
    total_amount = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(10), default="USD")
    payment_method = Column(Enum(PaymentMethod), nullable=False)
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING, nullable=False)
    is_reseller_order = Column(Boolean, default=False)
    merchant_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    reseller_commission = Column(Numeric(18, 4), default=0.0000)
    external_trx_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="orders", foreign_keys=[user_id])
    merchant = relationship("User", foreign_keys=[merchant_id])
    product = relationship("Product", back_populates="orders")
    esim_profile = relationship("ESIMProfile", uselist=False, back_populates="order")

class ESIMStatus(str, enum.Enum):
    ALLOCATED = "ALLOCATED"
    INSTALLED = "INSTALLED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"

class ESIMProfile(Base):
    __tablename__ = "esim_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String(36), ForeignKey("orders.id"), unique=True, nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    iccid = Column(String(30), unique=True, index=True, nullable=True)
    lpa_string = Column(Text, nullable=True)
    qr_code_data = Column(Text, nullable=True)
    qr_image_url = Column(String(500), nullable=True)
    supplier_reference = Column(String(100), nullable=True)
    status = Column(Enum(ESIMStatus), default=ESIMStatus.ALLOCATED, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    order = relationship("Order", back_populates="esim_profile")
