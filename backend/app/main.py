import asyncio
import uuid
import structlog
from decimal import Decimal
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.core.rate_limit import limiter
from sqlalchemy import select
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.user import User, UserRole, UserStatus
from app.models.settings import PlatformSetting, CurrencyRate, Language, Translation
from app.services.ledger_svc import LedgerService
from app.services.currency_svc import CurrencyService
from app.services.catalog_sync_svc import sync_vivape_catalog
from app.core.seed_translations import SHIPPED_LOCALE_CODES, PLACEHOLDER_LANGUAGES, load_shipped_translations, flatten, EN_TRANSLATIONS
from app.core.logging import configure_logging, get_logger
from app.api.v1 import api_v1_router

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is managed by Alembic migrations (run via entrypoint.sh before
    # this process starts), not by the app itself — see backend/alembic/.

    # Seed initial Super Admin, platform settings, currencies, and languages
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

    scheduler = AsyncIOScheduler()
    if settings.CATALOG_SYNC_INTERVAL_HOURS > 0:
        async def _scheduled_catalog_sync():
            async with AsyncSessionLocal() as db:
                try:
                    result = await sync_vivape_catalog(db)
                    logger.info("scheduled_catalog_sync_completed", **result)
                except Exception as e:
                    # A failed sync (VivaPe down, network blip) must not
                    # crash the scheduler - just log and let the next
                    # scheduled run try again.
                    logger.warning("scheduled_catalog_sync_failed", error=str(e))

        scheduler.add_job(
            _scheduled_catalog_sync, "interval",
            hours=settings.CATALOG_SYNC_INTERVAL_HOURS,
            id="vivape_catalog_sync", max_instances=1,
        )
        scheduler.start()
        logger.info("catalog_sync_scheduler_started", interval_hours=settings.CATALOG_SYNC_INTERVAL_HOURS)
        # APScheduler's interval trigger only fires after a full interval
        # has elapsed, not on registration - without this, a deploy would
        # otherwise wait up to CATALOG_SYNC_INTERVAL_HOURS before the
        # catalog ever refreshed automatically. Backgrounded so a slow
        # VivaPe response doesn't delay the app's own startup/health check.
        asyncio.create_task(_scheduled_catalog_sync())

    yield

    if scheduler.running:
        scheduler.shutdown(wait=False)

app = FastAPI(
    title="eSIM Marketplace API",
    description="Backend API for Global eSIM Marketplace Platform",
    version="1.0.0",
    lifespan=lifespan
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

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

# Serves admin-uploaded branding assets (logo/favicon) from the uploads_data
# volume — mounted under /api/v1 so it rides the same Dokploy/Traefik path
# rule as the rest of the API instead of needing a separate route.
import os
os.makedirs(settings.UPLOADS_DIR, exist_ok=True)
app.mount("/api/v1/uploads", StaticFiles(directory=settings.UPLOADS_DIR), name="uploads")

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
