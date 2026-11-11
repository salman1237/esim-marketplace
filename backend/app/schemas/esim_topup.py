from typing import Optional
from decimal import Decimal
from datetime import datetime
from pydantic import BaseModel
from app.models.order import EsimTopupStatus


class TopupOptionResponse(BaseModel):
    """A live, just-fetched option - never persisted as-is. package_code
    is what the purchase request echoes back, re-validated server-side
    against a fresh fetch rather than trusted from this response."""
    package_code: str
    title: str
    data_amount_gb: Decimal
    validity_days: int
    retail_price: Decimal
    currency: str


class TopupPurchaseRequest(BaseModel):
    package_code: str


class EsimTopupResponse(BaseModel):
    id: str
    esim_profile_id: str
    package_code: str
    title: str
    data_amount_gb: Decimal
    validity_days: int
    retail_price: Decimal
    currency: str
    status: EsimTopupStatus
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True
