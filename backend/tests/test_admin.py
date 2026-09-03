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
