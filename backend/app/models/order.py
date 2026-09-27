import uuid
from datetime import datetime, timezone
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
    buyer_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    beneficiary_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)
    total_amount = Column(Numeric(18, 4), nullable=False)
    # Supplier cost of the product at the moment of purchase, so the sales
    # report's profit stays true after later cost or profit % changes.
    cost_amount = Column(Numeric(18, 4), nullable=True)
    currency = Column(String(10), default="EUR")
    # A discount code applied at checkout. total_amount above is already net
    # of it - this is kept so the sales report can separate "we sold cheaper"
    # from "the product got cheaper", and so commission (calculated on
    # total_amount) is visibly on the discounted price.
    discount_code_id = Column(String(36), ForeignKey("discount_codes.id", ondelete="SET NULL"), nullable=True)
    # server_default so the NOT NULL holds for the orders that already exist.
    discount_amount = Column(Numeric(18, 4), default=0.0000, server_default="0", nullable=False)
    # How much of total_amount came out of the REWARD (promo credit) wallet.
    # Stored because a refund has to go back to the wallets that actually
    # paid - crediting a promo-funded order wholly to the main wallet would
    # turn non-withdrawable credit into withdrawable cash.
    reward_amount_used = Column(Numeric(18, 4), default=0.0000, server_default="0", nullable=False)
    payment_method = Column(Enum(PaymentMethod), nullable=False)
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING, nullable=False)
    is_reseller_order = Column(Boolean, default=False)
    reseller_commission_amount = Column(Numeric(18, 4), default=0.0000)
    # The agent behind the selling merchant, and what they earned. Snapshotted
    # onto the order so re-pointing a merchant to a different agent later
    # never rewrites who was paid for a past sale.
    agent_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    agent_commission_amount = Column(Numeric(18, 4), default=0.0000, server_default="0", nullable=False)
    external_trx_id = Column(String(100), nullable=True)
    # Partner Reseller API only — the partner's own identifier for this
    # order, echoed back in GET /partner/orders/{id} and the webhook
    # payload so they can reconcile without storing our order_id first.
    partner_customer_reference = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    buyer = relationship("User", foreign_keys=[buyer_id])
    beneficiary = relationship("User", foreign_keys=[beneficiary_id])
    product = relationship("Product", back_populates="orders")
    esim_profile = relationship("ESIMProfile", uselist=False, back_populates="order")

class ESIMStatus(str, enum.Enum):
    ALLOCATED = "ALLOCATED"
    RELEASED = "RELEASED"
    INSTALLED = "INSTALLED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"

class ESIMProfile(Base):
    __tablename__ = "esim_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String(36), ForeignKey("orders.id"), unique=True, nullable=False)
    beneficiary_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    iccid = Column(String(30), unique=True, index=True, nullable=True)
    lpa_string = Column(Text, nullable=True)
    qr_code_data = Column(Text, nullable=True)
    qr_image_url = Column(String(500), nullable=True)
    smdp_address = Column(String(255), nullable=True)
    matching_id = Column(String(100), nullable=True)
    supplier_reference = Column(String(100), nullable=True)
    status = Column(Enum(ESIMStatus), default=ESIMStatus.ALLOCATED, nullable=False)
    is_mock_fallback = Column(Boolean, default=False)
    # Validity runs from FIRST ACTIVATION, not from purchase — confirmed
    # against VivaPe's own status page and their usage API. Both stay NULL
    # until the customer installs the profile and telemetry tells us when
    # the clock actually started; computing them at purchase time made an
    # un-activated eSIM look expired while it was still perfectly usable.
    activated_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    order = relationship("Order", back_populates="esim_profile")
    telemetry = relationship("ESIMTelemetry", uselist=False, back_populates="esim_profile", cascade="all, delete-orphan")
