import pytest
from decimal import Decimal
from sqlalchemy import select
from conftest import register_and_login, fund_wallet, create_test_product
from app.models.order import Order, OrderStatus

pytestmark = pytest.mark.asyncio


async def test_checkout_insufficient_balance_rejected(client, db_session):
    user = await register_and_login(client, "poor")
    product = await create_test_product(db_session)
    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET"},
        headers=user["headers"],
    )
    assert res.status_code == 400


async def test_checkout_success_delivers_esim(client, db_session):
    """Regression test: this is the core purchase flow that previously
    crashed on every call (Order()/ESIMProfile() were constructed with
    field names that didn't exist on the actual models)."""
    user = await register_and_login(client, "buyer")
    await fund_wallet(db_session, user["user_id"], Decimal("50.0000"))
    product = await create_test_product(db_session, price=Decimal("9.9900"))

    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET"},
        headers=user["headers"],
    )
    assert res.status_code == 200, res.text
    order = res.json()
    assert order["status"] == "COMPLETED"
    assert order["buyer_id"] == user["user_id"]
    assert order["beneficiary_id"] == user["user_id"]
    assert order["esim_profile"] is not None
    assert order["esim_profile"]["iccid"]
    assert order["esim_profile"]["lpa_string"]

    # Wallet was actually debited
    me = await client.get("/api/v1/auth/me", headers=user["headers"])
    default_wallet = next(w for w in me.json()["wallets"] if w["type"] == "DEFAULT")
    assert Decimal(str(default_wallet["balance"])) == Decimal("50.0000") - Decimal("9.9900")

    # my-esims lists it
    mine = await client.get("/api/v1/orders/my-esims", headers=user["headers"])
    assert mine.status_code == 200
    assert len(mine.json()) == 1
    assert mine.json()[0]["is_mock_fallback"] is False
    # Drives "Unlimited" vs "0.00 GB" in the My eSIMs card - unlimited
    # plans carry no GB figure at all, so the raw number is meaningless.
    assert mine.json()[0]["is_unlimited"] is False


async def test_buy_for_user_forbidden_for_plain_user(client, db_session):
    """Regression test: previously any authenticated USER (not just
    Merchant/Admin/Super Admin) could pass is_buy_for_user=true, contradicting
    the plan's RBAC table which marks this feature no-access for User."""
    buyer = await register_and_login(client, "notreseller")
    await fund_wallet(db_session, buyer["user_id"], Decimal("50.0000"))
    product = await create_test_product(db_session)

    res = await client.post(
        "/api/v1/orders/checkout",
        json={
            "product_id": product.id,
            "payment_method": "WALLET",
            "is_buy_for_user": True,
            "auto_create_user": True,
        },
        headers=buyer["headers"],
    )
    assert res.status_code == 403


async def test_buy_for_user_auto_create(client, db_session, promote_role):
    """Merchants can buy on behalf of an auto-created customer account and
    the eSIM shows up on both dashboards."""
    merchant = await register_and_login(client, "merchseller")
    await promote_role(merchant["user_id"], "MERCHANT")
    await fund_wallet(db_session, merchant["user_id"], Decimal("50.0000"))
    product = await create_test_product(db_session, price=Decimal("10.0000"))

    res = await client.post(
        "/api/v1/orders/checkout",
        json={
            "product_id": product.id,
            "payment_method": "WALLET",
            "is_buy_for_user": True,
            "auto_create_user": True,
        },
        headers=merchant["headers"],
    )
    assert res.status_code == 200, res.text
    order = res.json()
    assert order["beneficiary_id"] != merchant["user_id"]
    assert order["buyer_id"] == merchant["user_id"]

    reseller_orders = await client.get("/api/v1/orders/reseller-orders", headers=merchant["headers"])
    assert reseller_orders.status_code == 200
    assert len(reseller_orders.json()) == 1
    assert Decimal(str(reseller_orders.json()[0]["commission_earned"])) > 0


async def test_checkout_refunds_wallet_when_vivape_fails(client, db_session, mock_vivape):
    """When VivaPe provisioning fails, the customer must never be left
    charged for a non-working eSIM: the order is marked FAILED, the wallet
    debit is reversed, and no eSIM is handed out."""
    mock_vivape.create_transaction.return_value = {"error": "Insufficient Balance.", "purchase_trx": []}

    user = await register_and_login(client, "unluckybuyer")
    await fund_wallet(db_session, user["user_id"], Decimal("50.0000"))
    product = await create_test_product(db_session, price=Decimal("9.9900"))

    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET"},
        headers=user["headers"],
    )
    assert res.status_code == 502
    assert "refunded" in res.json()["detail"].lower()

    # Wallet balance is back to what it was before the debit.
    me = await client.get("/api/v1/auth/me", headers=user["headers"])
    default_wallet = next(w for w in me.json()["wallets"] if w["type"] == "DEFAULT")
    assert Decimal(str(default_wallet["balance"])) == Decimal("50.0000")

    # No eSIM was created, and the order itself is marked FAILED.
    mine = await client.get("/api/v1/orders/my-esims", headers=user["headers"])
    assert mine.json() == []

    order_res = await db_session.execute(select(Order).where(Order.buyer_id == user["user_id"]))
    order = order_res.scalar_one()
    assert order.status == OrderStatus.FAILED


async def test_checkout_refunds_wallet_when_product_has_no_supplier_mapping(client, db_session):
    """Same refund guarantee for a product with no supplier_product_id at
    all (provision_esim's other failure branch, not VivaPe erroring)."""
    user = await register_and_login(client, "nosupplierbuyer")
    await fund_wallet(db_session, user["user_id"], Decimal("50.0000"))
    product = await create_test_product(db_session, price=Decimal("9.9900"), supplier_product_id=None, supplier_receiver_amount=None)

    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET"},
        headers=user["headers"],
    )
    assert res.status_code == 502

    me = await client.get("/api/v1/auth/me", headers=user["headers"])
    default_wallet = next(w for w in me.json()["wallets"] if w["type"] == "DEFAULT")
    assert Decimal(str(default_wallet["balance"])) == Decimal("50.0000")


async def test_buy_for_user_no_commission_when_vivape_fails(client, db_session, promote_role, mock_vivape):
    """A merchant buying for a customer must not keep commission on an
    order that fails and gets refunded - distribute_commission now runs
    only after provision_esim succeeds."""
    mock_vivape.create_transaction.return_value = {"error": "Insufficient Balance.", "purchase_trx": []}

    merchant = await register_and_login(client, "unluckymerchant")
    await promote_role(merchant["user_id"], "MERCHANT")
    await fund_wallet(db_session, merchant["user_id"], Decimal("50.0000"))
    product = await create_test_product(db_session, price=Decimal("10.0000"))

    res = await client.post(
        "/api/v1/orders/checkout",
        json={
            "product_id": product.id,
            "payment_method": "WALLET",
            "is_buy_for_user": True,
            "auto_create_user": True,
        },
        headers=merchant["headers"],
    )
    assert res.status_code == 502

    me = await client.get("/api/v1/auth/me", headers=merchant["headers"])
    commission_wallet = next(w for w in me.json()["wallets"] if w["type"] == "COMMISSION")
    assert Decimal(str(commission_wallet["balance"])) == Decimal("0.0000")

    reseller_orders = await client.get("/api/v1/orders/reseller-orders", headers=merchant["headers"])
    assert reseller_orders.status_code == 200
    assert len(reseller_orders.json()) == 1
    assert reseller_orders.json()[0]["status"] == "FAILED"
    assert Decimal(str(reseller_orders.json()[0]["commission_earned"])) == Decimal("0")
