import uuid
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

MIN_TOPUP_USD = Decimal("1.00")
MAX_TOPUP_USD = Decimal("2000.00")


@router.post("/shurjopay/topup")
async def topup_via_shurjopay(
    amount_usd: Decimal,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if amount_usd < MIN_TOPUP_USD or amount_usd > MAX_TOPUP_USD:
        raise HTTPException(status_code=400, detail=f"Amount must be between {MIN_TOPUP_USD} and {MAX_TOPUP_USD} USD")

    # Convert USD amount to BDT
    amount_bdt = await CurrencyService.convert(db, amount_usd, "BDT")
    order_id = f"TOPUP-{current_user.id}-{uuid.uuid4().hex[:10]}"

    pay_res = await ShurjoPayService.initiate_payment(
        db, order_id=order_id,
        amount_bdt=amount_bdt,
        customer_name=current_user.full_name or current_user.username,
        customer_email=current_user.email,
        customer_phone=current_user.phone or "01700000000"
    )
    await db.commit()
    return pay_res


@router.get("/shurjopay/callback")
async def shurjopay_callback(
    order_id: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    if not order_id.startswith("TOPUP-"):
        raise HTTPException(status_code=400, detail="Unknown order reference")

    # Format is "TOPUP-{user_id}-{random_suffix}"; user_id (a UUID) itself
    # contains hyphens, so strip the known prefix/suffix rather than splitting.
    remainder = order_id[len("TOPUP-"):]
    user_id, _, suffix = remainder.rpartition("-")
    if not user_id or not suffix:
        raise HTTPException(status_code=400, detail="Malformed order reference")

    verification = await ShurjoPayService.verify_payment(db, order_id)
    sp_code = verification.get("sp_code")
    if str(sp_code) != "1000":
        await db.commit()
        return {"status": "failed", "detail": verification}

    amount_paid_bdt = Decimal(str(verification.get("amount", "0")))

    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        await db.commit()
        return {"status": "failed", "detail": "Unknown user for this order"}

    w_res = await db.execute(
        select(Wallet).where(Wallet.user_id == user.id, Wallet.wallet_type == WalletType.DEFAULT)
    )
    wallet = w_res.scalar_one_or_none()
    if not wallet:
        await db.commit()
        return {"status": "failed", "detail": "No wallet found for user"}

    # Convert BDT back to USD
    rate = await CurrencyService.get_effective_rate(db, "BDT")
    usd_val = (amount_paid_bdt / rate).quantize(Decimal("0.0001"))

    # idempotency_key keyed on order_id means a replayed/duplicate callback
    # for the same order can never credit the wallet twice.
    await LedgerService.credit(
        db, wallet.id, usd_val,
        LedgerRefType.DEPOSIT_GATEWAY,
        ref_id=order_id,
        description=f"ShurjoPay Deposit: {amount_paid_bdt} BDT",
        idempotency_key=f"shurjopay-{order_id}"
    )
    await db.commit()
    return {"status": "success", "message": "Payment verified and credited"}
