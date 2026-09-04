import pytest
from datetime import timedelta
from conftest import register_and_login
from app.core.security import create_access_token

pytestmark = pytest.mark.asyncio


async def _make_partner_key(client, promote_role, suffix: str) -> str:
    """Approved merchant + issued raw API key (not yet exchanged for a
    token) - the prerequisite for testing the token endpoint itself."""
    admin = await register_and_login(client, f"tokadmin{suffix}")
    await promote_role(admin["user_id"], "SUPER_ADMIN")

    merchant_user = await register_and_login(client, f"tokmerchant{suffix}")
    await client.post(
        "/api/v1/auth/apply-merchant",
        json={"business_name": f"Token Partner {suffix}", "contact_phone": "+1000000000"},
        headers=merchant_user["headers"],
    )
    queue = await client.get("/api/v1/admin/merchants/queue", headers=admin["headers"])
    entry = next(m for m in queue.json() if m["user_id"] == merchant_user["user_id"])
    await client.post(f"/api/v1/admin/merchants/{entry['id']}/approve", headers=admin["headers"])

    key_res = await client.post(f"/api/v1/admin/merchants/{entry['id']}/api-key", headers=admin["headers"])
    return key_res.json()["api_key"]


async def test_valid_key_exchanges_for_usable_access_token(client, promote_role):
    raw_key = await _make_partner_key(client, promote_role, "1")

    token_res = await client.post("/api/v1/partner/auth/token", json={"api_key": raw_key})
    assert token_res.status_code == 200, token_res.text
    body = token_res.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    assert body["access_token"]

    # The raw key itself is never accepted anywhere else - only this token is.
    me = await client.get("/api/v1/partner/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200, me.text

    rejected = await client.get("/api/v1/partner/me", headers={"Authorization": f"Bearer {raw_key}"})
    assert rejected.status_code == 401


async def test_invalid_or_revoked_key_rejected_at_token_endpoint(client, promote_role, db_session):
    res = await client.post("/api/v1/partner/auth/token", json={"api_key": "esim_live_not_a_real_key"})
    assert res.status_code == 401

    raw_key = await _make_partner_key(client, promote_role, "2")
    from sqlalchemy import select
    from app.models.partner_api import ApiKey
    key_row = (await db_session.execute(
        select(ApiKey).where(ApiKey.is_active == True, ApiKey.key_prefix == raw_key[:16])
    )).scalar_one()
    key_row.is_active = False
    await db_session.commit()

    revoked_res = await client.post("/api/v1/partner/auth/token", json={"api_key": raw_key})
    assert revoked_res.status_code == 401


async def test_expired_partner_token_rejected(client, promote_role):
    raw_key = await _make_partner_key(client, promote_role, "3")
    token_res = await client.post("/api/v1/partner/auth/token", json={"api_key": raw_key})
    token = token_res.json()["access_token"]

    # Confirm it works before expiry, then craft an already-expired token
    # for the same key to prove get_current_partner actually enforces exp
    # (not just that garbage tokens fail).
    ok = await client.get("/api/v1/partner/me", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200

    from app.core.partner_auth import PARTNER_TOKEN_ROLE
    from app.core.security import decode_access_token
    payload = decode_access_token(token)
    expired_token = create_access_token(
        subject=payload["sub"], role=PARTNER_TOKEN_ROLE, expires_delta=timedelta(seconds=-1)
    )
    expired_res = await client.get("/api/v1/partner/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert expired_res.status_code == 401


async def test_regular_user_session_token_rejected_by_partner_endpoints(client, promote_role):
    """A logged-in user's normal session JWT must never work against
    /partner/* - only a token minted by /partner/auth/token can."""
    user = await register_and_login(client, "regularsessionuser")
    res = await client.get("/api/v1/partner/me", headers=user["headers"])
    assert res.status_code == 401


async def test_partner_access_token_rejected_by_regular_user_endpoints(client, promote_role):
    """The reverse defense-in-depth check: a partner token must never
    authenticate as a regular user, even though both are JWTs signed with
    the same SECRET_KEY."""
    raw_key = await _make_partner_key(client, promote_role, "4")
    token_res = await client.post("/api/v1/partner/auth/token", json={"api_key": raw_key})
    token = token_res.json()["access_token"]

    res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
