import uuid
import pytest
from decimal import Decimal
from unittest.mock import patch

from conftest import register_and_login
from app.models.catalog import Country, Product

pytestmark = pytest.mark.asyncio


async def _country_with_packages(db_session, name: str):
    suffix = uuid.uuid4().hex[:5]
    country = Country(
        id=int(uuid.uuid4().int % 1_000_000_000), iso2=f"Q{suffix[:4].upper()}",
        name_en=name, region="Asia", flag_url="https://example.com/f.png", is_active=True,
    )
    db_session.add(country)
    await db_session.flush()
    for gb, days, price, unlimited in [("5", 30, "9.00", False), ("1", 7, "4.00", False), ("0", 3, "6.50", True)]:
        db_session.add(Product(
            country_id=country.id, title_en=f"{name} {gb}GB {suffix}", data_amount_gb=Decimal(gb), validity_days=days,
            cost_price=Decimal("2.0000"), retail_price=Decimal(price), currency="EUR",
            is_unlimited=unlimited, is_active=True,
        ))
    # An inactive package must never reach the public page.
    db_session.add(Product(
        country_id=country.id, title_en=f"{name} hidden {suffix}", data_amount_gb=Decimal("99"), validity_days=30,
        cost_price=Decimal("1.0000"), retail_price=Decimal("1.00"), currency="EUR", is_active=False,
    ))
    await db_session.commit()
    return country


async def test_destination_page_by_slug_and_iso2(client, db_session):
    name = f"Slugland {uuid.uuid4().hex[:5]}"
    country = await _country_with_packages(db_session, name)
    slug = name.lower().replace(" ", "-")

    by_slug = await client.get(f"/api/v1/catalog/destinations/{slug}")
    assert by_slug.status_code == 200, by_slug.text
    body = by_slug.json()
    assert body["country"]["name_en"] == name
    assert body["country"]["slug"] == slug
    assert body["country"]["region"] == "Asia"

    prices = [Decimal(str(p["retail_price"])) for p in body["products"]]
    assert prices == sorted(prices)          # cheapest first
    assert len(body["products"]) == 3        # the inactive package is excluded
    assert all(p["is_active"] for p in body["products"])

    by_iso = await client.get(f"/api/v1/catalog/destinations/{country.iso2.lower()}")
    assert by_iso.status_code == 200
    assert by_iso.json()["country"]["id"] == country.id

    assert (await client.get("/api/v1/catalog/destinations/not-a-country")).status_code == 404
    assert (await client.get("/api/v1/catalog/destinations/zz")).status_code == 404


async def test_country_list_carries_slug_for_links(client, db_session):
    name = f"Linkland {uuid.uuid4().hex[:5]}"
    await _country_with_packages(db_session, name)
    res = await client.get(f"/api/v1/catalog/countries?search={name.split()[0]}")
    assert res.status_code == 200
    row = next(c for c in res.json() if c["name_en"] == name)
    assert row["slug"] == name.lower().replace(" ", "-")


async def test_topup_limits_are_admin_editable_and_enforced(client, promote_role):
    sa = await register_and_login(client, "topuplimits")
    await promote_role(sa["user_id"], "SUPER_ADMIN")
    user = await register_and_login(client, "topuppayer")
    try:
        defaults = await client.get("/api/v1/admin/topup-limits", headers=sa["headers"])
        assert defaults.json() == {"min": "1.00", "max": "2000.00", "currency": "EUR"}

        # Below the minimum is refused before the gateway is ever called.
        too_small = await client.post("/api/v1/payments/shurjopay/topup?amount=0.10", headers=user["headers"])
        assert too_small.status_code == 400
        assert "between" in too_small.json()["detail"]

        saved = await client.put("/api/v1/admin/topup-limits", json={"min": "0.05", "max": "50"}, headers=sa["headers"])
        assert saved.status_code == 200
        assert saved.json()["min"] == "0.05"

        public = (await client.get("/api/v1/settings/public")).json()
        assert Decimal(str(public["topup_min"])) == Decimal("0.05")

        # The same small amount now passes validation and reaches the
        # gateway - stubbed here, since this is about the limit, not ShurjoPay.
        with patch("app.api.v1.payments.ShurjoPayService.initiate_payment",
                   return_value={"checkout_url": "https://example.test/pay", "sp_order_id": "spTEST"}):
            retried = await client.post("/api/v1/payments/shurjopay/topup?amount=0.10", headers=user["headers"])
        assert retried.status_code == 200, retried.text

        assert (await client.put("/api/v1/admin/topup-limits", json={"min": "10", "max": "5"}, headers=sa["headers"])).status_code == 400
        assert (await client.put("/api/v1/admin/topup-limits", json={"min": "1", "max": "100"}, headers=user["headers"])).status_code == 403
    finally:
        await client.put("/api/v1/admin/topup-limits", json={"min": "1.00", "max": "2000.00"}, headers=sa["headers"])
