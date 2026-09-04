import pytest
from sqlalchemy import select
from conftest import register_and_login, partner_auth_headers
from app.models.merchant import MerchantProfile

pytestmark = pytest.mark.asyncio


async def _make_partner(client, promote_role, suffix: str):
    admin = await register_and_login(client, f"wcadmin{suffix}")
    await promote_role(admin["user_id"], "SUPER_ADMIN")

    merchant_user = await register_and_login(client, f"wcmerchant{suffix}")
    await client.post(
        "/api/v1/auth/apply-merchant",
        json={"business_name": f"Webhook Partner {suffix}", "contact_phone": "+1000000000"},
        headers=merchant_user["headers"],
    )
    queue = await client.get("/api/v1/admin/merchants/queue", headers=admin["headers"])
    entry = next(m for m in queue.json() if m["user_id"] == merchant_user["user_id"])
    await client.post(f"/api/v1/admin/merchants/{entry['id']}/approve", headers=admin["headers"])

    key_res = await client.post(f"/api/v1/admin/merchants/{entry['id']}/api-key", headers=admin["headers"])
    raw_key = key_res.json()["api_key"]

    headers = await partner_auth_headers(client, raw_key)
    return headers, entry["id"]


async def test_set_webhook_config_returns_secret_once_and_persists_url(client, db_session, promote_role):
    headers, merchant_id = await _make_partner(client, promote_role, "1")

    res = await client.put(
        "/api/v1/partner/webhook-config",
        json={"webhook_url": "https://partner.example.com/hooks/esim"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["webhook_url"] == "https://partner.example.com/hooks/esim"
    assert body["webhook_secret"].startswith("whsec_")

    m_res = await db_session.execute(select(MerchantProfile).where(MerchantProfile.id == merchant_id))
    merchant = m_res.scalar_one()
    assert merchant.webhook_url == "https://partner.example.com/hooks/esim"
    assert merchant.webhook_secret == body["webhook_secret"]

    me = await client.get("/api/v1/partner/me", headers=headers)
    assert me.json()["webhook_configured"] is True


async def test_reconfiguring_webhook_rotates_the_secret(client, db_session, promote_role):
    headers, merchant_id = await _make_partner(client, promote_role, "2")

    first = await client.put(
        "/api/v1/partner/webhook-config",
        json={"webhook_url": "https://partner.example.com/hooks/v1"},
        headers=headers,
    )
    second = await client.put(
        "/api/v1/partner/webhook-config",
        json={"webhook_url": "https://partner.example.com/hooks/v2"},
        headers=headers,
    )
    assert first.json()["webhook_secret"] != second.json()["webhook_secret"]

    m_res = await db_session.execute(select(MerchantProfile).where(MerchantProfile.id == merchant_id))
    merchant = m_res.scalar_one()
    assert merchant.webhook_url == "https://partner.example.com/hooks/v2"
    assert merchant.webhook_secret == second.json()["webhook_secret"]


async def test_clearing_webhook_config_removes_url_and_secret(client, db_session, promote_role):
    headers, merchant_id = await _make_partner(client, promote_role, "3")

    await client.put(
        "/api/v1/partner/webhook-config",
        json={"webhook_url": "https://partner.example.com/hooks/esim"},
        headers=headers,
    )
    clear = await client.put("/api/v1/partner/webhook-config", json={"webhook_url": None}, headers=headers)
    assert clear.status_code == 200
    assert clear.json() == {"webhook_url": None, "webhook_secret": None}

    m_res = await db_session.execute(select(MerchantProfile).where(MerchantProfile.id == merchant_id))
    merchant = m_res.scalar_one()
    assert merchant.webhook_url is None
    assert merchant.webhook_secret is None


async def test_webhook_config_requires_valid_partner_token(client):
    res = await client.put("/api/v1/partner/webhook-config", json={"webhook_url": "https://x.example.com"}, headers={"Authorization": "Bearer not-a-real-token"})
    assert res.status_code == 401
