import uuid
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.models.merchant import MerchantProfile
from app.models.catalog import Product
from app.models.wallet import Wallet, WalletType, LedgerRefType
from app.models.order import Order, OrderStatus, PaymentMethod, ESIMProfile, ESIMStatus
from app.schemas.order import OrderCreateRequest, OrderResponse, ESIMProfileResponse
from app.services.ledger_svc import LedgerService
from app.services.vivape_adapter import VivaPeAdapter
from app.services.audit_svc import AuditService
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/orders", tags=["Orders & eSIMs"])

RESELLER_ROLES = {UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.MERCHANT}


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
    beneficiary_id = current_user.id
    if req.is_buy_for_user:
        if req.auto_create_user:
            auto_username = f"user_{uuid.uuid4().hex[:8]}"
            auto_email = f"{auto_username}@customer.esim.local"
            new_user = User(
                email=auto_email,
                username=auto_username,
                hashed_password=get_password_hash(uuid.uuid4().hex),
                role=UserRole.USER
            )
            db.add(new_user)
            await db.flush()
            await LedgerService.ensure_wallets_for_user(db, new_user.id, new_user.role)
            beneficiary_id = new_user.id
        elif req.beneficiary_username or req.beneficiary_email:
            u_query = select(User).where(
                (User.username == req.beneficiary_username) | (User.email == req.beneficiary_email)
            )
            b_res = await db.execute(u_query)
            target = b_res.scalar_one_or_none()
            if not target:
                raise HTTPException(status_code=404, detail="Beneficiary user account not found")
            beneficiary_id = target.id

    # 3. Only WALLET checkout is handled here; gateway checkout goes through /payments
    if req.payment_method != PaymentMethod.WALLET:
        raise HTTPException(status_code=400, detail="Use /payments/shurjopay/initiate for gateway checkout")

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

    # Commission Distribution for Merchants buying on behalf of a customer
    if current_user.role == UserRole.MERCHANT and req.is_buy_for_user:
        m_res = await db.execute(select(MerchantProfile).where(MerchantProfile.user_id == current_user.id))
        merchant_profile = m_res.scalar_one_or_none()
        rate_pct = Decimal(str(merchant_profile.commission_rate_pct)) if merchant_profile else Decimal("5.0")
        commission_amount = (total_cost * (rate_pct / Decimal("100"))).quantize(Decimal("0.0001"))

        cw_res = await db.execute(
            select(Wallet).where(Wallet.user_id == current_user.id, Wallet.wallet_type == WalletType.COMMISSION)
        )
        comm_wallet = cw_res.scalar_one_or_none()
        if comm_wallet and commission_amount > Decimal("0"):
            await LedgerService.credit(
                db, comm_wallet.id, commission_amount,
                LedgerRefType.COMMISSION_EARNED,
                ref_id=order.id,
                description=f"Commission for order {order.order_no} ({rate_pct}%)",
                idempotency_key=f"order-commission-{order.id}"
            )
            order.reseller_commission_amount = commission_amount

    # 4. Provision eSIM Profile from VivaPe. A supplier failure does NOT
    # silently fabricate a working-looking profile — it's flagged via
    # is_mock_fallback so admins can see and reconcile it, since the customer
    # has already been charged.
    iccid = f"89882{uuid.uuid4().hex[:14].upper()}"
    matching_id = uuid.uuid4().hex[:12].upper()
    smdp = "rsp.truphone.com"
    lpa = f"LPA:1${smdp}${matching_id}"
    qr_data = lpa
    is_mock_fallback = True

    if product.supplier_product_id:
        try:
            trx = await VivaPeAdapter.create_transaction(
                db, product.supplier_product_id, current_user.phone or "8801700000000", float(product.cost_price)
            )
            trx_id = trx.get("purchase_trx", {}).get("id")
            if trx_id:
                esim_data = await VivaPeAdapter.get_esim_by_trx(db, trx_id)
                if esim_data.get("iccid"):
                    iccid = esim_data["iccid"]
                    lpa = esim_data.get("lpa") or lpa
                    qr_data = esim_data.get("qr_code") or lpa
                    is_mock_fallback = False
        except Exception as e:
            logger.warning("vivape_provisioning_failed_using_mock_fallback", order_id=order.id, error=str(e))

    if is_mock_fallback:
        await AuditService.log_action(
            db, actor_id=current_user.id, actor_role=current_user.role.value,
            action="MOCK_ESIM_FALLBACK",
            after_state={"order_id": order.id, "product_id": product.id, "reason": "VivaPe provisioning unavailable or failed"}
        )

    profile = ESIMProfile(
        order_id=order.id,
        beneficiary_id=beneficiary_id,
        iccid=iccid,
        lpa_string=lpa,
        qr_code_data=qr_data,
        smdp_address=smdp,
        matching_id=matching_id,
        status=ESIMStatus.RELEASED,
        is_mock_fallback=is_mock_fallback,
        expires_at=datetime.now(timezone.utc) + timedelta(days=product.validity_days)
    )
    db.add(profile)

    order.status = OrderStatus.COMPLETED
    await db.commit()

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
