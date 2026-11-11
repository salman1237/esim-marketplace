"""Merchant dashboard API - a reseller's own view of their business from a
logged-in browser session: balances, sales, orders (placed on the
storefront or through the Partner API), commission, and their Partner API
integration settings.

It never places orders - buy-for-customer goes through the storefront
checkout (orders.py) and server-to-server orders through partner.py - so
nothing here can change how an order is charged or provisioned."""
import ipaddress
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.rate_limit import limiter
from app.models.catalog import Country, Product
from app.models.commission_tier import CommissionTier
from app.models.merchant import MerchantProfile, MerchantStatus
from app.models.order import ESIMProfile, Order, OrderStatus
from app.models.partner_api import ApiKey, WebhookDeliveryLog
from app.models.user import User, UserRole
from app.models.wallet import LedgerRefType, Wallet, WalletType
from app.services.audit_svc import AuditService
from app.services.checkout_svc import get_effective_commission_rate
from app.services.esim_links import esim_install_links
from app.services import agent_svc, esim_telemetry_svc, finance_svc
from app.services.ledger_svc import LedgerService
from app.services.webhook_svc import send_test_webhook

router = APIRouter(prefix="/merchant", tags=["Merchant Dashboard"])

# Partner API orders are numbered PTR-..., storefront orders ORD-...
API_ORDER_PREFIX = "PTR-"
MONEY = Decimal("0.0001")


@dataclass
class MerchantContext:
    user: User
    merchant: MerchantProfile


async def get_current_merchant(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MerchantContext:
    res = await db.execute(select(MerchantProfile).where(MerchantProfile.user_id == current_user.id))
    merchant = res.scalar_one_or_none()
    # Both checks: commission is only ever paid to the MERCHANT role, so a
    # demoted account with a leftover approved profile isn't a merchant.
    if current_user.role != UserRole.MERCHANT or not merchant or merchant.status != MerchantStatus.APPROVED:
        raise HTTPException(status_code=403, detail="An approved merchant account is required")
    return MerchantContext(user=current_user, merchant=merchant)


def _money(value) -> str:
    return str(Decimal(str(value or 0)).quantize(MONEY))


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _audit_request_meta(request: Request) -> dict:
    return {
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }


async def _wallet(db: AsyncSession, user_id: str, wallet_type: WalletType, lock: bool = False) -> Optional[Wallet]:
    query = select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == wallet_type)
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


async def _order_stats(db: AsyncSession, user_id: str, since: Optional[datetime] = None) -> dict:
    conditions = [Order.buyer_id == user_id, Order.is_reseller_order == True]
    if since is not None:
        conditions.append(Order.created_at >= since)
    completed = Order.status == OrderStatus.COMPLETED
    in_progress = Order.status.in_([OrderStatus.PENDING, OrderStatus.PAID, OrderStatus.PROCESSING])
    total, n_completed, n_failed, n_open, volume, commission = (await db.execute(
        select(
            func.count(Order.id),
            func.count(Order.id).filter(completed),
            func.count(Order.id).filter(Order.status == OrderStatus.FAILED),
            func.count(Order.id).filter(in_progress),
            func.coalesce(func.sum(Order.total_amount).filter(completed), 0),
            func.coalesce(func.sum(Order.reseller_commission_amount).filter(completed), 0),
        ).where(*conditions)
    )).one()
    settled = n_completed + n_failed
    return {
        "orders": total,
        "completed": n_completed,
        "failed": n_failed,
        "in_progress": n_open,
        "success_rate_pct": round(n_completed * 100 / settled, 1) if settled else None,
        "volume": _money(volume),
        "commission": _money(commission),
    }


async def _commission_info(db: AsyncSession, merchant: MerchantProfile, completed_volume: Decimal) -> dict:
    """Everything here is the merchant's NET rate - what they are actually
    paid, after any agent bonus.

    The pre-deduction rate and the bonus itself are deliberately absent from
    this response and from every other merchant-facing one: the client's rule
    is that a merchant must not learn their agent takes a share. The number
    below is therefore the single rate the merchant sees anywhere, and it is
    the same one distribute_commission pays them.
    """
    gross_flat = Decimal(str(merchant.commission_rate_pct))
    gross_effective = Decimal(str(await get_effective_commission_rate(db, merchant.user_id, gross_flat)))
    effective = await agent_svc.effective_merchant_rate(db, merchant, gross_effective)
    # The headline flat rate must move with the deduction too, or the two
    # numbers on the dashboard would not agree and would give it away.
    flat = max(Decimal("0"), gross_flat - (gross_effective - effective))

    tiers = (await db.execute(select(CommissionTier).order_by(CommissionTier.min_volume_usd.asc()))).scalars().all()
    next_tier = next(
        (t for t in tiers
         if Decimal(str(t.min_volume_usd)) > completed_volume and Decimal(str(t.rate_pct)) > gross_effective),
        None,
    )
    next_tier_net = None
    if next_tier:
        tier_rate = Decimal(str(next_tier.rate_pct))
        next_tier_net = max(Decimal("0"), tier_rate - agent_svc.bonus_pct_for(merchant, tier_rate))

    return {
        "flat_rate_pct": str(flat),
        "effective_rate_pct": str(effective),
        "completed_volume": _money(completed_volume),
        "next_tier": {
            "min_volume": _money(next_tier.min_volume_usd),
            "rate_pct": str(next_tier_net),
            "volume_remaining": _money(Decimal(str(next_tier.min_volume_usd)) - completed_volume),
        } if next_tier else None,
    }


def _with_order_joins(stmt):
    return (
        stmt.join(Product, Order.product_id == Product.id)
        .join(Country, Product.country_id == Country.id)
        .join(User, Order.beneficiary_id == User.id)
        .outerjoin(ESIMProfile, ESIMProfile.order_id == Order.id)
    )


def _order_rows_stmt(user_id: str):
    return _with_order_joins(
        select(Order, Product, Country.iso2, User, ESIMProfile).select_from(Order)
    ).where(Order.buyer_id == user_id, Order.is_reseller_order == True)


def _serialize_order(order: Order, product: Product, country_iso2: str, beneficiary: User, profile, detail: bool = False) -> dict:
    is_api = order.order_no.startswith(API_ORDER_PREFIX)
    data = {
        "order_id": order.id,
        "order_no": order.order_no,
        "source": "api" if is_api else "web",
        "customer_reference": order.partner_customer_reference,
        # API orders are issued to an auto-created placeholder account, so
        # the partner's own customer_reference identifies the customer there.
        "customer": None if is_api else {"username": beneficiary.username, "email": beneficiary.email},
        "product": {
            "id": product.id,
            "title": product.title_en,
            "country_iso2": country_iso2,
            "data_amount_gb": float(product.data_amount_gb) if product.data_amount_gb is not None else None,
            "is_unlimited": bool(product.is_unlimited),
            "validity_days": product.validity_days,
        },
        "amount": _money(order.total_amount),
        "currency": order.currency,
        "commission_earned": _money(order.reseller_commission_amount),
        "status": order.status.value,
        "payment_method": order.payment_method.value,
        "iccid": profile.iccid if profile else None,
        "created_at": _iso(order.created_at),
        "updated_at": _iso(order.updated_at),
    }
    if detail:
        lpa = profile.lpa_string if profile else None
        data.update({
            "lpa_string": lpa,
            "qr_code_data": profile.qr_code_data if profile else None,
            "smdp_address": profile.smdp_address if profile else None,
            "matching_id": profile.matching_id if profile else None,
            "install_links": esim_install_links(lpa),
        })
    return data


@router.get("/overview")
async def get_overview(ctx: MerchantContext = Depends(get_current_merchant), db: AsyncSession = Depends(get_db)):
    user_id = ctx.user.id
    default_wallet = await _wallet(db, user_id, WalletType.DEFAULT)
    commission_wallet = await _wallet(db, user_id, WalletType.COMMISSION)
    all_time = await _order_stats(db, user_id)
    last_30_days = await _order_stats(db, user_id, since=datetime.now(timezone.utc) - timedelta(days=30))

    key = (await db.execute(
        select(ApiKey).where(ApiKey.merchant_id == ctx.merchant.id, ApiKey.is_active == True)
        .order_by(ApiKey.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    recent = (await db.execute(_order_rows_stmt(user_id).order_by(Order.created_at.desc()).limit(5))).all()

    return {
        "business": {
            "name": ctx.merchant.business_name,
            "contact_phone": ctx.merchant.contact_phone,
            "status": ctx.merchant.status.value,
            "member_since": _iso(ctx.merchant.created_at),
        },
        "wallets": {
            "wallet_balance": _money(default_wallet.balance if default_wallet else 0),
            "commission_balance": _money(commission_wallet.balance if commission_wallet else 0),
            "currency": settings.BASE_CURRENCY,
        },
        "stats": {"last_30_days": last_30_days, "all_time": all_time},
        "commission": await _commission_info(db, ctx.merchant, Decimal(all_time["volume"])),
        "api": {
            "key_active": key is not None,
            "key_prefix": key.key_prefix if key else None,
            "key_last_used_at": _iso(key.last_used_at) if key else None,
            "webhook_configured": bool(ctx.merchant.webhook_url),
        },
        "recent_orders": [_serialize_order(*row) for row in recent],
    }


@router.get("/orders")
async def list_orders(
    status: Optional[OrderStatus] = None,
    source: str = Query("all", pattern="^(all|web|api)$"),
    q: Optional[str] = None,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ctx: MerchantContext = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    conditions = [Order.buyer_id == ctx.user.id, Order.is_reseller_order == True]
    if status:
        conditions.append(Order.status == status)
    if source == "api":
        conditions.append(Order.order_no.startswith(API_ORDER_PREFIX))
    elif source == "web":
        conditions.append(~Order.order_no.startswith(API_ORDER_PREFIX))
    if q and q.strip():
        like = f"%{q.strip()}%"
        conditions.append(or_(
            Order.order_no.ilike(like),
            Order.partner_customer_reference.ilike(like),
            ESIMProfile.iccid.ilike(like),
            User.email.ilike(like),
            User.username.ilike(like),
            Product.title_en.ilike(like),
        ))

    total = (await db.execute(
        _with_order_joins(select(func.count(Order.id)).select_from(Order)).where(*conditions)
    )).scalar_one()
    rows = (await db.execute(
        _with_order_joins(select(Order, Product, Country.iso2, User, ESIMProfile).select_from(Order))
        .where(*conditions).order_by(Order.created_at.desc()).limit(limit).offset(offset)
    )).all()
    return {"orders": [_serialize_order(*row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/orders/{order_id}")
async def get_order(order_id: str, ctx: MerchantContext = Depends(get_current_merchant), db: AsyncSession = Depends(get_db)):
    row = (await db.execute(_order_rows_stmt(ctx.user.id).where(Order.id == order_id))).first()
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")

    deliveries = (await db.execute(
        select(WebhookDeliveryLog)
        .where(WebhookDeliveryLog.order_id == order_id, WebhookDeliveryLog.merchant_id == ctx.merchant.id)
        .order_by(WebhookDeliveryLog.created_at.desc())
    )).scalars().all()

    data = _serialize_order(*row, detail=True)
    data["webhook_deliveries"] = [
        {"attempt": d.attempt, "success": d.success, "response_status": d.response_status, "created_at": _iso(d.created_at)}
        for d in deliveries
    ]

    # Live status for the partner's own customer support: has the customer
    # installed it, on what handset, how much data have they used. Same shape
    # and same cache the customer sees, so the two never disagree.
    order, product, _iso2, _beneficiary, profile = row
    if profile:
        telemetry = await esim_telemetry_svc.get_telemetry(db, profile, product, order)
        data["live_status"] = esim_telemetry_svc.serialize(telemetry, profile, product, order)
    return data


class CommissionTransferRequest(BaseModel):
    # Omitted = transfer the whole commission balance.
    amount: Optional[str] = None


@router.post("/commission/transfer")
@limiter.limit("10/minute")
async def transfer_commission(
    request: Request,
    req: CommissionTransferRequest,
    ctx: MerchantContext = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """Moves earned commission into the main wallet, where it can pay for
    orders. Both ledger entries land in one transaction."""
    commission_wallet = await _wallet(db, ctx.user.id, WalletType.COMMISSION, lock=True)
    default_wallet = await _wallet(db, ctx.user.id, WalletType.DEFAULT, lock=True)
    if not commission_wallet or not default_wallet:
        raise HTTPException(status_code=400, detail="Wallet not found")

    available = Decimal(str(commission_wallet.balance))
    if req.amount is None or str(req.amount).strip() == "":
        amount = available
    else:
        try:
            amount = Decimal(str(req.amount).strip()).quantize(MONEY)
        except InvalidOperation:
            raise HTTPException(status_code=400, detail="Enter a valid amount")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="There is no commission to transfer" if req.amount is None else "Amount must be greater than zero")
    if amount > available:
        raise HTTPException(status_code=400, detail="Amount exceeds your commission balance")

    transfer_id = str(uuid.uuid4())
    await LedgerService.debit(
        db, commission_wallet.id, amount, LedgerRefType.COMMISSION_TRANSFER,
        ref_id=transfer_id, description="Transferred to main wallet",
        idempotency_key=f"commission-transfer-{transfer_id}-out",
    )
    await LedgerService.credit(
        db, default_wallet.id, amount, LedgerRefType.COMMISSION_TRANSFER,
        ref_id=transfer_id, description="Transferred from commission wallet",
        idempotency_key=f"commission-transfer-{transfer_id}-in",
    )
    await AuditService.log_action(
        db, actor_id=ctx.user.id, actor_role=ctx.user.role.value,
        action="MERCHANT_COMMISSION_TRANSFER",
        after_state={"transfer_id": transfer_id, "amount": _money(amount)},
        **_audit_request_meta(request),
    )
    await db.commit()
    return {
        "transferred": _money(amount),
        "commission_balance": _money(commission_wallet.balance),
        "wallet_balance": _money(default_wallet.balance),
    }


def _statement_month(month: Optional[str]):
    try:
        return finance_svc.month_bounds(month or datetime.now(timezone.utc).strftime("%Y-%m"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/statement")
async def my_monthly_statement(
    month: Optional[str] = None,
    ctx: MerchantContext = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """The same statement the admin sees for this merchant - both sides
    reconcile against one set of numbers."""
    start, end = _statement_month(month)
    return await finance_svc.merchant_statement(db, ctx.user.id, start, end)


@router.get("/statement.csv")
async def my_monthly_statement_csv(
    month: Optional[str] = None,
    ctx: MerchantContext = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    start, end = _statement_month(month)
    statement = await finance_svc.merchant_statement(db, ctx.user.id, start, end)
    return Response(
        content=finance_svc.statement_csv(statement),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="statement-{statement["period"]["month"]}.csv"'},
    )


@router.get("/api-access")
async def get_api_access(ctx: MerchantContext = Depends(get_current_merchant), db: AsyncSession = Depends(get_db)):
    key = (await db.execute(
        select(ApiKey).where(ApiKey.merchant_id == ctx.merchant.id, ApiKey.is_active == True)
        .order_by(ApiKey.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    deliveries = (await db.execute(
        select(WebhookDeliveryLog, Order.order_no)
        .join(Order, WebhookDeliveryLog.order_id == Order.id)
        .where(WebhookDeliveryLog.merchant_id == ctx.merchant.id)
        .order_by(WebhookDeliveryLog.created_at.desc()).limit(20)
    )).all()

    return {
        "base_url": f"{settings.FRONTEND_BASE_URL}/api/v1/partner",
        "docs_url": f"{settings.FRONTEND_BASE_URL}/api-docs",
        # The full key is only ever shown once, to the admin who issues it.
        "key": {
            "active": key is not None,
            "prefix": key.key_prefix if key else None,
            "created_at": _iso(key.created_at) if key else None,
            "last_used_at": _iso(key.last_used_at) if key else None,
        },
        "webhook": {"url": ctx.merchant.webhook_url, "configured": bool(ctx.merchant.webhook_url)},
        "recent_deliveries": [
            {
                "order_id": log.order_id,
                "order_no": order_no,
                "attempt": log.attempt,
                "success": log.success,
                "response_status": log.response_status,
                "created_at": _iso(log.created_at),
            }
            for log, order_no in deliveries
        ],
    }


def _validate_webhook_url(raw: str) -> str:
    url = raw.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        # Deliveries carry eSIM activation codes - never over plain http.
        raise HTTPException(status_code=400, detail="Webhook URL must be a full https:// URL")
    if len(url) > 500:
        raise HTTPException(status_code=400, detail="Webhook URL is too long")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise HTTPException(status_code=400, detail="Webhook URL must be publicly reachable")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified):
        raise HTTPException(status_code=400, detail="Webhook URL must be publicly reachable")
    return url


class MerchantWebhookRequest(BaseModel):
    webhook_url: Optional[str] = None  # empty/null clears the webhook


@router.put("/webhook-config")
@limiter.limit("10/minute")
async def update_webhook_config(
    request: Request,
    req: MerchantWebhookRequest,
    ctx: MerchantContext = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """Same effect as the Partner API's PUT /partner/webhook-config, for a
    merchant working from the dashboard rather than their own backend."""
    merchant = (await db.execute(
        select(MerchantProfile).where(MerchantProfile.id == ctx.merchant.id).with_for_update()
    )).scalar_one()
    before = {"webhook_url": merchant.webhook_url}

    if not req.webhook_url or not req.webhook_url.strip():
        merchant.webhook_url = None
        merchant.webhook_secret = None
        response = {"webhook_url": None, "webhook_secret": None}
    else:
        merchant.webhook_url = _validate_webhook_url(req.webhook_url)
        # A fresh secret on every change, exactly like the Partner API.
        merchant.webhook_secret = f"whsec_{secrets.token_hex(16)}"
        response = {
            "webhook_url": merchant.webhook_url,
            "webhook_secret": merchant.webhook_secret,
            "warning": "Store this secret securely - it will not be shown again in full.",
        }

    await AuditService.log_action(
        db, actor_id=ctx.user.id, actor_role=ctx.user.role.value,
        action="MERCHANT_WEBHOOK_UPDATED",
        before_state=before, after_state={"webhook_url": merchant.webhook_url},
        **_audit_request_meta(request),
    )
    await db.commit()
    return response


@router.post("/webhook-test")
@limiter.limit("5/minute")
async def test_webhook(
    request: Request,
    ctx: MerchantContext = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    if not ctx.merchant.webhook_url or not ctx.merchant.webhook_secret:
        raise HTTPException(status_code=400, detail="Set a webhook URL first")
    return await send_test_webhook(ctx.merchant)
