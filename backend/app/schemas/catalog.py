import re
from typing import Optional, List
from decimal import Decimal
from pydantic import BaseModel, computed_field

class CountryResponse(BaseModel):
    id: int
    iso2: str
    iso3: Optional[str] = None
    name_en: str
    name_bn: Optional[str] = None
    flag_url: Optional[str] = None
    region: Optional[str] = None
    is_popular: bool
    popular_order: int = 0
    is_active: bool

    @computed_field
    @property
    def slug(self) -> str:
        """Used to build /explore/<slug> links."""
        return re.sub(r"[^a-z0-9]+", "-", (self.name_en or "").lower()).strip("-")

    class Config:
        from_attributes = True

class ProductResponse(BaseModel):
    id: str
    country_id: int
    title_en: str
    title_bn: Optional[str] = None
    data_amount_gb: Decimal
    validity_days: int
    retail_price: Decimal
    currency: str
    is_unlimited: bool
    is_active: bool
    is_featured: bool = False
    coverage_networks: Optional[str] = None
    # Set only for a Day Pass variant (see catalog_parsing.py's
    # DAY_PASS_VARIANT_DAYS) - lets the storefront split a country's
    # plans into "Fixed" vs "Day Pass" tabs.
    supplier_period_num: Optional[int] = None
    # Resolved country names for a regional/multi-country package (e.g.
    # ["Norway", "Serbia", "Germany"]) - populated by the catalog
    # endpoints from Product.coverage_country_isos, not a plain
    # pass-through column. None for a single-country product.
    coverage_countries: Optional[List[str]] = None

    class Config:
        from_attributes = True

class DestinationResponse(BaseModel):
    country: CountryResponse
    products: List[ProductResponse]

class FeaturedPackageResponse(BaseModel):
    """One admin-picked product for the storefront's top "Global" card -
    see GET /catalog/featured. A cheap, flat summary so a search-sheet
    header doesn't need to fetch every country's products to find it."""
    product_id: str
    title: str
    retail_price: Decimal
    currency: str
    data_amount_gb: Decimal
    validity_days: int
    is_unlimited: bool
    # None when the product's own coverage_country_isos isn't populated
    # (true for a plain VivaPe/esimgo_bundle "Global" row - that supplier
    # never reports a coverage list, only eSIM Access's regional packages
    # do). The client should omit a "covers N countries" line rather than
    # show 0 when this is None.
    country_count: Optional[int] = None
    # The destination to open on tap - same country the product belongs
    # to, via its existing /catalog/destinations/{slug or iso2} endpoint.
    country_iso2: str
    country_name: str
    country_slug: str
    flag_url: Optional[str] = None

class PriceMarkupRequest(BaseModel):
    product_id: str
    new_retail_price: Decimal
