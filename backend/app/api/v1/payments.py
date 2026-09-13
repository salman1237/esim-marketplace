import uuid
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.wallet import Wallet, WalletType, LedgerRefType
from app.models.catalog import Product
from app.models.order import Order, OrderStatus, PaymentMethod
from app.schemas.order import OrderCreateRequest
from app.services.shurjopay_svc import ShurjoPayService
from app.services.currency_svc import CurrencyService
from app.services.ledger_svc import LedgerService
from app.services.checkout_svc import resolve_beneficiary, RESELLER_ROLES
from app.services.order_fulfilment import start_fulfilment
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/payments", tags=["Payment Gateways"])


MIN_TOPUP = Decimal("1.00")
MAX_TOPUP = Decimal("2000.00")


@router.post("/shurjopay/topup")
async def topup_via_shurjopay(
    amount: Decimal,  # in the base currency (EUR)
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if amount < MIN_TOPUP or amount > MAX_TOPUP:
        raise HTTPException(status_code=400, detail=f"Amount must be between {MIN_TOPUP} and {MAX_TOPUP} {settings.BASE_CURRENCY}")

    # Convert the base-currency amount to BDT for the gateway
    amount_bdt = await CurrencyService.convert(db, amount, "BDT")
    order_id = f"TOPUP-{current_user.id}-{uuid.uuid4().hex[:10]}"

    pay_res = await ShurjoPayService.initiate_payment(
        db, order_id=order_id,
        amount_bdt=amount_bdt,
        customer_name=current_user.full_name or current_user.username,
        customer_email=current_user.email,
        customer_phone=current_user.phone or "01700000000",
        client_ip=request.client.host if request.client else "127.0.0.1"
    )
    await db.commit()
    return pay_res


@router.post("/shurjopay/order-initiate")
async def initiate_order_via_shurjopay(
    req: OrderCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Pays for a specific eSIM directly via ShurjoPay instead of wallet
    balance - orders.py's /orders/checkout only accepts WALLET and points
    here for anything else. The order is created PENDING now and only
    actually provisioned when the gateway callback confirms payment (see
    shurjopay_callback below) - unlike the wallet path, there's no way to
    charge synchronously here, the customer has to complete checkout on
    ShurjoPay's own page first.
    """
    if req.is_buy_for_user and current_user.role not in RESELLER_ROLES:
        raise HTTPException(status_code=403, detail="Only merchants, admins, and super admins can buy for another user")

    p_res = await db.execute(select(Product).where(Product.id == req.product_id, Product.is_active == True))
    product = p_res.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found or inactive")

    try:
        beneficiary_id = await resolve_beneficiary(
            db, current_user, req.is_buy_for_user, req.auto_create_user,
            req.beneficiary_username, req.beneficiary_email
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    total_cost = Decimal(str(product.retail_price))
    order_no = f"ORD-{uuid.uuid4().hex[:6].upper()}"
    order = Order(
        order_no=order_no,
        buyer_id=current_user.id,
        beneficiary_id=beneficiary_id,
        product_id=product.id,
        total_amount=total_cost,
        cost_amount=product.cost_price,
        currency=product.currency,
        payment_method=PaymentMethod.SHURJOPAY,
        status=OrderStatus.PENDING,
        is_reseller_order=req.is_buy_for_user
    )
    db.add(order)
    await db.flush()

    amount_bdt = await CurrencyService.convert(db, total_cost, "BDT")
    # "ORDERPAY-" prefix distinguishes this from a wallet TOPUP- callback;
    # the order id itself (a UUID, so already globally unique) is the
    # entire remainder - no need for the extra random suffix TOPUP uses.
    sp_reference = f"ORDERPAY-{order.id}"

    try:
        pay_res = await ShurjoPayService.initiate_payment(
            db, order_id=sp_reference,
            amount_bdt=amount_bdt,
            customer_name=current_user.full_name or current_user.username,
            customer_email=current_user.email,
            customer_phone=current_user.phone or "01700000000",
            client_ip=request.client.host if request.client else "127.0.0.1"
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"Could not start ShurjoPay checkout: {e}")

    await db.commit()
    return {**pay_res, "order_id": order.id, "order_no": order.order_no}


@router.get("/shurjopay/callback")
async def shurjopay_callback(
    order_id: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """`order_id` here is ShurjoPay's own sp_order_id (e.g. "sp6a99c..."),
    not the "TOPUP-{user_id}-..." reference we sent them — confirmed by
    actually completing a sandbox payment end-to-end: their return_url
    redirect comes back as "?order_id=<their sp_order_id>", and that's the
    only identifier a real callback ever gives us. Our own reference is
    recovered from the verification response's customer_order_id field,
    which ShurjoPay echoes back for us.

    Also: GET /api/verification always returns a JSON array ([{...}]), not
    a bare object — confirmed the same way. Both of these were previously
    unhandled and would have made every real top-up fail (order-not-found
    from ShurjoPay, or an AttributeError from treating the list as a dict).
    """
    def _fail(reason: str, redirect_path: str = "/wallet", query_key: str = "topup") -> RedirectResponse:
        # query_key stays "topup" by default — the wallet page only reads
        # ?topup=..., not ?payment=...; the ORDERPAY branch below passes
        # query_key="payment" explicitly for its own /my-esims redirect.
        sep = "&" if "?" in redirect_path else "?"
        return RedirectResponse(f"{settings.FRONTEND_BASE_URL}{redirect_path}{sep}{query_key}=failed&reason={reason}", status_code=302)

    verification = await ShurjoPayService.verify_payment(db, order_id)
    record = verification[0] if isinstance(verification, list) and verification else verification
    if not isinstance(record, dict):
        await db.commit()
        return _fail("unexpected_response")

    # Checked before sp_code so an unpaid/failed ORDERPAY order redirects
    # back to /my-esims (where the purchase happened) instead of /wallet —
    # sp_code alone can't tell these two payment kinds apart, only
    # customer_order_id's prefix can.
    customer_order_id = record.get("customer_order_id") or ""
    is_order_payment = customer_order_id.startswith("ORDERPAY-")

    sp_code = record.get("sp_code")
    if str(sp_code) != "1000":
        await db.commit()
        if is_order_payment:
            return _fail("not_paid", "/my-esims", "payment")
        return _fail("not_paid")

    if is_order_payment:
        return await _complete_gateway_order(db, customer_order_id, _fail)

    if not customer_order_id.startswith("TOPUP-"):
        await db.commit()
        return _fail("unknown_order")

    # Format is "TOPUP-{user_id}-{random_suffix}"; user_id (a UUID) itself
    # contains hyphens, so strip the known prefix/suffix rather than splitting.
    remainder = customer_order_id[len("TOPUP-"):]
    user_id, _, suffix = remainder.rpartition("-")
    if not user_id or not suffix:
        await db.commit()
        return _fail("malformed_order")

    amount_paid_bdt = Decimal(str(record.get("amount", "0")))

    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        await db.commit()
        return _fail("unknown_user")

    w_res = await db.execute(
        select(Wallet).where(Wallet.user_id == user.id, Wallet.wallet_type == WalletType.DEFAULT)
    )
    wallet = w_res.scalar_one_or_none()
    if not wallet:
        await db.commit()
        return _fail("no_wallet")

    # Convert the BDT actually paid back into the base currency
    rate = await CurrencyService.get_effective_rate(db, "BDT")
    amount_base = (amount_paid_bdt / rate).quantize(Decimal("0.0001"))

    # idempotency_key keyed on ShurjoPay's own order_id (globally unique)
    # means a replayed/duplicate callback for the same order can never
    # credit the wallet twice.
    await LedgerService.credit(
        db, wallet.id, amount_base,
        LedgerRefType.DEPOSIT_GATEWAY,
        ref_id=order_id,
        description=f"ShurjoPay Deposit: {amount_paid_bdt} BDT",
        idempotency_key=f"shurjopay-{order_id}"
    )
    await db.commit()
    return RedirectResponse(f"{settings.FRONTEND_BASE_URL}/wallet?topup=success", status_code=302)


async def _complete_gateway_order(db: AsyncSession, customer_order_id: str, _fail) -> RedirectResponse:
    """Completes a direct-gateway eSIM purchase (POST
    /payments/shurjopay/order-initiate) once ShurjoPay confirms payment.
    Hands off to the same background fulfil_order() the wallet checkout
    uses, so provisioning, refunds and the delivery email can't drift
    between the two payment methods."""
    db_order_id = customer_order_id[len("ORDERPAY-"):]

    res = await db.execute(select(Order).where(Order.id == db_order_id))
    order = res.scalar_one_or_none()
    if not order:
        await db.commit()
        return _fail("unknown_order", "/my-esims", "payment")

    if order.status != OrderStatus.PENDING:
        # Already handed off (a replayed callback) or otherwise not awaiting
        # payment - starting fulfilment again would duplicate the eSIM.
        # Redirect to the same polling view so a replay still shows status.
        await db.commit()
        return RedirectResponse(f"{settings.FRONTEND_BASE_URL}/my-esims?order={order.id}", status_code=302)

    p_res = await db.execute(select(Product).where(Product.id == order.product_id))
    product = p_res.scalar_one_or_none()
    if not product:
        await db.commit()
        return _fail("product_no_longer_available", "/my-esims", "payment")

    # Payment is confirmed: hand off to background fulfilment and redirect
    # at once, rather than holding the customer's browser on a blank
    # redirect for the ~10-30s supplier call. The My eSIMs page polls this
    # order and shows the outcome. If provisioning fails, fulfil_order
    # refunds the full amount to the wallet (no gateway refund API is wired
    # up, so wallet credit is the compensation). Moving off PENDING is also
    # what makes a replayed callback a no-op.
    order.status = OrderStatus.PROCESSING
    await db.commit()
    start_fulfilment(order.id)
    return RedirectResponse(f"{settings.FRONTEND_BASE_URL}/my-esims?order={order.id}", status_code=302)
