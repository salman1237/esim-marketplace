import pytest
import httpx
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.models.settings import CurrencyRate
from app.services.currency_svc import CurrencyService

pytestmark = pytest.mark.asyncio


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _mock_get_factory(primary_ok: bool):
    async def _mock_get(self, url, *args, **kwargs):
        if "open.er-api.com" in str(url):
            if not primary_ok:
                raise httpx.ConnectError("simulated primary outage")
            return _FakeResponse(200, {"rates": {"USD": 1, "BDT": 111.11, "EUR": 0.80}})
        if "jsdelivr.net" in str(url):
            # Real shape: {"usd": {"bdt": ..., "eur": ...}} - lowercase keys.
            return _FakeResponse(200, {"usd": {"bdt": 122.22, "eur": 0.85}})
        raise AssertionError(f"Unexpected URL in test: {url}")
    return _mock_get


async def _set_bdt_rate(db_session, **fields):
    """Tests share one persistent DB with no per-test rollback (see
    conftest.py) - a plain INSERT collides with the "BDT" row main.py's
    own startup seeding (or an earlier test in this file) may already
    have created. Delete-then-insert instead of a blind add()."""
    existing = await db_session.execute(select(CurrencyRate).where(CurrencyRate.currency_code == "BDT"))
    row = existing.scalar_one_or_none()
    if row:
        await db_session.delete(row)
        await db_session.flush()
    db_session.add(CurrencyRate(currency_code="BDT", **fields))
    await db_session.commit()


async def test_primary_source_used_when_available(db_session, monkeypatch):
    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get_factory(primary_ok=True))
    result = await CurrencyService.sync_rates_from_api(db_session)
    await db_session.commit()
    assert result["status"] == "success"

    res = await db_session.execute(select(CurrencyRate).where(CurrencyRate.currency_code == "BDT"))
    rate = res.scalar_one()
    assert Decimal(str(rate.rate_to_base)) == Decimal("111.11")
    assert rate.source == "AUTO_API"


async def test_fallback_to_jsdelivr_when_primary_fails(db_session, monkeypatch):
    """Regression-proofing for the plan's explicit requirement: 'Verify
    live rates fetch from open.er-api.com and fallback to jsDelivr CDN if
    mock failure is injected.' Confirms both that the fallback fires at
    all and that its differently-shaped response ({"usd": {...}}
    lowercase, vs. primary's {"rates": {...}} uppercase) parses correctly."""
    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get_factory(primary_ok=False))
    result = await CurrencyService.sync_rates_from_api(db_session)
    await db_session.commit()
    assert result["status"] == "success"

    res = await db_session.execute(select(CurrencyRate).where(CurrencyRate.currency_code == "BDT"))
    rate = res.scalar_one()
    assert Decimal(str(rate.rate_to_base)) == Decimal("122.22")


async def test_both_sources_failing_returns_error_without_crashing(db_session, monkeypatch):
    async def _always_fail(self, url, *args, **kwargs):
        raise httpx.ConnectError("simulated total outage")
    monkeypatch.setattr(httpx.AsyncClient, "get", _always_fail)

    result = await CurrencyService.sync_rates_from_api(db_session)
    assert "error" in result


async def test_manual_override_takes_precedence_over_live_rate(db_session, monkeypatch):
    """Regression-proofing: 'Verify Super Admin manual overrides take
    priority over live rates.' A stale/wrong live rate must never leak
    through once a manual override is set - and the override must not
    even trigger a live API call."""
    async def _fail_if_called(self, url, *args, **kwargs):
        raise AssertionError("get_effective_rate should not call the API when a manual override exists")
    monkeypatch.setattr(httpx.AsyncClient, "get", _fail_if_called)

    await _set_bdt_rate(
        db_session, rate_to_base=Decimal("100.00"),
        is_manual_override=True, manual_rate=Decimal("130.00"), source="MANUAL_OVERRIDE",
        updated_at=datetime.now(timezone.utc),
    )

    rate = await CurrencyService.get_effective_rate(db_session, "BDT")
    assert rate == Decimal("130.00")


async def test_stale_rate_triggers_resync(db_session, monkeypatch):
    """6h TTL: a rate last updated more than 6 hours ago must trigger a
    fresh sync rather than silently serving a stale value forever."""
    await _set_bdt_rate(
        db_session, rate_to_base=Decimal("100.00"),
        is_manual_override=False, source="AUTO_API",
        updated_at=datetime.now(timezone.utc) - timedelta(hours=7),
    )

    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get_factory(primary_ok=True))
    rate = await CurrencyService.get_effective_rate(db_session, "BDT")
    assert rate == Decimal("111.11")  # the fresh mocked value, not the stale 100.00


async def test_convert_uses_fixed_point_decimal_not_float(db_session):
    """Regression-proofing: 'Verify fixed-point decimal arithmetic avoids
    floating-point inaccuracies.' 0.1 + 0.2 style drift must not appear."""
    await _set_bdt_rate(
        db_session, rate_to_base=Decimal("110.1"),
        is_manual_override=False, source="AUTO_API",
        updated_at=datetime.now(timezone.utc),
    )

    converted = await CurrencyService.convert(db_session, Decimal("9.99"), "BDT")
    assert converted == Decimal("9.99") * Decimal("110.1")
    assert isinstance(converted, Decimal)
    # Quantized to 4 decimal places, not an unbounded float-derived tail.
    assert converted == converted.quantize(Decimal("0.0001"))
