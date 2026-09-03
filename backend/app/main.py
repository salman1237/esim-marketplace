import uuid
from decimal import Decimal
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from app.core.config import settings
from app.core.database import engine, Base, AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.user import User, UserRole, UserStatus
from app.models.settings import PlatformSetting, CurrencyRate, Language
from app.services.ledger_svc import LedgerService
from app.services.currency_svc import CurrencyService
from app.api.v1 import api_v1_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Automatically create all database tables if they do not exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # 2. Seed initial Super Admin, platform settings, currencies, and languages
    async with AsyncSessionLocal() as db:
        # Super Admin
        sa_res = await db.execute(select(User).where(User.email == "superadmin@esim.local"))
        sa = sa_res.scalar_one_or_none()
        if not sa:
            sa = User(
                email="superadmin@esim.local",
                username="superadmin",
                hashed_password=get_password_hash("SuperAdmin2026!"),
                role=UserRole.SUPER_ADMIN,
                status=UserStatus.ACTIVE,
                full_name="Platform Super Admin"
            )
            db.add(sa)
            await db.commit()
            await db.refresh(sa)
            await LedgerService.ensure_wallets_for_user(db, sa.id, sa.role)
            print("Seeded default Super Admin: superadmin@esim.local / SuperAdmin2026!")

        # Default Settings
        default_settings = [
            ("platform_name", "eSIM Global"),
            ("tagline_en", "Instant Global eSIM Data in 200+ Destinations"),
            ("tagline_bn", "২০০+ দেশে ইন্সট্যান্ট গ্লোবাল ই-সিম ইন্টারনেট ডাটা"),
            ("support_phone", "+880 1700-000000"),
            ("support_email", "support@esim.local"),
            ("support_whatsapp", "+880 1700-000000"),
            ("default_currency", "USD"),
            ("maintenance_mode", False)
        ]
        for k, v in default_settings:
            res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == k))
            if not res.scalar_one_or_none():
                db.add(PlatformSetting(key=k, value=v, is_public=True))

        # Default Languages
        langs = [
            ("en", "English", "English", "🇺🇸", True, False),
            ("bn", "Bangla", "বাংলা", "🇧🇩", True, False),
            ("ar", "Arabic", "العربية", "🇸🇦", True, True),
            ("es", "Spanish", "Español", "🇪🇸", True, False),
            ("fr", "French", "Français", "🇫🇷", True, False),
            ("de", "German", "Deutsch", "🇩🇪", True, False),
            ("zh", "Chinese", "中文", "🇨🇳", True, False)
        ]
        for code, name, native, flag, active, rtl in langs:
            res = await db.execute(select(Language).where(Language.code == code))
            if not res.scalar_one_or_none():
                db.add(Language(code=code, name=name, native_name=native, flag_emoji=flag, is_active=active, is_rtl=rtl))

        # Default Currency Rates
        rates = [
            ("USD", Decimal("1.0"), False),
            ("BDT", Decimal("122.63"), False),
            ("EUR", Decimal("0.863"), False),
            ("GBP", Decimal("0.741"), False),
            ("AED", Decimal("3.672"), False),
            ("SAR", Decimal("3.750"), False),
            ("THB", Decimal("33.20"), False),
            ("SGD", Decimal("1.271"), False)
        ]
        for c_code, r_val, ov in rates:
            res = await db.execute(select(CurrencyRate).where(CurrencyRate.currency_code == c_code))
            if not res.scalar_one_or_none():
                db.add(CurrencyRate(currency_code=c_code, rate_to_base=r_val, is_manual_override=ov, source="AUTO_API"))

        await db.commit()

    yield

app = FastAPI(
    title="eSIM Marketplace API",
    description="Backend API for Global eSIM Marketplace Platform",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Correlation ID Middleware
@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    correlation_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    response = await call_next(request)
    response.headers["X-Request-ID"] = correlation_id
    return response

# Include Routers
app.include_router(api_v1_router)

@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "service": "esim-api",
        "version": "1.0.0"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
