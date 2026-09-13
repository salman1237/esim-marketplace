import uuid
import pytest
from decimal import Decimal

from conftest import register_and_login
from app.models.catalog import Country, Product
from app.models.order import Order, OrderStatus, PaymentMethod

pytestmark = pytest.mark.asyncio


async def _seed(db_session, buyer_id):
    """Three completed orders across two bundles, one via the Partner API.
    Every product title carries `tag` so `q=tag` isolates them in the
    shared test database."""
    tag = uuid.uuid4().hex[:8]
    country = Country(id=int(uuid.uuid4().int % 1_000_000_000), iso2=f"B{tag[:5].upper()}", name_en=f"Bundleland {tag}", is_active=True)
    db_session.add(country)
    await db_session.flush()
    unlimited = Product(country_id=country.id, title_en=f"Unlimited {tag}", data_amount_gb=Decimal("0"), validity_days=7,
                        cost_price=Decimal("6"), retail_price=Decimal("9"), currency="EUR", is_unlimited=True, is_active=True)
    data = Product(country_id=country.id, title_en=f"5GB {tag}", data_amount_gb=Decimal("5"), validity_days=30,
                   cost_price=Decimal("3"), retail_price=Decimal("4"), currency="EUR", is_unlimited=False, is_active=True)
    db_session.add_all([unlimited, data])
    await db_session.flush()

    def order(product, total, cost, prefix="ORD"):
        return Order(order_no=f"{prefix}-{uuid.uuid4().hex[:12].upper()}", buyer_id=buyer_id, beneficiary_id=buyer_id,
                     product_id=product.id, total_amount=Decimal(total), cost_amount=Decimal(cost), currency="EUR",
                     payment_method=PaymentMethod.WALLET, status=OrderStatus.COMPLETED)

    db_session.add_all([
        order(unlimited, "9.00", "6.00"),
        order(data, "4.00", "3.00"),
        order(data, "4.00", "3.00", prefix="PTR"),
    ])
    await db_session.commit()
    return tag, country


async def test_sales_report_filters_by_plan_validity_channel_and_country(client, db_session, promote_role):
    admin = await register_and_login(client, "salesfilter")
    await promote_role(admin["user_id"], "ADMIN")
    tag, country = await _seed(db_session, admin["user_id"])
    get = lambda qs: client.get(f"/api/v1/admin/reports/sales?q={tag}&{qs}", headers=admin["headers"])

    unlimited = (await get("plan=unlimited")).json()
    assert [r["plan"] for r in unlimited["rows"]] == ["Unlimited · 7 days"]
    assert unlimited["totals"]["orders"] == 1

    thirty = (await get("validity=30")).json()
    assert thirty["totals"]["orders"] == 2 and all(r["validity_days"] == 30 for r in thirty["rows"])

    api_only = (await get("channel=api")).json()
    assert [r["channel"] for r in api_only["rows"]] == ["api"]
    assert (await get("channel=web")).json()["totals"]["orders"] == 2

    assert (await get(f"country={country.iso2.lower()}")).json()["totals"]["orders"] == 3
    assert (await get("country=ZZ")).json()["totals"]["orders"] == 0

    assert (await get("plan=bundle")).status_code == 400
    assert (await get("channel=fax")).status_code == 400


async def test_sales_report_sorting(client, db_session, promote_role):
    admin = await register_and_login(client, "salessort")
    await promote_role(admin["user_id"], "ADMIN")
    tag, _ = await _seed(db_session, admin["user_id"])
    get = lambda qs: client.get(f"/api/v1/admin/reports/sales?q={tag}&{qs}", headers=admin["headers"])

    by_price = [Decimal(r["selling_price"]) for r in (await get("sort=price&direction=asc")).json()["rows"]]
    assert by_price == sorted(by_price) and by_price[0] == Decimal("4.00")

    by_profit = [Decimal(r["profit"]) for r in (await get("sort=profit&direction=desc")).json()["rows"]]
    assert by_profit == sorted(by_profit, reverse=True) and by_profit[0] == Decimal("3.00")

    assert (await get("sort=mood")).status_code == 400
    assert (await get("direction=sideways")).status_code == 422

    csv_res = await client.get(f"/api/v1/admin/reports/sales.csv?q={tag}&plan=unlimited", headers=admin["headers"])
    assert csv_res.status_code == 200
    assert "Unlimited · 7 days" in csv_res.text and f"5GB {tag}" not in csv_res.text


async def test_sales_breakdown_by_day_bundle_and_country(client, db_session, promote_role):
    admin = await register_and_login(client, "salesbreak")
    await promote_role(admin["user_id"], "ADMIN")
    tag, country = await _seed(db_session, admin["user_id"])

    res = await client.get(f"/api/v1/admin/reports/sales/breakdown?q={tag}", headers=admin["headers"])
    assert res.status_code == 200, res.text
    body = res.json()

    assert len(body["daily"]) == 1
    today = body["daily"][0]
    assert today["orders"] == 3 and today["selling_price"] == "17.00" and today["profit"] == "5.00"

    bundles = {b["plan"]: b for b in body["by_bundle"]}
    assert set(bundles) == {"Unlimited · 7 days", "5 GB · 30 days"}
    assert bundles["5 GB · 30 days"]["orders"] == 2 and bundles["5 GB · 30 days"]["profit"] == "2.00"
    assert bundles["Unlimited · 7 days"]["profit_pct"] == "50.00"

    assert [c["country_iso2"] for c in body["by_country"]] == [country.iso2]
    assert 7 in body["validity_options"] and 30 in body["validity_options"]

    only_api = (await client.get(f"/api/v1/admin/reports/sales/breakdown?q={tag}&channel=api", headers=admin["headers"])).json()
    assert only_api["daily"][0]["orders"] == 1
