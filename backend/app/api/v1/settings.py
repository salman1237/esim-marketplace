from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from app.services.legal_content_svc import LEGAL_TITLES, fill_placeholders, get_legal_document
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings as app_settings
from app.core.database import get_db
from app.core.seed_translations import EN_TRANSLATIONS
from app.models.settings import PlatformSetting, CurrencyRate, Language, Translation
from app.services.payment_methods_svc import PAYMENT_METHODS_KEY, parse_payment_methods
from app.schemas.settings import PublicSettingsResponse, CurrencyRateResponse, LanguageResponse, TranslationsResponse

router = APIRouter(prefix="/settings", tags=["Public Settings"])

@router.get("/public", response_model=PublicSettingsResponse)
async def get_public_settings(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(PlatformSetting).where(PlatformSetting.is_public == True))
    settings_rows = res.scalars().all()
    cfg = {s.key: s.value for s in settings_rows}

    return PublicSettingsResponse(
        platform_name=cfg.get("platform_name", "eSIM Global"),
        tagline_en=cfg.get("tagline_en", "Instant Global eSIM Data in 200+ Destinations"),
        tagline_bn=cfg.get("tagline_bn", "২০০+ দেশে ইন্সট্যান্ট গ্লোবাল ই-সিম ইন্টারনেট ডাটা"),
        logo_light=cfg.get("logo_light"),
        logo_dark=cfg.get("logo_dark"),
        favicon=cfg.get("favicon"),
        # No made-up fallbacks: an unset contact is hidden, not shown as a fake number.
        support_phone=cfg.get("support_phone") or None,
        support_email=cfg.get("support_email") or None,
        support_whatsapp=cfg.get("support_whatsapp") or None,
        default_currency=cfg.get("default_currency", app_settings.DEFAULT_CURRENCY),
        maintenance_mode=bool(cfg.get("maintenance_mode", False)),
        social_links=cfg.get("social_links") or {},
        seo_title=cfg.get("seo_title"),
        seo_description=cfg.get("seo_description"),
        og_image=cfg.get("og_image"),
        bangla_qr_image=cfg.get("bangla_qr_image"),
        payment_methods=[m for m in parse_payment_methods(cfg.get(PAYMENT_METHODS_KEY)) if m.is_active],
        google_client_id=app_settings.GOOGLE_CLIENT_ID or None,
    )

@router.get("/legal")
async def list_legal_documents(db: AsyncSession = Depends(get_db)):
    docs = [await get_legal_document(db, slug) for slug in LEGAL_TITLES]
    return [{k: d[k] for k in ("slug", "title", "updated_at")} for d in docs]

@router.get("/legal/{slug}")
async def get_legal(slug: str, db: AsyncSession = Depends(get_db)):
    doc = await get_legal_document(db, slug)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    res = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key.in_(["platform_name", "support_email"]), PlatformSetting.is_public == True)
    )
    cfg = {s.key: s.value for s in res.scalars().all()}
    return {
        "slug": doc["slug"],
        "title": doc["title"],
        "body": fill_placeholders(doc["body"], cfg.get("platform_name"), cfg.get("support_email")),
        "updated_at": doc["updated_at"],
    }

@router.get("/languages", response_model=List[LanguageResponse])
async def list_languages(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Language).where(Language.is_active == True))
    return res.scalars().all()

@router.get("/rates", response_model=List[CurrencyRateResponse])
async def list_rates(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(CurrencyRate))
    return res.scalars().all()

@router.get("/translations/{language_code}", response_model=TranslationsResponse)
async def get_translations(language_code: str, db: AsyncSession = Depends(get_db)):
    """Returns all translation strings for a language, grouped by namespace.
    Any key missing for the requested language falls back to the English
    value, so the frontend never has to handle a gap itself."""
    namespaces: dict = {ns: dict(entries) for ns, entries in EN_TRANSLATIONS.items()}

    # DB rows (Super Admin edits, or seeded/auto-translated non-English
    # strings) overlay the English base — including for "en" itself, so
    # editing an English string through the Translation Editor takes effect.
    res = await db.execute(select(Translation).where(Translation.language_code == language_code.lower()))
    for t in res.scalars().all():
        namespaces.setdefault(t.namespace, {})[t.key] = t.value

    return TranslationsResponse(language_code=language_code.lower(), namespaces=namespaces)
