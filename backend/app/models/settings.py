import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Numeric, Text, JSON
from app.core.database import Base

class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    key = Column(String(100), primary_key=True)
    value = Column(JSON, nullable=False)
    description = Column(String(255), nullable=True)
    is_public = Column(Boolean, default=True)
    updated_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class CurrencyRate(Base):
    __tablename__ = "currency_rates"

    currency_code = Column(String(3), primary_key=True)
    rate_to_base = Column(Numeric(18, 6), nullable=False)  # rate against USD (1 USD = X Currency)
    is_manual_override = Column(Boolean, default=False)
    manual_rate = Column(Numeric(18, 6), nullable=True)
    source = Column(String(50), default="AUTO_API")  # AUTO_API or MANUAL_OVERRIDE
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Language(Base):
    __tablename__ = "languages"

    code = Column(String(10), primary_key=True)  # en, bn, ar, es
    name = Column(String(50), nullable=False)
    native_name = Column(String(50), nullable=False)
    flag_emoji = Column(String(10), nullable=True)
    is_active = Column(Boolean, default=True)
    is_rtl = Column(Boolean, default=False)
