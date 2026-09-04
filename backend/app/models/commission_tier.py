import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Numeric
from app.core.database import Base


class CommissionTier(Base):
    """Global volume-based commission tiers. When any tier rows exist,
    a merchant's effective commission rate is looked up here (by their
    cumulative completed reseller-order volume) instead of their flat
    MerchantProfile.commission_rate_pct — that flat rate remains the
    fallback for merchants below the lowest tier, or when no tiers are
    configured at all (the "default flat %" the plan also calls for)."""
    __tablename__ = "commission_tiers"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    min_volume_usd = Column(Numeric(18, 4), nullable=False, unique=True)
    rate_pct = Column(Numeric(5, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
