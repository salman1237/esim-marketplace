import os
from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "eSIM Marketplace"
    ENVIRONMENT: str = "production"
    
    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://esim_user:esim_secure_password_2026@esim-db:5432/esim_db"
    )
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-only-insecure-secret-key-do-not-use-in-production")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
    # Upstream Supplier: VivaPe API. No real credential default here — see
    # the production boot guard below, which refuses to start with these
    # dev-only placeholders when ENVIRONMENT=production (same pattern as
    # SECRET_KEY). Local dev/tests never call the real API directly
    # (mocked/monkeypatched), so a placeholder is fine there.
    VIVAPE_BASE_URL: str = os.getenv("VIVAPE_BASE_URL", "https://app.vivape.net/api")
    VIVAPE_EMAIL: str = os.getenv("VIVAPE_EMAIL", "dev-only-not-a-real-account@example.com")
    VIVAPE_PASSWORD: str = os.getenv("VIVAPE_PASSWORD", "dev-only-not-a-real-password")
    VIVAPE_CURRENCY: str = "EUR"

    # Payment Gateway: ShurjoPay
    SHURJOPAY_BASE_URL: str = os.getenv("SHURJOPAY_BASE_URL", "https://sandbox.shurjopayment.com")
    SHURJOPAY_USERNAME: str = os.getenv("SHURJOPAY_USERNAME", "dev-only-not-a-real-username")
    SHURJOPAY_PASSWORD: str = os.getenv("SHURJOPAY_PASSWORD", "dev-only-not-a-real-password")
    SHURJOPAY_PREFIX: str = os.getenv("SHURJOPAY_PREFIX", "NOK")
    # Must be a URL the customer's browser can actually reach after leaving
    # the ShurjoPay checkout page — a localhost default here is a real bug,
    # not a placeholder: it silently breaks the return trip for every real
    # user (a Dokploy env var is normally the intended override, but a
    # deployment that forgets to set one should still get a working
    # default, not one that only ever worked on a developer's own machine).
    SHURJOPAY_RETURN_URL: str = os.getenv("SHURJOPAY_RETURN_URL", "https://triptel.co/api/v1/payments/shurjopay/callback")
    SHURJOPAY_CANCEL_URL: str = os.getenv("SHURJOPAY_CANCEL_URL", "https://triptel.co/wallet?topup=cancelled")

    # Where GET /payments/shurjopay/callback redirects the browser after
    # processing — the frontend's own origin, not this API's.
    FRONTEND_BASE_URL: str = os.getenv("FRONTEND_BASE_URL", "https://triptel.co")

    # Sign in with Google - the OAuth 2.0 *Web* client ID from Google Cloud
    # Console (project "triptel", authorized origin https://triptel.co). Not a
    # secret: it ships to browsers. Only the ID-token flow is used, so the
    # client secret is never needed. Set the env var to "" to disable.
    GOOGLE_CLIENT_ID: str = os.getenv(
        "GOOGLE_CLIENT_ID", "1095507553767-hkuh44db04q1lvrnptill6frtckcb42t.apps.googleusercontent.com"
    )

    # Transactional email (password reset, order confirmation, welcome).
    # Deliberately optional, unlike the VivaPe/ShurjoPay/SECRET_KEY guards:
    # an unconfigured SMTP_HOST means EmailService just logs a warning and
    # skips sending rather than failing the request that triggered it -
    # registration/checkout must never break because email isn't set up.
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    SMTP_FROM_EMAIL: str = os.getenv("SMTP_FROM_EMAIL", "no-reply@esim.local")
    SMTP_FROM_NAME: str = os.getenv("SMTP_FROM_NAME", "eSIM Global")

    @property
    def smtp_configured(self) -> bool:
        return bool(self.SMTP_HOST and self.SMTP_USERNAME)

    # Admin-uploaded branding assets (logo/favicon). Defaults to "uploads"
    # (relative to the process's working directory) so local dev and CI —
    # where /app doesn't exist and isn't creatable without root — just get
    # a throwaway folder; the real deployment overrides this to the
    # /app/uploads path backed by the uploads_data Docker volume.
    UPLOADS_DIR: str = os.getenv("UPLOADS_DIR", "uploads")

    # KYC documents (national ID photos) - deliberately a SEPARATE
    # directory from UPLOADS_DIR, which is served publicly via the
    # StaticFiles mount in main.py. These are only ever served through an
    # authenticated endpoint (GET /admin/kyc/{id}/document/{side}).
    KYC_UPLOADS_DIR: str = os.getenv("KYC_UPLOADS_DIR", "kyc_uploads")

    # Payout proof screenshots attached when an admin marks a withdrawal
    # paid. Private for the same reason as KYC: the image shows a bank or
    # mobile-wallet account. Only served via GET /admin/withdrawals/{id}/proof
    # and the owner's own receipt endpoint.
    WITHDRAWAL_UPLOADS_DIR: str = os.getenv("WITHDRAWAL_UPLOADS_DIR", "withdrawal_uploads")

    # Support ticket attachments. Private for the same reason as the two
    # above: a customer troubleshooting an eSIM will photograph a screen
    # showing their own account details. Served only to the ticket's owner
    # and to staff, never from the public uploads mount.
    SUPPORT_UPLOADS_DIR: str = os.getenv("SUPPORT_UPLOADS_DIR", "support_uploads")

    # How often the background job re-syncs the VivaPe catalog (countries +
    # products for the popular-destination list). 0 disables the scheduled
    # job entirely (sync still available on-demand via POST
    # /admin/catalog/sync) - useful for local dev where nobody wants a
    # background job silently hitting the live VivaPe API.
    CATALOG_SYNC_INTERVAL_HOURS: float = float(os.getenv("CATALOG_SYNC_INTERVAL_HOURS", "4"))

    # Currency Engine
    EXCHANGE_RATE_API_URL: str = "https://open.er-api.com/v6/latest"
    EXCHANGE_RATE_FALLBACK_URL: str = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies"
    # Every stored money amount - product prices, wallet balances, ledger,
    # orders, commission - is in this currency. It is VivaPe's pricing
    # currency, so catalog costs are stored exactly as VivaPe reports them.
    # Exchange rates are stored as "1 BASE_CURRENCY = X".
    BASE_CURRENCY: str = "EUR"
    DEFAULT_CURRENCY: str = "EUR"

    # CORS: comma-separated list of allowed origins. Never combine a "*"
    # wildcard with allow_credentials=True (browsers reject it, and any
    # server that honored it would allow cross-site credentialed requests).
    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:3001")

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]
    
    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()

if settings.ENVIRONMENT == "production":
    if settings.SECRET_KEY == "dev-only-insecure-secret-key-do-not-use-in-production":
        raise RuntimeError(
            "SECRET_KEY environment variable must be set to a unique, random value in production "
            "(the app refuses to boot with the committed development default)."
        )
    _dev_only_placeholders = {
        "VIVAPE_EMAIL": "dev-only-not-a-real-account@example.com",
        "VIVAPE_PASSWORD": "dev-only-not-a-real-password",
        "SHURJOPAY_USERNAME": "dev-only-not-a-real-username",
        "SHURJOPAY_PASSWORD": "dev-only-not-a-real-password",
    }
    _unset = [k for k, placeholder in _dev_only_placeholders.items() if getattr(settings, k) == placeholder]
    if _unset:
        raise RuntimeError(
            f"{', '.join(_unset)} must be set via environment variables in production "
            "(the app refuses to boot with committed development placeholders — these used to be "
            "real credentials hardcoded in this file, which is exactly the problem this guard exists to prevent)."
        )
