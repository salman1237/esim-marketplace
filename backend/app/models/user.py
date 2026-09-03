import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Enum, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.core.database import Base

class UserRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    MERCHANT = "MERCHANT"
    USER = "USER"

class UserStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    PENDING = "PENDING"
    SUSPENDED = "SUSPENDED"

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.USER, nullable=False, index=True)
    status = Column(Enum(UserStatus), default=UserStatus.ACTIVE, nullable=False)
    phone = Column(String(50), nullable=True)
    full_name = Column(String(150), nullable=True)
    
    # KYC
    nid_number = Column(String(50), nullable=True)
    nid_photo_url = Column(String(255), nullable=True)
    is_kyc_verified = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    wallets = relationship("Wallet", back_populates="user", cascade="all, delete-orphan")
    merchant_profile = relationship("MerchantProfile", back_populates="user", uselist=False)
    placed_orders = relationship("Order", back_populates="buyer", foreign_keys="Order.buyer_id")
    beneficiary_orders = relationship("Order", back_populates="beneficiary", foreign_keys="Order.beneficiary_id")
