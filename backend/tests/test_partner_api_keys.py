import pytest
from fastapi import HTTPException
from sqlalchemy import select
from conftest import register_and_login
from app.models.partner_api import ApiKey
from app.models.merchant import MerchantProfile
from app.core.partner_auth import get_current_partner

pytestmark = pytest.mark.asyncio


async def _make_approved_merchant(client, db_session, promote_role, suffix: str):
    """Registers a user, applies as a merchant, and approves them - the
    prerequisite state for issuing a Partner API key."""
    admin = await register_and_login(client, f"pakadmin{suffix}")
    await promote_role(admin["user_id"], "ADMIN")

    merchant_user = await register_and_login(client, f"pakmerchant{suffix}")
    apply = await client.post(
        "/api/v1/auth/apply-merchant",
        json={"business_name": f"Partner Co {suffix}", "contact_phone": "+1000000000"},
        headers=merchant_user["headers"],
    )
    assert apply.status_code == 200

    queue = await client.get("/api/v1/admin/merchants/queue", headers=admin["headers"])
    entry = next(m for m in queue.json() if m["user_id"] == merchant_user["user_id"])
    approve = await client.post(f"/api/v1/admin/merchants/{entry['id']}/approve", headers=admin["headers"])
    assert approve.status_code == 200
    return admin, merchant_user, entry["id"]


async def test_api_key_requires_approved_merchant(client, promote_role):
    admin = await register_and_login(client, "pakunapproved")
    await promote_role(admin["user_id"], "SUPER_ADMIN")

    applicant = await register_and_login(client, "pakpending")
    await client.post(
        "/api/v1/auth/apply-merchant",
        json={"business_name": "Pending Co", "contact_phone": "+1000000001"},
        headers=applicant["headers"],
    )
    queue = await client.get("/api/v1/admin/merchants/queue", headers=admin["headers"])
    entry = next(m for m in queue.json() if m["user_id"] == applicant["user_id"])

    res = await client.post(f"/api/v1/admin/merchants/{entry['id']}/api-key", headers=admin["headers"])
    assert res.status_code == 400


async def test_generate_api_key_requires_super_admin(client, db_session, promote_role):
    admin, _, merchant_id = await _make_approved_merchant(client, db_session, promote_role, "1")

    # `admin` above was promoted to ADMIN by itself via apply/approve flow - it's
    # still just ADMIN, not SUPER_ADMIN, so key generation must be denied.
    denied = await client.post(f"/api/v1/admin/merchants/{merchant_id}/api-key", headers=admin["headers"])
    assert denied.status_code == 403


async def test_generate_key_shows_raw_value_once_and_stores_only_hash(client, db_session, promote_role):
    admin, _, merchant_id = await _make_approved_merchant(client, db_session, promote_role, "2")
    await promote_role(admin["user_id"], "SUPER_ADMIN")

    res = await client.post(f"/api/v1/admin/merchants/{merchant_id}/api-key", headers=admin["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["api_key"].startswith("esim_live_")
    assert body["key_prefix"] == body["api_key"][:16]

    result = await db_session.execute(select(ApiKey).where(ApiKey.merchant_id == merchant_id, ApiKey.is_active == True))
    row = result.scalar_one()
    assert row.key_hash != body["api_key"]  # never the raw value
    assert len(row.key_hash) == 64  # sha256 hex digest

    status = await client.get(f"/api/v1/admin/merchants/{merchant_id}/api-key", headers=admin["headers"])
    assert status.json()["has_active_key"] is True
    assert status.json()["key_prefix"] == body["key_prefix"]


async def test_regenerating_key_retires_the_old_one(client, db_session, promote_role):
    admin, _, merchant_id = await _make_approved_merchant(client, db_session, promote_role, "3")
    await promote_role(admin["user_id"], "SUPER_ADMIN")

    first = await client.post(f"/api/v1/admin/merchants/{merchant_id}/api-key", headers=admin["headers"])
    second = await client.post(f"/api/v1/admin/merchants/{merchant_id}/api-key", headers=admin["headers"])
    assert first.json()["api_key"] != second.json()["api_key"]

    result = await db_session.execute(select(ApiKey).where(ApiKey.merchant_id == merchant_id))
    all_keys = result.scalars().all()
    assert len(all_keys) == 2
    active = [k for k in all_keys if k.is_active]
    assert len(active) == 1
    assert active[0].key_prefix == second.json()["key_prefix"]


async def test_revoke_key_requires_super_admin_and_deactivates(client, db_session, promote_role):
    admin, _, merchant_id = await _make_approved_merchant(client, db_session, promote_role, "4")

    denied = await client.delete(f"/api/v1/admin/merchants/{merchant_id}/api-key", headers=admin["headers"])
    assert denied.status_code == 403

    await promote_role(admin["user_id"], "SUPER_ADMIN")
    await client.post(f"/api/v1/admin/merchants/{merchant_id}/api-key", headers=admin["headers"])

    revoke = await client.delete(f"/api/v1/admin/merchants/{merchant_id}/api-key", headers=admin["headers"])
    assert revoke.status_code == 200

    status = await client.get(f"/api/v1/admin/merchants/{merchant_id}/api-key", headers=admin["headers"])
    assert status.json()["has_active_key"] is False

    # Revoking again with nothing active is a 404, not a silent no-op.
    revoke_again = await client.delete(f"/api/v1/admin/merchants/{merchant_id}/api-key", headers=admin["headers"])
    assert revoke_again.status_code == 404


async def test_get_current_partner_resolves_valid_key_and_rejects_invalid(client, db_session, promote_role):
    admin, merchant_user, merchant_id = await _make_approved_merchant(client, db_session, promote_role, "5")
    await promote_role(admin["user_id"], "SUPER_ADMIN")

    generated = await client.post(f"/api/v1/admin/merchants/{merchant_id}/api-key", headers=admin["headers"])
    raw_key = generated.json()["api_key"]

    ctx = await get_current_partner(x_api_key=raw_key, db=db_session)
    assert ctx.merchant.id == merchant_id
    assert ctx.user.id == merchant_user["user_id"]

    with pytest.raises(HTTPException) as exc_info:
        await get_current_partner(x_api_key="not-a-real-key", db=db_session)
    assert exc_info.value.status_code == 401

    # A revoked key must also stop authenticating.
    result = await db_session.execute(select(ApiKey).where(ApiKey.merchant_id == merchant_id, ApiKey.is_active == True))
    active_key = result.scalar_one()
    active_key.is_active = False
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info2:
        await get_current_partner(x_api_key=raw_key, db=db_session)
    assert exc_info2.value.status_code == 401
