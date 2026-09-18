"""A merchant buying an eSIM for a customer can now pay through ShurjoPay
(when their wallet doesn't cover it) instead of only from the wallet. The
order must still go to the right customer and still earn the merchant's
commission once delivered - otherwise moving merchants onto the gateway
would silently cost them money."""
import pytest
from decimal import Decimal
from unittest.mock import patch
from sqlalchemy import select

from conftest import register_and_login, create_test_product, wait_for_order
from test_gateway_checkout import FAKE_INITIATE_RESPONSE, _paid_response
from app.models.order import Order
from app.models.wallet import Wallet, WalletType

pytestmark = pytest.mark.asyncio


async def _approved_merchant(client, promote_role, name):
    admin = await register_and_login(client, f"{name}admin")
    await promote_role(admin["user_id"], "SUPER_ADMIN")
    merchant = await register_and_login(client, name)
    await client.post(
        "/api/v1/auth/apply-merchant",
        json={"business_name": f"{name} Travels", "contact_phone": "+1000000000"},
        headers=merchant["headers"],
    )
    queue = await client.get("/api/v1/admin/merchants/queue", headers=admin["headers"])
    entry = next(m for m in queue.json() if m["user_id"] == merchant["user_id"])
    assert (await client.post(f"/api/v1/admin/merchants/{entry['id']}/approve", headers=admin["headers"])).status_code == 200
    return merchant


async def test_merchant_gateway_purchase_issues_to_customer_and_pays_commission(client, db_session, promote_role):
    merchant = await _approved_merchant(client, promote_role, "gwmerchant")
    customer = await register_and_login(client, "gwmerchantcustomer")
    product = await create_test_product(db_session, price=Decimal("10.0000"))

    with patch("app.api.v1.payments.ShurjoPayService.initiate_payment", return_value=FAKE_INITIATE_RESPONSE):
        initiate = await client.post(
            "/api/v1/payments/shurjopay/order-initiate",
            json={
                "product_id": product.id, "payment_method": "SHURJOPAY",
                "is_buy_for_user": True, "beneficiary_email": customer["email"], "auto_create_user": False,
            },
            headers=merchant["headers"],
        )
    assert initiate.status_code == 200, initiate.text
    order_id = initiate.json()["order_id"]

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.is_reseller_order is True
    assert order.buyer_id == merchant["user_id"]
    assert order.beneficiary_id == customer["user_id"]

    with patch("app.api.v1.payments.ShurjoPayService.verify_payment", return_value=_paid_response(f"ORDERPAY-{order_id}")):
        callback = await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c460a9300"})
    assert callback.status_code == 302

    settled = await wait_for_order(client, order_id, merchant["headers"])
    assert settled["status"] == "COMPLETED"

    # Commission lands exactly as it would for a wallet-paid reseller order.
    db_session.expire_all()
    commission_wallet = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == merchant["user_id"], Wallet.wallet_type == WalletType.COMMISSION)
    )).scalar_one()
    assert Decimal(str(commission_wallet.balance)) > 0

    # And the merchant's own wallet was never touched - the gateway paid.
    main_wallet = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == merchant["user_id"], Wallet.wallet_type == WalletType.DEFAULT)
    )).scalar_one()
    assert Decimal(str(main_wallet.balance)) == Decimal("0")


async def test_customer_without_account_gets_one_on_gateway_path(client, db_session, promote_role):
    merchant = await _approved_merchant(client, promote_role, "gwmerchantnew")
    product = await create_test_product(db_session, price=Decimal("10.0000"))

    with patch("app.api.v1.payments.ShurjoPayService.initiate_payment", return_value=FAKE_INITIATE_RESPONSE):
        missing = await client.post(
            "/api/v1/payments/shurjopay/order-initiate",
            json={"product_id": product.id, "payment_method": "SHURJOPAY", "is_buy_for_user": True,
                  "beneficiary_email": "nobody-here@example.com", "auto_create_user": False},
            headers=merchant["headers"],
        )
        # The dashboard retries with auto_create_user, exactly as the wallet path does.
        assert missing.status_code == 404
        assert "Beneficiary user account not found" in missing.json()["detail"]

        created = await client.post(
            "/api/v1/payments/shurjopay/order-initiate",
            json={"product_id": product.id, "payment_method": "SHURJOPAY", "is_buy_for_user": True, "auto_create_user": True},
            headers=merchant["headers"],
        )
    assert created.status_code == 200, created.text
    order = (await db_session.execute(select(Order).where(Order.id == created.json()["order_id"]))).scalar_one()
    assert order.beneficiary_id != merchant["user_id"]
    assert order.is_reseller_order is True
