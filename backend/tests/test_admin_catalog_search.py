import pytest
from conftest import register_and_login, create_test_product

pytestmark = pytest.mark.asyncio


async def test_admin_catalog_is_paged_and_exposes_unlimited_flag(client, db_session, promote_role):
    """Syncing every country (not just ten popular ones) grew this table
    from ~135 rows to thousands, so the endpoint returns a paged envelope
    instead of a flat newest-200 slice."""
    admin = await register_and_login(client, "catalogadmin")
    await promote_role(admin["user_id"], "ADMIN")
    product = await create_test_product(db_session)

    res = await client.get("/api/v1/admin/catalog", headers=admin["headers"])
    assert res.status_code == 200, res.text
    body = res.json()

    assert {"total", "limit", "offset", "items"} <= set(body)
    assert body["total"] >= 1
    # The admin table renders "Unlimited" instead of a meaningless
    # "0.00 GB" off this flag, so it must always be present.
    assert all("is_unlimited" in item for item in body["items"])


async def test_admin_catalog_search_filters_by_title(client, db_session, promote_role):
    admin = await register_and_login(client, "catalogsearch")
    await promote_role(admin["user_id"], "ADMIN")
    product = await create_test_product(db_session)

    res = await client.get(
        "/api/v1/admin/catalog", params={"q": product.title_en}, headers=admin["headers"]
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] >= 1
    assert all(product.title_en in item["title"] for item in body["items"])

    missing = await client.get(
        "/api/v1/admin/catalog",
        params={"q": "definitely-no-such-product-xyz"},
        headers=admin["headers"],
    )
    assert missing.json()["total"] == 0
    assert missing.json()["items"] == []


async def test_admin_catalog_filters_by_active_state(client, db_session, promote_role):
    admin = await register_and_login(client, "catalogactive")
    await promote_role(admin["user_id"], "ADMIN")
    product = await create_test_product(db_session)

    deactivate = await client.put(
        f"/api/v1/admin/catalog/{product.id}",
        json={"is_active": False},
        headers=admin["headers"],
    )
    assert deactivate.status_code == 200, deactivate.text

    active_only = await client.get(
        "/api/v1/admin/catalog",
        params={"q": product.title_en, "is_active": True},
        headers=admin["headers"],
    )
    assert all(item["id"] != product.id for item in active_only.json()["items"])

    inactive_only = await client.get(
        "/api/v1/admin/catalog",
        params={"q": product.title_en, "is_active": False},
        headers=admin["headers"],
    )
    assert any(item["id"] == product.id for item in inactive_only.json()["items"])


async def test_admin_catalog_exposes_supplier_and_coverage_network(client, db_session, promote_role):
    """The admin table's Supplier/IP columns need these on every row -
    without them there's no way for an admin to tell an eSIM Access
    product apart from a VivaPe one, or which exit-IP variant it is."""
    admin = await register_and_login(client, "catalogsupplier")
    await promote_role(admin["user_id"], "ADMIN")
    product = await create_test_product(db_session, supplier_reference="esimaccess")
    product.coverage_networks = "nonhkip"
    await db_session.commit()

    res = await client.get(
        "/api/v1/admin/catalog", params={"q": product.title_en}, headers=admin["headers"]
    )
    assert res.status_code == 200, res.text
    item = next(i for i in res.json()["items"] if i["id"] == product.id)
    assert item["supplier_reference"] == "esimaccess"
    assert item["coverage_networks"] == "nonhkip"


async def test_admin_catalog_requires_admin(client):
    plain = await register_and_login(client, "catalognobody")
    res = await client.get("/api/v1/admin/catalog", headers=plain["headers"])
    assert res.status_code == 403
