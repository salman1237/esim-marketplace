from typing import Optional, Any, Dict
from decimal import Decimal
from pydantic import BaseModel

class PublicSettingsResponse(BaseModel):
    platform_name: str = "eSIM Global"
    tagline_en: str = "Instant Global eSIM Data in 200+ Destinations"
    tagline_bn: str = "২০০+ দেশে ইন্সট্যান্ট গ্লোবাল ই-সিম ইন্টারনেট ডাটা"
    logo_light: Optional[str] = None
    logo_dark: Optional[str] = None
    favicon: Optional[str] = None
    support_phone: Optional[str] = None
    support_email: Optional[str] = None
    support_whatsapp: Optional[str] = None
    default_currency: str = "EUR"
    maintenance_mode: bool = False
    social_links: Dict[str, str] = {}
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    og_image: Optional[str] = None
    bangla_qr_image: Optional[str] = None
    # OAuth client ID for the "Sign in with Google" button; None hides it.
    google_client_id: Optional[str] = None

class UpdateBrandingRequest(BaseModel):
    platform_name: Optional[str] = None
    tagline_en: Optional[str] = None
    tagline_bn: Optional[str] = None
    logo_light: Optional[str] = None
    logo_dark: Optional[str] = None
    favicon: Optional[str] = None
    support_phone: Optional[str] = None
    support_email: Optional[str] = None
    support_whatsapp: Optional[str] = None
    maintenance_mode: Optional[bool] = None
    default_currency: Optional[str] = None
    # Keyed by platform (facebook/instagram/twitter/youtube/linkedin) -> URL.
    # A JSON PlatformSetting value, so no migration needed - same generic
    # upsert path as every other branding field.
    social_links: Optional[Dict[str, str]] = None
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    og_image: Optional[str] = None
    bangla_qr_image: Optional[str] = None

class CurrencyRateResponse(BaseModel):
    currency_code: str
    rate_to_base: Decimal
    is_manual_override: bool
    manual_rate: Optional[Decimal] = None
    source: str

    class Config:
        from_attributes = True

class CurrencyOverrideRequest(BaseModel):
    currency_code: str
    is_manual_override: bool
    manual_rate: Optional[Decimal] = None

class LanguageResponse(BaseModel):
    code: str
    name: str
    native_name: str
    flag_emoji: Optional[str] = None
    is_active: bool
    is_rtl: bool

    class Config:
        from_attributes = True

class LanguageToggleRequest(BaseModel):
    code: str
    is_active: bool

class LanguageCreateRequest(BaseModel):
    code: str
    name: str
    native_name: str
    flag_emoji: Optional[str] = None
    is_rtl: bool = False
    seed_from_english: bool = True

class TranslationsResponse(BaseModel):
    language_code: str
    namespaces: Dict[str, Dict[str, str]]

class TranslationUpsertRequest(BaseModel):
    language_code: str
    namespace: str
    key: str
    value: str
