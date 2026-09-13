import httpx
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.settings import CurrencyRate
from app.core.config import settings
from app.core.logging import get_logger

RATE_TTL = timedelta(hours=6)
logger = get_logger(__name__)

class CurrencyService:
    @staticmethod
    async def sync_rates_from_api(db: AsyncSession) -> dict:
        rates = {}
        # 1. Try Primary: open.er-api.com
        try:
            async with httpx.AsyncClient(verify=True, timeout=10.0) as client:
                resp = await client.get(f"{settings.EXCHANGE_RATE_API_URL}/{settings.BASE_CURRENCY}")
                if resp.status_code == 200:
                    data = resp.json()
                    rates = data.get("rates", {})
        except Exception as e:
            logger.warning("currency_api_primary_failed", error=str(e))

        # 2. Fallback if empty: jsDelivr CDN
        if not rates:
            try:
                async with httpx.AsyncClient(verify=True, timeout=10.0) as client:
                    resp = await client.get(f"{settings.EXCHANGE_RATE_FALLBACK_URL}/{settings.BASE_CURRENCY.lower()}.json")
                    if resp.status_code == 200:
                        data = resp.json()
                        raw_rates = data.get(settings.BASE_CURRENCY.lower(), {})
                        rates = {k.upper(): v for k, v in raw_rates.items()}
            except Exception as e:
                logger.warning("currency_api_fallback_failed", error=str(e))

        if not rates:
            return {"error": "Could not fetch rates from either source"}

        # Store/update supported currencies
        supported = ["USD", "BDT", "EUR", "GBP", "AED", "SAR", "THB", "SGD", "JPY", "MYR", "INR"]
        for curr in supported:
            if curr in rates:
                rate_val = Decimal(str(rates[curr]))
                # Check existing
                res = await db.execute(select(CurrencyRate).where(CurrencyRate.currency_code == curr))
                existing = res.scalar_one_or_none()
                if existing:
                    existing.rate_to_base = rate_val
                    existing.updated_at = datetime.now(timezone.utc)
                else:
                    new_rate = CurrencyRate(
                        currency_code=curr,
                        rate_to_base=rate_val,
                        is_manual_override=False,
                        manual_rate=None,
                        source="AUTO_API",
                        updated_at=datetime.now(timezone.utc)
                    )
                    db.add(new_rate)
        
        await db.commit()
        return {"status": "success", "synced_currencies": len(rates)}

    @staticmethod
    async def get_effective_rate(db: AsyncSession, currency_code: str) -> Decimal:
        if currency_code.upper() == settings.BASE_CURRENCY:
            return Decimal("1.0")

        res = await db.execute(select(CurrencyRate).where(CurrencyRate.currency_code == currency_code.upper()))
        record = res.scalar_one_or_none()

        if record and record.is_manual_override and record.manual_rate:
            # A manual override always wins and is never auto-refreshed.
            return Decimal(str(record.manual_rate))

        if record:
            stale = record.updated_at is None or (datetime.now(timezone.utc) - record.updated_at) > RATE_TTL
            if stale:
                await CurrencyService.sync_rates_from_api(db)
                await db.refresh(record)
            return Decimal(str(record.rate_to_base))

        # Not in the DB yet at all: try a live sync once, then fall back to a
        # safe default rather than blocking every subsequent call.
        await CurrencyService.sync_rates_from_api(db)
        res2 = await db.execute(select(CurrencyRate).where(CurrencyRate.currency_code == currency_code.upper()))
        record2 = res2.scalar_one_or_none()
        if record2:
            return Decimal(str(record2.rate_to_base))

        # Last-resort rates per 1 EUR, only if no source has ever been reachable.
        defaults = {"BDT": Decimal("142.10"), "USD": Decimal("1.16"), "GBP": Decimal("0.86")}
        return defaults.get(currency_code.upper(), Decimal("1.0"))

    @staticmethod
    async def convert(db: AsyncSession, amount: Decimal, target_currency: str) -> Decimal:
        """Converts an amount in the base currency (EUR) to target_currency."""
        rate = await CurrencyService.get_effective_rate(db, target_currency)
        converted = amount * rate
        return converted.quantize(Decimal("0.0001"))
