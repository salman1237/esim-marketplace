import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Enum, ForeignKey, Text, false
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum

class UserRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    MERCHANT = "MERCHANT"
    USER = "USER"

class UserStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    role = Column(Enum(UserRole), default=UserRole.USER, nullable=False)
    status = Column(Enum(UserStatus), default=UserStatus.ACTIVE, nullable=False)
    preferred_currency = Column(String(10), default="EUR")
    preferred_language = Column(String(10), default="en")
    is_kyc_verified = Column(Boolean, default=False)
    # Sign in with Google. google_sub is Google's stable account id (the ID
    # token's `sub`) - matched on first, since an email address can change.
    google_sub = Column(String(255), unique=True, index=True, nullable=True)
    avatar_url = Column(String(1024), nullable=True)
    email_verified = Column(Boolean, default=False, server_default=false(), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    merchant_profile = relationship("MerchantProfile", uselist=False, back_populates="user", foreign_keys="MerchantProfile.user_id")
    wallets = relationship("Wallet", back_populates="user", cascade="all, delete-orphan")
