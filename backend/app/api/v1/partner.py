import uuid
import asyncio
import secrets
from decimal import Decimal
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.core.database import get_db, AsyncSessionLocal
from app.core.partner_auth import get_current_partner, PartnerContext
from app.core.rate_limit import limiter, get_partner_api_key
from app.models.catalog import Country, Product
from app.models.merchant import MerchantProfile
from app.models.user import User
from app.models.wallet import Wallet, WalletType, LedgerRefType
from app.models.order import Order, OrderStatus, PaymentMethod
from app.schemas.catalog import CountryResponse, ProductResponse
from app.services.checkout_svc import get_effective_commission_rate, resolve_beneficiary, provision_esim, distribute_commission
from app.services.ledger_svc import LedgerService
from app.services.webhook_svc import deliver_webhook
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/partner", tags=["Partner API"])


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
        select(Product).where(Product.country_id == country.id, Product.is_active == True).order_by(Product.data_amount_gb.asc())
    )
    return p_res.scalars().all()


@router.get("/me")
@limiter.limit("120/minute", key_func=get_partner_api_key)
async def get_partner_profile(
    request: Request,
    ctx: PartnerContext = Depends(get_current_partner),
    db: AsyncSession = Depends(get_db)
):
    rate = await get_effective_commission_rate(db, ctx.user.id, ctx.merchant.commission_rate_pct)

    w_res = await db.execute(
        select(Wallet).where(Wallet.user_id == ctx.user.id, Wallet.wallet_type == WalletType.DEFAULT)
    )
    wallet = w_res.scalar_one_or_none()

    return {
        "business_name": ctx.merchant.business_name,
        "commission_rate_pct": rate,
        "wallet_balance": wallet.balance if wallet else 0,
        "wallet_currency": wallet.currency if wallet else "USD",
        "webhook_configured": bool(ctx.merchant.webhook_url),
    }


class PartnerOrderCreateRequest(BaseModel):
    product_id: str
    customer_reference: Optional[str] = None


def _serialize_order(order: Order) -> dict:
    profile = order.esim_profile
    return {
        "order_id": order.id,
        "order_no": order.order_no,
        "customer_reference": order.partner_customer_reference,
        "status": order.status.value,
        "iccid": profile.iccid if profile else None,
        "lpa_string": profile.lpa_string if profile else None,
        "qr_code_data": profile.qr_code_data if profile else None,
        "is_mock_fallback": profile.is_mock_fallback if profile else None,
        "created_at": order.created_at,
    }


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
    p_res = await db.execute(select(Product).where(Product.id == req.product_id, Product.is_active == True))
    product = p_res.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found or inactive")

    beneficiary_id = await resolve_beneficiary(db, ctx.user, True, True, None, None)

    total_cost = Decimal(str(product.retail_price))
    w_res = await db.execute(
        select(Wallet).where(Wallet.user_id == ctx.user.id, Wallet.wallet_type == WalletType.DEFAULT)
    )
    wallet = w_res.scalar_one_or_none()
    if not wallet or Decimal(str(wallet.balance)) < total_cost:
        raise HTTPException(status_code=400, detail="Insufficient wallet balance. Please top up.")

    order_no = f"PTR-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    order = Order(
        order_no=order_no,
        buyer_id=ctx.user.id,
        beneficiary_id=beneficiary_id,
        product_id=product.id,
        total_amount=total_cost,
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
    order_id = order.id

    asyncio.create_task(_process_partner_order_background(order_id))

    return {"order_id": order_id, "order_no": order_no, "status": "PROCESSING"}


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
    return _serialize_order(order)


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
