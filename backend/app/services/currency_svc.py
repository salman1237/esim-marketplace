import ssl
import httpx
from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.settings import CurrencyRate
from app.core.config import settings

class CurrencyService:
    @staticmethod
    async def sync_rates_from_api(db: AsyncSession) -> dict:
        rates = {}
        # 1. Try Primary: open.er-api.com
        try:
            async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                resp = await client.get(f"{settings.EXCHANGE_RATE_API_URL}/USD")
                if resp.status_code == 200:
                    data = resp.json()
                    rates = data.get("rates", {})
        except Exception as e:
            print("Primary exchange rate API error:", e)

        # 2. Fallback if empty: jsDelivr CDN
        if not rates:
            try:
                async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                    resp = await client.get(f"{settings.EXCHANGE_RATE_FALLBACK_URL}/usd.json")
                    if resp.status_code == 200:
                        data = resp.json()
                        raw_rates = data.get("usd", {})
                        rates = {k.upper(): v for k, v in raw_rates.items()}
            except Exception as e:
                print("Fallback exchange rate API error:", e)

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
        if currency_code.upper() == "USD":
            return Decimal("1.0")
        
        res = await db.execute(select(CurrencyRate).where(CurrencyRate.currency_code == currency_code.upper()))
        record = res.scalar_one_or_none()
        if record:
            if record.is_manual_override and record.manual_rate:
                return Decimal(str(record.manual_rate))
            return Decimal(str(record.rate_to_base))
        
        # Default safe fallbacks if not yet in DB
        defaults = {"BDT": Decimal("122.50"), "EUR": Decimal("0.86"), "GBP": Decimal("0.74")}
        return defaults.get(currency_code.upper(), Decimal("1.0"))

    @staticmethod
    async def convert(db: AsyncSession, amount_usd: Decimal, target_currency: str) -> Decimal:
        rate = await CurrencyService.get_effective_rate(db, target_currency)
        converted = amount_usd * rate
        return converted.quantize(Decimal("0.0001"))
