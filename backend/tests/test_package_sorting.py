import uuid
import pytest
from decimal import Decimal

from app.models.catalog import Country, Product

pytestmark = pytest.mark.asyncio


async def _country_with_packages(db_session):
    """Deliberately inserted out of price order, and with the biggest data
    plan being the cheapest, so data-amount ordering can't pass by accident."""
    suffix = uuid.uuid4().hex[:6]
    country = Country(id=int(uuid.uuid4().int % 1_000_000_000), iso2=f"S{suffix.upper()}", name_en=f"Sortland {suffix}", is_active=True)
    db_session.add(country)
    await db_session.flush()
    for title, gb, price in [("Mid", "3.0", "9.50"), ("Big but cheap", "10.0", "4.20"), ("Small", "1.0", "12.00"), ("Unlimited", "0", "7.75")]:
        db_session.add(Product(
            country_id=country.id, title_en=f"{title} {suffix}", data_amount_gb=Decimal(gb), validity_days=7,
            cost_price=Decimal("1.0000"), retail_price=Decimal(price), currency="EUR",
            is_unlimited=(gb == "0"), is_active=True,
        ))
    await db_session.commit()
    return country


async def test_storefront_lists_packages_cheapest_first(client, db_session):
    country = await _country_with_packages(db_session)
    res = await client.get(f"/api/v1/catalog/countries/{country.iso2}/products")
    assert res.status_code == 200
    prices = [Decimal(str(p["retail_price"])) for p in res.json()]
    assert prices == sorted(prices)
    assert prices[0] == Decimal("4.20")


async def test_partner_api_lists_packages_cheapest_first(client, db_session, promote_role):
    from test_partner_catalog import _make_partner

    headers, _, _ = await _make_partner(client, db_session, promote_role, "sortpartner")
    country = await _country_with_packages(db_session)
    res = await client.get(f"/api/v1/partner/countries/{country.iso2}/products", headers=headers)
    assert res.status_code == 200
    prices = [Decimal(str(p["retail_price"])) for p in res.json()]
    assert prices == sorted(prices)
