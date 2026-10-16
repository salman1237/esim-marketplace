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
    # Recruits merchants and earns on what they sell. Only for accounts that
    # are *just* agents - agent capability itself comes from an approved
    # AgentProfile, so a MERCHANT can be an agent too (see models/agent.py).
    AGENT = "AGENT"
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
    # What this account is shown prices in. NOT what anything is stored in -
    # that is always the base currency (EUR). New accounts start on taka
    # because the home market is Bangladesh; anyone can switch, and the
    # choice then follows them between devices.
    preferred_currency = Column(String(10), default="BDT")
    preferred_language = Column(String(10), default="en")
    is_kyc_verified = Column(Boolean, default=False)
    # Referrals. referral_code is this user's own code to share; referred_by_id
    # is who brought them in, set once at sign-up and never changed - a reward
    # that could be re-pointed later is a reward that can be paid twice.
    referral_code = Column(String(16), unique=True, index=True, nullable=True)
    referred_by_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
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
