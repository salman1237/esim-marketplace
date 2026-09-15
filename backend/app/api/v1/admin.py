import asyncio
import csv
import io
import uuid
import secrets
import hashlib
from decimal import Decimal
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from app.core.config import settings
from app.core.database import get_db, AsyncSessionLocal
from app.core.deps import require_admin, require_super_admin
from app.core.security import get_password_hash
from app.models.user import User, UserRole, UserStatus
from app.models.merchant import MerchantProfile, MerchantStatus
from app.models.wallet import Wallet, WalletType, LedgerRefType
from app.models.order import Order, ESIMProfile, OrderStatus, PaymentMethod
from app.models.catalog import Country, Product
from app.models.payment import ManualPaymentRequest, ManualPaymentStatus
from app.models.settings import PlatformSetting, CurrencyRate, Language, Translation
from app.models.audit import AuditLog, SupplierTransactionLog
from app.models.kyc import KYCSubmission, KYCStatus
from app.models.commission_tier import CommissionTier
from app.models.partner_api import ApiKey
from datetime import date as Date, datetime, timedelta, timezone
from app.core.seed_translations import EN_TRANSLATIONS, flatten
from app.schemas.settings import (
    UpdateBrandingRequest, CurrencyOverrideRequest, LanguageToggleRequest,
    LanguageCreateRequest, TranslationUpsertRequest, UpdatePaymentMethodsRequest, UpdateLegalDocumentRequest,
)
from app.services.ledger_svc import LedgerService
from app.services.payment_methods_svc import get_payment_methods, set_payment_methods
from app.services.legal_content_svc import LEGAL_TITLES, get_legal_document, save_legal_document
from app.services import gateway_config_svc
from app.services.catalog_export_svc import build_catalog_workbook
from app.services.shurjopay_svc import ShurjoPayService
from app.services.pricing_svc import MAX_SELLING_PROFIT_PCT, get_selling_profit_pct, retail_price_for, set_selling_profit_pct
from app.services.audit_svc import AuditService
from app.services.catalog_sync_svc import sync_vivape_catalog
from app.services.currency_svc import CurrencyService
from app.services.checkout_svc import provision_esim
from app.services.email_svc import EmailService


from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from app.core.logging import get_logger

logger = get_logger(__name__)


class ProductUpdateRequest(BaseModel):
    retail_price: Optional[float] = None
    is_active: Optional[bool] = None

class UserRoleUpdateRequest(BaseModel):
    role: UserRole

class UserStatusUpdateRequest(BaseModel):
    is_active: bool

class MerchantCommissionUpdateRequest(BaseModel):
    rate_pct: Decimal = Field(..., ge=0, le=100)

class CommissionTierCreateRequest(BaseModel):
    min_volume_usd: Decimal = Field(..., ge=0)
    rate_pct: Decimal = Field(..., ge=0, le=100)

class StaffAccountCreateRequest(BaseModel):
    email: EmailStr
    username: str
    password: str
    role: UserRole
    full_name: Optional[str] = None

router = APIRouter(prefix="/admin", tags=["Admin & Super Admin"])

# --- Overview & Analytics ---
@router.get("/stats", dependencies=[Depends(require_admin)])
async def get_admin_stats(db: AsyncSession = Depends(get_db)):
    users_count = await db.scalar(select(func.count(User.id)))
    orders_count = await db.scalar(select(func.count(Order.id)))
    revenue = await db.scalar(select(func.sum(Order.total_amount)))
    esims_count = await db.scalar(select(func.count(ESIMProfile.id)))

    return {
        "total_users": users_count or 0,
        "total_orders": orders_count or 0,
        "total_revenue": float(revenue or 0),
        "currency": settings.BASE_CURRENCY,
        "total_esims_issued": esims_count or 0
    }

# --- Catalog Sync & Pricing ---
@router.post("/catalog/sync", dependencies=[Depends(require_admin)])
async def sync_catalog_from_vivape(db: AsyncSession = Depends(get_db)):
    return await sync_vivape_catalog(db)

# --- Merchant Approval Queue ---
@router.get("/merchants/queue", dependencies=[Depends(require_admin)])
async def get_merchant_queue(db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(MerchantProfile, User).join(User, MerchantProfile.user_id == User.id)
    )
    return [
        {
            "id": m.id,
            "user_id": u.id,
            "username": u.username,
            "email": u.email,
            "business_name": m.business_name,
            "trade_license": m.trade_license,
            "contact_phone": m.contact_phone,
            "status": m.status.value,
            "commission_rate_pct": float(m.commission_rate_pct),
            "created_at": m.created_at
        }
        for m, u in res.all()
    ]

@router.put("/merchants/{merchant_id}/commission", dependencies=[Depends(require_super_admin)])
async def update_merchant_commission(
    merchant_id: str,
    req: MerchantCommissionUpdateRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(MerchantProfile).where(MerchantProfile.id == merchant_id))
    m = res.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found")

    before_rate = float(m.commission_rate_pct)
    m.commission_rate_pct = req.rate_pct

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_MERCHANT_COMMISSION",
        before_state={"merchant_id": m.id, "commission_rate_pct": before_rate},
        after_state={"merchant_id": m.id, "commission_rate_pct": float(req.rate_pct)},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success", "commission_rate_pct": float(req.rate_pct)}


# --- Partner Reseller API Keys ---
@router.get("/merchants/{merchant_id}/api-key", dependencies=[Depends(require_admin)])
async def get_partner_api_key_status(merchant_id: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(ApiKey).where(ApiKey.merchant_id == merchant_id, ApiKey.is_active == True)
    )
    key = res.scalar_one_or_none()
    if not key:
        return {"has_active_key": False}
    return {
        "has_active_key": True,
        "key_prefix": key.key_prefix,
        "created_at": key.created_at,
        "last_used_at": key.last_used_at,
    }

@router.post("/merchants/{merchant_id}/api-key", dependencies=[Depends(require_super_admin)])
async def generate_partner_api_key(
    merchant_id: str,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(MerchantProfile).where(MerchantProfile.id == merchant_id))
    m = res.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found")
    if m.status != MerchantStatus.APPROVED:
        raise HTTPException(status_code=400, detail="Merchant must be approved before issuing a Partner API key")

    # One active key per merchant for v1 - generating a new one retires
    # any existing key rather than allowing several live at once.
    existing_res = await db.execute(
        select(ApiKey).where(ApiKey.merchant_id == merchant_id, ApiKey.is_active == True)
    )
    for existing in existing_res.scalars().all():
        existing.is_active = False
        existing.revoked_at = datetime.now(timezone.utc)

    raw_key = f"esim_live_{secrets.token_hex(16)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    new_key = ApiKey(merchant_id=merchant_id, key_prefix=raw_key[:16], key_hash=key_hash)
    db.add(new_key)

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="GENERATE_PARTNER_API_KEY",
        after_state={"merchant_id": merchant_id, "key_prefix": new_key.key_prefix},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {
        "status": "success",
        "api_key": raw_key,
        "key_prefix": new_key.key_prefix,
        "warning": "This is the only time the full key is shown - store it securely.",
    }

@router.delete("/merchants/{merchant_id}/api-key", dependencies=[Depends(require_super_admin)])
async def revoke_partner_api_key(
    merchant_id: str,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(ApiKey).where(ApiKey.merchant_id == merchant_id, ApiKey.is_active == True)
    )
    keys = res.scalars().all()
    if not keys:
        raise HTTPException(status_code=404, detail="No active API key for this merchant")
    for k in keys:
        k.is_active = False
        k.revoked_at = datetime.now(timezone.utc)

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="REVOKE_PARTNER_API_KEY", before_state={"merchant_id": merchant_id},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success"}


# --- Commission Tiers (global, volume-based - see
# checkout_svc.get_effective_commission_rate for how these apply) ---
@router.get("/commission-tiers", dependencies=[Depends(require_admin)])
async def list_commission_tiers(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(CommissionTier).order_by(CommissionTier.min_volume_usd.asc()))
    return [
        {"id": t.id, "min_volume_usd": float(t.min_volume_usd), "rate_pct": float(t.rate_pct)}
        for t in res.scalars().all()
    ]

@router.post("/commission-tiers", dependencies=[Depends(require_super_admin)])
async def create_commission_tier(
    req: CommissionTierCreateRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    existing = await db.execute(select(CommissionTier).where(CommissionTier.min_volume_usd == req.min_volume_usd))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="A tier already exists at that volume threshold")

    tier = CommissionTier(min_volume_usd=req.min_volume_usd, rate_pct=req.rate_pct)
    db.add(tier)
    await db.flush()

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="CREATE_COMMISSION_TIER",
        after_state={"min_volume_usd": float(req.min_volume_usd), "rate_pct": float(req.rate_pct)},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"id": tier.id, "min_volume_usd": float(tier.min_volume_usd), "rate_pct": float(tier.rate_pct)}

@router.delete("/commission-tiers/{tier_id}", dependencies=[Depends(require_super_admin)])
async def delete_commission_tier(
    tier_id: str,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(CommissionTier).where(CommissionTier.id == tier_id))
    tier = res.scalar_one_or_none()
    if not tier:
        raise HTTPException(status_code=404, detail="Tier not found")

    before = {"min_volume_usd": float(tier.min_volume_usd), "rate_pct": float(tier.rate_pct)}
    await db.delete(tier)

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="DELETE_COMMISSION_TIER", before_state=before,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success"}


@router.post("/merchants/{merchant_id}/approve", dependencies=[Depends(require_admin)])
async def approve_merchant(
    merchant_id: str,
    request: Request,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(MerchantProfile).where(MerchantProfile.id == merchant_id))
    m = res.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant application not found")
    if m.status != MerchantStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Application already {m.status.value.lower()}")

    m.status = MerchantStatus.APPROVED
    m.reviewed_by_id = admin_user.id

    # Upgrade user role
    u_res = await db.execute(select(User).where(User.id == m.user_id))
    user = u_res.scalar_one_or_none()
    if user:
        user.role = UserRole.MERCHANT
        await LedgerService.ensure_wallets_for_user(db, user.id, UserRole.MERCHANT)

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="APPROVE_MERCHANT", after_state={"merchant_id": m.id, "business": m.business_name},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success", "message": "Merchant approved"}


@router.post("/merchants/{merchant_id}/reject", dependencies=[Depends(require_admin)])
async def reject_merchant(
    merchant_id: str,
    request: Request,
    reason: Optional[str] = None,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(MerchantProfile).where(MerchantProfile.id == merchant_id))
    m = res.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant application not found")
    if m.status != MerchantStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Application already {m.status.value.lower()}")

    m.status = MerchantStatus.REJECTED
    m.reviewed_by_id = admin_user.id
    m.rejection_reason = reason

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="REJECT_MERCHANT", after_state={"merchant_id": m.id, "reason": reason},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success", "message": "Merchant application rejected"}

# --- Manual Payments Queue ---
@router.get("/payments/manual-queue", dependencies=[Depends(require_admin)])
async def get_manual_payments(db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(ManualPaymentRequest, User).join(User, ManualPaymentRequest.user_id == User.id)
        .order_by(ManualPaymentRequest.created_at.desc())
    )
    return [
        {
            "id": p.id,
            "username": u.username,
            "email": u.email,
            "amount": float(p.amount),
            "currency": p.currency,
            "bank_name": p.bank_name,
            "transaction_id": p.transaction_id,
            "receipt_url": p.receipt_url,
            "status": p.status.value,
            "created_at": p.created_at
        }
        for p, u in res.all()
    ]

@router.post("/payments/manual/{request_id}/approve", dependencies=[Depends(require_admin)])
async def approve_manual_payment(
    request_id: str,
    request: Request,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(ManualPaymentRequest).where(ManualPaymentRequest.id == request_id))
    p = res.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Payment request not found")
    if p.status != ManualPaymentStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Request already {p.status.value.lower()}")

    p.status = ManualPaymentStatus.APPROVED
    p.reviewed_by_id = admin_user.id

    # Credit Default Wallet
    w_res = await db.execute(
        select(Wallet).where(Wallet.user_id == p.user_id, Wallet.wallet_type == WalletType.DEFAULT)
    )
    wallet = w_res.scalar_one_or_none()
    if wallet:
        # Convert the deposited currency (usually BDT) into the base currency.
        rate = await CurrencyService.get_effective_rate(db, p.currency)
        amount_base = (Decimal(str(p.amount)) / rate).quantize(Decimal("0.0001"))
        await LedgerService.credit(
            db, wallet.id, amount_base,
            LedgerRefType.DEPOSIT_MANUAL,
            ref_id=p.id,
            description=f"Manual Deposit Approved ({p.amount} {p.currency})",
            idempotency_key=f"manual-payment-{p.id}"
        )

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="APPROVE_MANUAL_PAYMENT", after_state={"payment_id": p.id, "amount": float(p.amount)},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success", "message": "Payment approved and wallet credited"}


@router.post("/payments/manual/{request_id}/reject", dependencies=[Depends(require_admin)])
async def reject_manual_payment(
    request_id: str,
    request: Request,
    reason: Optional[str] = None,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(ManualPaymentRequest).where(ManualPaymentRequest.id == request_id))
    p = res.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Payment request not found")
    if p.status != ManualPaymentStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Request already {p.status.value.lower()}")

    p.status = ManualPaymentStatus.REJECTED
    p.reviewed_by_id = admin_user.id
    p.admin_notes = reason

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="REJECT_MANUAL_PAYMENT", after_state={"payment_id": p.id, "reason": reason},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success", "message": "Payment request rejected"}


# --- Customer Wallet & Order Actions (Admin console "Customer Wallet" tab) ---
# Available to both Admin and Super Admin, matching the manual-deposit
# approval gate above - the admin action here *is* the approval, there's
# no separate review step. A narrower search endpoint than GET /users
# (which is Super-Admin-only, since it also exposes role editing) so a
# plain Admin can find a customer without gaining that broader access.

@router.get("/customers/search", dependencies=[Depends(require_admin)])
async def search_customers(q: str = Query(..., min_length=2), db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(User).where(
            (User.username.ilike(f"%{q}%")) | (User.email.ilike(f"%{q}%"))
        ).limit(10)
    )
    users = res.scalars().all()
    results = []
    for u in users:
        w_res = await db.execute(
            select(Wallet).where(Wallet.user_id == u.id, Wallet.wallet_type == WalletType.DEFAULT)
        )
        wallet = w_res.scalar_one_or_none()
        results.append({
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "role": u.role.value,
            "wallet_balance": float(wallet.balance) if wallet else 0.0,
        })
    return results


class RechargeWalletRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    description: Optional[str] = None


@router.post("/customers/{user_id}/wallet/recharge", dependencies=[Depends(require_admin)])
async def recharge_customer_wallet(
    user_id: str,
    req: RechargeWalletRequest,
    request: Request,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    w_res = await db.execute(select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.DEFAULT))
    wallet = w_res.scalar_one_or_none()
    if not wallet:
        raise HTTPException(status_code=404, detail="Customer wallet not found")

    entry = await LedgerService.credit(
        db, wallet.id, req.amount,
        LedgerRefType.ADMIN_ADJUSTMENT,
        ref_id=None,
        description=req.description or f"Admin balance recharge by {admin_user.username}",
        idempotency_key=None
    )

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="ADMIN_RECHARGE_CUSTOMER_WALLET",
        after_state={"target_user_id": user_id, "amount": str(req.amount), "new_balance": str(entry.balance_after)},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success", "new_balance": float(entry.balance_after)}


async def _send_order_confirmation_background(email: str, order_no: str, product_title: str, iccid: str, lpa_string: str, **details):
    # Own session, not the request's - that one closes as soon as the
    # response is returned, before this background task gets to run.
    # Mirrors the same helper in orders.py / payments.py.
    async with AsyncSessionLocal() as bg_db:
        try:
            await EmailService.send_order_confirmation(bg_db, email, order_no, product_title, iccid, lpa_string, **details)
        except Exception as e:
            logger.warning("order_confirmation_email_background_task_failed", email=email, error=str(e))


class AdminPurchaseEsimRequest(BaseModel):
    product_id: str


@router.post("/customers/{user_id}/purchase-esim", dependencies=[Depends(require_admin)])
async def admin_purchase_esim_for_customer(
    user_id: str,
    req: AdminPurchaseEsimRequest,
    request: Request,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Admin-triggered purchase on behalf of an existing customer - charges
    the customer's own wallet (not the admin's), same as if they'd bought
    it themselves. Not a reseller order (no commission)."""
    target_res = await db.execute(select(User).where(User.id == user_id))
    target = target_res.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Customer not found")

    p_res = await db.execute(select(Product).where(Product.id == req.product_id, Product.is_active == True))
    product = p_res.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found or inactive")

    total_cost = Decimal(str(product.retail_price))
    w_res = await db.execute(select(Wallet).where(Wallet.user_id == target.id, Wallet.wallet_type == WalletType.DEFAULT))
    wallet = w_res.scalar_one_or_none()
    if not wallet or Decimal(str(wallet.balance)) < total_cost:
        raise HTTPException(status_code=400, detail="Customer has insufficient wallet balance.")

    order_no = f"ADM-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    order = Order(
        order_no=order_no,
        buyer_id=target.id,
        beneficiary_id=target.id,
        product_id=product.id,
        total_amount=total_cost,
        cost_amount=product.cost_price,
        currency=product.currency,
        payment_method=PaymentMethod.WALLET,
        status=OrderStatus.PROCESSING,
        is_reseller_order=False,
    )
    db.add(order)
    await db.flush()

    try:
        await LedgerService.debit(
            db, wallet.id, total_cost,
            LedgerRefType.ORDER_PURCHASE,
            ref_id=order.id,
            description=f"Purchase eSIM (admin-assisted): {product.title_en}",
            idempotency_key=f"order-debit-{order.id}"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    profile = await provision_esim(db, order, product, target.id, admin_user.id, admin_user.role.value)

    if not profile:
        await db.commit()
        raise HTTPException(status_code=502, detail="eSIM provisioning failed. The customer's payment has been refunded to their wallet.")

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="ADMIN_PURCHASE_ESIM_FOR_CUSTOMER",
        after_state={"order_id": order.id, "target_user_id": target.id, "product_id": product.id},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()

    # The customer gets the same eSIM delivery email as a self-service
    # purchase - an admin buying on their behalf shouldn't leave them
    # without the ICCID and activation code.
    if target.email:
        asyncio.create_task(_send_order_confirmation_background(
            target.email, order.order_no, product.title_en, profile.iccid, profile.lpa_string,
            validity_days=product.validity_days,
            data_label="Unlimited" if product.is_unlimited else f"{product.data_amount_gb} GB",
            purchase_reference=profile.supplier_reference,
            purchased_at=order.created_at,
        ))

    return {"order_id": order.id, "order_no": order_no, "status": order.status.value, "iccid": profile.iccid}


# --- Super Admin Controls: Branding, Currency, Languages ---
@router.put("/branding", dependencies=[Depends(require_super_admin)])
async def update_branding(
    req: UpdateBrandingRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    updates = req.model_dump(exclude_unset=True)
    before = {}
    for k, v in updates.items():
        res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == k))
        setting = res.scalar_one_or_none()
        if setting:
            before[k] = setting.value
            setting.value = v
            setting.updated_by_id = admin_user.id
        else:
            setting = PlatformSetting(key=k, value=v, is_public=True, updated_by_id=admin_user.id)
            db.add(setting)

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_BRANDING", before_state=before, after_state=updates,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success", "updated": list(updates.keys())}

class ShurjoPayConfigRequest(BaseModel):
    mode: str = Field(..., pattern="^(live|sandbox)$")
    username: str = Field(..., min_length=1, max_length=100)
    # Blank keeps the saved password - it is never sent back to the browser.
    password: Optional[str] = Field(default=None, max_length=200)
    prefix: str = Field(..., min_length=2, max_length=10)


@router.get("/payment-gateways/shurjopay", dependencies=[Depends(require_super_admin)])
async def get_shurjopay_settings(db: AsyncSession = Depends(get_db)):
    return await gateway_config_svc.describe_shurjopay_config(db)


@router.put("/payment-gateways/shurjopay", dependencies=[Depends(require_super_admin)])
async def update_shurjopay_settings(
    req: ShurjoPayConfigRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        config = await gateway_config_svc.candidate_config(db, req.mode, req.username, req.password, req.prefix)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    change = await gateway_config_svc.save_shurjopay_config(db, config, admin_user.id)
    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_SHURJOPAY_CONFIG", before_state=change["before"], after_state=change["after"],
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return await gateway_config_svc.describe_shurjopay_config(db)


@router.delete("/payment-gateways/shurjopay", dependencies=[Depends(require_super_admin)])
async def reset_shurjopay_settings(
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Removes the admin-saved credentials; the server's environment settings apply again."""
    removed = await gateway_config_svc.clear_shurjopay_config(db)
    if removed:
        await AuditService.log_action(
            db, actor_id=admin_user.id, actor_role=admin_user.role.value,
            action="RESET_SHURJOPAY_CONFIG",
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    await db.commit()
    return await gateway_config_svc.describe_shurjopay_config(db)


@router.post("/payment-gateways/shurjopay/test", dependencies=[Depends(require_super_admin)])
async def test_shurjopay_settings(req: Optional[ShurjoPayConfigRequest] = None, db: AsyncSession = Depends(get_db)):
    """Logs in to ShurjoPay with the form's values (or the active settings)
    to confirm they work before customers depend on them. The token is
    never returned."""
    try:
        config = (
            await gateway_config_svc.candidate_config(db, req.mode, req.username, req.password, req.prefix)
            if req else await gateway_config_svc.get_shurjopay_config(db)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        data = await ShurjoPayService.authenticate(db, config)
    except Exception as e:
        logger.warning("shurjopay_test_connection_failed", error=str(e))
        return {"ok": False, "mode": config.mode, "message": "Couldn't reach ShurjoPay - try again in a moment"}
    if isinstance(data, dict) and data.get("token"):
        return {"ok": True, "mode": config.mode, "store_id": data.get("store_id"), "message": "Connected - ShurjoPay accepted these credentials"}
    message = (data.get("message") or data.get("sp_message")) if isinstance(data, dict) else None
    return {"ok": False, "mode": config.mode, "message": message or "ShurjoPay rejected these credentials"}


@router.get("/payment-methods", dependencies=[Depends(require_admin)])
async def list_payment_methods(db: AsyncSession = Depends(get_db)):
    """Full list including inactive methods - admins approve deposits
    against these, so they can see them; only a Super Admin edits."""
    return {"methods": [m.model_dump() for m in await get_payment_methods(db)]}


@router.put("/payment-methods", dependencies=[Depends(require_super_admin)])
async def update_payment_methods(
    req: UpdatePaymentMethodsRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        before, after = await set_payment_methods(db, req.methods, admin_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_PAYMENT_METHODS", before_state={"methods": before}, after_state={"methods": after},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return {"methods": after}


@router.get("/legal", dependencies=[Depends(require_admin)])
async def list_legal_for_admin(db: AsyncSession = Depends(get_db)):
    """Raw bodies (placeholders unfilled) plus whether each is still the built-in draft."""
    return {"documents": [await get_legal_document(db, slug) for slug in LEGAL_TITLES]}


@router.put("/legal/{slug}", dependencies=[Depends(require_super_admin)])
async def update_legal_document(
    slug: str,
    req: UpdateLegalDocumentRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    if slug not in LEGAL_TITLES:
        raise HTTPException(status_code=404, detail="Document not found")
    before_body, doc = await save_legal_document(db, slug, req.body, admin_user.id)
    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_LEGAL_DOCUMENT",
        before_state={"slug": slug, "chars": len(before_body)},
        after_state={"slug": slug, "chars": len(doc["body"]), "reset_to_default": doc["is_default"]},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return doc


UPLOAD_DIR = Path(settings.UPLOADS_DIR) / "branding"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

BRANDING_UPLOAD_KINDS = {"logo_light", "logo_dark", "favicon", "og_image", "bangla_qr_image"}
UPLOAD_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2MB — plenty for a logo/favicon, keeps the shared volume small

@router.post("/branding/upload", dependencies=[Depends(require_super_admin)])
async def upload_branding_asset(
    request: Request,
    kind: str = Form(...),
    file: UploadFile = File(...),
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    if kind not in BRANDING_UPLOAD_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(BRANDING_UPLOAD_KINDS)}")
    ext = UPLOAD_CONTENT_TYPES.get(file.content_type)
    if not ext:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 2MB)")

    filename = f"{kind}-{uuid.uuid4().hex}{ext}"
    (UPLOAD_DIR / filename).write_bytes(contents)
    # Served by the StaticFiles mount at /api/v1/uploads (see main.py) - kept
    # under the existing /api/v1 prefix so it rides the same Dokploy/Traefik
    # routing rule as every other endpoint instead of needing a new one.
    url = f"/api/v1/uploads/branding/{filename}"

    res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == kind))
    setting = res.scalar_one_or_none()
    before = {kind: setting.value if setting else None}
    if setting:
        setting.value = url
        setting.updated_by_id = admin_user.id
    else:
        db.add(PlatformSetting(key=kind, value=url, is_public=True, updated_by_id=admin_user.id))

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPLOAD_BRANDING_ASSET", before_state=before, after_state={kind: url},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success", "kind": kind, "url": url}

@router.put("/currencies/override", dependencies=[Depends(require_super_admin)])
async def override_currency_rate(
    req: CurrencyOverrideRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(CurrencyRate).where(CurrencyRate.currency_code == req.currency_code.upper()))
    rate_obj = res.scalar_one_or_none()
    if not rate_obj:
        raise HTTPException(status_code=404, detail="Currency not supported")

    before = {"is_manual_override": rate_obj.is_manual_override, "manual_rate": float(rate_obj.manual_rate or 0)}
    rate_obj.is_manual_override = req.is_manual_override
    if req.is_manual_override and req.manual_rate:
        rate_obj.manual_rate = req.manual_rate
        rate_obj.source = "MANUAL_OVERRIDE"
    else:
        rate_obj.source = "AUTO_API"

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="CURRENCY_RATE_OVERRIDE", before_state=before,
        after_state={"currency": req.currency_code, "override": req.is_manual_override, "rate": float(req.manual_rate or 0)},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success", "currency": req.currency_code}

@router.put("/languages/toggle", dependencies=[Depends(require_super_admin)])
async def toggle_language(
    req: LanguageToggleRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(Language).where(Language.code == req.code.lower()))
    lang = res.scalar_one_or_none()
    if not lang:
        raise HTTPException(status_code=404, detail="Language not found")

    before = {"is_active": lang.is_active}
    lang.is_active = req.is_active
    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="LANGUAGE_TOGGLE", before_state=before, after_state={"code": req.code, "is_active": req.is_active},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success", "language": req.code, "is_active": req.is_active}

@router.get("/languages", dependencies=[Depends(require_super_admin)])
async def get_all_languages(db: AsyncSession = Depends(get_db)):
    """Unlike the public GET /settings/languages (active-only, for the
    storefront switcher), this returns every language including inactive
    ones so the Super Admin manager can re-activate them."""
    res = await db.execute(select(Language))
    return res.scalars().all()

@router.post("/languages", dependencies=[Depends(require_super_admin)])
async def create_language(
    req: LanguageCreateRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    code = req.code.lower()
    res = await db.execute(select(Language).where(Language.code == code))
    if res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Language already exists")

    db.add(Language(code=code, name=req.name, native_name=req.native_name, flag_emoji=req.flag_emoji, is_active=True, is_rtl=req.is_rtl))

    seeded_keys = 0
    if req.seed_from_english:
        for namespace, key, value in flatten(EN_TRANSLATIONS):
            db.add(Translation(language_code=code, namespace=namespace, key=key, value=value, is_machine_translated=True))
            seeded_keys += 1

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="CREATE_LANGUAGE", after_state={"code": code, "seeded_keys": seeded_keys},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success", "code": code, "seeded_keys": seeded_keys}

@router.put("/translations", dependencies=[Depends(require_super_admin)])
async def upsert_translation(
    req: TranslationUpsertRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    code = req.language_code.lower()
    lang_res = await db.execute(select(Language).where(Language.code == code))
    if not lang_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Language not found")

    res = await db.execute(
        select(Translation).where(
            Translation.language_code == code,
            Translation.namespace == req.namespace,
            Translation.key == req.key,
        )
    )
    entry = res.scalar_one_or_none()
    before = {"value": entry.value} if entry else None
    if entry:
        entry.value = req.value
        entry.is_machine_translated = False
        entry.updated_by_id = admin_user.id
    else:
        db.add(Translation(
            language_code=code, namespace=req.namespace, key=req.key, value=req.value,
            is_machine_translated=False, updated_by_id=admin_user.id
        ))

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_TRANSLATION", before_state=before,
        after_state={"language_code": code, "namespace": req.namespace, "key": req.key, "value": req.value},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success"}

@router.post("/languages/{code}/auto-translate", dependencies=[Depends(require_super_admin)])
async def auto_translate_language(
    code: str,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """Fills every English key missing for this language with a placeholder
    copy of the English string, flagged is_machine_translated=True for later
    human review. No external machine-translation provider is configured in
    this deployment (VivaPe/ShurjoPay credentials are the only third-party
    integrations wired up) — this is an honest placeholder, not a real
    translation, and exists so the language is immediately usable (with
    English text) rather than showing blank strings."""
    code = code.lower()
    res = await db.execute(select(Language).where(Language.code == code))
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Language not found")

    existing_res = await db.execute(select(Translation.namespace, Translation.key).where(Translation.language_code == code))
    existing = {(ns, key) for ns, key in existing_res.all()}

    filled = 0
    for namespace, key, value in flatten(EN_TRANSLATIONS):
        if (namespace, key) not in existing:
            db.add(Translation(language_code=code, namespace=namespace, key=key, value=value, is_machine_translated=True))
            filled += 1

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="AUTO_TRANSLATE_LANGUAGE", after_state={"language_code": code, "filled_keys": filled},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success", "filled_keys": filled}

# --- 360 Log Viewers ---
@router.get("/audit-logs", dependencies=[Depends(require_super_admin)])
async def get_audit_logs(limit: int = 50, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    return res.scalars().all()

@router.get("/audit-logs/summary", dependencies=[Depends(require_admin)])
async def get_audit_logs_summary(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Admin (Ops) gets a summarized view - action, actor, timestamp - with
    none of the forensic detail (before/after diffs, IP, user agent) the
    full /audit-logs endpoint carries. That detail stays Super-Admin-only;
    plain Admins previously had no visibility into audit logs at all."""
    res = await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    logs = res.scalars().all()

    action_counts_res = await db.execute(
        select(AuditLog.action, func.count(AuditLog.id)).group_by(AuditLog.action)
    )
    return {
        "action_counts": {action: count for action, count in action_counts_res.all()},
        "recent": [
            {"id": l.id, "action": l.action, "actor_role": l.actor_role, "created_at": l.created_at}
            for l in logs
        ],
    }

@router.get("/supplier-logs", dependencies=[Depends(require_admin)])
async def get_supplier_logs(limit: int = 50, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(SupplierTransactionLog).order_by(SupplierTransactionLog.created_at.desc()).limit(limit))
    return res.scalars().all()


# --- Admin Operations: Customer Orders Viewer ---
@router.get("/orders", dependencies=[Depends(require_admin)])
async def get_all_orders(limit: int = 100, db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(Order, User, Product, ESIMProfile)
        .join(User, Order.buyer_id == User.id)
        .join(Product, Order.product_id == Product.id)
        .outerjoin(ESIMProfile, Order.id == ESIMProfile.order_id)
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": o.id,
            "order_no": o.order_no,
            "username": u.username,
            "email": u.email,
            "product_title": p.title_en,
            "total_amount": float(o.total_amount),
            "currency": o.currency,
            "status": o.status.value,
            "created_at": o.created_at,
            # Support-tooling data: without this an admin looking into a
            # "my eSIM won't install" ticket had no way to see the actual
            # ICCID/QR/LPA from this screen.
            "iccid": profile.iccid if profile else None,
            "lpa_string": profile.lpa_string if profile else None,
            "qr_code_data": profile.qr_code_data if profile else None,
            "smdp_address": profile.smdp_address if profile else None,
            "esim_status": profile.status.value if profile else None,
            "is_mock_fallback": profile.is_mock_fallback if profile else None,
        }
        for o, u, p, profile in res.all()
    ]

# --- Admin Operations: Catalog Editor ---
@router.get("/catalog", dependencies=[Depends(require_admin)])
async def get_admin_catalog(
    q: str | None = None,
    country_iso: str | None = None,
    is_active: bool | None = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Searchable, paged product list. Syncing every country (not just ten)
    grew this from ~135 rows to thousands, so returning a flat newest-200
    slice was no longer a usable way for an admin to find one product."""
    limit = max(1, min(limit, 200))
    filters = []
    if q:
        term = f"%{q.strip()}%"
        filters.append(Product.title_en.ilike(term) | Country.name_en.ilike(term))
    if country_iso:
        filters.append(Country.iso2 == country_iso.strip().upper())
    if is_active is not None:
        filters.append(Product.is_active == is_active)

    base = select(Product, Country).join(Country, Product.country_id == Country.id)
    if filters:
        base = base.where(*filters)

    count_q = select(func.count()).select_from(Product).join(Country, Product.country_id == Country.id)
    if filters:
        count_q = count_q.where(*filters)
    total = (await db.execute(count_q)).scalar_one()

    res = await db.execute(
        base.order_by(Country.name_en.asc(), Product.data_amount_gb.asc())
        .limit(limit)
        .offset(max(0, offset))
    )
    return {
        "total": total,
        "limit": limit,
        "offset": max(0, offset),
        "items": [
            {
                "id": p.id,
                "title": p.title_en,
                "country": c.name_en,
                "country_iso": c.iso2,
                "data_gb": float(p.data_amount_gb),
                "is_unlimited": bool(p.is_unlimited),
                "validity_days": p.validity_days,
                "cost_price": float(p.cost_price),
                "retail_price": float(p.retail_price),
                "currency": p.currency,
                "supplier_reference": p.supplier_reference,
                "is_active": p.is_active,
            }
            for p, c in res.all()
        ],
    }

@router.get("/catalog/export.xlsx", dependencies=[Depends(require_admin)])
async def export_catalog_xlsx(
    q: str | None = None,
    country_iso: str | None = None,
    is_active: bool | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Every product matching the same filters as the catalog list (all of
    them by default) as a formatted Excel workbook."""
    content = await build_catalog_workbook(db, q=q, is_active=is_active, country_iso=country_iso)
    filename = f"triptel-catalog-{datetime.now(timezone.utc).date()}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.put("/catalog/{product_id}", dependencies=[Depends(require_admin)])
async def update_product(
    product_id: str,
    req: ProductUpdateRequest,
    request: Request,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(Product).where(Product.id == product_id))
    p = res.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")

    before = {"retail_price": float(p.retail_price), "is_active": p.is_active}
    if req.retail_price is not None:
        p.retail_price = Decimal(str(req.retail_price))
    if req.is_active is not None:
        p.is_active = req.is_active

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_CATALOG_PRODUCT", before_state=before,
        after_state={"product_id": p.id, "retail_price": float(p.retail_price), "is_active": p.is_active},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success", "product_id": p.id}

# --- Pricing: global selling profit % ---

class SellingProfitUpdateRequest(BaseModel):
    selling_profit_pct: Decimal


@router.get("/pricing", dependencies=[Depends(require_admin)])
async def get_pricing(db: AsyncSession = Depends(get_db)):
    pct = await get_selling_profit_pct(db)
    product_count = (await db.execute(select(func.count(Product.id)))).scalar_one()
    return {
        "selling_profit_pct": str(pct),
        "currency": settings.BASE_CURRENCY,
        "product_count": product_count,
        "example": {"cost": "1.00", "selling_price": str(retail_price_for(Decimal("1"), pct))},
    }


@router.put("/pricing", dependencies=[Depends(require_super_admin)])
async def update_pricing(
    req: SellingProfitUpdateRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """Sets the global selling profit % and immediately reprices every
    product: selling price = supplier cost x (1 + profit / 100)."""
    pct = req.selling_profit_pct.quantize(Decimal("0.01"))
    if pct < 0 or pct > MAX_SELLING_PROFIT_PCT:
        raise HTTPException(status_code=400, detail=f"Selling profit must be between 0 and {MAX_SELLING_PROFIT_PCT}%")

    before = await get_selling_profit_pct(db)
    repriced = await set_selling_profit_pct(db, pct, admin_user.id)
    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_SELLING_PROFIT",
        before_state={"selling_profit_pct": str(before)},
        after_state={"selling_profit_pct": str(pct), "products_repriced": repriced},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {
        "selling_profit_pct": str(pct),
        "products_repriced": repriced,
        "example": {"cost": "1.00", "selling_price": str(retail_price_for(Decimal("1"), pct))},
    }


# --- Sales & profit report ---

_CENTS = Decimal("0.01")


def _cents(value) -> Optional[str]:
    return None if value is None else str(Decimal(str(value)).quantize(_CENTS))


def _order_channel(order_no: str) -> str:
    if order_no.startswith("PTR-"):
        return "api"
    if order_no.startswith("ADM-"):
        return "admin"
    return "web"


def _sales_filters(
    date_from: Optional[Date], date_to: Optional[Date], status: str, q: Optional[str],
    plan: Optional[str] = None, validity: Optional[int] = None, channel: Optional[str] = None, country: Optional[str] = None,
) -> list:
    conditions = []
    if plan:
        if plan not in ("data", "unlimited"):
            raise HTTPException(status_code=400, detail="plan must be 'data' or 'unlimited'")
        conditions.append(Product.is_unlimited == (plan == "unlimited"))
    if validity:
        conditions.append(Product.validity_days == validity)
    if country and country.strip():
        conditions.append(Country.iso2 == country.strip().upper())
    if channel:
        if channel == "api":
            conditions.append(Order.order_no.like("PTR-%"))
        elif channel == "admin":
            conditions.append(Order.order_no.like("ADM-%"))
        elif channel == "web":
            conditions.extend([~Order.order_no.like("PTR-%"), ~Order.order_no.like("ADM-%")])
        else:
            raise HTTPException(status_code=400, detail="channel must be web, api or admin")
    status = (status or "COMPLETED").upper()
    if status != "ALL":
        if status not in OrderStatus.__members__:
            raise HTTPException(status_code=400, detail="Unknown order status")
        conditions.append(Order.status == OrderStatus[status])
    if date_from:
        conditions.append(Order.created_at >= datetime(date_from.year, date_from.month, date_from.day, tzinfo=timezone.utc))
    if date_to:
        end = date_to + timedelta(days=1)
        conditions.append(Order.created_at < datetime(end.year, end.month, end.day, tzinfo=timezone.utc))
    if q and q.strip():
        like = f"%{q.strip()}%"
        conditions.append(or_(
            Order.order_no.ilike(like), User.email.ilike(like), User.username.ilike(like), Product.title_en.ilike(like),
        ))
    return conditions


def _sales_joins(stmt):
    return (
        stmt.join(Product, Order.product_id == Product.id)
        .join(Country, Product.country_id == Country.id)
        .join(User, Order.buyer_id == User.id)
    )


def _plan_label(product: Product) -> str:
    size = "Unlimited" if product.is_unlimited else f"{Decimal(str(product.data_amount_gb)).normalize():f} GB"
    return f"{size} · {product.validity_days} days"


_SALES_SORTS = {
    "date": lambda: Order.created_at,
    "price": lambda: Order.total_amount,
    "cost": lambda: Order.cost_amount,
    "profit": lambda: Order.total_amount - Order.cost_amount,
    "commission": lambda: Order.reseller_commission_amount,
    "product": lambda: Product.title_en,
    "country": lambda: Country.iso2,
}


def _sales_order_by(sort: str, direction: str) -> list:
    if sort not in _SALES_SORTS:
        raise HTTPException(status_code=400, detail=f"sort must be one of: {', '.join(_SALES_SORTS)}")
    column = _SALES_SORTS[sort]()
    ordered = column.asc() if direction == "asc" else column.desc()
    # Orders without a cost snapshot sort last either way; newest breaks ties.
    return [ordered.nulls_last(), Order.created_at.desc()]


def _sales_row(order: Order, product: Product, country_iso2: str, buyer: User) -> dict:
    selling = Decimal(str(order.total_amount))
    cost = Decimal(str(order.cost_amount)) if order.cost_amount is not None else None
    commission = Decimal(str(order.reseller_commission_amount or 0))
    profit = selling - cost if cost is not None else None
    return {
        "order_id": order.id,
        "order_no": order.order_no,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "status": order.status.value,
        "channel": _order_channel(order.order_no),
        "payment_method": order.payment_method.value,
        "buyer": {"username": buyer.username, "email": buyer.email},
        "product": product.title_en,
        "plan": _plan_label(product),
        "is_unlimited": bool(product.is_unlimited),
        "validity_days": product.validity_days,
        "country_iso2": country_iso2,
        "currency": order.currency,
        "cost": _cents(cost),
        "selling_price": _cents(selling),
        "profit": _cents(profit),
        # Markup on cost - the same basis as the selling profit % setting.
        "profit_pct": _cents(profit / cost * 100) if cost else None,
        "merchant_commission": _cents(commission),
        "net_profit": _cents(profit - commission) if profit is not None else None,
    }


@router.get("/reports/sales", dependencies=[Depends(require_admin)])
async def sales_report(
    date_from: Optional[Date] = None,
    date_to: Optional[Date] = None,
    status: str = "COMPLETED",
    q: Optional[str] = None,
    plan: Optional[str] = None,
    validity: Optional[int] = None,
    channel: Optional[str] = None,
    country: Optional[str] = None,
    sort: str = "date",
    direction: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """Per-transaction base cost, selling price, profit, merchant commission
    and Triptel's net profit, with totals for the filtered range."""
    conditions = _sales_filters(date_from, date_to, status, q, plan, validity, channel, country)
    order_by = _sales_order_by(sort, direction)
    has_cost = Order.cost_amount.isnot(None)

    count, selling_total, selling_with_cost, cost_total, commission_total = (await db.execute(
        _sales_joins(select(
            func.count(Order.id),
            func.coalesce(func.sum(Order.total_amount), 0),
            func.coalesce(func.sum(Order.total_amount).filter(has_cost), 0),
            func.coalesce(func.sum(Order.cost_amount), 0),
            func.coalesce(func.sum(Order.reseller_commission_amount), 0),
        ).select_from(Order)).where(*conditions)
    )).one()

    rows = (await db.execute(
        _sales_joins(select(Order, Product, Country.iso2, User).select_from(Order))
        .where(*conditions).order_by(*order_by).limit(limit).offset(offset)
    )).all()

    cost_total = Decimal(str(cost_total))
    profit_total = Decimal(str(selling_with_cost)) - cost_total
    commission_total = Decimal(str(commission_total))
    return {
        "currency": settings.BASE_CURRENCY,
        "totals": {
            "orders": count,
            "selling_price": _cents(selling_total),
            "cost": _cents(cost_total),
            "profit": _cents(profit_total),
            "profit_pct": _cents(profit_total / cost_total * 100) if cost_total else None,
            "merchant_commission": _cents(commission_total),
            "net_profit": _cents(profit_total - commission_total),
        },
        "rows": [_sales_row(*row) for row in rows],
        "limit": limit,
        "offset": offset,
    }


def _money_group(n, selling, selling_with_cost, cost, commission) -> dict:
    profit = Decimal(str(selling_with_cost)) - Decimal(str(cost))
    cost = Decimal(str(cost))
    return {
        "orders": n,
        "selling_price": _cents(selling),
        "cost": _cents(cost),
        "profit": _cents(profit),
        "profit_pct": _cents(profit / cost * 100) if cost else None,
        "merchant_commission": _cents(commission),
        "net_profit": _cents(profit - Decimal(str(commission))),
    }


@router.get("/reports/sales/breakdown", dependencies=[Depends(require_admin)])
async def sales_breakdown(
    date_from: Optional[Date] = None,
    date_to: Optional[Date] = None,
    status: str = "COMPLETED",
    q: Optional[str] = None,
    plan: Optional[str] = None,
    validity: Optional[int] = None,
    channel: Optional[str] = None,
    country: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """The same filtered sales grouped by UTC day, by bundle (data size +
    validity) and by country - for spotting which days and packages earn."""
    conditions = _sales_filters(date_from, date_to, status, q, plan, validity, channel, country)
    money = (
        func.count(Order.id),
        func.coalesce(func.sum(Order.total_amount), 0),
        func.coalesce(func.sum(Order.total_amount).filter(Order.cost_amount.isnot(None)), 0),
        func.coalesce(func.sum(Order.cost_amount), 0),
        func.coalesce(func.sum(Order.reseller_commission_amount), 0),
    )

    day = func.date(func.timezone("UTC", Order.created_at))
    daily = (await db.execute(
        _sales_joins(select(day, *money).select_from(Order)).where(*conditions).group_by(day).order_by(day.desc())
    )).all()

    bundles = (await db.execute(
        _sales_joins(select(Product.is_unlimited, Product.data_amount_gb, Product.validity_days, *money).select_from(Order))
        .where(*conditions)
        .group_by(Product.is_unlimited, Product.data_amount_gb, Product.validity_days)
    )).all()

    countries = (await db.execute(
        _sales_joins(select(Country.iso2, Country.name_en, *money).select_from(Order))
        .where(*conditions).group_by(Country.iso2, Country.name_en)
        .order_by(func.sum(Order.total_amount).desc()).limit(50)
    )).all()

    validity_options = (await db.execute(
        select(Product.validity_days).where(Product.is_active == True).distinct().order_by(Product.validity_days)
    )).scalars().all()

    by_bundle = []
    for is_unlimited, gb, days, *m in bundles:
        size = "Unlimited" if is_unlimited else f"{Decimal(str(gb)).normalize():f} GB"
        by_bundle.append({"plan": f"{size} · {days} days", "is_unlimited": bool(is_unlimited),
                          "data_gb": None if is_unlimited else str(gb), "validity_days": days, **_money_group(*m)})
    by_bundle.sort(key=lambda b: Decimal(b["selling_price"]), reverse=True)

    return {
        "currency": settings.BASE_CURRENCY,
        "daily": [{"day": d.isoformat(), **_money_group(*m)} for d, *m in daily],
        "by_bundle": by_bundle,
        "by_country": [{"country_iso2": iso2, "country": name, **_money_group(*m)} for iso2, name, *m in countries],
        "validity_options": validity_options,
    }


@router.get("/reports/sales.csv", dependencies=[Depends(require_admin)])
async def sales_report_csv(
    date_from: Optional[Date] = None,
    date_to: Optional[Date] = None,
    status: str = "COMPLETED",
    q: Optional[str] = None,
    plan: Optional[str] = None,
    validity: Optional[int] = None,
    channel: Optional[str] = None,
    country: Optional[str] = None,
    sort: str = "date",
    direction: str = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db)
):
    conditions = _sales_filters(date_from, date_to, status, q, plan, validity, channel, country)
    rows = (await db.execute(
        _sales_joins(select(Order, Product, Country.iso2, User).select_from(Order))
        .where(*conditions).order_by(*_sales_order_by(sort, direction)).limit(50000)
    )).all()

    currency = settings.BASE_CURRENCY
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Order no", "Date (UTC)", "Status", "Channel", "Payment", "Buyer", "Buyer email", "Product", "Plan", "Country",
        f"Base cost ({currency})", f"Selling price ({currency})", f"Profit ({currency})", "Profit %",
        f"Merchant commission ({currency})", f"Net profit ({currency})",
    ])
    for row in rows:
        r = _sales_row(*row)
        writer.writerow([
            r["order_no"], r["created_at"], r["status"], r["channel"], r["payment_method"],
            r["buyer"]["username"], r["buyer"]["email"], r["product"], r["plan"], r["country_iso2"],
            r["cost"], r["selling_price"], r["profit"], r["profit_pct"], r["merchant_commission"], r["net_profit"],
        ])

    filename = f"triptel-sales-{date_from or 'start'}-to-{date_to or 'now'}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Super Admin: Staff Management ---
@router.post("/users", dependencies=[Depends(require_super_admin)])
async def create_staff_account(
    req: StaffAccountCreateRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    # This endpoint is for staff accounts specifically - MERCHANT and USER
    # already have their own proper flows (self-registration, then the
    # merchant application review queue). Creating those roles directly
    # here would bypass that review process.
    if req.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(status_code=400, detail="This endpoint only creates ADMIN or SUPER_ADMIN staff accounts")

    existing = await db.execute(select(User).where((User.email == req.email) | (User.username == req.username)))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email or username already exists")

    user = User(
        email=req.email,
        username=req.username,
        hashed_password=get_password_hash(req.password),
        role=req.role,
        status=UserStatus.ACTIVE,
        full_name=req.full_name
    )
    db.add(user)
    await db.flush()
    await LedgerService.ensure_wallets_for_user(db, user.id, user.role)

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="CREATE_STAFF_ACCOUNT",
        after_state={"user_id": user.id, "email": user.email, "role": user.role.value},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success", "user_id": user.id, "email": user.email, "role": user.role.value}

@router.get("/users", dependencies=[Depends(require_super_admin)])
async def get_all_users(limit: int = 100, q: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    query = select(User)
    if q:
        # Without this only the newest `limit` users are reachable, so an
        # older account couldn't be found to promote or make a reseller.
        query = query.where(User.username.ilike(f"%{q}%") | User.email.ilike(f"%{q}%"))
    res = await db.execute(query.order_by(User.created_at.desc()).limit(limit))
    users = res.scalars().all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "role": u.role.value,
            "status": u.status.value,
            "is_active": u.status == UserStatus.ACTIVE,
            "created_at": u.created_at
        }
        for u in users
    ]

class MakeResellerRequest(BaseModel):
    business_name: str
    contact_phone: str
    commission_rate_pct: Optional[float] = None


@router.post("/users/{user_id}/make-reseller", dependencies=[Depends(require_super_admin)])
async def make_user_reseller(
    user_id: str,
    req: MakeResellerRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """Makes an existing account an approved reseller in one step, for a
    partner onboarded directly by us rather than through the /reseller
    application form. Same end state as apply + approve: an APPROVED
    MerchantProfile, the MERCHANT role, and a commission wallet - after
    which a Partner API key can be issued from the Merchants tab."""
    res = await db.execute(select(User).where(User.id == user_id))
    u = res.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if u.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(status_code=400, detail="Staff accounts can't be made resellers")
    if not req.business_name.strip() or not req.contact_phone.strip():
        raise HTTPException(status_code=400, detail="Business name and contact phone are required")
    if req.commission_rate_pct is not None and not (0 <= req.commission_rate_pct <= 100):
        raise HTTPException(status_code=400, detail="Commission rate must be between 0 and 100")

    m_res = await db.execute(select(MerchantProfile).where(MerchantProfile.user_id == u.id))
    merchant = m_res.scalar_one_or_none()
    if merchant and merchant.status == MerchantStatus.APPROVED and u.role == UserRole.MERCHANT:
        raise HTTPException(status_code=400, detail="This user is already an approved reseller")

    before = {"role": u.role.value, "merchant_status": merchant.status.value if merchant else None}
    if not merchant:
        merchant = MerchantProfile(user_id=u.id, business_name=req.business_name.strip(), contact_phone=req.contact_phone.strip())
        db.add(merchant)
    else:
        # An earlier pending/rejected/suspended application is approved in
        # place - user_id is unique, so a second profile can't be created.
        merchant.business_name = req.business_name.strip()
        merchant.contact_phone = req.contact_phone.strip()
        merchant.rejection_reason = None
    merchant.status = MerchantStatus.APPROVED
    merchant.reviewed_by_id = admin_user.id
    if req.commission_rate_pct is not None:
        merchant.commission_rate_pct = Decimal(str(req.commission_rate_pct))

    u.role = UserRole.MERCHANT
    await LedgerService.ensure_wallets_for_user(db, u.id, UserRole.MERCHANT)
    await db.flush()

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="MAKE_RESELLER", before_state=before,
        after_state={"user_id": u.id, "merchant_id": merchant.id, "business": merchant.business_name},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success", "merchant_id": merchant.id, "message": "User is now an approved reseller"}


@router.put("/users/{user_id}/role", dependencies=[Depends(require_super_admin)])
async def update_user_role(
    user_id: str,
    req: UserRoleUpdateRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(User).where(User.id == user_id))
    u = res.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    before = {"role": u.role.value}
    u.role = req.role
    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_USER_ROLE", before_state=before, after_state={"user_id": u.id, "new_role": req.role.value},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success"}

@router.put("/users/{user_id}/status", dependencies=[Depends(require_super_admin)])
async def update_user_status(
    user_id: str,
    req: UserStatusUpdateRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(User).where(User.id == user_id))
    u = res.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if u.id == admin_user.id:
        raise HTTPException(status_code=400, detail="Cannot change your own account status")

    before = {"status": u.status.value}
    u.status = UserStatus.ACTIVE if req.is_active else UserStatus.SUSPENDED
    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_USER_STATUS", before_state=before, after_state={"user_id": u.id, "status": u.status.value},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success"}


# --- KYC Review (Super Admin + Admin; NOT Merchant/User, who submit their
# own via /kyc/submit and never see this queue) ---
KYC_UPLOAD_DIR = Path(settings.KYC_UPLOADS_DIR)


@router.get("/kyc/queue", dependencies=[Depends(require_admin)])
async def get_kyc_queue(db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(KYCSubmission, User).join(User, KYCSubmission.user_id == User.id)
        .order_by(KYCSubmission.submitted_at.desc())
    )
    return [
        {
            "id": s.id,
            "user_id": u.id,
            "username": u.username,
            "email": u.email,
            "nid_number": s.nid_number,
            "status": s.status.value,
            "rejection_reason": s.rejection_reason,
            "has_back_document": s.document_back_filename is not None,
            "submitted_at": s.submitted_at,
        }
        for s, u in res.all()
    ]


@router.get("/kyc/{submission_id}/document/{side}", dependencies=[Depends(require_admin)])
async def get_kyc_document(submission_id: str, side: str, db: AsyncSession = Depends(get_db)):
    if side not in ("front", "back"):
        raise HTTPException(status_code=400, detail="side must be 'front' or 'back'")

    res = await db.execute(select(KYCSubmission).where(KYCSubmission.id == submission_id))
    submission = res.scalar_one_or_none()
    if not submission:
        raise HTTPException(status_code=404, detail="KYC submission not found")

    filename = submission.document_front_filename if side == "front" else submission.document_back_filename
    if not filename:
        raise HTTPException(status_code=404, detail=f"No {side} document on this submission")

    path = KYC_UPLOAD_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Document file missing from storage")
    return FileResponse(path)


@router.post("/kyc/{submission_id}/approve", dependencies=[Depends(require_admin)])
async def approve_kyc(
    submission_id: str,
    request: Request,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(KYCSubmission).where(KYCSubmission.id == submission_id))
    submission = res.scalar_one_or_none()
    if not submission:
        raise HTTPException(status_code=404, detail="KYC submission not found")
    if submission.status != KYCStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Submission already {submission.status.value.lower()}")

    submission.status = KYCStatus.APPROVED
    submission.reviewed_by_id = admin_user.id
    submission.reviewed_at = datetime.now(timezone.utc)

    user_res = await db.execute(select(User).where(User.id == submission.user_id))
    user = user_res.scalar_one_or_none()
    if user:
        user.is_kyc_verified = True

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="APPROVE_KYC", after_state={"submission_id": submission.id, "user_id": submission.user_id},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success"}


@router.post("/kyc/{submission_id}/reject", dependencies=[Depends(require_admin)])
async def reject_kyc(
    submission_id: str,
    request: Request,
    reason: Optional[str] = None,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(KYCSubmission).where(KYCSubmission.id == submission_id))
    submission = res.scalar_one_or_none()
    if not submission:
        raise HTTPException(status_code=404, detail="KYC submission not found")
    if submission.status != KYCStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Submission already {submission.status.value.lower()}")

    submission.status = KYCStatus.REJECTED
    submission.rejection_reason = reason
    submission.reviewed_by_id = admin_user.id
    submission.reviewed_at = datetime.now(timezone.utc)

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="REJECT_KYC", after_state={"submission_id": submission.id, "reason": reason},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success"}
