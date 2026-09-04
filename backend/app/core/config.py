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
    VIVAPE_CURRENCY: str = "USD"

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
    SHURJOPAY_RETURN_URL: str = os.getenv("SHURJOPAY_RETURN_URL", "https://esim.salmandev.io/api/v1/payments/shurjopay/callback")
    SHURJOPAY_CANCEL_URL: str = os.getenv("SHURJOPAY_CANCEL_URL", "https://esim.salmandev.io/wallet?topup=cancelled")

    # Where GET /payments/shurjopay/callback redirects the browser after
    # processing — the frontend's own origin, not this API's.
    FRONTEND_BASE_URL: str = os.getenv("FRONTEND_BASE_URL", "https://esim.salmandev.io")

    # Admin-uploaded branding assets (logo/favicon). Defaults to "uploads"
    # (relative to the process's working directory) so local dev and CI —
    # where /app doesn't exist and isn't creatable without root — just get
    # a throwaway folder; the real deployment overrides this to the
    # /app/uploads path backed by the uploads_data Docker volume.
    UPLOADS_DIR: str = os.getenv("UPLOADS_DIR", "uploads")

    # Currency Engine
    EXCHANGE_RATE_API_URL: str = "https://open.er-api.com/v6/latest"
    EXCHANGE_RATE_FALLBACK_URL: str = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies"
    DEFAULT_CURRENCY: str = "USD"

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
