import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Numeric, Integer, Text, Index
from sqlalchemy.orm import relationship
from app.core.database import Base

class Country(Base):
    __tablename__ = "countries"

    id = Column(Integer, primary_key=True)  # matching VivaPe country id if available or auto
    iso2 = Column(String(10), unique=True, index=True, nullable=False)
    iso3 = Column(String(3), nullable=True)
    name_en = Column(String(100), nullable=False)
    name_bn = Column(String(100), nullable=True)
    flag_url = Column(String(255), nullable=True)
    region = Column(String(50), nullable=True)
    is_popular = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    products = relationship("Product", back_populates="country")

class Product(Base):
    __tablename__ = "products"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    supplier_product_id = Column(Integer, index=True, nullable=True)
    country_id = Column(Integer, ForeignKey("countries.id"), nullable=False, index=True)
    title_en = Column(String(150), nullable=False)
    title_bn = Column(String(150), nullable=True)
    data_amount_gb = Column(Numeric(8, 2), nullable=False)  # in GB (e.g. 1.0, 3.0, 5.0)
    validity_days = Column(Integer, nullable=False)
    cost_price = Column(Numeric(18, 4), nullable=False)
    retail_price = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    is_unlimited = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    supplier_reference = Column(String(100), nullable=True)  # esimgo_bundle or worldmove_esim
    coverage_networks = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    country = relationship("Country", back_populates="products")
    orders = relationship("Order", back_populates="product")
