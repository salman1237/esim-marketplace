"""Topping up in the customer's own currency.

Three currencies are in play and conflating them is the trap: the customer
types theirs, the wallet is held in EUR, and ShurjoPay always settles in BDT.
The rules worth guarding are that limits are still enforced in EUR whatever
was typed, and that someone typing taka is charged exactly the taka on screen.
"""
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.settings import CurrencyRate
from app.models.user import User
from conftest import register_and_login

pytestmark = pytest.mark.asyncio


async def _rate(db_session, code: str) -> Decimal:
    from app.services.currency_svc import CurrencyService
    return Decimal(str(await CurrencyService.get_effective_rate(db_session, code)))


def _gateway():
    """Captures what ShurjoPay would be asked to charge."""
    seen = {}

    async def fake_initiate(db, order_id, amount_bdt, **kwargs):
        seen["order_id"] = order_id
        seen["amount_bdt"] = Decimal(str(amount_bdt))
        return {"checkout_url": "https://example.test/pay", "sp_order_id": "sp-test"}

    from app.services.shurjopay_svc import ShurjoPayService
    return seen, patch.object(ShurjoPayService, "initiate_payment", AsyncMock(side_effect=fake_initiate))


async def test_an_account_carries_its_own_currency(client, db_session):
    user = await register_and_login(client, "curr")
    me = (await client.get("/api/v1/auth/me", headers=user["headers"])).json()
    assert me["preferred_currency"] == "EUR"

    saved = await client.put(
        "/api/v1/auth/me/preferences", json={"preferred_currency": "bdt"}, headers=user["headers"]
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["preferred_currency"] == "BDT"

    # It survives a fresh read, which browser storage never did across devices.
    me = (await client.get("/api/v1/auth/me", headers=user["headers"])).json()
    assert me["preferred_currency"] == "BDT"

    row = (await db_session.execute(select(User).where(User.id == user["user_id"]))).scalar_one()
    await db_session.refresh(row)
    assert row.preferred_currency == "BDT"


async def test_an_unknown_currency_is_refused(client, db_session):
    user = await register_and_login(client, "curr")
    res = await client.put(
        "/api/v1/auth/me/preferences", json={"preferred_currency": "XYZ"}, headers=user["headers"]
    )
    assert res.status_code == 400
    assert "rate" in res.json()["detail"]


async def test_typing_taka_charges_exactly_that_many_taka(client, db_session):
    """Round-tripping through EUR would bill a different number than the one
    on screen, which is indefensible on a payment page."""
    user = await register_and_login(client, "curr")
    seen, patched = _gateway()
    with patched:
        res = await client.post(
            "/api/v1/payments/shurjopay/topup?amount=1500&currency=BDT", headers=user["headers"]
        )
    assert res.status_code == 200, res.text
    assert seen["amount_bdt"] == Decimal("1500.0000")


async def test_typing_euros_still_converts_for_the_gateway(client, db_session):
    user = await register_and_login(client, "curr")
    seen, patched = _gateway()
    with patched:
        res = await client.post("/api/v1/payments/shurjopay/topup?amount=10", headers=user["headers"])
    assert res.status_code == 200, res.text
    expected = (Decimal("10") * await _rate(db_session, "BDT")).quantize(Decimal("0.0001"))
    assert seen["amount_bdt"] == expected


async def test_another_currency_converts_through_the_base(client, db_session):
    user = await register_and_login(client, "curr")
    usd_rate = await _rate(db_session, "USD")
    seen, patched = _gateway()
    with patched:
        res = await client.post(
            "/api/v1/payments/shurjopay/topup?amount=20&currency=USD", headers=user["headers"]
        )
    assert res.status_code == 200, res.text

    in_eur = (Decimal("20") / usd_rate).quantize(Decimal("0.0001"))
    expected = (in_eur * await _rate(db_session, "BDT")).quantize(Decimal("0.0001"))
    assert seen["amount_bdt"] == expected


async def test_limits_are_still_enforced_in_euros(client, db_session, promote_role):
    """A customer typing taka must hit the same floor and ceiling as one
    typing euros - otherwise the limits mean nothing outside the base currency."""
    admin = await register_and_login(client, "curradmin")
    await promote_role(admin["user_id"], "SUPER_ADMIN")
    await client.put(
        "/api/v1/admin/topup-limits", json={"min": "5", "max": "100"}, headers=admin["headers"]
    )

    user = await register_and_login(client, "curr")
    bdt_rate = await _rate(db_session, "BDT")
    seen, patched = _gateway()

    with patched:
        # 100 BDT is well under the 5 EUR floor.
        too_small = await client.post(
            "/api/v1/payments/shurjopay/topup?amount=100&currency=BDT", headers=user["headers"]
        )
        assert too_small.status_code == 400
        assert "between 5" in too_small.json()["detail"]

        # And a huge taka amount is over the 100 EUR ceiling.
        too_big = await client.post(
            f"/api/v1/payments/shurjopay/topup?amount={int(bdt_rate * 200)}&currency=BDT",
            headers=user["headers"],
        )
        assert too_big.status_code == 400
        assert "between 5" in too_big.json()["detail"]

        # Something inside the range works.
        ok_amount = int(bdt_rate * 20)
        fine = await client.post(
            f"/api/v1/payments/shurjopay/topup?amount={ok_amount}&currency=BDT", headers=user["headers"]
        )
        assert fine.status_code == 200, fine.text
        assert seen["amount_bdt"] == Decimal(ok_amount).quantize(Decimal("0.0001"))

    await client.put(
        "/api/v1/admin/topup-limits", json={"min": "1", "max": "2000"}, headers=admin["headers"]
    )


async def test_a_topup_currency_we_dont_hold_is_refused(client, db_session):
    user = await register_and_login(client, "curr")
    res = await client.post(
        "/api/v1/payments/shurjopay/topup?amount=10&currency=ZWL", headers=user["headers"]
    )
    assert res.status_code == 400
    assert "rate" in res.json()["detail"]

    zero = await client.post(
        "/api/v1/payments/shurjopay/topup?amount=0&currency=BDT", headers=user["headers"]
    )
    assert zero.status_code == 400


async def test_manual_deposits_accept_any_held_currency(client, db_session, promote_role):
    user = await register_and_login(client, "currmanual")

    accepted = await client.post(
        "/api/v1/wallets/manual-deposit",
        json={"amount": "2000", "currency": "bdt", "bank_name": "bKash", "transaction_id": "CURRTEST1"},
        headers=user["headers"],
    )
    assert accepted.status_code == 200, accepted.text
    # Normalised, so the approval screen and the conversion agree.
    assert accepted.json()["currency"] == "BDT"

    refused = await client.post(
        "/api/v1/wallets/manual-deposit",
        json={"amount": "50", "currency": "XYZ", "bank_name": "bKash", "transaction_id": "CURRTEST2"},
        headers=user["headers"],
    )
    assert refused.status_code == 400
    assert "rate" in refused.json()["detail"]


async def test_approving_a_foreign_deposit_credits_the_right_euros(client, db_session, promote_role):
    """The amount lands in the wallet converted, not at face value."""
    from app.models.wallet import Wallet, WalletType

    user = await register_and_login(client, "currapprove")
    admin = await register_and_login(client, "curradmin2")
    await promote_role(admin["user_id"], "SUPER_ADMIN")

    bdt_rate = await _rate(db_session, "BDT")
    deposit = await client.post(
        "/api/v1/wallets/manual-deposit",
        json={"amount": "1418.70", "currency": "BDT", "bank_name": "bKash", "transaction_id": "CURRTEST3"},
        headers=user["headers"],
    )
    assert deposit.status_code == 200, deposit.text

    approved = await client.post(
        f"/api/v1/admin/payments/manual/{deposit.json()['id']}/approve", headers=admin["headers"]
    )
    assert approved.status_code == 200, approved.text

    wallet = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == user["user_id"], Wallet.wallet_type == WalletType.DEFAULT)
    )).scalar_one()
    await db_session.refresh(wallet)
    expected = (Decimal("1418.70") / bdt_rate).quantize(Decimal("0.0001"))
    assert Decimal(str(wallet.balance)) == expected


async def test_the_rates_the_frontend_converts_with_are_available(client, db_session):
    """The wallet page converts client-side, so the rates must be public."""
    rates = (await client.get("/api/v1/settings/rates")).json()
    codes = {r["currency_code"] for r in rates}
    assert "BDT" in codes
    row = (await db_session.execute(
        select(CurrencyRate).where(CurrencyRate.currency_code == "BDT")
    )).scalar_one()
    assert Decimal(str(row.rate_to_base)) > 0
