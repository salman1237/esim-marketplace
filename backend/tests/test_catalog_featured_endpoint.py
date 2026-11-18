"""GET /catalog/featured - the storefront's "Global" search-sheet card.

Deliberately separate from Product.is_featured (per-country "recommended
pick", already set on many products): this is a dedicated admin-picked
flag (is_storefront_highlight) + endpoint, because there is no existing
field that cheaply identifies "the one global package" - see both
Product.is_storefront_highlight's own comment and the endpoint's.
"""
from decimal import Decimal

import pytest

from app.models.catalog import Country, Product
from conftest import create_test_product, register_and_login

pytestmark = pytest.mark.asyncio


async def test_products_default_to_not_highlighted(db_session):
    product = await create_test_product(db_session)
    assert product.is_storefront_highlight is False


async def test_no_highlighted_products_returns_empty_list(client, db_session):
    await create_test_product(db_session)  # an ordinary, non-highlighted product
    res = await client.get("/api/v1/catalog/featured")
    assert res.status_code == 200
    assert res.json() == []


async def test_highlighted_product_is_returned_with_a_flat_summary(client, db_session):
    product = await create_test_product(db_session, price=Decimal("26.90"))
    product.is_storefront_highlight = True
    product.coverage_country_isos = "US,GB,DE,JP,SG"
    await db_session.commit()

    res = await client.get("/api/v1/catalog/featured")
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body) == 1
    item = body[0]
    assert item["product_id"] == product.id
    assert item["retail_price"] == "26.90" or float(item["retail_price"]) == 26.90
    assert item["currency"] == "EUR"
    assert item["country_count"] == 5
    assert item["country_iso2"]
    assert item["country_slug"]


async def test_unhighlighted_products_are_never_included(client, db_session):
    highlighted = await create_test_product(db_session)
    highlighted.is_storefront_highlight = True
    await db_session.commit()
    other = await create_test_product(db_session)  # not highlighted

    res = await client.get("/api/v1/catalog/featured")
    body = res.json()
    ids = [i["product_id"] for i in body]
    assert highlighted.id in ids
    assert other.id not in ids


async def test_country_count_is_none_when_coverage_is_not_set(client, db_session):
    """A plain esimgo_bundle/worldmove "Global" row has no
    coverage_country_isos at all - the client must be told there is no
    count (None), not shown a false 0."""
    product = await create_test_product(db_session)
    product.is_storefront_highlight = True
    assert product.coverage_country_isos is None
    await db_session.commit()

    res = await client.get("/api/v1/catalog/featured")
    body = res.json()
    assert body[0]["country_count"] is None


async def test_inactive_highlighted_product_is_excluded(client, db_session):
    product = await create_test_product(db_session)
    product.is_storefront_highlight = True
    product.is_active = False
    await db_session.commit()

    res = await client.get("/api/v1/catalog/featured")
    assert res.json() == []


async def test_highlighted_product_in_an_inactive_country_is_excluded(client, db_session):
    product = await create_test_product(db_session)
    product.is_storefront_highlight = True
    await db_session.commit()

    from sqlalchemy import select
    country = (await db_session.execute(
        select(Country).where(Country.id == product.country_id)
    )).scalar_one()
    country.is_active = False
    await db_session.commit()

    res = await client.get("/api/v1/catalog/featured")
    assert res.json() == []


async def test_admin_can_set_and_unset_the_storefront_highlight(client, db_session, promote_role):
    admin = await register_and_login(client, "highlightadmin")
    await promote_role(admin["user_id"], "ADMIN")
    product = await create_test_product(db_session)

    res = await client.put(
        f"/api/v1/admin/catalog/{product.id}",
        json={"is_storefront_highlight": True},
        headers=admin["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["is_storefront_highlight"] is True

    featured = await client.get("/api/v1/catalog/featured")
    assert product.id in [i["product_id"] for i in featured.json()]

    res = await client.put(
        f"/api/v1/admin/catalog/{product.id}",
        json={"is_storefront_highlight": False},
        headers=admin["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["is_storefront_highlight"] is False

    featured = await client.get("/api/v1/catalog/featured")
    assert product.id not in [i["product_id"] for i in featured.json()]
