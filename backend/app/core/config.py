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
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change_this_super_secret_key_in_production_32chars_min")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
    # Upstream Supplier: VivaPe API
    VIVAPE_BASE_URL: str = os.getenv("VIVAPE_BASE_URL", "https://app.vivape.net/api")
    VIVAPE_EMAIL: str = os.getenv("VIVAPE_EMAIL", "merchantusd@vivape.co")
    VIVAPE_PASSWORD: str = os.getenv("VIVAPE_PASSWORD", "merchantusd@36")
    VIVAPE_CURRENCY: str = "USD"
    
    # Payment Gateway: ShurjoPay Sandbox
    SHURJOPAY_BASE_URL: str = os.getenv("SHURJOPAY_BASE_URL", "https://sandbox.shurjopayment.com")
    SHURJOPAY_USERNAME: str = os.getenv("SHURJOPAY_USERNAME", "sp_sandbox")
    SHURJOPAY_PASSWORD: str = os.getenv("SHURJOPAY_PASSWORD", "pyyk97hu&6u6")
    SHURJOPAY_PREFIX: str = os.getenv("SHURJOPAY_PREFIX", "NOK")
    SHURJOPAY_RETURN_URL: str = os.getenv("SHURJOPAY_RETURN_URL", "http://localhost:3000/payments/callback")
    SHURJOPAY_CANCEL_URL: str = os.getenv("SHURJOPAY_CANCEL_URL", "http://localhost:3000/payments/cancel")
    
    # Currency Engine
    EXCHANGE_RATE_API_URL: str = "https://open.er-api.com/v6/latest"
    EXCHANGE_RATE_FALLBACK_URL: str = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies"
    DEFAULT_CURRENCY: str = "USD"
    
    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()
