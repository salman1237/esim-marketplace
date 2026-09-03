from typing import List, Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.settings import PlatformSetting, CurrencyRate, Language
from app.schemas.settings import PublicSettingsResponse, CurrencyRateResponse, LanguageResponse

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
        support_phone=cfg.get("support_phone", "+880 1700-000000"),
        support_email=cfg.get("support_email", "support@esim.local"),
        support_whatsapp=cfg.get("support_whatsapp", "+880 1700-000000"),
        default_currency=cfg.get("default_currency", "USD"),
        maintenance_mode=bool(cfg.get("maintenance_mode", False))
    )

@router.get("/languages", response_model=List[LanguageResponse])
async def list_languages(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Language).where(Language.is_active == True))
    return res.scalars().all()

@router.get("/rates", response_model=List[CurrencyRateResponse])
async def list_rates(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(CurrencyRate))
    return res.scalars().all()
