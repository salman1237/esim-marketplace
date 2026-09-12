import pytest
from sqlalchemy import select
from conftest import create_test_product
from app.models.catalog import Country

pytestmark = pytest.mark.asyncio


async def test_country_is_hidden_once_it_has_no_active_products(client, db_session):
    """VivaPe lists ~250 countries but most have no eSIM inventory at all,
    and products are now synced for every one of them. Listing a country
    with nothing to sell gave visitors a destination tile that opened to
    an empty package list."""
    product = await create_test_product(db_session)
    country = (
        await db_session.execute(select(Country).where(Country.id == product.country_id))
    ).scalar_one()

    listed = await client.get("/api/v1/catalog/countries")
    assert listed.status_code == 200
    assert any(c["iso2"] == country.iso2 for c in listed.json())

    product.is_active = False
    await db_session.commit()

    after = await client.get("/api/v1/catalog/countries")
    assert after.status_code == 200
    assert all(c["iso2"] != country.iso2 for c in after.json())
