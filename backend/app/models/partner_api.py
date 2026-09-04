import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from app.core.database import Base


class ApiKey(Base):
    """A partner's credential for the Reseller API (app/api/v1/partner.py).
    Issued explicitly by a Super Admin per approved merchant - not granted
    automatically on merchant approval, matching how every other
    sensitive grant on this platform works.
    """
    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    merchant_id = Column(String(36), ForeignKey("merchant_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    # First 8 chars of the raw key (e.g. "esim_liv") - shown in the admin
    # UI so a key can be identified without ever re-displaying the secret.
    key_prefix = Column(String(16), nullable=False)
    # SHA-256 of the full raw key - same reasoning as PasswordResetToken:
    # a DB read should never hand out a live, usable credential.
    key_hash = Column(String(64), unique=True, index=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
