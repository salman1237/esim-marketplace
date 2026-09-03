from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.wallet import Wallet, WalletType, LedgerRefType
from app.services.shurjopay_svc import ShurjoPayService
from app.services.currency_svc import CurrencyService
from app.services.ledger_svc import LedgerService

router = APIRouter(prefix="/payments", tags=["Payment Gateways"])

@router.post("/shurjopay/topup")
async def topup_via_shurjopay(
    amount_usd: Decimal,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Convert USD amount to BDT
    amount_bdt = await CurrencyService.convert(db, amount_usd, "BDT")
    order_id = f"TOPUP-{current_user.id[:8]}-{int(amount_usd)}"
    
    pay_res = await ShurjoPayService.initiate_payment(
        db, order_id=order_id,
        amount_bdt=amount_bdt,
        customer_name=current_user.full_name or current_user.username,
        customer_email=current_user.email,
        customer_phone=current_user.phone or "01700000000"
    )
    return pay_res

@router.get("/shurjopay/callback")
async def shurjopay_callback(
    order_id: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    verification = await ShurjoPayService.verify_payment(db, order_id)
    # Check verification status
    sp_code = verification.get("sp_code")
    if str(sp_code) == "1000":
        # Payment verified successfully
        amount_paid_bdt = Decimal(str(verification.get("amount", "0")))
        # If topup order, credit user's wallet
        if order_id.startswith("TOPUP-"):
            parts = order_id.split("-")
            user_prefix = parts[1]
            # locate user
            res = await db.execute(select(User).where(User.id.startswith(user_prefix)))
            user = res.scalar_one_or_none()
            if user:
                w_res = await db.execute(
                    select(Wallet).where(Wallet.user_id == user.id, Wallet.wallet_type == WalletType.DEFAULT)
                )
                wallet = w_res.scalar_one_or_none()
                if wallet:
                    # Convert BDT back to USD
                    rate = await CurrencyService.get_effective_rate(db, "BDT")
                    usd_val = (amount_paid_bdt / rate).quantize(Decimal("0.0001"))
                    await LedgerService.credit(
                        db, wallet.id, usd_val,
                        LedgerRefType.DEPOSIT_GATEWAY,
                        ref_id=order_id,
                        description=f"ShurjoPay Deposit: {amount_paid_bdt} BDT"
                    )
        return {"status": "success", "message": "Payment verified and credited"}
    
    return {"status": "failed", "detail": verification}
