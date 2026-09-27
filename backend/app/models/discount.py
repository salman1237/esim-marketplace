"""Discount codes and their redemptions.

Two things are deliberately NOT stored here:

1. A `times_used` counter. Usage is counted from the redemptions joined to
   their orders, so a failed or cancelled order never eats a use. A counter
   would have to be corrected on every refund path and would drift.
2. The list price of a discounted order. Order.total_amount is what the
   customer was actually charged and Order.discount_amount is what came off,
   so the list price is their sum - one source of truth for profit and for
   commission, which is calculated on the discounted amount.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class DiscountType(str, enum.Enum):
    PERCENT = "PERCENT"
    FIXED = "FIXED"


class DiscountScope(str, enum.Enum):
    ALL = "ALL"
    COUNTRY = "COUNTRY"
    PRODUCT = "PRODUCT"


class DiscountCode(Base):
    __tablename__ = "discount_codes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Stored upper-case; matched case-insensitively at checkout.
    code = Column(String(40), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)

    discount_type = Column(Enum(DiscountType), default=DiscountType.PERCENT, nullable=False)
    value = Column(Numeric(18, 4), nullable=False)
    # Ceiling for a percentage code, so "50% off" can't give away €40 on a
    # large bundle. Ignored for a fixed-amount code.
    max_discount_amount = Column(Numeric(18, 4), nullable=True)
    min_order_amount = Column(Numeric(18, 4), nullable=True)

    starts_at = Column(DateTime(timezone=True), nullable=True)
    ends_at = Column(DateTime(timezone=True), nullable=True)

    max_uses = Column(Integer, nullable=True)          # null = unlimited
    max_uses_per_user = Column(Integer, nullable=True)  # null = unlimited
    first_order_only = Column(Boolean, default=False, nullable=False)

    scope = Column(Enum(DiscountScope), default=DiscountScope.ALL, nullable=False)
    country_id = Column(Integer, ForeignKey("countries.id", ondelete="SET NULL"), nullable=True)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    created_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    country = relationship("Country", foreign_keys=[country_id])
    product = relationship("Product", foreign_keys=[product_id])


class DiscountRedemption(Base):
    __tablename__ = "discount_redemptions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    discount_code_id = Column(String(36), ForeignKey("discount_codes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(String(36), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    discount_amount = Column(Numeric(18, 4), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    code = relationship("DiscountCode", foreign_keys=[discount_code_id])

    __table_args__ = (
        # One code per order, enforced by the database rather than by whoever
        # remembers to check it at the next call site.
        UniqueConstraint("order_id", name="uq_discount_redemption_order"),
    )
