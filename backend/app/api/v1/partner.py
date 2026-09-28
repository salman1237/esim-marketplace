import uuid
import asyncio
import secrets
from decimal import Decimal
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.core.database import get_db, AsyncSessionLocal
from app.core.timeutil import bd_datestamp
from app.core.security import create_access_token
from app.core.partner_auth import get_current_partner, authenticate_partner_api_key, PartnerContext, PARTNER_TOKEN_ROLE
from app.core.rate_limit import limiter, get_partner_api_key
from app.models.catalog import Country, Product
from app.models.merchant import MerchantProfile
from app.models.user import User
from app.models.wallet import Wallet, WalletType, LedgerRefType
from app.models.order import Order, OrderStatus, PaymentMethod
from app.schemas.catalog import CountryResponse, ProductResponse
from app.services import agent_svc
from app.services.checkout_svc import get_effective_commission_rate, resolve_beneficiary, provision_esim, distribute_commission
from app.services.ledger_svc import LedgerService
from app.services.webhook_svc import deliver_webhook, build_partner_order_payload
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/partner", tags=["Partner API"])

PARTNER_TOKEN_EXPIRY = timedelta(hours=1)

# The event loop only weakly references tasks; without this a paid partner
# order's provisioning task could be garbage-collected mid-flight.
_background_tasks: set[asyncio.Task] = set()


class PartnerTokenRequest(BaseModel):
    api_key: str


@router.post("/auth/token")
@limiter.limit("10/minute")
async def issue_partner_access_token(
    request: Request,
    req: PartnerTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """Exchanges a partner's long-lived API key for a short-lived access
    token. The raw key is never accepted on any other /partner/* route -
    every other call authenticates with the token this returns, via
    `Authorization: Bearer <access_token>`."""
    api_key = await authenticate_partner_api_key(req.api_key, db)
    access_token = create_access_token(
        subject=api_key.id, role=PARTNER_TOKEN_ROLE, expires_delta=PARTNER_TOKEN_EXPIRY
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": int(PARTNER_TOKEN_EXPIRY.total_seconds()),
    }


@router.get("/countries", response_model=List[CountryResponse])
@limiter.limit("120/minute", key_func=get_partner_api_key)
async def list_countries(
    request: Request,
    search: Optional[str] = None,
    ctx: PartnerContext = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db)
):
    query = select(Country).where(Country.is_active == True)
    if search:
        query = query.where(Country.name_en.ilike(f"%{search}%") | Country.iso2.ilike(f"%{search}%"))
    query = query.order_by(Country.name_en.asc())
    res = await db.execute(query)
    return res.scalars().all()


@router.get("/countries/{iso2}/products", response_model=List[ProductResponse])
@limiter.limit("120/minute", key_func=get_partner_api_key)
async def list_country_products(
    request: Request,
    iso2: str,
    ctx: PartnerContext = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db)
):
    c_res = await db.execute(select(Country).where(Country.iso2 == iso2.upper()))
    country = c_res.scalar_one_or_none()
    if not country:
        raise HTTPException(status_code=404, detail="Country not found")

    p_res = await db.execute(
        select(Product).where(Product.country_id == country.id, Product.is_active == True)
        .order_by(Product.retail_price.asc(), Product.data_amount_gb.asc())
    )
    return p_res.scalars().all()


@router.get("/me")
@limiter.limit("120/minute", key_func=get_partner_api_key)
async def get_partner_profile(
    request: Request,
    ctx: PartnerContext = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db)
):
    # The NET rate, after any agent bonus - the same number the partner
    # dashboard shows and the same one they are actually paid. Returning the
    # pre-deduction rate here would expose the agent's share through the API,
    # which is exactly what the merchant must not see.
    gross = await get_effective_commission_rate(db, ctx.user.id, ctx.merchant.commission_rate_pct)
    rate = await agent_svc.effective_merchant_rate(db, ctx.merchant, Decimal(str(gross)))

    w_res = await db.execute(
        select(Wallet).where(Wallet.user_id == ctx.user.id, Wallet.wallet_type == WalletType.DEFAULT)
    )
    wallet = w_res.scalar_one_or_none()
    cw_res = await db.execute(
        select(Wallet).where(Wallet.user_id == ctx.user.id, Wallet.wallet_type == WalletType.COMMISSION)
    )
    commission_wallet = cw_res.scalar_one_or_none()

    return {
        "business_name": ctx.merchant.business_name,
        "commission_rate_pct": rate,
        "wallet_balance": wallet.balance if wallet else 0,
        "wallet_currency": wallet.currency if wallet else "EUR",
        "commission_balance": commission_wallet.balance if commission_wallet else 0,
        "webhook_configured": bool(ctx.merchant.webhook_url),
    }


class PartnerOrderCreateRequest(BaseModel):
    product_id: str
    customer_reference: Optional[str] = None


async def _process_partner_order_background(order_id: str):
    """Provisions the eSIM and delivers the webhook for a partner order
    that was already debited and committed by the request handler. Runs
    in its own session/task so a slow VivaPe call or webhook POST never
    holds up the API response - mirrors the order-confirmation-email
    background task in orders.py."""
    async with AsyncSessionLocal() as bg_db:
        try:
            o_res = await bg_db.execute(select(Order).where(Order.id == order_id))
            order = o_res.scalar_one()
            p_res = await bg_db.execute(select(Product).where(Product.id == order.product_id))
            product = p_res.scalar_one()
            m_res = await bg_db.execute(select(MerchantProfile).where(MerchantProfile.user_id == order.buyer_id))
            merchant = m_res.scalar_one()
            u_res = await bg_db.execute(select(User).where(User.id == order.buyer_id))
            buyer = u_res.scalar_one()

            profile = await provision_esim(bg_db, order, product, order.beneficiary_id, order.buyer_id, "MERCHANT")

            if profile:
                # Commission only on orders that actually succeed -
                # provision_esim already refunds+fails an order that
                # doesn't, and the merchant must not also keep commission
                # on a sale that didn't happen.
                await distribute_commission(bg_db, order, Decimal(str(order.total_amount)), buyer)

            await bg_db.commit()

            await deliver_webhook(bg_db, merchant, order, profile)
        except Exception as e:
            logger.error("partner_order_background_processing_failed", order_id=order_id, error=str(e))


@router.post("/orders")
@limiter.limit("30/minute", key_func=get_partner_api_key)
async def create_partner_order(
    request: Request,
    req: PartnerOrderCreateRequest,
    ctx: PartnerContext = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db)
):
    # Lock the wallet before anything else. It serialises concurrent orders
    # from this partner, which is what makes the customer_reference replay
    # check below race-free: two identical retries can't both see "no
    # existing order" and both get charged.
    w_res = await db.execute(
        select(Wallet).where(Wallet.user_id == ctx.user.id, Wallet.wallet_type == WalletType.DEFAULT).with_for_update()
    )
    wallet = w_res.scalar_one_or_none()

    if req.customer_reference:
        e_res = await db.execute(
            select(Order).options(selectinload(Order.esim_profile))
            .where(Order.buyer_id == ctx.user.id, Order.partner_customer_reference == req.customer_reference)
            .order_by(Order.created_at.asc()).limit(1)
        )
        existing = e_res.scalar_one_or_none()
        if existing:
            if existing.product_id != req.product_id:
                raise HTTPException(
                    status_code=409,
                    detail="customer_reference was already used for an order of a different product",
                )
            # A retry of an order we already accepted (e.g. the response was
            # lost to a timeout): hand back that order, never charge again.
            payload = await build_partner_order_payload(db, existing, existing.esim_profile)
            return {**payload, "idempotent_replay": True}

    p_res = await db.execute(select(Product).where(Product.id == req.product_id, Product.is_active == True))
    product = p_res.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found or inactive")

    beneficiary_id = await resolve_beneficiary(db, ctx.user, True, True, None, None)

    total_cost = Decimal(str(product.retail_price))
    if not wallet or Decimal(str(wallet.balance)) < total_cost:
        raise HTTPException(status_code=400, detail="Insufficient wallet balance. Please top up.")

    order_no = f"PTR-{bd_datestamp()}-{uuid.uuid4().hex[:6].upper()}"
    order = Order(
        order_no=order_no,
        buyer_id=ctx.user.id,
        beneficiary_id=beneficiary_id,
        product_id=product.id,
        total_amount=total_cost,
        cost_amount=product.cost_price,
        currency=product.currency,
        payment_method=PaymentMethod.WALLET,
        status=OrderStatus.PROCESSING,
        is_reseller_order=True,
        partner_customer_reference=req.customer_reference,
    )
    db.add(order)
    await db.flush()

    try:
        await LedgerService.debit(
            db, wallet.id, total_cost,
            LedgerRefType.ORDER_PURCHASE,
            ref_id=order.id,
            description=f"Partner order: {product.title_en}",
            idempotency_key=f"order-debit-{order.id}"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Commission is distributed in the background task, only once
    # provisioning has actually succeeded - see _process_partner_order_background.
    await db.commit()

    task = asyncio.create_task(_process_partner_order_background(order.id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    payload = await build_partner_order_payload(db, order, None)
    return {**payload, "idempotent_replay": False}


@router.get("/orders")
@limiter.limit("120/minute", key_func=get_partner_api_key)
async def list_partner_orders(
    request: Request,
    customer_reference: Optional[str] = None,
    status: Optional[OrderStatus] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ctx: PartnerContext = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db)
):
    """Orders placed through this API, newest first - for reconciling
    against the partner's own records."""
    conditions = [Order.buyer_id == ctx.user.id, Order.order_no.startswith("PTR-")]
    if customer_reference:
        conditions.append(Order.partner_customer_reference == customer_reference)
    if status:
        conditions.append(Order.status == status)

    total = (await db.execute(select(func.count(Order.id)).where(*conditions))).scalar_one()
    res = await db.execute(
        select(Order).options(selectinload(Order.esim_profile)).where(*conditions)
        .order_by(Order.created_at.desc()).limit(limit).offset(offset)
    )
    orders = [await build_partner_order_payload(db, o, o.esim_profile) for o in res.scalars().all()]
    return {"orders": orders, "total": total, "limit": limit, "offset": offset}


@router.get("/orders/{order_id}")
@limiter.limit("120/minute", key_func=get_partner_api_key)
async def get_partner_order(
    request: Request,
    order_id: str,
    ctx: PartnerContext = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(Order).options(selectinload(Order.esim_profile))
        .where(Order.id == order_id, Order.buyer_id == ctx.user.id)
    )
    order = res.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return await build_partner_order_payload(db, order, order.esim_profile)


class WebhookConfigRequest(BaseModel):
    webhook_url: Optional[str] = None  # empty/null clears the webhook


@router.put("/webhook-config")
@limiter.limit("10/minute", key_func=get_partner_api_key)
async def update_webhook_config(
    request: Request,
    req: WebhookConfigRequest,
    ctx: PartnerContext = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db)
):
    m_res = await db.execute(select(MerchantProfile).where(MerchantProfile.id == ctx.merchant.id).with_for_update())
    merchant = m_res.scalar_one()

    if not req.webhook_url:
        merchant.webhook_url = None
        merchant.webhook_secret = None
        await db.commit()
        return {"webhook_url": None, "webhook_secret": None}

    merchant.webhook_url = req.webhook_url
    # A fresh secret every time the URL is (re)configured - never silently
    # reuse a secret the new endpoint has no way of already knowing.
    new_secret = f"whsec_{secrets.token_hex(16)}"
    merchant.webhook_secret = new_secret
    await db.commit()

    return {
        "webhook_url": merchant.webhook_url,
        "webhook_secret": new_secret,
        "warning": "Store this secret securely - it will not be shown again in full.",
    }
