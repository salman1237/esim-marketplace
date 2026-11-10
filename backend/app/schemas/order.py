from typing import Optional
from decimal import Decimal
from datetime import datetime
from pydantic import BaseModel
from app.models.order import OrderStatus, PaymentMethod, ESIMStatus

class OrderCreateRequest(BaseModel):
    product_id: str
    payment_method: PaymentMethod = PaymentMethod.WALLET
    # One code per order - the request carries a single field, and the unique
    # constraint on discount_redemptions.order_id enforces it in the database.
    discount_code: Optional[str] = None
    # Reseller flow
    is_buy_for_user: bool = False
    beneficiary_username: Optional[str] = None
    beneficiary_email: Optional[str] = None
    # Becomes the new customer's first password, so the merchant standing
    # in front of them can say how to sign in.
    beneficiary_phone: Optional[str] = None
    auto_create_user: bool = False
    # Set by the mobile app only, on the SHURJOPAY path - tells
    # /payments/shurjopay/order-initiate to route the post-payment redirect
    # back to the app's custom URL scheme instead of the web frontend. No
    # effect on the WALLET path, which never redirects anywhere.
    mobile: bool = False

class ESIMProfileResponse(BaseModel):
    id: str
    order_id: str
    iccid: Optional[str] = None
    lpa_string: Optional[str] = None
    qr_code_data: Optional[str] = None
    smdp_address: Optional[str] = None
    status: ESIMStatus
    is_mock_fallback: bool = False
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
    # Already deducted from total_amount; kept in the response so a receipt
    # can show what the code saved.
    discount_amount: Decimal = Decimal("0")
    currency: str
    payment_method: PaymentMethod
    status: OrderStatus
    created_at: datetime
    esim_profile: Optional[ESIMProfileResponse] = None

    class Config:
        from_attributes = True
