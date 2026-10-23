"""Admin control over which package is "recommended" for a destination.

Product.is_featured is a plain admin pick - no cap is enforced at the
database or API level (the admin console is what keeps it to a sane
couple of picks per country, the same way Country.is_popular is
self-policed) - but it must actually change what customers see first.
"""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.catalog import Country, Product
from conftest import create_test_product, register_and_login

pytestmark = pytest.mark.asyncio


async def _admin(client, promote_role, role="ADMIN", name="featadmin"):
    admin = await register_and_login(client, name)
    await promote_role(admin["user_id"], role)
    return admin


async def test_products_default_to_not_featured(db_session):
    product = await create_test_product(db_session)
    assert product.is_featured is False


async def test_admin_can_mark_and_unmark_a_product_as_featured(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    product = await create_test_product(db_session)

    res = await client.put(
        f"/api/v1/admin/catalog/{product.id}", json={"is_featured": True}, headers=admin["headers"]
    )
    assert res.status_code == 200, res.text
    assert res.json()["is_featured"] is True

    res = await client.put(
        f"/api/v1/admin/catalog/{product.id}", json={"is_featured": False}, headers=admin["headers"]
    )
    assert res.status_code == 200
    assert res.json()["is_featured"] is False


async def test_featured_flag_does_not_disturb_the_price_or_active_toggle(client, db_session, promote_role):
    """A plain admin editing is_featured must not accidentally touch the
    other fields this same endpoint can change."""
    admin = await _admin(client, promote_role, name="featadmin2")
    product = await create_test_product(db_session, price=Decimal("12.5000"))

    res = await client.put(
        f"/api/v1/admin/catalog/{product.id}", json={"is_featured": True}, headers=admin["headers"]
    )
    assert res.status_code == 200
    await db_session.refresh(product)
    assert product.is_active is True
    assert float(product.retail_price) == 12.5


async def test_featured_product_appears_first_on_the_destination_page(client, db_session):
    country_product = await create_test_product(db_session, price=Decimal("5.0000"))
    country = (await db_session.execute(
        select(Country).where(Country.id == country_product.country_id)
    )).scalar_one()

    # A cheaper, non-featured product in the same country - without the
    # featured-first ordering this would naturally sort ahead on price.
    cheaper = Product(
        country_id=country.id, title_en="Cheaper non-featured", data_amount_gb=Decimal("1.0"),
        validity_days=15, cost_price=Decimal("1.0000"), retail_price=Decimal("2.0000"),
        currency="EUR", is_active=True,
    )
    db_session.add(cheaper)
    await db_session.commit()

    await db_session.refresh(country_product)
    country_product.is_featured = True
    await db_session.commit()

    res = await client.get(f"/api/v1/catalog/destinations/{country.iso2}")
    assert res.status_code == 200
    products = res.json()["products"]
    assert products[0]["id"] == country_product.id
    assert products[0]["is_featured"] is True
    assert products[1]["is_featured"] is False


async def test_admin_can_filter_the_catalog_to_only_featured_products(client, db_session, promote_role):
    admin = await _admin(client, promote_role, name="featadmin3")
    featured = await create_test_product(db_session, is_featured=True)
    await create_test_product(db_session, is_featured=False)

    res = await client.get("/api/v1/admin/catalog?featured_only=true", headers=admin["headers"])
    assert res.status_code == 200
    ids = [item["id"] for item in res.json()["items"]]
    assert featured.id in ids
    assert all(item["is_featured"] for item in res.json()["items"])


async def test_a_plain_admin_can_set_featured_same_as_active(client, db_session, promote_role):
    """is_featured sits on the same endpoint/gate as is_active (require_admin),
    not the super-admin-only gate used for catalog-wide settings like pricing
    or supplier visibility - it's a per-product merchandising pick."""
    admin = await _admin(client, promote_role, role="ADMIN", name="plainfeatadmin")
    product = await create_test_product(db_session)
    res = await client.put(
        f"/api/v1/admin/catalog/{product.id}", json={"is_featured": True}, headers=admin["headers"]
    )
    assert res.status_code == 200


async def test_unauthenticated_cannot_set_featured(client, db_session):
    product = await create_test_product(db_session)
    res = await client.put(f"/api/v1/admin/catalog/{product.id}", json={"is_featured": True})
    assert res.status_code in (401, 403)
