import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Numeric, Integer, Text, Index
from sqlalchemy.orm import relationship
from app.core.database import Base

class Country(Base):
    __tablename__ = "countries"

    id = Column(Integer, primary_key=True)  # matching VivaPe country id if available or auto
    # Widened from 10 (migration b2d5f93a8e61): still every real ISO2 (2
    # chars), but eSIM Access's own stable regional identifiers need up to
    # 14 - e.g. "EU-42" (Europe, 42 countries), "SAAEQAKWOMBH-6". A
    # multi-country/regional package has no single ISO2 to key on, so it
    # gets its own pseudo-Country row keyed on this code instead - see
    # catalog_parsing.py's region handling.
    iso2 = Column(String(20), unique=True, index=True, nullable=False)
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
    # supplier_product_id is Integer-typed, which fits VivaPe (plain integer
    # ids) but not eSIM Access, whose packageCode is a string like
    # "TOPUP_CKH491" - see migration a1c4e82f7d93 for why this is a new,
    # purely additive column rather than a retype of supplier_product_id.
    # NULL for every VivaPe-sourced row; only ever set for
    # supplier_reference == "esimaccess" rows.
    supplier_package_code = Column(String(100), index=True, nullable=True)
    # A Day Pass's packageCode is the SAME regardless of how many days a
    # customer buys - periodNum is an order-time parameter, not a separate
    # catalog entry (confirmed live, see esimaccess_adapter.py's
    # day_pass_total_price and backend/docs/esimaccess_integration_
    # reference.md section 4.2). Syncing a Day Pass as several
    # fixed-looking Product variants (one per offered duration) means
    # several rows legitimately share one supplier_package_code,
    # distinguished only by this field - see catalog_parsing.py. NULL for
    # every fixed-data (dataType 1) row and every VivaPe row. A partial
    # unique index (migration b2d5f93a8e61) enforces
    # (supplier_package_code, this column) can't collide among eSIM
    # Access rows.
    supplier_period_num = Column(Integer, nullable=True)
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
    # Admin-picked "recommended" package for its destination - shown first
    # and badged on the explore page. Not unique or capped at the database
    # level: the admin console is what keeps it to a sane couple of picks
    # per country, the same way is_popular is self-policed on Country.
    is_featured = Column(Boolean, default=False, server_default="false", nullable=False)
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
    # Comma-separated ISO2 list for a regional/multi-country eSIM Access
    # package (e.g. "NO,RS,DE") - what the storefront resolves into
    # country names to show "Covers: Norway, Serbia, Germany". NULL for
    # every single-country row. Deliberately a separate column from
    # coverage_networks above, which already holds an unrelated value
    # (ipExport) for those rows - see migration c4f6a92e0137.
    coverage_country_isos = Column(Text, nullable=True)
    # When the supplier's product feed last listed this product. Tracked
    # explicitly rather than inferred from updated_at, which only advances
    # when a row's VALUES actually change: a product whose price and data
    # are identical run-to-run produces no UPDATE at all, so updated_at
    # froze and the retirement sweep deactivated 1400+ live products it had
    # just seen in the feed (prod, 23-28 Oct 2026). Written by a direct
    # UPDATE, never by ORM attribute assignment, so it can never again be
    # silently skipped by change detection.
    last_seen_in_feed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    country = relationship("Country", back_populates="products")
    orders = relationship("Order", back_populates="product")
