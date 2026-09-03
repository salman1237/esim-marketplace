import uuid
import structlog
from decimal import Decimal
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from app.core.config import settings
from app.core.database import engine, Base, AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.user import User, UserRole, UserStatus
from app.models.settings import PlatformSetting, CurrencyRate, Language, Translation
from app.services.ledger_svc import LedgerService
from app.services.currency_svc import CurrencyService
from app.core.seed_translations import SHIPPED_LOCALE_CODES, PLACEHOLDER_LANGUAGES, load_shipped_translations, flatten, EN_TRANSLATIONS
from app.core.logging import configure_logging, get_logger
from app.api.v1 import api_v1_router

configure_logging()
logger = get_logger(__name__)

async def _reset_stale_pre_migration_schema(conn):
    """One-time compatibility shim (2026-09-03 schema realignment).

    Several columns were renamed/restructured (users.phone_number -> phone,
    orders.user_id -> buyer_id + new beneficiary_id, etc.) but the app has
    no migration tool and creates schema via create_all, which only adds
    missing tables — it never alters existing ones. Any database created by
    an earlier version of this app is left with the old, incompatible
    columns, which crashes every route touching them.

    This detects that old schema (via the renamed users.phone_number
    column, which only exists pre-migration) and drops everything so
    create_all rebuilds it fresh from the current models. Confirmed safe to
    do unconditionally for this deployment (no production data to
    preserve). Once the schema is current this column no longer exists, so
    the check — and the drop — becomes a permanent no-op on every future
    boot; this is not a general-purpose migration mechanism and shouldn't
    be extended for future schema changes (use Alembic instead).
    """
    result = await conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'users' AND column_name = 'phone_number'"
    ))
    if result.first():
        logger.warning("stale_pre_migration_schema_detected_resetting")
        await conn.run_sync(Base.metadata.drop_all)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Automatically create all database tables if they do not exist
    async with engine.begin() as conn:
        await _reset_stale_pre_migration_schema(conn)
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
            logger.warning("seeded_default_super_admin", email="superadmin@esim.local")

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

        # Default Languages — shipped with real hand-authored strings
        shipped_langs = [
            ("en", "English", "English", "🇺🇸", False),
            ("bn", "Bangla", "বাংলা", "🇧🇩", False),
            ("ar", "Arabic", "العربية", "🇸🇦", True),
            ("es", "Spanish", "Español", "🇪🇸", False),
        ]
        for code, name, native, flag, rtl in shipped_langs:
            res = await db.execute(select(Language).where(Language.code == code))
            if not res.scalar_one_or_none():
                db.add(Language(code=code, name=name, native_name=native, flag_emoji=flag, is_active=True, is_rtl=rtl))
            if code != "en":
                t_res = await db.execute(select(Translation.id).where(Translation.language_code == code).limit(1))
                if not t_res.scalar_one_or_none():
                    for namespace, key, value in load_shipped_translations(code):
                        db.add(Translation(language_code=code, namespace=namespace, key=key, value=value, is_machine_translated=False))

        # Additional plan-listed languages without hand-authored strings yet:
        # seeded active with English placeholder text (flagged
        # is_machine_translated=True) so they're usable immediately rather
        # than blank, pending a Super Admin auto-translate/edit pass.
        for code, name, native, flag, rtl in PLACEHOLDER_LANGUAGES:
            res = await db.execute(select(Language).where(Language.code == code))
            if not res.scalar_one_or_none():
                db.add(Language(code=code, name=name, native_name=native, flag_emoji=flag, is_active=True, is_rtl=rtl))
                for namespace, key, value in flatten(EN_TRANSLATIONS):
                    db.add(Translation(language_code=code, namespace=namespace, key=key, value=value, is_machine_translated=True))

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

# CORS — explicit origin allowlist (required when allow_credentials=True;
# a "*" wildcard combined with credentials is both spec-invalid and a
# cross-site credential exposure).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Correlation ID Middleware — binds X-Request-ID into structlog's
# contextvars so every log line emitted while handling this request
# (including from services called deep in the stack) carries it.
@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    correlation_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=correlation_id)
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
