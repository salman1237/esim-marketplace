import pytest
from decimal import Decimal
from unittest.mock import patch
from sqlalchemy import select
from conftest import register_and_login, create_test_product, wait_for_order
from app.models.wallet import Wallet, WalletType

pytestmark = pytest.mark.asyncio

FAKE_INITIATE_RESPONSE = {"checkout_url": "https://sandbox.shurjopayment.com/pay/fake123", "sp_order_id": "spFAKE123"}


def _paid_response(customer_order_id: str, amount: str = "10.0000"):
    return [{
        "order_id": "sp6a99c460a9300",
        "amount": amount,
        "customer_order_id": customer_order_id,
        "sp_code": "1000",
        "sp_message": "Success",
    }]


def _pending_response(customer_order_id: str):
    return [{
        "order_id": "sp6a99c2d29fb09",
        "amount": "10.0000",
        "customer_order_id": customer_order_id,
        "sp_code": "1068",
        "sp_message": "initiated",
    }]


async def test_order_initiate_creates_pending_order_and_returns_checkout_url(client, db_session):
    """Regression test: /orders/checkout previously rejected everything but
    WALLET and pointed at a URL that didn't exist (/payments/shurjopay/
    initiate) for anything else - this is the endpoint that actually
    exists now, and this proves it does something real."""
    user = await register_and_login(client, "gatewaybuyer")
    product = await create_test_product(db_session, price=Decimal("9.9900"))

    with patch("app.api.v1.payments.ShurjoPayService.initiate_payment", return_value=FAKE_INITIATE_RESPONSE):
        res = await client.post(
            "/api/v1/payments/shurjopay/order-initiate",
            json={"product_id": product.id, "payment_method": "SHURJOPAY"},
            headers=user["headers"],
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["checkout_url"] == FAKE_INITIATE_RESPONSE["checkout_url"]
    assert body["order_id"]
    assert body["order_no"].startswith("ORD-")

    # No eSIM yet - payment hasn't been confirmed.
    mine = await client.get("/api/v1/orders/my-esims", headers=user["headers"])
    assert mine.json() == []


async def test_gateway_callback_completes_order_and_provisions_esim(client, db_session):
    user = await register_and_login(client, "gatewaypay")
    product = await create_test_product(db_session, price=Decimal("9.9900"))

    with patch("app.api.v1.payments.ShurjoPayService.initiate_payment", return_value=FAKE_INITIATE_RESPONSE):
        initiate = await client.post(
            "/api/v1/payments/shurjopay/order-initiate",
            json={"product_id": product.id, "payment_method": "SHURJOPAY"},
            headers=user["headers"],
        )
    order_id = initiate.json()["order_id"]

    response = _paid_response(f"ORDERPAY-{order_id}")
    with patch("app.api.v1.payments.ShurjoPayService.verify_payment", return_value=response):
        callback = await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c460a9300"})
    assert callback.status_code == 302
    # Redirects at once to the polling view instead of holding the browser
    # on a blank redirect for the supplier call.
    assert f"/my-esims?order={order_id}" in callback.headers["location"]

    settled = await wait_for_order(client, order_id, user["headers"])
    assert settled["status"] == "COMPLETED"

    mine = await client.get("/api/v1/orders/my-esims", headers=user["headers"])
    assert len(mine.json()) == 1
    assert mine.json()[0]["order_no"] == initiate.json()["order_no"]
    assert mine.json()[0]["iccid"]


async def test_gateway_callback_replay_does_not_duplicate_esim(client, db_session):
    user = await register_and_login(client, "gatewayreplay")
    product = await create_test_product(db_session, price=Decimal("9.9900"))

    with patch("app.api.v1.payments.ShurjoPayService.initiate_payment", return_value=FAKE_INITIATE_RESPONSE):
        initiate = await client.post(
            "/api/v1/payments/shurjopay/order-initiate",
            json={"product_id": product.id, "payment_method": "SHURJOPAY"},
            headers=user["headers"],
        )
    order_id = initiate.json()["order_id"]
    response = _paid_response(f"ORDERPAY-{order_id}")

    with patch("app.api.v1.payments.ShurjoPayService.verify_payment", return_value=response):
        await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c460a9300"})
        await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c460a9300"})

    await wait_for_order(client, order_id, user["headers"])
    mine = await client.get("/api/v1/orders/my-esims", headers=user["headers"])
    assert len(mine.json()) == 1


async def test_gateway_callback_unpaid_does_not_provision(client, db_session):
    user = await register_and_login(client, "gatewayunpaid")
    product = await create_test_product(db_session, price=Decimal("9.9900"))

    with patch("app.api.v1.payments.ShurjoPayService.initiate_payment", return_value=FAKE_INITIATE_RESPONSE):
        initiate = await client.post(
            "/api/v1/payments/shurjopay/order-initiate",
            json={"product_id": product.id, "payment_method": "SHURJOPAY"},
            headers=user["headers"],
        )
    order_id = initiate.json()["order_id"]
    response = _pending_response(f"ORDERPAY-{order_id}")

    with patch("app.api.v1.payments.ShurjoPayService.verify_payment", return_value=response):
        callback = await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c2d29fb09"})
    assert callback.status_code == 302
    assert "payment=failed" in callback.headers["location"]

    mine = await client.get("/api/v1/orders/my-esims", headers=user["headers"])
    assert mine.json() == []


async def test_order_initiate_buy_for_user_forbidden_for_plain_user(client, db_session):
    user = await register_and_login(client, "gatewaynotreseller")
    product = await create_test_product(db_session)

    res = await client.post(
        "/api/v1/payments/shurjopay/order-initiate",
        json={"product_id": product.id, "payment_method": "SHURJOPAY", "is_buy_for_user": True, "auto_create_user": True},
        headers=user["headers"],
    )
    assert res.status_code == 403


async def test_gateway_callback_refunds_wallet_when_vivape_fails(client, db_session, mock_vivape):
    """ShurjoPay already charged the customer by the time the callback
    fires - if VivaPe then fails, there's no wallet debit to reverse (this
    order was never wallet-paid), so the compensation is a wallet credit
    for the full amount instead, and the redirect must not claim success."""
    mock_vivape.create_transaction.return_value = {"error": "Insufficient Balance.", "purchase_trx": []}

    user = await register_and_login(client, "gatewayfails")
    product = await create_test_product(db_session, price=Decimal("9.9900"))

    with patch("app.api.v1.payments.ShurjoPayService.initiate_payment", return_value=FAKE_INITIATE_RESPONSE):
        initiate = await client.post(
            "/api/v1/payments/shurjopay/order-initiate",
            json={"product_id": product.id, "payment_method": "SHURJOPAY"},
            headers=user["headers"],
        )
    order_id = initiate.json()["order_id"]

    response = _paid_response(f"ORDERPAY-{order_id}", amount="9.9900")
    with patch("app.api.v1.payments.ShurjoPayService.verify_payment", return_value=response):
        callback = await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c460a9300"})
    assert callback.status_code == 302
    # The outcome isn't known at redirect time any more - the page polls.
    assert f"/my-esims?order={order_id}" in callback.headers["location"]

    settled = await wait_for_order(client, order_id, user["headers"])
    assert settled["status"] == "FAILED"

    mine = await client.get("/api/v1/orders/my-esims", headers=user["headers"])
    assert mine.json() == []

    me = await client.get("/api/v1/auth/me", headers=user["headers"])
    default_wallet = next(w for w in me.json()["wallets"] if w["type"] == "DEFAULT")
    assert Decimal(str(default_wallet["balance"])) == Decimal("9.9900")


async def test_mobile_order_initiate_uses_marked_reference(client, db_session):
    """Triptel-MobileApp's FR-306: the mobile app sends mobile=true so the
    callback later knows to redirect to the app's custom URL scheme instead
    of the web frontend - see docs/Architecture.md in that repo, "Payment"."""
    user = await register_and_login(client, "mobilegatewaybuyer")
    product = await create_test_product(db_session, price=Decimal("9.9900"))

    with patch("app.api.v1.payments.ShurjoPayService.initiate_payment", return_value=FAKE_INITIATE_RESPONSE):
        res = await client.post(
            "/api/v1/payments/shurjopay/order-initiate",
            json={"product_id": product.id, "payment_method": "SHURJOPAY", "mobile": True},
            headers=user["headers"],
        )
    assert res.status_code == 200, res.text
    assert res.json()["order_id"]


async def test_mobile_gateway_callback_redirects_to_app_scheme(client, db_session):
    user = await register_and_login(client, "mobilegatewaypay")
    product = await create_test_product(db_session, price=Decimal("9.9900"))

    with patch("app.api.v1.payments.ShurjoPayService.initiate_payment", return_value=FAKE_INITIATE_RESPONSE):
        initiate = await client.post(
            "/api/v1/payments/shurjopay/order-initiate",
            json={"product_id": product.id, "payment_method": "SHURJOPAY", "mobile": True},
            headers=user["headers"],
        )
    order_id = initiate.json()["order_id"]

    response = _paid_response(f"ORDERPAY-M-{order_id}")
    with patch("app.api.v1.payments.ShurjoPayService.verify_payment", return_value=response):
        callback = await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c460a9300"})
    assert callback.status_code == 302
    location = callback.headers["location"]
    assert location.startswith("triptel://payment-callback")
    assert f"order={order_id}" in location
    # Must not fall back to the web frontend for a mobile order.
    assert "triptel.co" not in location

    settled = await wait_for_order(client, order_id, user["headers"])
    assert settled["status"] == "COMPLETED"


async def test_mobile_gateway_callback_unpaid_redirects_to_app_scheme_with_failure(client, db_session):
    user = await register_and_login(client, "mobilegatewayunpaid")
    product = await create_test_product(db_session, price=Decimal("9.9900"))

    with patch("app.api.v1.payments.ShurjoPayService.initiate_payment", return_value=FAKE_INITIATE_RESPONSE):
        initiate = await client.post(
            "/api/v1/payments/shurjopay/order-initiate",
            json={"product_id": product.id, "payment_method": "SHURJOPAY", "mobile": True},
            headers=user["headers"],
        )
    order_id = initiate.json()["order_id"]
    response = _pending_response(f"ORDERPAY-M-{order_id}")

    with patch("app.api.v1.payments.ShurjoPayService.verify_payment", return_value=response):
        callback = await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c2d29fb09"})
    assert callback.status_code == 302
    location = callback.headers["location"]
    assert location.startswith("triptel://payment-callback")
    assert "payment=failed" in location
    assert "triptel.co" not in location

    mine = await client.get("/api/v1/orders/my-esims", headers=user["headers"])
    assert mine.json() == []


async def test_web_gateway_callback_still_redirects_to_frontend(client, db_session):
    """Regression guard: adding the mobile branch must not change the
    default (mobile=false / omitted) web redirect target."""
    user = await register_and_login(client, "webgatewaypay")
    product = await create_test_product(db_session, price=Decimal("9.9900"))

    with patch("app.api.v1.payments.ShurjoPayService.initiate_payment", return_value=FAKE_INITIATE_RESPONSE):
        initiate = await client.post(
            "/api/v1/payments/shurjopay/order-initiate",
            json={"product_id": product.id, "payment_method": "SHURJOPAY"},
            headers=user["headers"],
        )
    order_id = initiate.json()["order_id"]

    response = _paid_response(f"ORDERPAY-{order_id}")
    with patch("app.api.v1.payments.ShurjoPayService.verify_payment", return_value=response):
        callback = await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c460a9300"})
    assert callback.status_code == 302
    location = callback.headers["location"]
    assert f"/my-esims?order={order_id}" in location
    assert not location.startswith("triptel://")


async def test_topup_callback_still_uses_topup_query_param(client, db_session):
    """Regression guard: adding the ORDERPAY branch must not change the
    existing TOPUP failure redirect's query param (?topup=... - the wallet
    page only reads that key, not ?payment=...)."""
    user = await register_and_login(client, "topupstillworks")
    response = _pending_response(f"TOPUP-{user['user_id']}-abc1234567")

    with patch("app.api.v1.payments.ShurjoPayService.verify_payment", return_value=response):
        res = await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c2d29fb09"})
    assert res.status_code == 302
    assert "topup=failed" in res.headers["location"]
