from typing import Optional, List
from decimal import Decimal
from pydantic import BaseModel

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

class PriceMarkupRequest(BaseModel):
    product_id: str
    new_retail_price: Decimal
