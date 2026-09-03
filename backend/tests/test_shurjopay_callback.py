import pytest
from decimal import Decimal
from unittest.mock import patch
from conftest import register_and_login

pytestmark = pytest.mark.asyncio

# Captured directly from a real completed sandbox transaction (see the
# ShurjoPay Postman collection at documenter.getpostman.com/view/6335853/U16dS8ig
# for the endpoint list). Two things this proves that the code previously
# got wrong: /api/verification returns a JSON *array*, and the "order_id"
# ShurjoPay's return_url redirect passes back is *their* sp_order_id
# ("sp6a99c460a9300"), not the "TOPUP-{user_id}-..." reference we sent them
# — our own reference only comes back inside the response as
# customer_order_id.
REAL_SUCCESS_RESPONSE = [{
    "id": 138234,
    "order_id": "sp6a99c460a9300",
    "currency": "BDT",
    "amount": "10.0000",
    "payable_amount": "10.0000",
    "recived_amount": "10.0000",
    "is_verify": 0,
    "card_holder_name": "visa",
    "bank_status": "Success",
    "customer_order_id": "TOPUP-{user_id}-abc1234567",
    "sp_code": "1000",
    "sp_message": "Success",
    "transaction_status": "Success",
    "method": "Ebl Visa",
}]

REAL_PENDING_RESPONSE = [{
    "order_id": "sp6a99c2d29fb09",
    "sp_code": "1068",
    "sp_message": "initiated",
    "customer_order_id": "TOPUP-{user_id}-abc1234567",
    "amount": "10.0000",
    "transaction_status": None,
}]


async def test_callback_credits_wallet_using_sp_order_id_and_array_response(client, db_session):
    """Regression test for the two bugs found by actually completing a
    sandbox payment: the callback must query/credit using the
    customer_order_id recovered from ShurjoPay's response (not the
    sp_order_id passed in the query string), and must handle
    /api/verification's list-wrapped response shape."""
    user = await register_and_login(client, "sptopup")
    response = [dict(REAL_SUCCESS_RESPONSE[0], customer_order_id=f"TOPUP-{user['user_id']}-abc1234567")]

    with patch("app.api.v1.payments.ShurjoPayService.verify_payment", return_value=response):
        res = await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c460a9300"})
    # The callback redirects the browser to the frontend wallet page rather
    # than returning JSON — a real payment redirect target, not an API
    # response a customer's browser would otherwise render as raw text.
    assert res.status_code == 302, res.text
    assert "topup=success" in res.headers["location"]

    me = await client.get("/api/v1/auth/me", headers=user["headers"])
    default_wallet = next(w for w in me.json()["wallets"] if w["type"] == "DEFAULT")
    assert Decimal(str(default_wallet["balance"])) > Decimal("0")


async def test_callback_is_idempotent_on_replay(client, db_session):
    """A replayed callback for the same ShurjoPay order must not double-credit."""
    user = await register_and_login(client, "spreplay")
    response = [dict(REAL_SUCCESS_RESPONSE[0], customer_order_id=f"TOPUP-{user['user_id']}-abc1234567")]

    with patch("app.api.v1.payments.ShurjoPayService.verify_payment", return_value=response):
        await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c460a9300-replay"})
        await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c460a9300-replay"})

    me = await client.get("/api/v1/auth/me", headers=user["headers"])
    default_wallet = next(w for w in me.json()["wallets"] if w["type"] == "DEFAULT")
    # Credited once (~10 BDT worth of USD), not twice.
    assert Decimal(str(default_wallet["balance"])) < Decimal("1.0000")


async def test_callback_pending_payment_not_credited(client, db_session):
    """An 'initiated but not yet paid' verification response (sp_code 1068,
    confirmed live — not the guessed '1000') must not credit anything."""
    user = await register_and_login(client, "sppending")
    response = [dict(REAL_PENDING_RESPONSE[0], customer_order_id=f"TOPUP-{user['user_id']}-abc1234567")]

    with patch("app.api.v1.payments.ShurjoPayService.verify_payment", return_value=response):
        res = await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c2d29fb09"})
    assert res.status_code == 302
    assert "topup=failed" in res.headers["location"]

    me = await client.get("/api/v1/auth/me", headers=user["headers"])
    default_wallet = next(w for w in me.json()["wallets"] if w["type"] == "DEFAULT")
    assert Decimal(str(default_wallet["balance"])) == Decimal("0.0000")
