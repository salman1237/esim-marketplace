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
from sqlalchemy.orm import aliased
from app.core.config import settings
from app.core.database import get_db, AsyncSessionLocal
from app.core.timeutil import bd_datestamp
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
from app.models.withdrawal import WithdrawalRequest, WithdrawalStatus
from app.models.discount import DiscountCode, DiscountRedemption, DiscountScope, DiscountType
from app.models.referral import ReferralEvent, ReferralReward, ReferralRewardStatus
from app.models.agent import AgentProfile, AgentStatus
from app.models.agent_bonus import AgentBonusRequest, AgentBonusStatus
from datetime import date as Date, datetime, timedelta, timezone
from app.core.seed_translations import EN_TRANSLATIONS, flatten
from app.schemas.settings import (
    UpdateBrandingRequest, CurrencyOverrideRequest, LanguageToggleRequest,
    LanguageCreateRequest, TranslationUpsertRequest, UpdatePaymentMethodsRequest, UpdateLegalDocumentRequest,
)
from app.services.ledger_svc import LedgerService
from app.services.payment_methods_svc import get_payment_methods, set_payment_methods
from app.services.legal_content_svc import LEGAL_TITLES, get_legal_document, save_legal_document
from app.services import (
    agent_svc, discount_svc, esim_telemetry_svc, gateway_config_svc, notify_svc,
    referral_settings_svc, referral_svc, topup_limits_svc, withdrawal_settings_svc, withdrawal_svc,
)
from app.services.admin_overview_svc import build_overview
from app.services.catalog_export_svc import build_catalog_workbook
from app.services.shurjopay_svc import ShurjoPayService
from app.services.pricing_svc import MAX_SELLING_PROFIT_PCT, get_selling_profit_pct, retail_price_for, set_selling_profit_pct
from app.services.audit_svc import AuditService
from app.services.catalog_sync_svc import sync_vivape_catalog
from app.services.supplier_settings_svc import get_enabled_suppliers, serialize_all, set_enabled_suppliers, supplier_visible_filter
from app.services.vivape_adapter import VivaPeAdapter
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
    """Includes each partner's agent, so the Merchants tab can show who earns
    on their sales and change it."""
    agent_user = aliased(User)
    res = await db.execute(
        select(MerchantProfile, User, agent_user.username, AgentProfile.agent_code, AgentProfile.commission_rate_pct)
        .join(User, MerchantProfile.user_id == User.id)
        .outerjoin(agent_user, MerchantProfile.agent_id == agent_user.id)
        .outerjoin(AgentProfile, AgentProfile.user_id == MerchantProfile.agent_id)
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
            "agent": {
                "user_id": m.agent_id,
                "username": agent_username,
                "agent_code": agent_code,
                "commission_rate_pct": float(agent_rate) if agent_rate is not None else None,
            } if m.agent_id else None,
            "created_at": m.created_at
        }
        for m, u, agent_username, agent_code, agent_rate in res.all()
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
        # Whoever referred this account earns the new-partner reward, if the
        # admin configured one. Never fails the approval.
        try:
            reward = await referral_svc.grant(db, user, ReferralEvent.NEW_MERCHANT)
            if reward:
                referrer = (await db.execute(
                    select(User).where(User.id == reward.referrer_id)
                )).scalar_one_or_none()
                if referrer:
                    notify_svc.referred_became_merchant(
                        to=referrer.email, referrer=referrer.username,
                        business_name=m.business_name,
                        reward=str(reward.referrer_amount), currency=settings.BASE_CURRENCY,
                    )
        except Exception as e:
            logger.warning("referral_new_merchant_grant_failed", user_id=user.id, error=str(e))

        notify_svc.merchant_approved(
            to=user.email, business_name=m.business_name,
            rate_pct=str(m.commission_rate_pct), username=user.username,
        )

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

    p_res = await db.execute(
        select(Product).where(
            Product.id == req.product_id, Product.is_active == True,
            supplier_visible_filter(Product.supplier_reference, await get_enabled_suppliers(db)),
        )
    )
    product = p_res.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found or inactive")

    total_cost = Decimal(str(product.retail_price))
    w_res = await db.execute(select(Wallet).where(Wallet.user_id == target.id, Wallet.wallet_type == WalletType.DEFAULT))
    wallet = w_res.scalar_one_or_none()
    if not wallet or Decimal(str(wallet.balance)) < total_cost:
        raise HTTPException(status_code=400, detail="Customer has insufficient wallet balance.")

    order_no = f"ADM-{bd_datestamp()}-{uuid.uuid4().hex[:6].upper()}"
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
            status_url=esim_telemetry_svc.share_url(profile),
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

class TopupLimitsRequest(BaseModel):
    min: Decimal = Field(..., gt=0)
    max: Decimal = Field(..., gt=0)


@router.get("/dashboard", dependencies=[Depends(require_admin)])
async def admin_dashboard(days: int = Query(30, ge=7, le=365), db: AsyncSession = Depends(get_db)):
    """The Overview tab: KPIs against the previous period, daily trends,
    where sales come from, and what needs attention - one consistent slice."""
    return await build_overview(db, days)


@router.get("/topup-limits", dependencies=[Depends(require_admin)])
async def get_topup_limits_settings(db: AsyncSession = Depends(get_db)):
    minimum, maximum = await topup_limits_svc.get_topup_limits(db)
    return {"min": str(minimum), "max": str(maximum), "currency": settings.BASE_CURRENCY}


@router.put("/topup-limits", dependencies=[Depends(require_super_admin)])
async def update_topup_limits(
    req: TopupLimitsRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Lets a small live-gateway test through without a redeploy - set the
    minimum to a token amount, run the test, then put it back."""
    try:
        change = await topup_limits_svc.set_topup_limits(db, req.min, req.max, admin_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_TOPUP_LIMITS", before_state=change["before"], after_state=change["after"],
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    minimum, maximum = await topup_limits_svc.get_topup_limits(db)
    return {"min": str(minimum), "max": str(maximum), "currency": settings.BASE_CURRENCY}


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
            # So the row can pull live carrier telemetry on demand via
            # GET /esims/{id}/status, which staff are allowed to read.
            "esim_id": profile.id if profile else None,
            "activated_at": profile.activated_at if profile else None,
            "expires_at": profile.expires_at if profile else None,
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


@router.get("/supplier-settings", dependencies=[Depends(require_admin)])
async def get_supplier_settings(db: AsyncSession = Depends(get_db)):
    """Every supplier catalog_parsing recognises, with its label and
    current on/off state - what the admin console renders as checkboxes."""
    return {"suppliers": await serialize_all(db)}


class SupplierSettingsRequest(BaseModel):
    enabled_suppliers: list[str]


@router.put("/supplier-settings", dependencies=[Depends(require_super_admin)])
async def update_supplier_settings(
    req: SupplierSettingsRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """Which suppliers' products a customer or partner can browse and buy.
    Super-admin-only, the same gate as the global selling-profit percentage
    (PUT /pricing) - this changes what the entire storefront offers, not one
    product. Never deletes or deactivates anything: a disabled supplier's
    products stay exactly as they are in the catalog, just unreachable by a
    customer or partner until re-enabled."""
    try:
        change = await set_enabled_suppliers(db, req.enabled_suppliers, admin_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_ENABLED_SUPPLIERS",
        before_state={"enabled_suppliers": change["before"]},
        after_state={"enabled_suppliers": change["after"]},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"suppliers": await serialize_all(db)}


@router.get("/countries", dependencies=[Depends(require_admin)])
async def list_admin_countries(search: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """Every destination with inventory, for the Popular Destinations admin
    panel - not filtered to is_popular, so an admin can both add new ones
    and remove existing ones from the home page."""
    has_products = select(Product.id).where(Product.country_id == Country.id, Product.is_active == True).exists()  # noqa: E712
    query = select(Country).where(Country.is_active == True, has_products)
    if search:
        query = query.where(Country.name_en.ilike(f"%{search}%") | Country.iso2.ilike(f"%{search}%"))
    res = await db.execute(query.order_by(Country.popular_order.asc(), Country.name_en.asc()))
    countries = res.scalars().all()
    return {
        "countries": [
            {"id": c.id, "iso2": c.iso2, "name_en": c.name_en, "flag_url": c.flag_url,
             "is_popular": c.is_popular, "popular_order": c.popular_order}
            for c in countries
        ]
    }


class PopularDestinationEntry(BaseModel):
    id: int
    is_popular: bool
    popular_order: int = 0


class PopularDestinationsRequest(BaseModel):
    # The whole set, replaced atomically - an admin reordering the list sees
    # one save button, not a race between several per-row PATCH calls.
    countries: list[PopularDestinationEntry]


@router.put("/countries/popular", dependencies=[Depends(require_super_admin)])
async def update_popular_destinations(
    req: PopularDestinationsRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """Which destinations show on the home page, and in what order. Same
    gate as PUT /pricing and PUT /supplier-settings: this changes what
    every visitor sees first, not one record."""
    ids = [e.id for e in req.countries]
    res = await db.execute(select(Country).where(Country.id.in_(ids)))
    by_id = {c.id: c for c in res.scalars().all()}
    before = {c.id: {"is_popular": c.is_popular, "popular_order": c.popular_order} for c in by_id.values()}

    for entry in req.countries:
        country = by_id.get(entry.id)
        if not country:
            raise HTTPException(status_code=404, detail=f"Country {entry.id} not found")
        country.is_popular = entry.is_popular
        country.popular_order = entry.popular_order

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_POPULAR_DESTINATIONS",
        before_state=before,
        after_state={c.id: {"is_popular": c.is_popular, "popular_order": c.popular_order} for c in by_id.values()},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return await list_admin_countries(search=None, db=db)


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
    discount_code: Optional[str] = None,
) -> list:
    conditions = []
    if discount_code and discount_code.strip():
        code = discount_svc.normalize_code(discount_code)
        if code == "ANY":
            # "Any code" - every discounted sale, whichever campaign it came from.
            conditions.append(Order.discount_code_id.isnot(None))
        elif code == "NONE":
            conditions.append(Order.discount_code_id.is_(None))
        else:
            conditions.append(Order.discount_code_id.in_(
                select(DiscountCode.id).where(func.upper(DiscountCode.code) == code)
            ))
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
        # Outer: most orders carry no code. discount_code_id is single-valued,
        # so this can't duplicate a row and inflate the aggregates.
        .outerjoin(DiscountCode, Order.discount_code_id == DiscountCode.id)
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
    "discount": lambda: Order.discount_amount,
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


def _sales_row(order: Order, product: Product, country_iso2: str, buyer: User, discount_code: Optional[str] = None) -> dict:
    # selling_price is what the customer actually paid: total_amount is
    # already net of any discount, so profit here is the real profit and
    # needs no separate adjustment.
    selling = Decimal(str(order.total_amount))
    cost = Decimal(str(order.cost_amount)) if order.cost_amount is not None else None
    commission = Decimal(str(order.reseller_commission_amount or 0))
    discount = Decimal(str(order.discount_amount or 0))
    profit = selling - cost if cost is not None else None
    return {
        "discount_code": discount_code,
        "discount": _cents(discount),
        "list_price": _cents(selling + discount),
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
    discount_code: Optional[str] = None,
    sort: str = "date",
    direction: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """Per-transaction base cost, selling price, profit, merchant commission
    and Triptel's net profit, with totals for the filtered range.
    `discount_code` accepts a code, ANY (every discounted sale) or NONE."""
    conditions = _sales_filters(date_from, date_to, status, q, plan, validity, channel, country, discount_code)
    order_by = _sales_order_by(sort, direction)
    has_cost = Order.cost_amount.isnot(None)

    count, selling_total, selling_with_cost, cost_total, commission_total, discount_total, discounted_orders = (await db.execute(
        _sales_joins(select(
            func.count(Order.id),
            func.coalesce(func.sum(Order.total_amount), 0),
            func.coalesce(func.sum(Order.total_amount).filter(has_cost), 0),
            func.coalesce(func.sum(Order.cost_amount), 0),
            func.coalesce(func.sum(Order.reseller_commission_amount), 0),
            func.coalesce(func.sum(Order.discount_amount), 0),
            func.count(Order.id).filter(Order.discount_code_id.isnot(None)),
        ).select_from(Order)).where(*conditions)
    )).one()

    rows = (await db.execute(
        _sales_joins(select(Order, Product, Country.iso2, User, DiscountCode.code).select_from(Order))
        .where(*conditions).order_by(*order_by).limit(limit).offset(offset)
    )).all()

    cost_total = Decimal(str(cost_total))
    profit_total = Decimal(str(selling_with_cost)) - cost_total
    commission_total = Decimal(str(commission_total))
    discount_total = Decimal(str(discount_total))
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
            # Revenue given away, and the list price it came off.
            "discount": _cents(discount_total),
            "discounted_orders": discounted_orders,
            "list_price": _cents(Decimal(str(selling_total)) + discount_total),
        },
        "rows": [_sales_row(*row) for row in rows],
        "limit": limit,
        "offset": offset,
    }


def _money_group(n, selling, selling_with_cost, cost, commission, discount=0) -> dict:
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
        "discount": _cents(discount),
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
    discount_code: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """The same filtered sales grouped by UTC day, by bundle (data size +
    validity), by country and by discount code - for spotting which days,
    packages and campaigns earn."""
    conditions = _sales_filters(date_from, date_to, status, q, plan, validity, channel, country, discount_code)
    money = (
        func.count(Order.id),
        func.coalesce(func.sum(Order.total_amount), 0),
        func.coalesce(func.sum(Order.total_amount).filter(Order.cost_amount.isnot(None)), 0),
        func.coalesce(func.sum(Order.cost_amount), 0),
        func.coalesce(func.sum(Order.reseller_commission_amount), 0),
        func.coalesce(func.sum(Order.discount_amount), 0),
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

    # Per-campaign performance: what each code sold and what it gave away.
    by_code_rows = (await db.execute(
        _sales_joins(select(DiscountCode.code, *money).select_from(Order))
        .where(*conditions, Order.discount_code_id.isnot(None))
        .group_by(DiscountCode.code)
        .order_by(func.sum(Order.total_amount).desc())
    )).all()

    validity_options = (await db.execute(
        select(Product.validity_days).where(Product.is_active == True).distinct().order_by(Product.validity_days)
    )).scalars().all()

    code_options = (await db.execute(
        select(DiscountCode.code).order_by(DiscountCode.created_at.desc()).limit(200)
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
        "by_discount_code": [{"code": code, **_money_group(*m)} for code, *m in by_code_rows],
        "validity_options": validity_options,
        "discount_code_options": code_options,
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
    discount_code: Optional[str] = None,
    sort: str = "date",
    direction: str = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db)
):
    conditions = _sales_filters(date_from, date_to, status, q, plan, validity, channel, country, discount_code)
    rows = (await db.execute(
        _sales_joins(select(Order, Product, Country.iso2, User, DiscountCode.code).select_from(Order))
        .where(*conditions).order_by(*_sales_order_by(sort, direction)).limit(50000)
    )).all()

    currency = settings.BASE_CURRENCY
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Order no", "Date (UTC)", "Status", "Channel", "Payment", "Buyer", "Buyer email", "Product", "Plan", "Country",
        f"Base cost ({currency})", f"List price ({currency})", "Discount code", f"Discount ({currency})",
        f"Selling price ({currency})", f"Profit ({currency})", "Profit %",
        f"Merchant commission ({currency})", f"Net profit ({currency})",
    ])
    for row in rows:
        r = _sales_row(*row)
        writer.writerow([
            r["order_no"], r["created_at"], r["status"], r["channel"], r["payment_method"],
            r["buyer"]["username"], r["buyer"]["email"], r["product"], r["plan"], r["country_iso2"],
            r["cost"], r["list_price"], r["discount_code"] or "", r["discount"],
            r["selling_price"], r["profit"], r["profit_pct"], r["merchant_commission"], r["net_profit"],
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


# --- Withdrawals (Admin + Super Admin review; the settings behind them are
# Super-Admin-only to change, matching topup-limits) ---
WITHDRAWAL_UPLOAD_DIR = Path(settings.WITHDRAWAL_UPLOADS_DIR)
WITHDRAWAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

WITHDRAWAL_PROOF_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "application/pdf": ".pdf"}
MAX_WITHDRAWAL_PROOF_BYTES = 5 * 1024 * 1024


class WithdrawalSettingsRequest(BaseModel):
    min_amount: Decimal = Field(..., gt=0)
    max_amount: Decimal = Field(..., gt=0)
    fee_type: str = "flat"
    fee_value: Decimal = Field(Decimal("0"), ge=0)
    payout_currency: str = "BDT"
    processing_time: str = "1-3 business days"
    is_enabled: bool = True


@router.get("/withdrawal-settings", dependencies=[Depends(require_admin)])
async def get_withdrawal_settings_endpoint(db: AsyncSession = Depends(get_db)):
    cfg = await withdrawal_settings_svc.get_withdrawal_settings(db)
    return {
        **withdrawal_settings_svc.serialize(cfg),
        "fee_types": list(withdrawal_settings_svc.FEE_TYPES),
        "payout_currencies": list(withdrawal_settings_svc.PAYOUT_CURRENCIES),
        "base_currency": settings.BASE_CURRENCY,
    }


@router.put("/withdrawal-settings", dependencies=[Depends(require_super_admin)])
async def update_withdrawal_settings(
    req: WithdrawalSettingsRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    try:
        change = await withdrawal_settings_svc.set_withdrawal_settings(db, req.model_dump(), admin_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_WITHDRAWAL_SETTINGS",
        before_state=change["before"], after_state=change["after"],
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return change["after"]


@router.get("/withdrawals", dependencies=[Depends(require_admin)])
async def list_withdrawals(
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db)
):
    query = (
        select(WithdrawalRequest, User)
        .join(User, WithdrawalRequest.user_id == User.id)
        .order_by(WithdrawalRequest.created_at.desc())
        .limit(limit)
    )
    if status:
        try:
            query = query.where(WithdrawalRequest.status == WithdrawalStatus(status.upper()))
        except ValueError:
            raise HTTPException(status_code=400, detail="Unknown withdrawal status")
    res = await db.execute(query)
    return [withdrawal_svc.serialize(w, include_user=u) for w, u in res.all()]


@router.get("/withdrawals/{withdrawal_id}/proof", dependencies=[Depends(require_admin)])
async def get_withdrawal_proof(withdrawal_id: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(WithdrawalRequest).where(WithdrawalRequest.id == withdrawal_id))
    withdrawal = res.scalar_one_or_none()
    if not withdrawal or not withdrawal.proof_filename:
        raise HTTPException(status_code=404, detail="No payment proof on this withdrawal")
    path = WITHDRAWAL_UPLOAD_DIR / withdrawal.proof_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Proof file missing from storage")
    return FileResponse(path)


@router.post("/withdrawals/{withdrawal_id}/approve", dependencies=[Depends(require_admin)])
async def approve_withdrawal(
    withdrawal_id: str,
    request: Request,
    payment_reference: str = Form(...),
    proof: UploadFile = File(...),
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Marks a payout sent. The proof screenshot and the reference are both
    required: this is the only record that the money actually left, and the
    conversion rate is frozen onto the request at this moment."""
    res = await db.execute(select(WithdrawalRequest).where(WithdrawalRequest.id == withdrawal_id))
    withdrawal = res.scalar_one_or_none()
    if not withdrawal:
        raise HTTPException(status_code=404, detail="Withdrawal not found")

    ext = WITHDRAWAL_PROOF_TYPES.get(proof.content_type)
    if not ext:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {proof.content_type}")
    contents = await proof.read()
    if len(contents) > MAX_WITHDRAWAL_PROOF_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 5MB)")
    proof_filename = f"{uuid.uuid4().hex}{ext}"

    try:
        await withdrawal_svc.approve_withdrawal(db, withdrawal, admin_user, payment_reference, proof_filename)
    except withdrawal_svc.WithdrawalError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Written only once the request itself is accepted, so a refused approval
    # does not litter the volume with orphan files.
    (WITHDRAWAL_UPLOAD_DIR / proof_filename).write_bytes(contents)

    user_res = await db.execute(select(User).where(User.id == withdrawal.user_id))
    user = user_res.scalar_one()
    payload = withdrawal_svc.email_payload(withdrawal, user)

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="APPROVE_WITHDRAWAL",
        after_state={
            "withdrawal_id": withdrawal.id, "reference_no": withdrawal.reference_no,
            "user_id": withdrawal.user_id, "amount": str(withdrawal.amount),
            "payout_amount": str(withdrawal.payout_amount), "payout_currency": withdrawal.payout_currency,
            "conversion_rate": str(withdrawal.conversion_rate), "payment_reference": withdrawal.payment_reference,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()

    cfg = await withdrawal_settings_svc.get_withdrawal_settings(db)
    admin_copy_to = await EmailService.finance_notice_address(db)
    # The client asked for the receipt to reach the user and the admin.
    asyncio.create_task(withdrawal_svc.send_email_background(
        "paid", user.email, payload, {"processing_time": cfg["processing_time"]}
    ))
    asyncio.create_task(withdrawal_svc.send_email_background(
        "paid", admin_copy_to, payload, {"processing_time": cfg["processing_time"], "for_admin": True}
    ))
    return withdrawal_svc.serialize(withdrawal, include_user=user)


@router.post("/withdrawals/{withdrawal_id}/reject", dependencies=[Depends(require_admin)])
async def reject_withdrawal(
    withdrawal_id: str,
    request: Request,
    reason: Optional[str] = None,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(WithdrawalRequest).where(WithdrawalRequest.id == withdrawal_id))
    withdrawal = res.scalar_one_or_none()
    if not withdrawal:
        raise HTTPException(status_code=404, detail="Withdrawal not found")

    try:
        await withdrawal_svc.reject_withdrawal(db, withdrawal, admin_user, reason)
    except withdrawal_svc.WithdrawalError as e:
        raise HTTPException(status_code=400, detail=str(e))

    user_res = await db.execute(select(User).where(User.id == withdrawal.user_id))
    user = user_res.scalar_one()
    payload = withdrawal_svc.email_payload(withdrawal, user)

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="REJECT_WITHDRAWAL",
        after_state={
            "withdrawal_id": withdrawal.id, "reference_no": withdrawal.reference_no,
            "user_id": withdrawal.user_id, "amount_returned": str(withdrawal.amount), "reason": reason,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()

    asyncio.create_task(withdrawal_svc.send_email_background("rejected", user.email, payload, {"reason": reason}))
    return withdrawal_svc.serialize(withdrawal, include_user=user)


# --- Discount codes (Admin + Super Admin; the usage report is what makes a
# campaign judgeable, so it ships with the CRUD rather than after it) ---

class DiscountCodeRequest(BaseModel):
    code: str = Field(..., min_length=3, max_length=40)
    description: Optional[str] = None
    discount_type: DiscountType = DiscountType.PERCENT
    value: Decimal = Field(..., gt=0)
    max_discount_amount: Optional[Decimal] = Field(None, gt=0)
    min_order_amount: Optional[Decimal] = Field(None, ge=0)
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    max_uses: Optional[int] = Field(None, ge=1)
    max_uses_per_user: Optional[int] = Field(None, ge=1)
    first_order_only: bool = False
    scope: DiscountScope = DiscountScope.ALL
    country_id: Optional[int] = None
    product_id: Optional[str] = None
    is_active: bool = True


def _validate_discount_request(req: "DiscountCodeRequest") -> None:
    if req.discount_type == DiscountType.PERCENT and req.value > 100:
        raise HTTPException(status_code=400, detail="A percentage discount cannot exceed 100%")
    if req.starts_at and req.ends_at and req.ends_at <= req.starts_at:
        raise HTTPException(status_code=400, detail="The end date must be after the start date")
    if req.scope == DiscountScope.COUNTRY and not req.country_id:
        raise HTTPException(status_code=400, detail="Choose the destination this code applies to")
    if req.scope == DiscountScope.PRODUCT and not req.product_id:
        raise HTTPException(status_code=400, detail="Choose the package this code applies to")


async def _discount_usage(db: AsyncSession, code_ids: List[str]) -> dict:
    """Uses, discount given and revenue kept, per code - counted the same way
    discount_svc counts them, so the admin figures match what checkout
    enforces."""
    if not code_ids:
        return {}
    now = datetime.now(timezone.utc)
    rows = (await db.execute(
        select(
            DiscountRedemption.discount_code_id,
            func.count(DiscountRedemption.id),
            func.coalesce(func.sum(DiscountRedemption.discount_amount), 0),
            func.coalesce(func.sum(Order.total_amount), 0),
        )
        .join(Order, DiscountRedemption.order_id == Order.id)
        .where(
            DiscountRedemption.discount_code_id.in_(code_ids),
            discount_svc._counted_orders_clause(now),
        )
        .group_by(DiscountRedemption.discount_code_id)
    )).all()
    return {code_id: (n, Decimal(str(given)), Decimal(str(revenue))) for code_id, n, given, revenue in rows}


@router.get("/discounts", dependencies=[Depends(require_admin)])
async def list_discount_codes(db: AsyncSession = Depends(get_db)):
    codes = (await db.execute(select(DiscountCode).order_by(DiscountCode.created_at.desc()))).scalars().all()
    usage = await _discount_usage(db, [c.id for c in codes])
    return [
        discount_svc.serialize(
            c,
            total_uses=usage.get(c.id, (0, Decimal("0"), Decimal("0")))[0],
            given=usage.get(c.id, (0, Decimal("0"), Decimal("0")))[1],
            revenue=usage.get(c.id, (0, Decimal("0"), Decimal("0")))[2],
        )
        for c in codes
    ]


@router.post("/discounts", dependencies=[Depends(require_admin)])
async def create_discount_code(
    req: DiscountCodeRequest,
    request: Request,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    _validate_discount_request(req)
    code_str = discount_svc.normalize_code(req.code)
    if await discount_svc.find_code(db, code_str):
        raise HTTPException(status_code=400, detail="That code already exists")

    code = DiscountCode(
        code=code_str,
        description=req.description,
        discount_type=req.discount_type,
        value=req.value,
        max_discount_amount=req.max_discount_amount,
        min_order_amount=req.min_order_amount,
        starts_at=req.starts_at,
        ends_at=req.ends_at,
        max_uses=req.max_uses,
        max_uses_per_user=req.max_uses_per_user,
        first_order_only=req.first_order_only,
        scope=req.scope,
        country_id=req.country_id if req.scope == DiscountScope.COUNTRY else None,
        product_id=req.product_id if req.scope == DiscountScope.PRODUCT else None,
        is_active=req.is_active,
        created_by_id=admin_user.id,
    )
    db.add(code)
    await db.flush()

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="CREATE_DISCOUNT_CODE",
        after_state={"code": code.code, "type": code.discount_type.value, "value": str(code.value)},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    await db.refresh(code)
    return discount_svc.serialize(code)


@router.put("/discounts/{code_id}", dependencies=[Depends(require_admin)])
async def update_discount_code(
    code_id: str,
    req: DiscountCodeRequest,
    request: Request,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    code = (await db.execute(select(DiscountCode).where(DiscountCode.id == code_id))).scalar_one_or_none()
    if not code:
        raise HTTPException(status_code=404, detail="Discount code not found")
    _validate_discount_request(req)

    new_code = discount_svc.normalize_code(req.code)
    if new_code != code.code:
        clash = await discount_svc.find_code(db, new_code)
        if clash and clash.id != code.id:
            raise HTTPException(status_code=400, detail="That code already exists")

    before = {"code": code.code, "value": str(code.value), "is_active": code.is_active}
    # Orders already placed keep the discount they were given: only the code's
    # future behaviour changes here, never a past redemption.
    code.code = new_code
    code.description = req.description
    code.discount_type = req.discount_type
    code.value = req.value
    code.max_discount_amount = req.max_discount_amount
    code.min_order_amount = req.min_order_amount
    code.starts_at = req.starts_at
    code.ends_at = req.ends_at
    code.max_uses = req.max_uses
    code.max_uses_per_user = req.max_uses_per_user
    code.first_order_only = req.first_order_only
    code.scope = req.scope
    code.country_id = req.country_id if req.scope == DiscountScope.COUNTRY else None
    code.product_id = req.product_id if req.scope == DiscountScope.PRODUCT else None
    code.is_active = req.is_active

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_DISCOUNT_CODE", before_state=before,
        after_state={"code": code.code, "value": str(code.value), "is_active": code.is_active},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    await db.refresh(code)
    return discount_svc.serialize(code)


@router.delete("/discounts/{code_id}", dependencies=[Depends(require_admin)])
async def delete_discount_code(
    code_id: str,
    request: Request,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Only ever deletes a code nobody used. A used code is deactivated
    instead, because deleting it would cut the link from those orders to the
    campaign that discounted them."""
    code = (await db.execute(select(DiscountCode).where(DiscountCode.id == code_id))).scalar_one_or_none()
    if not code:
        raise HTTPException(status_code=404, detail="Discount code not found")

    used = (await db.execute(
        select(func.count(DiscountRedemption.id)).where(DiscountRedemption.discount_code_id == code.id)
    )).scalar() or 0

    action = "DELETE_DISCOUNT_CODE"
    if used:
        code.is_active = False
        action = "DEACTIVATE_USED_DISCOUNT_CODE"
    else:
        await db.delete(code)

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action=action, after_state={"code": code.code, "redemptions": used},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {
        "status": "success",
        "deleted": not used,
        "message": (
            f"{code.code} has been used {used} time(s), so it was switched off rather than deleted."
            if used else f"{code.code} deleted."
        ),
    }


@router.get("/discounts/{code_id}/redemptions", dependencies=[Depends(require_admin)])
async def list_discount_redemptions(
    code_id: str,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db)
):
    rows = (await db.execute(
        select(DiscountRedemption, Order, User)
        .join(Order, DiscountRedemption.order_id == Order.id)
        .join(User, DiscountRedemption.user_id == User.id)
        .where(DiscountRedemption.discount_code_id == code_id)
        .order_by(DiscountRedemption.created_at.desc())
        .limit(limit)
    )).all()
    return [
        {
            "id": r.id,
            "order_id": o.id,
            "order_no": o.order_no,
            "order_status": o.status.value,
            "username": u.username,
            "email": u.email,
            "discount_amount": str(r.discount_amount),
            "paid_amount": str(o.total_amount),
            "created_at": r.created_at,
        }
        for r, o, u in rows
    ]


# --- Referral programme (Admin + Super Admin can see it; only a Super Admin
# changes the amounts, matching the other money settings) ---

class ReferralEventAmounts(BaseModel):
    referrer: Decimal = Field(Decimal("0"), ge=0)
    referred: Decimal = Field(Decimal("0"), ge=0)
    enabled: bool = False


class ReferralSettingsRequest(BaseModel):
    is_enabled: bool = False
    events: dict[str, ReferralEventAmounts] = {}
    max_rewarded_referrals: Optional[int] = Field(None, ge=1)


@router.get("/referral-settings", dependencies=[Depends(require_admin)])
async def get_referral_settings_endpoint(db: AsyncSession = Depends(get_db)):
    cfg = await referral_settings_svc.get_referral_settings(db)
    return {
        **referral_settings_svc.serialize(cfg),
        "event_labels": referral_settings_svc.EVENT_LABELS,
        "base_currency": settings.BASE_CURRENCY,
        "max_reward": str(referral_settings_svc.ABSOLUTE_MAX_REWARD),
    }


@router.put("/referral-settings", dependencies=[Depends(require_super_admin)])
async def update_referral_settings(
    req: ReferralSettingsRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    payload = {
        "is_enabled": req.is_enabled,
        "events": {k: v.model_dump() for k, v in req.events.items()},
        "max_rewarded_referrals": req.max_rewarded_referrals,
    }
    try:
        change = await referral_settings_svc.set_referral_settings(db, payload, admin_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_REFERRAL_SETTINGS",
        before_state=change["before"], after_state=change["after"],
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return change["after"]


@router.get("/referrals", dependencies=[Depends(require_admin)])
async def referral_report(
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db)
):
    """Who is bringing people in, what it cost in promo credit, and how much
    of that credit is still an outstanding liability."""
    referrer = aliased(User)
    referred = aliased(User)

    rows = (await db.execute(
        select(ReferralReward, referrer.username, referred.username)
        .join(referrer, ReferralReward.referrer_id == referrer.id)
        .join(referred, ReferralReward.referred_id == referred.id)
        .order_by(ReferralReward.created_at.desc())
        .limit(limit)
    )).all()

    granted = ReferralReward.status == ReferralRewardStatus.GRANTED
    totals = (await db.execute(
        select(
            func.count(ReferralReward.id),
            func.coalesce(func.sum(ReferralReward.referrer_amount).filter(granted), 0),
            func.coalesce(func.sum(ReferralReward.referred_amount).filter(granted), 0),
            func.count(ReferralReward.id).filter(ReferralReward.status == ReferralRewardStatus.REVERSED),
        )
    )).one()

    # Top referrers by credit earned, ignoring reversed rewards.
    leaders = (await db.execute(
        select(
            referrer.username,
            func.count(func.distinct(ReferralReward.referred_id)),
            func.coalesce(func.sum(ReferralReward.referrer_amount), 0),
        )
        .join(referrer, ReferralReward.referrer_id == referrer.id)
        .where(granted)
        .group_by(referrer.username)
        .order_by(func.sum(ReferralReward.referrer_amount).desc())
        .limit(20)
    )).all()

    # Promo credit still sitting in REWARD wallets - what we owe in eSIMs, not
    # in cash, since it can never be withdrawn.
    outstanding = (await db.execute(
        select(func.coalesce(func.sum(Wallet.balance), 0)).where(Wallet.wallet_type == WalletType.REWARD)
    )).scalar() or 0

    # Signed up with a code but nothing granted yet (the programme was off, or
    # the event they qualify for isn't configured).
    referred_users = (await db.execute(
        select(func.count(User.id)).where(User.referred_by_id.isnot(None))
    )).scalar() or 0

    return {
        "currency": settings.BASE_CURRENCY,
        "totals": {
            "rewards": totals[0],
            "paid_to_referrers": _cents(Decimal(str(totals[1]))),
            "paid_to_referred": _cents(Decimal(str(totals[2]))),
            "total_granted": _cents(Decimal(str(totals[1])) + Decimal(str(totals[2]))),
            "reversed": totals[3],
            "referred_users": referred_users,
            "promo_credit_outstanding": _cents(Decimal(str(outstanding))),
        },
        "leaders": [
            {"username": name, "referrals": n, "earned": _cents(Decimal(str(amount)))}
            for name, n, amount in leaders
        ],
        "rewards": [
            {
                "id": r.id,
                "event": r.event.value,
                "referrer": referrer_name,
                "referred": referred_name,
                "referrer_amount": _cents(Decimal(str(r.referrer_amount))),
                "referred_amount": _cents(Decimal(str(r.referred_amount))),
                "status": r.status.value,
                "order_id": r.order_id,
                "reversal_reason": r.reversal_reason,
                "created_at": r.created_at,
            }
            for r, referrer_name, referred_name in rows
        ],
    }


# --- Agents (Admin + Super Admin approve and map; only a Super Admin sets a
# commission rate, matching the merchant-commission gate) ---

class AgentCommissionRequest(BaseModel):
    rate_pct: Decimal = Field(..., ge=0, le=agent_svc.MAX_AGENT_COMMISSION_PCT)


class MerchantAgentRequest(BaseModel):
    # Null clears the mapping; otherwise an agent's code or user id.
    agent_code: Optional[str] = None
    agent_user_id: Optional[str] = None


@router.get("/agents", dependencies=[Depends(require_admin)])
async def list_agents(status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    query = (
        select(AgentProfile, User).join(User, AgentProfile.user_id == User.id)
        .order_by(AgentProfile.created_at.desc())
    )
    if status:
        try:
            query = query.where(AgentProfile.status == AgentStatus(status.upper()))
        except ValueError:
            raise HTTPException(status_code=400, detail="Unknown agent status")

    rows = (await db.execute(query)).all()
    completed = Order.status == OrderStatus.COMPLETED
    out = []
    for profile, user in rows:
        earned = (await db.execute(
            select(
                func.count(Order.id).filter(completed),
                func.coalesce(func.sum(Order.agent_commission_amount).filter(completed), 0),
            ).where(Order.agent_id == user.id)
        )).one()
        out.append(agent_svc.serialize(
            profile, user,
            merchants=await agent_svc.merchant_count(db, user.id),
            stats={"orders": earned[0], "commission_earned": _cents(Decimal(str(earned[1])))},
        ))
    return out


@router.get("/agents/margin-check", dependencies=[Depends(require_admin)])
async def agent_margin_check(
    merchant_pct: Decimal = Query(Decimal("5.00"), ge=0),
    agent_pct: Decimal = Query(Decimal("2.00"), ge=0),
    db: AsyncSession = Depends(get_db)
):
    """What is left of a sale after both commissions. Both are percentages of
    the selling price (the client's rule for agents), so a pair of rates can
    add up to more than the margin - this is what warns before that happens."""
    return await agent_svc.margin_check(db, merchant_pct, agent_pct)


@router.post("/agents/{profile_id}/approve", dependencies=[Depends(require_admin)])
async def approve_agent(
    profile_id: str,
    request: Request,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    profile = (await db.execute(select(AgentProfile).where(AgentProfile.id == profile_id))).scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Agent application not found")
    if profile.status == AgentStatus.APPROVED:
        raise HTTPException(status_code=400, detail="This agent is already approved")

    profile.status = AgentStatus.APPROVED
    profile.rejection_reason = None
    profile.reviewed_by_id = admin_user.id
    profile.reviewed_at = datetime.now(timezone.utc)

    user = (await db.execute(select(User).where(User.id == profile.user_id))).scalar_one_or_none()
    if user:
        # A merchant stays a MERCHANT: the agent portal is gated on the
        # approved profile, not the role, so both capabilities coexist.
        if user.role == UserRole.USER:
            user.role = UserRole.AGENT
        await LedgerService.ensure_commission_wallet(db, user.id)

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="APPROVE_AGENT",
        after_state={"agent_id": profile.id, "user_id": profile.user_id, "company": profile.company_name,
                     "rate_pct": str(profile.commission_rate_pct)},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    if user:
        notify_svc.agent_approved(
            to=user.email, company_name=profile.company_name, agent_code=profile.agent_code,
            rate_pct=str(profile.commission_rate_pct), username=user.username,
        )
    return {"status": "success", "agent_code": profile.agent_code}


@router.post("/agents/{profile_id}/reject", dependencies=[Depends(require_admin)])
async def reject_agent(
    profile_id: str,
    request: Request,
    reason: Optional[str] = None,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    profile = (await db.execute(select(AgentProfile).where(AgentProfile.id == profile_id))).scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Agent application not found")

    was_approved = profile.status == AgentStatus.APPROVED
    profile.status = AgentStatus.SUSPENDED if was_approved else AgentStatus.REJECTED
    profile.rejection_reason = reason
    profile.reviewed_by_id = admin_user.id
    profile.reviewed_at = datetime.now(timezone.utc)

    # Suspending stops future commission (commission_rate_for_merchant only
    # pays an APPROVED agent) but never touches what was already earned.
    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="SUSPEND_AGENT" if was_approved else "REJECT_AGENT",
        after_state={"agent_id": profile.id, "user_id": profile.user_id, "reason": reason},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success", "agent_status": profile.status.value}


@router.put("/agents/{profile_id}/commission", dependencies=[Depends(require_super_admin)])
async def update_agent_commission(
    profile_id: str,
    req: AgentCommissionRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    profile = (await db.execute(select(AgentProfile).where(AgentProfile.id == profile_id))).scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Agent not found")

    before = str(profile.commission_rate_pct)
    profile.commission_rate_pct = req.rate_pct

    # The highest merchant rate this agent's partners are on - the pair that
    # would cost the most per sale.
    worst_merchant_pct = (await db.execute(
        select(func.coalesce(func.max(MerchantProfile.commission_rate_pct), 0))
        .where(MerchantProfile.agent_id == profile.user_id)
    )).scalar() or Decimal("0")
    margin = await agent_svc.margin_check(db, Decimal(str(worst_merchant_pct)), req.rate_pct)

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_AGENT_COMMISSION",
        before_state={"rate_pct": before},
        after_state={"agent_id": profile.id, "rate_pct": str(req.rate_pct), "margin": margin},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    # Saved either way - the rate is the admin's call. The warning is returned
    # so the console can show what it costs.
    return {"status": "success", "rate_pct": str(req.rate_pct), "margin": margin}


@router.put("/merchants/{merchant_id}/agent", dependencies=[Depends(require_admin)])
async def update_merchant_agent(
    merchant_id: str,
    req: MerchantAgentRequest,
    request: Request,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Assigns, moves or clears a partner's agent. Past orders keep the agent
    they were paid to (it is snapshotted on the order), so this only ever
    changes who earns on sales from here on."""
    merchant = (await db.execute(select(MerchantProfile).where(MerchantProfile.id == merchant_id))).scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")

    before = merchant.agent_id
    new_agent_id = None
    if req.agent_user_id or req.agent_code:
        if req.agent_code:
            profile = await agent_svc.find_by_code(db, req.agent_code)
        else:
            profile = (await db.execute(
                select(AgentProfile).where(AgentProfile.user_id == req.agent_user_id)
            )).scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=404, detail="No agent found for that code")
        if profile.status != AgentStatus.APPROVED:
            raise HTTPException(status_code=400, detail="That agent isn't approved")
        if profile.user_id == merchant.user_id:
            raise HTTPException(status_code=400, detail="A partner can't be their own agent")
        new_agent_id = profile.user_id

    merchant.agent_id = new_agent_id
    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_MERCHANT_AGENT",
        before_state={"agent_user_id": before},
        after_state={"merchant_id": merchant.id, "agent_user_id": new_agent_id},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()

    margin = None
    if new_agent_id:
        _, agent_pct = await agent_svc.commission_rate_for_merchant(db, merchant)
        margin = await agent_svc.margin_check(db, Decimal(str(merchant.commission_rate_pct)), agent_pct)
    return {"status": "success", "agent_user_id": new_agent_id, "margin": margin}


# --- Supplier account (Admin + Super Admin) ---
# The prepaid balance every eSIM purchase is drawn from. Worth its own card
# because an empty VivaPe account does NOT fail loudly: create-transaction
# answers HTTP 200 with a generic "Insufficient Balance." that is
# indistinguishable from an ordinary decline, so the first sign is customers
# with failed orders. Cached briefly - it is a live supplier call.
_SUPPLIER_BALANCE_CACHE: dict = {"at": 0.0, "value": None}
SUPPLIER_BALANCE_TTL = 300.0
# Under this many EUR, the console warns. Roughly a handful of eSIMs.
SUPPLIER_BALANCE_WARN_BELOW = Decimal("25.00")


@router.get("/supplier/account", dependencies=[Depends(require_admin)])
async def get_supplier_account(refresh: bool = False, db: AsyncSession = Depends(get_db)):
    import time as _time

    fresh = (_time.time() - _SUPPLIER_BALANCE_CACHE["at"]) < SUPPLIER_BALANCE_TTL
    if fresh and not refresh and _SUPPLIER_BALANCE_CACHE["value"]:
        return {**_SUPPLIER_BALANCE_CACHE["value"], "cached": True}

    try:
        raw = await VivaPeAdapter.get_account_profile(db)
    except Exception as e:
        logger.warning("supplier_account_fetch_failed", error=str(e))
        stale = _SUPPLIER_BALANCE_CACHE["value"]
        if stale:
            return {**stale, "cached": True, "error": str(e)[:200]}
        raise HTTPException(status_code=502, detail=f"Could not reach the supplier: {e}")

    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="The supplier returned an unexpected profile response")

    balance = Decimal(str(data.get("balance") or 0))
    payload = {
        "account": data.get("email"),
        "name": data.get("name"),
        "supplier_id": data.get("vivape_id"),
        "user_type": data.get("user_type"),
        "balance": _cents(balance),
        "currency": data.get("currency") or settings.BASE_CURRENCY,
        "wallets": [
            {
                "type": w.get("type"),
                "balance": _cents(Decimal(str(w.get("balance") or 0))),
                "currency": w.get("currency"),
                "status": w.get("status"),
            }
            for w in (data.get("wallets") or [])
            if isinstance(w, dict)
        ],
        "low_balance": balance < SUPPLIER_BALANCE_WARN_BELOW,
        "warn_below": _cents(SUPPLIER_BALANCE_WARN_BELOW),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }
    _SUPPLIER_BALANCE_CACHE.update(at=_time.time(), value=payload)
    return payload


# --- Agent bonus approvals (Admin + Super Admin) ---
# An agent's bonus is a slice of a merchant's commission, so nothing they ask
# for takes effect until it is approved here. The queue shows the merchant's
# real rate and what approving would leave them on - the merchant themselves
# never sees either figure.

class BonusDecisionRequest(BaseModel):
    note: Optional[str] = Field(None, max_length=500)


@router.get("/agent-bonus-requests", dependencies=[Depends(require_admin)])
async def list_agent_bonus_requests(status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    agent_user = aliased(User)
    query = (
        select(AgentBonusRequest, MerchantProfile, agent_user.username)
        .join(MerchantProfile, AgentBonusRequest.merchant_profile_id == MerchantProfile.id)
        .join(agent_user, AgentBonusRequest.agent_id == agent_user.id)
        .order_by(AgentBonusRequest.created_at.desc())
        .limit(200)
    )
    if status:
        try:
            query = query.where(AgentBonusRequest.status == AgentBonusStatus(status.upper()))
        except ValueError:
            raise HTTPException(status_code=400, detail="Unknown request status")

    rows = (await db.execute(query)).all()
    return [
        agent_svc.serialize_bonus_request(r, merchant=m, agent_name=agent_name, for_admin=True)
        for r, m, agent_name in rows
    ]


@router.post("/agent-bonus-requests/{request_id}/approve", dependencies=[Depends(require_admin)])
async def approve_agent_bonus_request(
    request_id: str,
    request: Request,
    req: Optional[BonusDecisionRequest] = None,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """The only place a merchant's agent_bonus_pct is ever written."""
    row = (await db.execute(
        select(AgentBonusRequest, MerchantProfile)
        .join(MerchantProfile, AgentBonusRequest.merchant_profile_id == MerchantProfile.id)
        .where(AgentBonusRequest.id == request_id)
    )).first()
    if not row:
        raise HTTPException(status_code=404, detail="Request not found")
    bonus_request, merchant = row
    if bonus_request.status != AgentBonusStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Already {bonus_request.status.value.lower()}")

    before = str(merchant.agent_bonus_pct or 0)
    merchant.agent_bonus_pct = bonus_request.requested_pct
    bonus_request.status = AgentBonusStatus.APPROVED
    bonus_request.decision_note = req.note if req else None
    bonus_request.reviewed_by_id = admin_user.id
    bonus_request.reviewed_at = datetime.now(timezone.utc)

    merchant_rate = Decimal(str(merchant.commission_rate_pct))
    resulting = max(Decimal("0"), merchant_rate - Decimal(str(bonus_request.requested_pct))).quantize(Decimal("0.01"))

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="APPROVE_AGENT_BONUS",
        before_state={"agent_bonus_pct": before},
        after_state={
            "request_id": bonus_request.id, "merchant_id": merchant.id,
            "business_name": merchant.business_name, "agent_user_id": bonus_request.agent_id,
            "agent_bonus_pct": str(bonus_request.requested_pct),
            "merchant_rate_pct": str(merchant_rate),
            "merchant_keeps_pct": str(resulting),
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {
        "status": "success",
        "agent_bonus_pct": str(bonus_request.requested_pct),
        "merchant_keeps_pct": str(resulting),
        "zeroes_merchant": resulting <= 0,
    }


@router.post("/agent-bonus-requests/{request_id}/reject", dependencies=[Depends(require_admin)])
async def reject_agent_bonus_request(
    request_id: str,
    request: Request,
    req: Optional[BonusDecisionRequest] = None,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    bonus_request = (await db.execute(
        select(AgentBonusRequest).where(AgentBonusRequest.id == request_id)
    )).scalar_one_or_none()
    if not bonus_request:
        raise HTTPException(status_code=404, detail="Request not found")
    if bonus_request.status != AgentBonusStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Already {bonus_request.status.value.lower()}")

    bonus_request.status = AgentBonusStatus.REJECTED
    bonus_request.decision_note = req.note if req else None
    bonus_request.reviewed_by_id = admin_user.id
    bonus_request.reviewed_at = datetime.now(timezone.utc)

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="REJECT_AGENT_BONUS",
        after_state={"request_id": bonus_request.id, "requested_pct": str(bonus_request.requested_pct)},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success"}


class KycReverificationRequest(BaseModel):
    user_id: str
    reason: str = Field(..., min_length=3, max_length=500)


@router.post("/kyc/request-reverification", dependencies=[Depends(require_admin)])
async def request_kyc_reverification(
    req: KycReverificationRequest,
    request: Request,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Sends any user back through KYC.

    Deliberately reuses the rejection path rather than inventing a new state:
    the user already sees a "resubmit" screen for a rejected submission, and
    POST /kyc/submit already resets it to PENDING. Clearing is_kyc_verified is
    what gives this teeth - withdrawals check it, so the account cannot cash
    out until the documents are re-approved.
    """
    user = (await db.execute(select(User).where(User.id == req.user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    submission = (await db.execute(
        select(KYCSubmission).where(KYCSubmission.user_id == user.id)
    )).scalar_one_or_none()

    was_verified = bool(user.is_kyc_verified)
    user.is_kyc_verified = False
    if submission:
        submission.status = KYCStatus.REJECTED
        submission.rejection_reason = req.reason
        submission.reviewed_by_id = admin_user.id
        submission.reviewed_at = datetime.now(timezone.utc)

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="REQUEST_KYC_REVERIFICATION",
        before_state={"is_kyc_verified": was_verified},
        after_state={"user_id": user.id, "username": user.username, "reason": req.reason},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {
        "status": "success",
        "message": f"{user.username} must verify again before they can withdraw.",
        "had_submission": submission is not None,
    }


# --- Notification settings (Admin sees it, Super Admin changes it) ---

class SystemEmailRequest(BaseModel):
    system_notice_email: EmailStr


@router.get("/notification-settings", dependencies=[Depends(require_admin)])
async def get_notification_settings(db: AsyncSession = Depends(get_db)):
    from app.services.email_svc import EmailService

    # Enough to diagnose "nobody is getting emails" without shell access:
    # which host we are talking to, as whom, on which port, and - the part
    # that was invisible before - what the last failure actually said.
    missing = [
        name for name, value in (
            ("SMTP_HOST", settings.SMTP_HOST),
            ("SMTP_USERNAME", settings.SMTP_USERNAME),
            ("SMTP_PASSWORD", settings.SMTP_PASSWORD),
        ) if not value
    ]
    return {
        "system_notice_email": await notify_svc.get_system_email(db),
        "default": notify_svc.DEFAULT_SYSTEM_EMAIL,
        "sender": settings.SMTP_FROM_EMAIL,
        "sender_name": settings.SMTP_FROM_NAME,
        "smtp_configured": settings.smtp_configured,
        "smtp_host": settings.SMTP_HOST or None,
        "smtp_port": settings.SMTP_PORT,
        "smtp_username": settings.SMTP_USERNAME or None,
        "smtp_mode": "implicit TLS (SMTPS)" if settings.SMTP_PORT == 465 else ("STARTTLS" if settings.SMTP_USE_TLS else "plain"),
        "missing_settings": missing,
        "bcc_email": settings.NOTICE_BCC_EMAIL or None,
        "last_error": EmailService._last_error,
    }


class TestEmailRequest(BaseModel):
    to_email: EmailStr


@router.post("/notification-settings/test", dependencies=[Depends(require_admin)])
async def send_test_email(
    req: TestEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Sends one real email and reports exactly what happened.

    Delivery problems were previously silent - a missing SMTP_HOST logged a
    warning inside the container and nothing else, so "emails aren't arriving"
    could not be told apart from "emails are arriving in spam". This answers
    that in one click.
    """
    from app.services.email_svc import EmailService

    if not settings.smtp_configured:
        missing = [n for n, v in (("SMTP_HOST", settings.SMTP_HOST), ("SMTP_USERNAME", settings.SMTP_USERNAME)) if not v]
        return {
            "sent": False,
            "reason": f"SMTP is not configured — {', '.join(missing)} is not set in the deployment environment.",
        }

    EmailService._last_error = None
    sent = await EmailService.send_notice(
        db, str(req.to_email),
        subject="Triptel email test",
        title="Email is working",
        intro="This is a test message sent from the admin console. If you are reading it, outgoing mail is configured correctly.",
        rows=[
            ("Sent to", str(req.to_email)),
            ("From", f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"),
            ("Server", f"{settings.SMTP_HOST}:{settings.SMTP_PORT}"),
            ("Blind copy", settings.NOTICE_BCC_EMAIL or "none"),
        ],
        footnote="Triggered by hand from the admin console.",
    )
    if sent:
        return {
            "sent": True,
            "reason": f"Sent to {req.to_email}"
                      + (f", blind-copied to {settings.NOTICE_BCC_EMAIL}" if settings.NOTICE_BCC_EMAIL else "")
                      + ". If it does not arrive within a minute or two, check the spam folder.",
        }
    return {"sent": False, "reason": EmailService._last_error or "The mail server rejected the message."}


@router.put("/notification-settings", dependencies=[Depends(require_super_admin)])
async def update_notification_settings(
    req: SystemEmailRequest,
    request: Request,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """The mailbox every monetary notice is copied to."""
    try:
        change = await notify_svc.set_system_email(db, str(req.system_notice_email), admin_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_SYSTEM_NOTICE_EMAIL",
        before_state={"system_notice_email": change["before"]},
        after_state={"system_notice_email": change["after"]},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await db.commit()
    return {"status": "success", "system_notice_email": change["after"]}
