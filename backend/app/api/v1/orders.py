import uuid
from decimal import Decimal
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.core.timeutil import bd_datestamp
from app.core.deps import get_current_user, require_password_changed
from app.models.user import User
from app.models.catalog import Product
from app.models.wallet import Wallet, WalletType, LedgerRefType
from app.models.order import Order, OrderStatus, PaymentMethod, ESIMProfile
from app.schemas.order import OrderCreateRequest, OrderResponse, ESIMProfileResponse
from app.services.ledger_svc import LedgerService
from app.services import discount_svc
from app.services.checkout_svc import resolve_beneficiary, RESELLER_ROLES
from app.services.email_svc import EmailService
from app.services.order_fulfilment import start_fulfilment
from app.core.logging import get_logger
from app.services.supplier_settings_svc import get_enabled_suppliers, supplier_visible_filter

logger = get_logger(__name__)

router = APIRouter(prefix="/orders", tags=["Orders & eSIMs"])


@router.post("/checkout", response_model=OrderResponse, status_code=202)
async def checkout_esim(
    req: OrderCreateRequest,
    current_user: User = Depends(require_password_changed),
    db: AsyncSession = Depends(get_db)
):
    if req.is_buy_for_user and current_user.role not in RESELLER_ROLES:
        raise HTTPException(status_code=403, detail="Only merchants, admins, and super admins can buy for another user")

    # 1. Fetch Product
    enabled_suppliers = await get_enabled_suppliers(db)
    p_res = await db.execute(
        select(Product).where(
            Product.id == req.product_id, Product.is_active == True,
            supplier_visible_filter(Product.supplier_reference, enabled_suppliers),
        )
    )
    product = p_res.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found or inactive")

    # 2. Determine Beneficiary
    try:
        beneficiary_id, new_account = await resolve_beneficiary(
            db, current_user, req.is_buy_for_user, req.auto_create_user,
            req.beneficiary_username, req.beneficiary_email, req.beneficiary_phone
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # 3. Only WALLET checkout is handled here; gateway checkout is
    # POST /payments/shurjopay/order-initiate, which redirects to ShurjoPay
    # and completes this same provisioning from the payment callback
    # instead of synchronously (see checkout_svc.provision_esim).
    if req.payment_method != PaymentMethod.WALLET:
        raise HTTPException(status_code=400, detail="Use POST /payments/shurjopay/order-initiate for gateway checkout")

    list_price = Decimal(str(product.retail_price))
    # A bad code is an error, not a silent full-price charge.
    try:
        discount_code, discount_amount = await discount_svc.resolve_for_checkout(
            db, req.discount_code, current_user, product, list_price
        )
    except discount_svc.DiscountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    total_cost = list_price - discount_amount

    # Promo credit counts towards paying for an eSIM (it just can't be
    # withdrawn), so the affordability check is both wallets together.
    funds = await LedgerService.spendable(db, current_user.id)
    if funds["frozen"]:
        raise HTTPException(status_code=400, detail="This wallet is frozen. Please contact support.")
    if funds["total"] < total_cost:
        raise HTTPException(status_code=400, detail="Insufficient wallet balance. Please top up.")

    order_no = f"ORD-{bd_datestamp()}-{uuid.uuid4().hex[:6].upper()}"
    order = Order(
        order_no=order_no,
        buyer_id=current_user.id,
        beneficiary_id=beneficiary_id,
        product_id=product.id,
        # What was actually charged - so the wallet debit, the refund on
        # failure, the profit report and the commission all use one figure.
        total_amount=total_cost,
        cost_amount=product.cost_price,
        currency=product.currency,
        payment_method=PaymentMethod.WALLET,
        status=OrderStatus.PROCESSING,
        is_reseller_order=req.is_buy_for_user
    )
    db.add(order)
    await db.flush()

    if discount_code:
        await discount_svc.apply_to_order(db, order, discount_code, current_user.id, discount_amount)

    # Debit — promo credit first, then the main wallet. Raises ValueError
    # (-> 400 below) if the two can't cover it, rolling back the whole
    # transaction including the Order row above. The promo share is recorded
    # on the order so a refund goes back to the wallets that actually paid.
    try:
        order.reward_amount_used = await LedgerService.spend(
            db, current_user.id, total_cost,
            LedgerRefType.ORDER_PURCHASE,
            ref_id=order.id,
            description=f"Purchase eSIM: {product.title_en}",
            idempotency_prefix=f"order-debit-{order.id}",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 4. Commit the paid order, then provision in the background. The
    # supplier call takes ~10-30s; holding the HTTP request open for it
    # froze the storefront, so this returns 202 at once and the client
    # polls GET /orders/{id}. fulfil_order handles the rest - eSIM,
    # commission (only on success), refund on failure, and the delivery
    # email - and recover_stuck_orders finishes the job if a deploy kills
    # the task partway.
    await db.commit()
    start_fulfilment(order.id)

    # The customer did not open this account, so the credentials mail has
    # to go out as soon as the order is real - before the eSIM arrives, so
    # the delivery email lands somewhere they can already sign in to.
    # Never lets an email failure undo a paid order.
    if new_account:
        try:
            await EmailService.send_account_created(
                db, new_account["email"],
                username=new_account["username"],
                password=new_account["password"],
                password_is_phone=new_account["password_is_phone"],
                created_by=current_user.full_name or current_user.username,
                for_order=order.order_no,
            )
        except Exception as e:
            logger.warning("beneficiary_account_email_failed", order_id=order.id, error=str(e))

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
            # Both stay null until the eSIM is installed - validity runs from
            # activation, so the list says "starts on install" rather than
            # counting down from the purchase date.
            "activated_at": profile.activated_at,
            "expires_at": profile.expires_at,
            "validity_days": product.validity_days,
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


# Declared last on purpose: a path parameter here would otherwise capture
# the fixed /my-esims and /reseller-orders routes above.
@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(order_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Polled while an order provisions in the background. Visible only to
    its buyer or the eSIM's recipient - anyone else gets the same 404 as a
    nonexistent id, so order ids can't be probed for existence."""
    res = await db.execute(
        select(Order).options(selectinload(Order.esim_profile)).where(Order.id == order_id)
    )
    order = res.scalar_one_or_none()
    if not order or current_user.id not in (order.buyer_id, order.beneficiary_id):
        raise HTTPException(status_code=404, detail="Order not found")
    return order
