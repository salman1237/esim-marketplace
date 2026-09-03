from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.deps import require_admin, require_super_admin
from app.models.user import User, UserRole
from app.models.merchant import MerchantProfile, MerchantStatus
from app.models.wallet import Wallet, WalletType, LedgerRefType
from app.models.order import Order, ESIMProfile
from app.models.catalog import Country, Product
from app.models.payment import ManualPaymentRequest, ManualPaymentStatus
from app.models.settings import PlatformSetting, CurrencyRate, Language
from app.models.audit import AuditLog, SupplierTransactionLog
from app.schemas.settings import UpdateBrandingRequest, CurrencyOverrideRequest, LanguageToggleRequest
from app.services.ledger_svc import LedgerService
from app.services.audit_svc import AuditService
from app.services.vivape_adapter import VivaPeAdapter
from app.services.currency_svc import CurrencyService

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
        "total_revenue_usd": float(revenue or 0),
        "total_esims_issued": esims_count or 0
    }

# --- Catalog Sync & Pricing ---
@router.post("/catalog/sync", dependencies=[Depends(require_admin)])
async def sync_catalog_from_vivape(db: AsyncSession = Depends(get_db)):
    raw_countries = await VivaPeAdapter.get_countries(db)
    synced_c = 0
    synced_p = 0

    popular_iso = ["US", "TH", "JP", "SA", "AE", "GB", "TR", "SG", "MY", "BD"]
    existing_res = await db.execute(select(Country.iso2))
    seen_iso = set(existing_res.scalars().all())

    for item in raw_countries:
        c_id = item.get("id")
        raw_iso = item.get("iso_alpha2") or item.get("iso2") or item.get("country_code", "")
        iso2 = raw_iso.strip().upper()
        name = item.get("country_name") or item.get("name", "")
        if not iso2 or iso2 in seen_iso:
            continue

        seen_iso.add(iso2)
        c_obj = Country(
            id=c_id,
            iso2=iso2,
            name_en=name,
            flag_url=f"https://flagcdn.com/w80/{iso2.lower()}.png",
            is_popular=iso2 in popular_iso,
            is_active=True
        )
        db.add(c_obj)
        synced_c += 1

    await db.commit()

    # Sync products for popular destination countries
    import re
    top_c = await db.execute(select(Country).where(Country.is_popular == True))
    for c in top_c.scalars().all():
        raw_products = await VivaPeAdapter.get_products(db, c.id)
        for p in raw_products:
            ref = str(p.get("reference") or "")
            title = str(p.get("title") or p.get("name") or "")
            if "esim" not in ref.lower() and "esim" not in title.lower():
                continue

            cost = Decimal(str(p.get("price") or p.get("amount") or 5.0))
            retail = (cost * Decimal("1.25")).quantize(Decimal("0.0001"))

            gb_match = re.search(r"(\d+(\.\d+)?)\s*GB", title, re.IGNORECASE)
            days_match = re.search(r"(\d+)\s*Days?", title, re.IGNORECASE)

            data_amount = Decimal(gb_match.group(1)) if gb_match else Decimal("3.0")
            validity = int(days_match.group(1)) if days_match else 15

            p_obj = Product(
                supplier_product_id=p.get("id"),
                country_id=c.id,
                title_en=title or f"{c.name_en} eSIM",
                data_amount_gb=data_amount,
                validity_days=validity,
                cost_price=cost,
                retail_price=retail,
                currency="USD",
                supplier_reference=ref
            )
            db.add(p_obj)
            synced_p += 1

    await db.commit()
    return {"status": "success", "synced_countries": synced_c, "synced_products": synced_p}

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
            "created_at": m.created_at
        }
        for m, u in res.all()
    ]

@router.post("/merchants/{merchant_id}/approve", dependencies=[Depends(require_admin)])
async def approve_merchant(
    merchant_id: str,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(MerchantProfile).where(MerchantProfile.id == merchant_id))
    m = res.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant application not found")

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
        action="APPROVE_MERCHANT", after_state={"merchant_id": m.id, "business": m.business_name}
    )
    await db.commit()
    return {"status": "success", "message": "Merchant approved"}

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
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(ManualPaymentRequest).where(ManualPaymentRequest.id == request_id))
    p = res.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Payment request not found")

    p.status = ManualPaymentStatus.APPROVED
    p.reviewed_by_id = admin_user.id

    # Credit Default Wallet
    w_res = await db.execute(
        select(Wallet).where(Wallet.user_id == p.user_id, Wallet.wallet_type == WalletType.DEFAULT)
    )
    wallet = w_res.scalar_one_or_none()
    if wallet:
        # Convert BDT to USD if currency is BDT
        rate = await CurrencyService.get_effective_rate(db, p.currency)
        amount_usd = (Decimal(str(p.amount)) / rate).quantize(Decimal("0.0001"))
        await LedgerService.credit(
            db, wallet.id, amount_usd,
            LedgerRefType.DEPOSIT_MANUAL,
            ref_id=p.id,
            description=f"Manual Deposit Approved ({p.amount} {p.currency})"
        )

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="APPROVE_MANUAL_PAYMENT", after_state={"payment_id": p.id, "amount": float(p.amount)}
    )
    await db.commit()
    return {"status": "success", "message": "Payment approved and wallet credited"}

# --- Super Admin Controls: Branding, Currency, Languages ---
@router.put("/branding", dependencies=[Depends(require_super_admin)])
async def update_branding(
    req: UpdateBrandingRequest,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    updates = req.model_dump(exclude_unset=True)
    for k, v in updates.items():
        res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == k))
        setting = res.scalar_one_or_none()
        if setting:
            setting.value = v
            setting.updated_by_id = admin_user.id
        else:
            setting = PlatformSetting(key=k, value=v, is_public=True, updated_by_id=admin_user.id)
            db.add(setting)

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="UPDATE_BRANDING", after_state=updates
    )
    await db.commit()
    return {"status": "success", "updated": list(updates.keys())}

@router.put("/currencies/override", dependencies=[Depends(require_super_admin)])
async def override_currency_rate(
    req: CurrencyOverrideRequest,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(CurrencyRate).where(CurrencyRate.currency_code == req.currency_code.upper()))
    rate_obj = res.scalar_one_or_none()
    if not rate_obj:
        raise HTTPException(status_code=404, detail="Currency not supported")

    rate_obj.is_manual_override = req.is_manual_override
    if req.is_manual_override and req.manual_rate:
        rate_obj.manual_rate = req.manual_rate
        rate_obj.source = "MANUAL_OVERRIDE"
    else:
        rate_obj.source = "AUTO_API"

    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="CURRENCY_RATE_OVERRIDE",
        after_state={"currency": req.currency_code, "override": req.is_manual_override, "rate": float(req.manual_rate or 0)}
    )
    await db.commit()
    return {"status": "success", "currency": req.currency_code}

@router.put("/languages/toggle", dependencies=[Depends(require_super_admin)])
async def toggle_language(
    req: LanguageToggleRequest,
    admin_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(Language).where(Language.code == req.code.lower()))
    lang = res.scalar_one_or_none()
    if not lang:
        raise HTTPException(status_code=404, detail="Language not found")

    lang.is_active = req.is_active
    await AuditService.log_action(
        db, actor_id=admin_user.id, actor_role=admin_user.role.value,
        action="LANGUAGE_TOGGLE", after_state={"code": req.code, "is_active": req.is_active}
    )
    await db.commit()
    return {"status": "success", "language": req.code, "is_active": req.is_active}

# --- 360 Log Viewers ---
@router.get("/audit-logs", dependencies=[Depends(require_super_admin)])
async def get_audit_logs(limit: int = 50, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    return res.scalars().all()

@router.get("/supplier-logs", dependencies=[Depends(require_admin)])
async def get_supplier_logs(limit: int = 50, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(SupplierTransactionLog).order_by(SupplierTransactionLog.created_at.desc()).limit(limit))
    return res.scalars().all()
