from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.deps import require_admin, require_super_admin
from app.models.user import User, UserRole, UserStatus
from app.models.merchant import MerchantProfile, MerchantStatus
from app.models.wallet import Wallet, WalletType, LedgerRefType
from app.models.order import Order, ESIMProfile
from app.models.catalog import Country, Product
from app.models.payment import ManualPaymentRequest, ManualPaymentStatus
from app.models.settings import PlatformSetting, CurrencyRate, Language, Translation
from app.models.audit import AuditLog, SupplierTransactionLog
from app.core.seed_translations import EN_TRANSLATIONS, flatten
from app.schemas.settings import (
    UpdateBrandingRequest, CurrencyOverrideRequest, LanguageToggleRequest,
    LanguageCreateRequest, TranslationUpsertRequest,
)
from app.services.ledger_svc import LedgerService
from app.services.audit_svc import AuditService
from app.services.vivape_adapter import VivaPeAdapter
from app.services.currency_svc import CurrencyService


from pydantic import BaseModel
from typing import Optional

class ProductUpdateRequest(BaseModel):
    retail_price: Optional[float] = None
    is_active: Optional[bool] = None

class UserRoleUpdateRequest(BaseModel):
    role: UserRole

class UserStatusUpdateRequest(BaseModel):
    is_active: bool

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
            ESIM_REFERENCES = ("esimgo_bundle", "worldmove_esim")
            if ref.lower() not in ESIM_REFERENCES and "esim" not in title.lower():
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
        # Convert BDT to USD if currency is BDT
        rate = await CurrencyService.get_effective_rate(db, p.currency)
        amount_usd = (Decimal(str(p.amount)) / rate).quantize(Decimal("0.0001"))
        await LedgerService.credit(
            db, wallet.id, amount_usd,
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

@router.get("/supplier-logs", dependencies=[Depends(require_admin)])
async def get_supplier_logs(limit: int = 50, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(SupplierTransactionLog).order_by(SupplierTransactionLog.created_at.desc()).limit(limit))
    return res.scalars().all()


# --- Admin Operations: Customer Orders Viewer ---
@router.get("/orders", dependencies=[Depends(require_admin)])
async def get_all_orders(limit: int = 100, db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(Order, User, Product)
        .join(User, Order.buyer_id == User.id)
        .join(Product, Order.product_id == Product.id)
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
            "created_at": o.created_at
        }
        for o, u, p in res.all()
    ]

# --- Admin Operations: Catalog Editor ---
@router.get("/catalog", dependencies=[Depends(require_admin)])
async def get_admin_catalog(limit: int = 200, db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(Product, Country)
        .join(Country, Product.country_id == Country.id)
        .order_by(Product.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": p.id,
            "title": p.title_en,
            "country": c.name_en,
            "data_gb": float(p.data_amount_gb),
            "validity_days": p.validity_days,
            "cost_price": float(p.cost_price),
            "retail_price": float(p.retail_price),
            "currency": p.currency,
            "is_active": p.is_active
        }
        for p, c in res.all()
    ]

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

# --- Super Admin: Staff Management ---
@router.get("/users", dependencies=[Depends(require_super_admin)])
async def get_all_users(limit: int = 100, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(User).order_by(User.created_at.desc()).limit(limit))
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
