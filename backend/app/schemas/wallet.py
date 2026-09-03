from typing import Optional, List
from decimal import Decimal
from datetime import datetime
from pydantic import BaseModel
from app.models.wallet import WalletType, LedgerTxType, LedgerRefType
from app.models.payment import ManualPaymentStatus

class WalletResponse(BaseModel):
    id: str
    wallet_type: WalletType
    balance: Decimal
    currency: str
    is_frozen: bool

    class Config:
        from_attributes = True

class LedgerEntryResponse(BaseModel):
    id: str
    tx_type: LedgerTxType
    amount: Decimal
    balance_before: Decimal
    balance_after: Decimal
    reference_type: LedgerRefType
    description: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class ManualDepositRequest(BaseModel):
    amount: Decimal
    currency: str = "BDT"
    bank_name: str
    transaction_id: str
    receipt_url: Optional[str] = None

class ManualDepositResponse(BaseModel):
    id: str
    amount: Decimal
    currency: str
    bank_name: str
    transaction_id: str
    status: ManualPaymentStatus
    created_at: datetime

    class Config:
        from_attributes = True
