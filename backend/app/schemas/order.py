from typing import Optional
from decimal import Decimal
from datetime import datetime
from pydantic import BaseModel
from app.models.order import OrderStatus, PaymentMethod, ESIMStatus

class OrderCreateRequest(BaseModel):
    product_id: str
    payment_method: PaymentMethod = PaymentMethod.WALLET
    # Reseller flow
    is_buy_for_user: bool = False
    beneficiary_username: Optional[str] = None
    beneficiary_email: Optional[str] = None
    auto_create_user: bool = False

class ESIMProfileResponse(BaseModel):
    id: str
    order_id: str
    iccid: Optional[str] = None
    lpa_string: Optional[str] = None
    qr_code_data: Optional[str] = None
    smdp_address: Optional[str] = None
    status: ESIMStatus
    created_at: datetime

    class Config:
        from_attributes = True

class OrderResponse(BaseModel):
    id: str
    order_no: str
    buyer_id: str
    beneficiary_id: str
    product_id: str
    total_amount: Decimal
    currency: str
    payment_method: PaymentMethod
    status: OrderStatus
    created_at: datetime
    esim_profile: Optional[ESIMProfileResponse] = None

    class Config:
        from_attributes = True
