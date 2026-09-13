import pytest
from conftest import register_and_login

pytestmark = pytest.mark.asyncio

SLUGS = ["terms", "privacy", "data-policy", "refund-policy"]


async def test_public_legal_documents_serve_drafts_with_branding_filled_in(client):
    listing = await client.get("/api/v1/settings/legal")
    assert listing.status_code == 200
    assert [d["slug"] for d in listing.json()] == SLUGS

    for slug in SLUGS:
        res = await client.get(f"/api/v1/settings/legal/{slug}")
        assert res.status_code == 200, slug
        body = res.json()["body"]
        assert len(body) > 500
        assert "{platform_name}" not in body and "{support_email}" not in body
        assert "is_default" not in res.json()  # internal detail stays in the admin API

    assert (await client.get("/api/v1/settings/legal/cookies")).status_code == 404


async def test_super_admin_edits_and_resets_a_policy(client, promote_role):
    sa = await register_and_login(client, "legalsuper")
    await promote_role(sa["user_id"], "SUPER_ADMIN")
    try:
        save = await client.put(
            "/api/v1/admin/legal/refund-policy",
            json={"body": "## Refunds\r\nEmail {support_email} within 3 days."},
            headers=sa["headers"],
        )
        assert save.status_code == 200, save.text
        assert save.json()["is_default"] is False
        assert save.json()["updated_at"]

        public = (await client.get("/api/v1/settings/legal/refund-policy")).json()
        assert public["body"].startswith("## Refunds\nEmail ")
        assert "{support_email}" not in public["body"]

        admin_view = (await client.get("/api/v1/admin/legal", headers=sa["headers"])).json()["documents"]
        refund = next(d for d in admin_view if d["slug"] == "refund-policy")
        assert "{support_email}" in refund["body"]  # admin edits the raw template

        logs = await client.get("/api/v1/admin/audit-logs", headers=sa["headers"])
        assert any(l["action"] == "UPDATE_LEGAL_DOCUMENT" for l in logs.json())

        reset = await client.put("/api/v1/admin/legal/refund-policy", json={"body": "  "}, headers=sa["headers"])
        assert reset.json()["is_default"] is True
        assert (await client.get("/api/v1/settings/legal/refund-policy")).json()["updated_at"] is None
    finally:
        await client.put("/api/v1/admin/legal/refund-policy", json={"body": ""}, headers=sa["headers"])


async def test_legal_edit_permissions_and_limits(client, promote_role):
    admin = await register_and_login(client, "legaladmin")
    await promote_role(admin["user_id"], "ADMIN")
    assert (await client.get("/api/v1/admin/legal", headers=admin["headers"])).status_code == 200
    assert (await client.put("/api/v1/admin/legal/terms", json={"body": "x"}, headers=admin["headers"])).status_code == 403

    sa = await register_and_login(client, "legallimits")
    await promote_role(sa["user_id"], "SUPER_ADMIN")
    assert (await client.put("/api/v1/admin/legal/cookies", json={"body": "x"}, headers=sa["headers"])).status_code == 404
    too_long = await client.put("/api/v1/admin/legal/terms", json={"body": "x" * 60_001}, headers=sa["headers"])
    assert too_long.status_code == 422
