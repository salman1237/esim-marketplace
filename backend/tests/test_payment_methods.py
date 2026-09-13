import pytest
from conftest import register_and_login

pytestmark = pytest.mark.asyncio

METHODS = [
    {"name": "bKash", "kind": "mobile", "account_name": "Triptel Ltd", "account_number": " 01811-111111 ", "instructions": "Send Money, not Cash Out"},
    {"name": "City Bank", "kind": "bank", "account_name": "Triptel Ltd", "account_number": "1234000099", "branch": "Gulshan"},
    {"name": "Retired Nagad", "kind": "mobile", "account_number": "01900-000000", "is_active": False},
]


async def _clear(client, headers):
    # Tests share one database - leave no configured methods behind, since
    # that switches on deposit-name validation for every other test.
    await client.put("/api/v1/admin/payment-methods", json={"methods": []}, headers=headers)


async def test_super_admin_configures_methods_and_public_sees_only_active(client, promote_role):
    sa = await register_and_login(client, "pmsuper")
    await promote_role(sa["user_id"], "SUPER_ADMIN")
    try:
        res = await client.put("/api/v1/admin/payment-methods", json={"methods": METHODS}, headers=sa["headers"])
        assert res.status_code == 200, res.text
        saved = res.json()["methods"]
        assert [m["id"] for m in saved] == ["bkash", "city-bank", "retired-nagad"]
        assert saved[0]["account_number"] == "01811-111111"  # trimmed

        admin_view = await client.get("/api/v1/admin/payment-methods", headers=sa["headers"])
        assert len(admin_view.json()["methods"]) == 3

        public = (await client.get("/api/v1/settings/public")).json()
        assert [m["name"] for m in public["payment_methods"]] == ["bKash", "City Bank"]

        logs = await client.get("/api/v1/admin/audit-logs", headers=sa["headers"])
        assert any(l["action"] == "UPDATE_PAYMENT_METHODS" for l in logs.json())
    finally:
        await _clear(client, sa["headers"])


async def test_payment_methods_edit_requires_super_admin(client, promote_role):
    admin = await register_and_login(client, "pmadmin")
    await promote_role(admin["user_id"], "ADMIN")
    assert (await client.get("/api/v1/admin/payment-methods", headers=admin["headers"])).status_code == 200
    res = await client.put("/api/v1/admin/payment-methods", json={"methods": METHODS}, headers=admin["headers"])
    assert res.status_code == 403


async def test_payment_methods_validation(client, promote_role):
    sa = await register_and_login(client, "pmvalid")
    await promote_role(sa["user_id"], "SUPER_ADMIN")
    dup = await client.put(
        "/api/v1/admin/payment-methods",
        json={"methods": [{"name": "bKash"}, {"name": "BKASH "}]},
        headers=sa["headers"],
    )
    assert dup.status_code == 400
    bad_kind = await client.put(
        "/api/v1/admin/payment-methods",
        json={"methods": [{"name": "Crypto", "kind": "bitcoin"}]},
        headers=sa["headers"],
    )
    assert bad_kind.status_code == 422


async def test_manual_deposit_must_use_an_active_method_once_configured(client, promote_role):
    sa = await register_and_login(client, "pmdeposit")
    await promote_role(sa["user_id"], "SUPER_ADMIN")
    user = await register_and_login(client, "pmdepositor")
    body = {"amount": "500.00", "currency": "BDT", "transaction_id": "TXPM1"}
    try:
        await client.put("/api/v1/admin/payment-methods", json={"methods": METHODS}, headers=sa["headers"])

        unknown = await client.post("/api/v1/wallets/manual-deposit", json={**body, "bank_name": "Some Bank"}, headers=user["headers"])
        assert unknown.status_code == 400

        retired = await client.post("/api/v1/wallets/manual-deposit", json={**body, "bank_name": "Retired Nagad"}, headers=user["headers"])
        assert retired.status_code == 400

        ok = await client.post("/api/v1/wallets/manual-deposit", json={**body, "bank_name": "bkash"}, headers=user["headers"])
        assert ok.status_code == 200, ok.text
        assert ok.json()["bank_name"] == "bKash"  # stored under the canonical name
    finally:
        await _clear(client, sa["headers"])


async def test_manual_deposit_rejects_non_positive_amount(client):
    user = await register_and_login(client, "pmzero")
    res = await client.post(
        "/api/v1/wallets/manual-deposit",
        json={"amount": "0", "currency": "BDT", "bank_name": "bKash", "transaction_id": "TX0"},
        headers=user["headers"],
    )
    assert res.status_code == 400
