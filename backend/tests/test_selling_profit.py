import csv
import io
import pytest
import pytest_asyncio
from decimal import Decimal
from sqlalchemy import delete, select

from conftest import register_and_login, fund_wallet, create_test_product, wait_for_order
from app.core.database import AsyncSessionLocal
from app.models.catalog import Product
from app.models.order import Order
from app.models.settings import PlatformSetting
from app.services.catalog_parsing import parse_vivape_product
from app.services.pricing_svc import SELLING_PROFIT_KEY, retail_price_for

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def reset_profit():
    """The setting lives in the shared test DB - put the default back so
    other tests keep seeing the original 25% markup."""
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(delete(PlatformSetting).where(PlatformSetting.key == SELLING_PROFIT_KEY))
        await db.commit()


async def _super_admin(client, promote_role, name):
    user = await register_and_login(client, name)
    await promote_role(user["user_id"], "SUPER_ADMIN")
    return user


async def test_selling_price_is_cost_plus_profit_rounded_to_the_cent():
    # The client's own example: EUR 1.00 at 80% profit sells for EUR 1.80.
    assert retail_price_for(Decimal("1"), Decimal("80")) == Decimal("1.80")
    assert retail_price_for(Decimal("3.129411764705978"), Decimal("25")) == Decimal("3.91")
    assert retail_price_for(Decimal("2.5"), Decimal("25")) == Decimal("3.13")  # 3.125 rounds half up
    assert retail_price_for(Decimal("10"), Decimal("0")) == Decimal("10.00")


async def test_catalog_sync_prices_products_from_the_profit_setting():
    vivape_product = {"id": 1, "price": 2.5, "reference": "esimgo_bundle", "title": "eSIM, 1GB, 7 Days, Thailand, V2"}
    assert parse_vivape_product(vivape_product, Decimal("80"))["retail_price"] == Decimal("4.50")
    # Unset, it keeps the markup the catalog always used.
    assert parse_vivape_product(vivape_product)["retail_price"] == Decimal("3.13")


async def test_profit_defaults_to_the_previous_markup_and_stays_private(client, promote_role):
    admin = await register_and_login(client, "profitviewer")
    await promote_role(admin["user_id"], "ADMIN")

    res = await client.get("/api/v1/admin/pricing", headers=admin["headers"])
    assert res.status_code == 200
    assert Decimal(res.json()["selling_profit_pct"]) == Decimal("25")
    assert res.json()["example"] == {"cost": "1.00", "selling_price": "1.25"}

    public = (await client.get("/api/v1/settings/public")).json()
    assert "selling_profit_pct" not in public


async def test_super_admin_sets_profit_and_every_price_follows(client, db_session, promote_role, reset_profit):
    product = await create_test_product(db_session, price=Decimal("9.99"))  # cost 5.0000

    admin = await register_and_login(client, "profitadminonly")
    await promote_role(admin["user_id"], "ADMIN")
    denied = await client.put("/api/v1/admin/pricing", json={"selling_profit_pct": "80"}, headers=admin["headers"])
    assert denied.status_code == 403

    sa = await _super_admin(client, promote_role, "profitsuper")
    for bad in ("-5", "5000"):
        res = await client.put("/api/v1/admin/pricing", json={"selling_profit_pct": bad}, headers=sa["headers"])
        assert res.status_code == 400, bad
    assert (await client.put("/api/v1/admin/pricing", json={"selling_profit_pct": "abc"}, headers=sa["headers"])).status_code == 422

    res = await client.put("/api/v1/admin/pricing", json={"selling_profit_pct": "80"}, headers=sa["headers"])
    assert res.status_code == 200, res.text
    assert res.json()["selling_profit_pct"] == "80.00"
    assert res.json()["products_repriced"] >= 1
    assert res.json()["example"]["selling_price"] == "1.80"

    async with AsyncSessionLocal() as db:
        repriced = (await db.execute(select(Product).where(Product.id == product.id))).scalar_one()
        assert Decimal(str(repriced.retail_price)) == Decimal("9.00")  # 5.00 x 1.80

    current = await client.get("/api/v1/admin/pricing", headers=sa["headers"])
    assert current.json()["selling_profit_pct"] == "80.00"


async def test_orders_record_cost_and_the_report_shows_profit_and_commission(client, db_session, promote_role):
    merchant = await register_and_login(client, "profitmerchant")
    await promote_role(merchant["user_id"], "MERCHANT")
    await fund_wallet(db_session, merchant["user_id"], Decimal("100.0000"))
    product = await create_test_product(db_session, price=Decimal("10.0000"))  # cost 5.0000

    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET", "is_buy_for_user": True, "auto_create_user": True},
        headers=merchant["headers"],
    )
    assert res.status_code == 202, res.text
    order = await wait_for_order(client, res.json()["id"], merchant["headers"])
    assert order["status"] == "COMPLETED"

    async with AsyncSessionLocal() as db:
        stored = (await db.execute(select(Order).where(Order.id == order["id"]))).scalar_one()
        assert Decimal(str(stored.cost_amount)) == Decimal("5.0000")

    admin = await register_and_login(client, "profitreportadmin")
    await promote_role(admin["user_id"], "ADMIN")
    report = await client.get(f"/api/v1/admin/reports/sales?q={order['order_no']}", headers=admin["headers"])
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["currency"] == "EUR"
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert (row["cost"], row["selling_price"], row["profit"], row["profit_pct"]) == ("5.00", "10.00", "5.00", "100.00")
    # 5% merchant commission of the EUR 10 selling price comes out of the profit.
    assert (row["merchant_commission"], row["net_profit"]) == ("0.50", "4.50")
    assert row["channel"] == "web"
    assert body["totals"]["orders"] == 1
    assert body["totals"]["net_profit"] == "4.50"

    export = await client.get(f"/api/v1/admin/reports/sales.csv?q={order['order_no']}", headers=admin["headers"])
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/csv")
    lines = list(csv.reader(io.StringIO(export.text)))
    assert lines[0][0] == "Order no"
    assert len(lines) == 2 and lines[1][0] == order["order_no"]
    assert lines[1][-1] == "4.50"

    assert (await client.get("/api/v1/admin/reports/sales?status=BOGUS", headers=admin["headers"])).status_code == 400
    user = await register_and_login(client, "profitnosy")
    assert (await client.get("/api/v1/admin/reports/sales", headers=user["headers"])).status_code == 403
