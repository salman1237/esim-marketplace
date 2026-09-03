import pytest
from decimal import Decimal
from conftest import register_and_login

pytestmark = pytest.mark.asyncio


async def test_merchant_application_approval_flow(client, promote_role):
    admin = await register_and_login(client, "mapprover")
    await promote_role(admin["user_id"], "ADMIN")

    applicant = await register_and_login(client, "mapplicant")
    apply_res = await client.post(
        "/api/v1/auth/apply-merchant",
        json={"business_name": "Approve Me Co", "contact_phone": "+1000000000"},
        headers=applicant["headers"],
    )
    assert apply_res.status_code == 200

    queue = await client.get("/api/v1/admin/merchants/queue", headers=admin["headers"])
    assert queue.status_code == 200
    entry = next(m for m in queue.json() if m["user_id"] == applicant["user_id"])

    approve = await client.post(f"/api/v1/admin/merchants/{entry['id']}/approve", headers=admin["headers"])
    assert approve.status_code == 200, approve.text

    # Re-approving is rejected (status guard prevents double-processing)
    approve_again = await client.post(f"/api/v1/admin/merchants/{entry['id']}/approve", headers=admin["headers"])
    assert approve_again.status_code == 400

    # Applicant is now a MERCHANT with a commission wallet
    me = await client.get("/api/v1/auth/me", headers=applicant["headers"])
    assert me.json()["role"] == "MERCHANT"
    assert any(w["type"] == "COMMISSION" for w in me.json()["wallets"])


async def test_manual_deposit_approval_credits_wallet(client, promote_role, db_session):
    """Regression test: manual deposit submission previously crashed because
    ManualPaymentRequest(receipt_url=...) didn't match the model's actual
    `deposit_slip_url` column."""
    admin = await register_and_login(client, "papprover")
    await promote_role(admin["user_id"], "ADMIN")

    depositor = await register_and_login(client, "depositor")
    submit = await client.post(
        "/api/v1/wallets/manual-deposit",
        json={"amount": "1000.00", "currency": "BDT", "bank_name": "Test Bank", "transaction_id": "TX123456", "receipt_url": "https://example.com/slip.jpg"},
        headers=depositor["headers"],
    )
    assert submit.status_code == 200, submit.text
    request_id = submit.json()["id"]

    queue = await client.get("/api/v1/admin/payments/manual-queue", headers=admin["headers"])
    assert queue.status_code == 200
    assert any(p["id"] == request_id for p in queue.json())

    approve = await client.post(f"/api/v1/admin/payments/manual/{request_id}/approve", headers=admin["headers"])
    assert approve.status_code == 200, approve.text

    me = await client.get("/api/v1/auth/me", headers=depositor["headers"])
    default_wallet = next(w for w in me.json()["wallets"] if w["type"] == "DEFAULT")
    assert Decimal(str(default_wallet["balance"])) > Decimal("0")

    # Double-approval is rejected by the status guard
    approve_again = await client.post(f"/api/v1/admin/payments/manual/{request_id}/approve", headers=admin["headers"])
    assert approve_again.status_code == 400


async def test_branding_update_writes_audit_log_with_before_after(client, promote_role):
    sa = await register_and_login(client, "auditor")
    await promote_role(sa["user_id"], "SUPER_ADMIN")

    await client.put("/api/v1/admin/branding", json={"support_email": "old@example.com"}, headers=sa["headers"])
    await client.put("/api/v1/admin/branding", json={"support_email": "new@example.com"}, headers=sa["headers"])

    logs = await client.get("/api/v1/admin/audit-logs", headers=sa["headers"])
    assert logs.status_code == 200
    branding_logs = [l for l in logs.json() if l["action"] == "UPDATE_BRANDING"]
    assert len(branding_logs) >= 2
    latest = branding_logs[0]
    assert latest["after_state"]["support_email"] == "new@example.com"
    assert latest["before_state"]["support_email"] == "old@example.com"
    assert latest["actor_id"] == sa["user_id"]


# A valid 1x1 PNG, small enough to embed inline rather than needing a fixture file.
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
    "53de0000000c4944415408d763f8ffffff3f0005fe02fea739666e0000000049454e44ae426082"
)


async def test_branding_upload_requires_super_admin(client, promote_role):
    admin = await register_and_login(client, "notquitesuper")
    await promote_role(admin["user_id"], "ADMIN")

    res = await client.post(
        "/api/v1/admin/branding/upload",
        data={"kind": "logo_light"},
        files={"file": ("logo.png", _TINY_PNG, "image/png")},
        headers=admin["headers"],
    )
    assert res.status_code == 403


async def test_branding_upload_stores_file_and_updates_public_settings(client, promote_role):
    sa = await register_and_login(client, "logouploader")
    await promote_role(sa["user_id"], "SUPER_ADMIN")

    res = await client.post(
        "/api/v1/admin/branding/upload",
        data={"kind": "logo_light"},
        files={"file": ("logo.png", _TINY_PNG, "image/png")},
        headers=sa["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["kind"] == "logo_light"
    assert body["url"].startswith("/api/v1/uploads/branding/logo_light-")
    assert body["url"].endswith(".png")

    public = await client.get("/api/v1/settings/public")
    assert public.json()["logo_light"] == body["url"]

    # The file is actually served back from the static mount.
    served = await client.get(body["url"])
    assert served.status_code == 200
    assert served.content == _TINY_PNG


async def test_branding_upload_rejects_unknown_kind_and_bad_content_type(client, promote_role):
    sa = await register_and_login(client, "loguploader2")
    await promote_role(sa["user_id"], "SUPER_ADMIN")

    bad_kind = await client.post(
        "/api/v1/admin/branding/upload",
        data={"kind": "hero_banner"},
        files={"file": ("logo.png", _TINY_PNG, "image/png")},
        headers=sa["headers"],
    )
    assert bad_kind.status_code == 400

    bad_type = await client.post(
        "/api/v1/admin/branding/upload",
        data={"kind": "favicon"},
        files={"file": ("payload.exe", b"not-an-image", "application/octet-stream")},
        headers=sa["headers"],
    )
    assert bad_type.status_code == 400
