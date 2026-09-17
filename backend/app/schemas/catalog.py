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
    coverage_networks: Optional[str] = None

    class Config:
        from_attributes = True

class DestinationResponse(BaseModel):
    country: CountryResponse
    products: List[ProductResponse]

class PriceMarkupRequest(BaseModel):
    product_id: str
    new_retail_price: Decimal
