import pytest
from conftest import register_and_login

pytestmark = pytest.mark.asyncio


async def test_register_and_login(client):
    user = await register_and_login(client, "authuser")
    assert user["token"]


async def test_duplicate_registration_rejected(client):
    user = await register_and_login(client, "dup")
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": user["email"], "username": f"other_{user['username']}", "password": "TestPass123!"},
    )
    assert res.status_code == 400


async def test_login_wrong_password_rejected(client):
    user = await register_and_login(client, "wrongpw")
    res = await client.post("/api/v1/auth/login", json={"email": user["email"], "password": "NotTheRightPassword"})
    assert res.status_code == 401


async def test_get_me_does_not_crash(client):
    """Regression test: GET /auth/me previously crashed for every user because
    it read `current_user.phone` / `is_kyc_verified`, attributes that didn't
    exist on the User model (real fields were `phone_number` / `is_verified`)."""
    user = await register_and_login(client, "meuser")
    res = await client.get("/api/v1/auth/me", headers=user["headers"])
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["email"] == user["email"]
    assert data["role"] == "USER"
    assert "is_kyc_verified" in data
    assert isinstance(data["wallets"], list)
    assert any(w["type"] == "DEFAULT" for w in data["wallets"])


async def test_apply_merchant_does_not_crash(client):
    """Regression test: MerchantProfile(..., website=...) previously crashed
    because the model had no `website` column."""
    user = await register_and_login(client, "merchantapp")
    res = await client.post(
        "/api/v1/auth/apply-merchant",
        json={"business_name": "Test Travel Co", "trade_license": "TR-1", "contact_phone": "+1234567890", "website": "https://example.com"},
        headers=user["headers"],
    )
    assert res.status_code == 200, res.text

    # Applying twice is rejected
    res2 = await client.post(
        "/api/v1/auth/apply-merchant",
        json={"business_name": "Test Travel Co", "contact_phone": "+1234567890"},
        headers=user["headers"],
    )
    assert res2.status_code == 400
