import uuid
import pytest
from datetime import date
from decimal import Decimal

from conftest import register_and_login
from app.models.catalog import Country, Product
from app.models.order import Order, OrderStatus, PaymentMethod

pytestmark = pytest.mark.asyncio

URL = "/api/v1/admin/dashboard"


async def _seed_sale(db_session, buyer_id, *, status=OrderStatus.COMPLETED, prefix="ORD", total="12.50", cost="10.00"):
    tag = uuid.uuid4().hex[:6]
    country = Country(id=int(uuid.uuid4().int % 1_000_000_000), iso2=f"D{tag[:5].upper()}", name_en=f"Dashland {tag}", is_active=True)
    db_session.add(country)
    await db_session.flush()
    product = Product(country_id=country.id, title_en=f"Dash 3GB {tag}", data_amount_gb=Decimal("3"), validity_days=7,
                      cost_price=Decimal(cost), retail_price=Decimal(total), currency="EUR", is_active=True)
    db_session.add(product)
    await db_session.flush()
    order = Order(order_no=f"{prefix}-{uuid.uuid4().hex[:10].upper()}", buyer_id=buyer_id, beneficiary_id=buyer_id,
                  product_id=product.id, total_amount=Decimal(total), cost_amount=Decimal(cost), currency="EUR",
                  payment_method=PaymentMethod.WALLET, status=status)
    db_session.add(order)
    await db_session.commit()
    return order, country


async def test_dashboard_shape_and_todays_sale(client, db_session, promote_role):
    admin = await register_and_login(client, "dashadmin")
    await promote_role(admin["user_id"], "ADMIN")
    order, country = await _seed_sale(db_session, admin["user_id"], prefix="PTR")
    await _seed_sale(db_session, admin["user_id"], status=OrderStatus.FAILED)

    res = await client.get(f"{URL}?days=7", headers=admin["headers"])
    assert res.status_code == 200, res.text
    body = res.json()

    # One row per day, oldest first, ending today - no gaps for quiet days.
    assert len(body["daily"]) == 7
    assert body["daily"][-1]["day"] == date.today().isoformat() or body["daily"][-1]["day"] == body["period"]["end"]
    today = body["daily"][-1]
    assert Decimal(today["sales"]) >= Decimal("12.50")
    assert today["orders"] >= 1 and today["failed"] >= 1

    kpis = body["kpis"]
    assert set(kpis) == {"sales", "net_profit", "orders", "new_customers", "topups", "wallet_liability"}
    assert Decimal(kpis["sales"]["current"]) >= Decimal("12.50")
    assert "previous" in kpis["sales"]

    channels = {c["channel"]: c for c in body["channels"]}
    assert set(channels) == {"web", "api", "admin"}
    assert channels["api"]["orders"] >= 1          # the PTR- order is a Partner API sale

    assert any(d["iso2"] == country.iso2 for d in body["top_destinations"])
    assert any(o["order_no"] == order.order_no and o["channel"] == "api" for o in body["recent_orders"])

    attention = body["attention"]
    for key in ("pending_merchants", "pending_deposits", "pending_kyc", "stuck_orders", "failed_orders", "failure_rate_pct", "ledger_ok"):
        assert key in attention
    assert attention["failed_orders"] >= 1


async def test_dashboard_permissions_and_range(client, promote_role):
    user = await register_and_login(client, "dashuser")
    assert (await client.get(URL, headers=user["headers"])).status_code == 403

    admin = await register_and_login(client, "dashadmin2")
    await promote_role(admin["user_id"], "ADMIN")
    assert (await client.get(f"{URL}?days=3", headers=admin["headers"])).status_code == 422
    ninety = await client.get(f"{URL}?days=90", headers=admin["headers"])
    assert ninety.status_code == 200 and len(ninety.json()["daily"]) == 90
