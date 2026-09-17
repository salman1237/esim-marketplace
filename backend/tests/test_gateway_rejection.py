"""ShurjoPay answers HTTP 200 even when it refuses a payment - the reason
sits in sp_message. Live example that prompted these tests:

    {"sp_code": 400, "message": "Transaction amount 1.42 is less than the
     minimum required amount of 10.00"}

Before this, the customer saw only "no checkout link" and the real reason
was buried in payment_logs."""
import pytest
from decimal import Decimal
from unittest.mock import patch
from sqlalchemy import func, select

from conftest import register_and_login, create_test_product
from app.models.order import Order, OrderStatus

pytestmark = pytest.mark.asyncio

REFUSED = {
    "sp_code": 400,
    "message": "Transaction amount 1.42 is less than the minimum required amount of 10.00",
    "sp_message": "Transaction amount 1.42 is less than the minimum required amount of 10.00",
}
INITIATE = "app.api.v1.payments.ShurjoPayService.initiate_payment"


async def test_topup_returns_the_gateway_reason(client):
    user = await register_and_login(client, "gwrefusetopup")
    with patch(INITIATE, return_value=REFUSED):
        res = await client.post("/api/v1/payments/shurjopay/topup?amount=1", headers=user["headers"])
    assert res.status_code == 400
    assert "minimum required amount" in res.json()["detail"]


async def test_topup_without_any_message_still_fails_clearly(client):
    user = await register_and_login(client, "gwrefusetopup2")
    with patch(INITIATE, return_value={"sp_code": 500}):
        res = await client.post("/api/v1/payments/shurjopay/topup?amount=1", headers=user["headers"])
    assert res.status_code == 400
    assert "checkout link" in res.json()["detail"]


async def test_refused_order_payment_leaves_no_pending_order(client, db_session):
    user = await register_and_login(client, "gwrefuseorder")
    product = await create_test_product(db_session, price=Decimal("9.9900"))

    before = (await db_session.execute(
        select(func.count(Order.id)).where(Order.buyer_id == user["user_id"])
    )).scalar_one()

    with patch(INITIATE, return_value=REFUSED):
        res = await client.post(
            "/api/v1/payments/shurjopay/order-initiate",
            json={"product_id": product.id, "payment_method": "SHURJOPAY"},
            headers=user["headers"],
        )
    assert res.status_code == 400
    assert "minimum required amount" in res.json()["detail"]

    # A PENDING order nobody can pay would sit in the reconciliation report
    # for ever, so the rollback matters.
    after = (await db_session.execute(
        select(func.count(Order.id)).where(Order.buyer_id == user["user_id"])
    )).scalar_one()
    assert after == before
    pending = (await db_session.execute(
        select(func.count(Order.id)).where(Order.buyer_id == user["user_id"], Order.status == OrderStatus.PENDING)
    )).scalar_one()
    assert pending == 0
