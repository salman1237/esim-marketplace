import pytest
from decimal import Decimal
from sqlalchemy import select

from conftest import register_and_login, create_test_product, fund_wallet
from app.models.order import Order, ESIMProfile

pytestmark = pytest.mark.asyncio


async def test_vivape_transaction_id_is_stored_on_order_and_profile(client, db_session):
    """VivaPe's transaction id is the only handle tying an order back to a
    specific supplier transaction. Without it, tracing a customer's eSIM -
    or a charge that failed - means scanning supplier logs by timestamp.
    It's also what the delivery email shows as "Purchase ID"."""
    user = await register_and_login(client, "trxref")
    await fund_wallet(db_session, user["user_id"], Decimal("50.0000"))
    product = await create_test_product(db_session)

    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET"},
        headers=user["headers"],
    )
    assert res.status_code == 200, res.text
    order_id = res.json()["id"]

    # Neither field is exposed through the API, so assert against the rows.
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    profile = (
        await db_session.execute(select(ESIMProfile).where(ESIMProfile.order_id == order_id))
    ).scalar_one()

    # 999001 is the transaction id the autouse mock_vivape fixture returns.
    assert order.external_trx_id == "999001"
    assert profile.supplier_reference == "999001"
