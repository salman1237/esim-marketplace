import pytest
from decimal import Decimal
from sqlalchemy import select
from conftest import register_and_login, fund_wallet, create_test_product, partner_auth_headers
from app.models.catalog import Country

pytestmark = pytest.mark.asyncio


async def _make_partner(client, db_session, promote_role, suffix: str):
    """Approved merchant + issued API key - the prerequisite for every
    /partner/* call. Returns (headers-with-api-key, user_id, merchant_id)."""
    admin = await register_and_login(client, f"pcadmin{suffix}")
    await promote_role(admin["user_id"], "SUPER_ADMIN")

    merchant_user = await register_and_login(client, f"pcmerchant{suffix}")
    await client.post(
        "/api/v1/auth/apply-merchant",
        json={"business_name": f"Catalog Partner {suffix}", "contact_phone": "+1000000000"},
        headers=merchant_user["headers"],
    )
    queue = await client.get("/api/v1/admin/merchants/queue", headers=admin["headers"])
    entry = next(m for m in queue.json() if m["user_id"] == merchant_user["user_id"])
    await client.post(f"/api/v1/admin/merchants/{entry['id']}/approve", headers=admin["headers"])

    key_res = await client.post(f"/api/v1/admin/merchants/{entry['id']}/api-key", headers=admin["headers"])
    raw_key = key_res.json()["api_key"]
    headers = await partner_auth_headers(client, raw_key)

    return headers, merchant_user["user_id"], entry["id"]


async def _seed_country_and_product(db_session, suffix: str):
    product = await create_test_product(db_session, price=Decimal("5.0000"))
    c_res = await db_session.execute(select(Country).where(Country.id == product.country_id))
    country = c_res.scalar_one()
    return country, product


async def test_partner_routes_reject_missing_or_invalid_token(client):
    res = await client.get("/api/v1/partner/countries")
    assert res.status_code == 401  # missing Authorization header

    res2 = await client.get("/api/v1/partner/countries", headers={"Authorization": "Bearer not-a-real-token"})
    assert res2.status_code == 401

    res3 = await client.get("/api/v1/partner/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert res3.status_code == 401


async def test_partner_list_countries_and_products(client, db_session, promote_role):
    headers, _, _ = await _make_partner(client, db_session, promote_role, "1")
    country, product = await _seed_country_and_product(db_session, "1")

    countries = await client.get("/api/v1/partner/countries", headers=headers)
    assert countries.status_code == 200
    assert any(c["iso2"] == country.iso2 for c in countries.json())

    products = await client.get(f"/api/v1/partner/countries/{country.iso2}/products", headers=headers)
    assert products.status_code == 200
    body = products.json()
    assert len(body) == 1
    assert body[0]["id"] == product.id
    assert body[0]["retail_price"] == "5.00" or float(body[0]["retail_price"]) == 5.00
    assert "cost_price" not in body[0]  # partners never see internal cost

    missing = await client.get("/api/v1/partner/countries/ZZ/products", headers=headers)
    assert missing.status_code == 404


async def test_partner_me_reports_profile_commission_and_wallet(client, db_session, promote_role):
    headers, user_id, _ = await _make_partner(client, db_session, promote_role, "2")
    await fund_wallet(db_session, user_id, Decimal("42.5000"))

    res = await client.get("/api/v1/partner/me", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["business_name"] == "Catalog Partner 2"
    assert Decimal(str(body["commission_rate_pct"])) == Decimal("5.00")
    assert Decimal(str(body["wallet_balance"])) == Decimal("42.5000")
    assert body["webhook_configured"] is False
