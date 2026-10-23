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
    # Where this destination sits in the home page's "Popular Destinations"
    # row when is_popular is set - lower shows first. Not unique: ties just
    # fall back to name order, which is harmless and saves an admin from
    # having to renumber everything after a single reorder.
    popular_order = Column(Integer, default=0, server_default="0", nullable=False)
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
    currency = Column(String(3), default="EUR", nullable=False)
    is_unlimited = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    supplier_reference = Column(String(100), nullable=True)  # esimgo_bundle or worldmove_esim
    # VivaPe's own receiver_amount_min for this product, stored verbatim
    # from the catalog sync and passed straight back to create-transaction.
    # This is NOT a price — confirmed against the live catalog it means
    # different things per supplier_reference (MB quantity for
    # esimgo_bundle, e.g. 1000 for a 1GB plan and -1 for unlimited; some
    # other cost-like unit for worldmove_esim, ~3.7x the USD price and
    # unrelated to the GB amount). There is no way to derive the correct
    # value from cost_price or the title — it must be round-tripped as-is.
    supplier_receiver_amount = Column(Numeric(18, 4), nullable=True)
    coverage_networks = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    country = relationship("Country", back_populates="products")
    orders = relationship("Order", back_populates="product")
