import pytest
from decimal import Decimal
from sqlalchemy import select
from conftest import register_and_login, fund_wallet, create_test_product
from app.models.order import Order, OrderStatus
from app.models.wallet import Wallet, WalletType

pytestmark = pytest.mark.asyncio


async def test_search_customers_requires_admin(client):
    user = await register_and_login(client, "plainuser")
    res = await client.get("/api/v1/admin/customers/search?q=plain", headers=user["headers"])
    assert res.status_code == 403


async def test_search_customers_finds_by_username_or_email(client, promote_role, db_session):
    admin = await register_and_login(client, "searchadmin")
    await promote_role(admin["user_id"], "ADMIN")

    target = await register_and_login(client, "findme_unique_handle")
    await fund_wallet(db_session, target["user_id"], Decimal("25.5000"))

    res = await client.get("/api/v1/admin/customers/search?q=findme_unique", headers=admin["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    match = next(u for u in body if u["id"] == target["user_id"])
    assert match["username"] == target["username"]
    assert Decimal(str(match["wallet_balance"])) == Decimal("25.5000")


async def test_recharge_wallet_requires_admin(client):
    user = await register_and_login(client, "plainrecharge")
    res = await client.post(
        f"/api/v1/admin/customers/{user['user_id']}/wallet/recharge",
        json={"amount": "10.00"},
        headers=user["headers"],
    )
    assert res.status_code == 403


async def test_recharge_wallet_credits_target_and_audit_logs(client, promote_role, db_session):
    admin = await register_and_login(client, "rechargeadmin")
    await promote_role(admin["user_id"], "ADMIN")
    target = await register_and_login(client, "rechargetarget")

    res = await client.post(
        f"/api/v1/admin/customers/{target['user_id']}/wallet/recharge",
        json={"amount": "50.00", "description": "goodwill credit"},
        headers=admin["headers"],
    )
    assert res.status_code == 200, res.text
    assert Decimal(str(res.json()["new_balance"])) == Decimal("50.00")

    w_res = await db_session.execute(
        select(Wallet).where(Wallet.user_id == target["user_id"], Wallet.wallet_type == WalletType.DEFAULT)
    )
    wallet = w_res.scalar_one()
    assert Decimal(str(wallet.balance)) == Decimal("50.00")

    summary = await client.get("/api/v1/admin/audit-logs/summary", headers=admin["headers"])
    assert "ADMIN_RECHARGE_CUSTOMER_WALLET" in summary.json()["action_counts"]


async def test_recharge_wallet_rejects_non_positive_amount(client, promote_role):
    admin = await register_and_login(client, "rechargeadmin2")
    await promote_role(admin["user_id"], "ADMIN")
    target = await register_and_login(client, "rechargetarget2")

    res = await client.post(
        f"/api/v1/admin/customers/{target['user_id']}/wallet/recharge",
        json={"amount": "0"},
        headers=admin["headers"],
    )
    assert res.status_code == 422


async def test_admin_purchase_esim_requires_admin(client, db_session):
    user = await register_and_login(client, "plainpurchase")
    product = await create_test_product(db_session, price=Decimal("10.0000"))
    res = await client.post(
        f"/api/v1/admin/customers/{user['user_id']}/purchase-esim",
        json={"product_id": product.id},
        headers=user["headers"],
    )
    assert res.status_code == 403


async def test_admin_purchase_esim_debits_customer_not_admin(client, promote_role, db_session):
    admin = await register_and_login(client, "purchaseadmin")
    await promote_role(admin["user_id"], "ADMIN")
    # Admin deliberately has zero balance - proves the charge comes from
    # the customer's wallet, not the admin's.
    target = await register_and_login(client, "purchasetarget")
    await fund_wallet(db_session, target["user_id"], Decimal("50.0000"))
    product = await create_test_product(db_session, price=Decimal("10.0000"))

    res = await client.post(
        f"/api/v1/admin/customers/{target['user_id']}/purchase-esim",
        json={"product_id": product.id},
        headers=admin["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "COMPLETED"
    assert body["iccid"]

    target_wallet = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == target["user_id"], Wallet.wallet_type == WalletType.DEFAULT)
    )).scalar_one()
    assert Decimal(str(target_wallet.balance)) == Decimal("40.0000")

    admin_wallet = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == admin["user_id"], Wallet.wallet_type == WalletType.DEFAULT)
    )).scalar_one()
    assert Decimal(str(admin_wallet.balance)) == Decimal("0.0000")

    order = (await db_session.execute(select(Order).where(Order.id == body["order_id"]))).scalar_one()
    assert order.buyer_id == target["user_id"]
    assert order.beneficiary_id == target["user_id"]
    assert order.is_reseller_order is False


async def test_admin_purchase_esim_insufficient_customer_balance(client, promote_role, db_session):
    admin = await register_and_login(client, "purchaseadmin2")
    await promote_role(admin["user_id"], "ADMIN")
    target = await register_and_login(client, "purchasetarget2")  # no funds
    product = await create_test_product(db_session, price=Decimal("10.0000"))

    res = await client.post(
        f"/api/v1/admin/customers/{target['user_id']}/purchase-esim",
        json={"product_id": product.id},
        headers=admin["headers"],
    )
    assert res.status_code == 400


async def test_admin_purchase_esim_refunds_customer_on_vivape_failure(client, promote_role, db_session, mock_vivape):
    mock_vivape.create_transaction.return_value = {"error": "Insufficient Balance.", "purchase_trx": []}

    admin = await register_and_login(client, "purchaseadmin3")
    await promote_role(admin["user_id"], "ADMIN")
    target = await register_and_login(client, "purchasetarget3")
    await fund_wallet(db_session, target["user_id"], Decimal("50.0000"))
    product = await create_test_product(db_session, price=Decimal("10.0000"))

    res = await client.post(
        f"/api/v1/admin/customers/{target['user_id']}/purchase-esim",
        json={"product_id": product.id},
        headers=admin["headers"],
    )
    assert res.status_code == 502
    assert "refunded" in res.json()["detail"].lower()

    target_wallet = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == target["user_id"], Wallet.wallet_type == WalletType.DEFAULT)
    )).scalar_one()
    assert Decimal(str(target_wallet.balance)) == Decimal("50.0000")  # debited then refunded

    order = (await db_session.execute(
        select(Order).where(Order.buyer_id == target["user_id"])
    )).scalar_one()
    assert order.status == OrderStatus.FAILED
