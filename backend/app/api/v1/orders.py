import uuid
import asyncio
from decimal import Decimal
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.core.database import get_db, AsyncSessionLocal
from app.core.deps import get_current_user
from app.models.user import User
from app.models.catalog import Product
from app.models.wallet import Wallet, WalletType, LedgerRefType
from app.models.order import Order, OrderStatus, PaymentMethod, ESIMProfile
from app.schemas.order import OrderCreateRequest, OrderResponse, ESIMProfileResponse
from app.services.ledger_svc import LedgerService
from app.services.email_svc import EmailService
from app.services.checkout_svc import resolve_beneficiary, provision_esim, distribute_commission, RESELLER_ROLES
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/orders", tags=["Orders & eSIMs"])


async def _send_order_confirmation_background(email: str, order_no: str, product_title: str, iccid: str, lpa_string: str, **details):
    async with AsyncSessionLocal() as bg_db:
        try:
            await EmailService.send_order_confirmation(bg_db, email, order_no, product_title, iccid, lpa_string, **details)
        except Exception as e:
            logger.warning("order_confirmation_email_background_task_failed", email=email, error=str(e))


@router.post("/checkout", response_model=OrderResponse)
async def checkout_esim(
    req: OrderCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if req.is_buy_for_user and current_user.role not in RESELLER_ROLES:
        raise HTTPException(status_code=403, detail="Only merchants, admins, and super admins can buy for another user")

    # 1. Fetch Product
    p_res = await db.execute(select(Product).where(Product.id == req.product_id, Product.is_active == True))
    product = p_res.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found or inactive")

    # 2. Determine Beneficiary
    try:
        beneficiary_id = await resolve_beneficiary(
            db, current_user, req.is_buy_for_user, req.auto_create_user,
            req.beneficiary_username, req.beneficiary_email
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # 3. Only WALLET checkout is handled here; gateway checkout is
    # POST /payments/shurjopay/order-initiate, which redirects to ShurjoPay
    # and completes this same provisioning from the payment callback
    # instead of synchronously (see checkout_svc.provision_esim).
    if req.payment_method != PaymentMethod.WALLET:
        raise HTTPException(status_code=400, detail="Use POST /payments/shurjopay/order-initiate for gateway checkout")

    total_cost = Decimal(str(product.retail_price))

    w_res = await db.execute(
        select(Wallet).where(Wallet.user_id == current_user.id, Wallet.wallet_type == WalletType.DEFAULT)
    )
    wallet = w_res.scalar_one_or_none()
    if not wallet or Decimal(str(wallet.balance)) < total_cost:
        raise HTTPException(status_code=400, detail="Insufficient wallet balance. Please top up.")

    order_no = f"ORD-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    order = Order(
        order_no=order_no,
        buyer_id=current_user.id,
        beneficiary_id=beneficiary_id,
        product_id=product.id,
        total_amount=total_cost,
        currency=product.currency,
        payment_method=PaymentMethod.WALLET,
        status=OrderStatus.PROCESSING,
        is_reseller_order=req.is_buy_for_user
    )
    db.add(order)
    await db.flush()

    # Debit wallet — raises ValueError (-> 400 below) on insufficient balance,
    # rolling back the whole transaction including the Order row above.
    try:
        await LedgerService.debit(
            db, wallet.id, total_cost,
            LedgerRefType.ORDER_PURCHASE,
            ref_id=order.id,
            description=f"Purchase eSIM: {product.title_en}",
            idempotency_key=f"order-debit-{order.id}"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 4. Provision eSIM Profile from VivaPe (shared with the ShurjoPay
    # gateway path, which calls this same function from its callback).
    # Must happen before commission distribution: an order that fails and
    # gets refunded here must not also leave the merchant with commission
    # earned on a sale that didn't actually happen.
    profile = await provision_esim(db, order, product, beneficiary_id, current_user.id, current_user.role.value)

    if not profile:
        await db.commit()
        # provision_esim already marked the order FAILED and refunded the
        # wallet debit - surface this as an error response (not a 200 with
        # status=FAILED) so the frontend's existing catch/alert handles it
        # instead of rendering a "success" screen with no eSIM data.
        raise HTTPException(status_code=502, detail="eSIM provisioning failed. Your payment has been refunded to your wallet.")

    # Commission Distribution for Merchants buying on behalf of a customer -
    # only reached once provisioning has actually succeeded.
    await distribute_commission(db, order, total_cost, current_user)
    await db.commit()

    beneficiary_res = await db.execute(select(User.email).where(User.id == beneficiary_id))
    beneficiary_email = beneficiary_res.scalar_one_or_none()
    if beneficiary_email:
        asyncio.create_task(_send_order_confirmation_background(
            beneficiary_email, order.order_no, product.title_en, profile.iccid, profile.lpa_string,
            validity_days=product.validity_days,
            data_label="Unlimited" if product.is_unlimited else f"{product.data_amount_gb} GB",
            purchase_reference=profile.supplier_reference,
            purchased_at=order.created_at,
        ))

    # Re-fetch with the eSIM profile eagerly loaded: Pydantic's response
    # serialization is synchronous and can't trigger an async lazy load.
    res = await db.execute(
        select(Order).options(selectinload(Order.esim_profile)).where(Order.id == order.id)
    )
    return res.scalar_one()


@router.get("/my-esims")
async def list_my_esims(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Returns eSIMs where current_user is beneficiary OR buyer
    query = (
        select(ESIMProfile, Order, Product)
        .join(Order, ESIMProfile.order_id == Order.id)
        .join(Product, Order.product_id == Product.id)
        .where((ESIMProfile.beneficiary_id == current_user.id) | (Order.buyer_id == current_user.id))
        .order_by(ESIMProfile.created_at.desc())
    )
    res = await db.execute(query)
    results = []
    for profile, order, product in res.all():
        results.append({
            "id": profile.id,
            "order_no": order.order_no,
            "product_title": product.title_en,
            "data_amount_gb": float(product.data_amount_gb),
            "is_unlimited": bool(product.is_unlimited),
            "validity_days": product.validity_days,
            "iccid": profile.iccid,
            "lpa_string": profile.lpa_string,
            "qr_code_data": profile.qr_code_data,
            "smdp_address": profile.smdp_address,
            "status": profile.status.value,
            "is_mock_fallback": profile.is_mock_fallback,
            "created_at": profile.created_at,
            "expires_at": profile.expires_at,
            "is_beneficiary": profile.beneficiary_id == current_user.id
        })
    return results


@router.get("/reseller-orders")
async def list_reseller_orders(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role not in RESELLER_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized for reseller orders")

    query = (
        select(Order, User, Product, ESIMProfile)
        .join(User, Order.beneficiary_id == User.id)
        .join(Product, Order.product_id == Product.id)
        .outerjoin(ESIMProfile, Order.id == ESIMProfile.order_id)
        .where(Order.buyer_id == current_user.id, Order.is_reseller_order == True)
        .order_by(Order.created_at.desc())
    )
    res = await db.execute(query)
    results = []
    for order, user, product, profile in res.all():
        results.append({
            "order_id": order.id,
            "order_no": order.order_no,
            "beneficiary_username": user.username,
            "product_title": product.title_en,
            "total_amount": float(order.total_amount),
            "commission_earned": float(order.reseller_commission_amount or 0),
            "status": order.status.value,
            "iccid": profile.iccid if profile else None,
            "created_at": order.created_at
        })
    return results
