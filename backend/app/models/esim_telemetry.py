"""Cached live telemetry for a delivered eSIM.

Cached rather than fetched per request for three reasons: the status page must
still render something when VivaPe is unreachable, a forced refresh makes
VivaPe poll the upstream carrier (so it must not run on every page view), and
support needs to see the last known state of an eSIM whose supplier lookup is
currently failing - which is exactly when someone is asking about it.

`fetch_error` is therefore kept alongside the data, not instead of it: a failed
refresh leaves the previous snapshot intact and records why it is stale.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class ESIMTelemetry(Base):
    __tablename__ = "esim_telemetry"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    esim_profile_id = Column(
        String(36), ForeignKey("esim_profiles.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )

    data_used_bytes = Column(BigInteger, default=0, nullable=False)
    data_used_mb = Column(Numeric(18, 2), default=0, nullable=False)

    # VivaPe's own status code and label. Only 0 (Unknown, never installed)
    # and 1 (Active) have been observed, so the text is stored and shown as
    # given rather than mapped through a guessed lookup table.
    status_code = Column(Integer, nullable=True)
    status_text = Column(String(60), nullable=True)

    is_installed = Column(Boolean, default=False, nullable=False)
    device_model = Column(String(120), nullable=True)
    # The handset's eUICC id. Stored for support to match against the carrier
    # history; never shown to the customer, who has no use for it.
    eid = Column(String(64), nullable=True)

    # Both come from VivaPe and are the authoritative validity window: it runs
    # from FIRST ACTIVATION, not from purchase.
    activated_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    # Carrier provisioning events, and per-day usage with country/carrier.
    history = Column(JSON, nullable=True)
    daily_breakdown = Column(JSON, nullable=True)

    fetched_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    # Tracked separately from fetched_at so the refresh cooldown throttles only
    # repeated forced polls. Sharing one timestamp made the button dead for the
    # first 45 seconds after any ordinary page view, which is exactly when
    # someone presses it.
    last_forced_at = Column(DateTime(timezone=True), nullable=True)
    fetch_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    esim_profile = relationship("ESIMProfile", back_populates="telemetry")
