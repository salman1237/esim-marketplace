import pytest
from conftest import register_and_login

pytestmark = pytest.mark.asyncio


async def test_plain_user_cannot_reach_admin_stats(client):
    user = await register_and_login(client, "plain")
    res = await client.get("/api/v1/admin/stats", headers=user["headers"])
    assert res.status_code == 403


async def test_admin_cannot_reach_super_admin_only_routes(client, promote_role):
    admin = await register_and_login(client, "adminonly")
    await promote_role(admin["user_id"], "ADMIN")

    # ADMIN can reach admin-level routes...
    res = await client.get("/api/v1/admin/stats", headers=admin["headers"])
    assert res.status_code == 200

    # ...but not super-admin-only ones: branding, currency override,
    # language toggle, staff role management, audit log viewer.
    for method, path, payload in [
        ("PUT", "/api/v1/admin/branding", {"platform_name": "Hacked"}),
        ("PUT", "/api/v1/admin/currencies/override", {"currency_code": "USD", "is_manual_override": True, "manual_rate": 1}),
        ("PUT", "/api/v1/admin/languages/toggle", {"code": "en", "is_active": False}),
        ("GET", "/api/v1/admin/audit-logs", None),
    ]:
        if method == "PUT":
            res = await client.put(path, json=payload, headers=admin["headers"])
        else:
            res = await client.get(path, headers=admin["headers"])
        assert res.status_code == 403, f"{method} {path} should be super-admin-only, got {res.status_code}"


async def test_super_admin_can_update_branding(client, promote_role):
    sa = await register_and_login(client, "superadm")
    await promote_role(sa["user_id"], "SUPER_ADMIN")
    res = await client.put(
        "/api/v1/admin/branding",
        json={"platform_name": "Test Platform Renamed"},
        headers=sa["headers"],
    )
    assert res.status_code == 200, res.text

    public = await client.get("/api/v1/settings/public")
    assert public.json()["platform_name"] == "Test Platform Renamed"


async def test_unauthenticated_request_rejected(client):
    res = await client.get("/api/v1/auth/me")
    assert res.status_code == 401
