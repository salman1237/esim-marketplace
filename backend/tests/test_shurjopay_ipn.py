import pytest
from decimal import Decimal
from unittest.mock import patch

from conftest import register_and_login, create_test_product, wait_for_order
from test_gateway_checkout import FAKE_INITIATE_RESPONSE, _paid_response, _pending_response

pytestmark = pytest.mark.asyncio

VERIFY = "app.api.v1.payments.ShurjoPayService.verify_payment"


async def _default_balance(client, headers) -> Decimal:
    me = await client.get("/api/v1/auth/me", headers=headers)
    return Decimal(str(next(w for w in me.json()["wallets"] if w["type"] == "DEFAULT")["balance"]))


async def test_ipn_credits_topup_once_even_when_browser_return_also_arrives(client):
    user = await register_and_login(client, "ipntopup")
    response = _paid_response(f"TOPUP-{user['user_id']}-ipn1234567", amount="1200.0000")

    with patch(VERIFY, return_value=response):
        ipn = await client.post("/api/v1/payments/shurjopay/ipn", data={"order_id": "spIPNTOPUP01"})
    assert ipn.status_code == 200, ipn.text
    assert ipn.json()["payment"] == "confirmed"
    credited = await _default_balance(client, user["headers"])
    assert credited > 0

    # Customer's browser comes back afterwards - must not credit again.
    with patch(VERIFY, return_value=response):
        callback = await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "spIPNTOPUP01"})
        again = await client.post("/api/v1/payments/shurjopay/ipn", json={"order_id": "spIPNTOPUP01"})
    assert callback.status_code == 302 and "topup=success" in callback.headers["location"]
    assert again.status_code == 200
    assert await _default_balance(client, user["headers"]) == credited


async def test_ipn_completes_gateway_order_without_duplicating_esim(client, db_session):
    user = await register_and_login(client, "ipnorder")
    product = await create_test_product(db_session, price=Decimal("9.9900"))
    with patch("app.api.v1.payments.ShurjoPayService.initiate_payment", return_value=FAKE_INITIATE_RESPONSE):
        initiate = await client.post(
            "/api/v1/payments/shurjopay/order-initiate",
            json={"product_id": product.id, "payment_method": "SHURJOPAY"},
            headers=user["headers"],
        )
    order_id = initiate.json()["order_id"]
    response = _paid_response(f"ORDERPAY-{order_id}")

    with patch(VERIFY, return_value=response):
        ipn = await client.get("/api/v1/payments/shurjopay/ipn", params={"order_id": "sp6a99c460a9300"})
        await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c460a9300"})
    assert ipn.status_code == 200 and ipn.json()["payment"] == "confirmed"

    settled = await wait_for_order(client, order_id, user["headers"])
    assert settled["status"] == "COMPLETED"
    mine = await client.get("/api/v1/orders/my-esims", headers=user["headers"])
    assert len(mine.json()) == 1


async def test_ipn_for_unpaid_payment_changes_nothing(client):
    user = await register_and_login(client, "ipnunpaid")
    with patch(VERIFY, return_value=_pending_response(f"TOPUP-{user['user_id']}-ipnunpaid01")):
        res = await client.post("/api/v1/payments/shurjopay/ipn", data={"order_id": "sp6a99c2d29fb09"})
    assert res.status_code == 200
    assert res.json()["payment"] == "not_confirmed"
    assert await _default_balance(client, user["headers"]) == Decimal("0")


async def test_ipn_requires_order_id(client):
    assert (await client.post("/api/v1/payments/shurjopay/ipn", data={})).status_code == 400
    assert (await client.post("/api/v1/payments/shurjopay/ipn", json={"foo": "bar"})).status_code == 400
    assert (await client.get("/api/v1/payments/shurjopay/ipn")).status_code == 400
