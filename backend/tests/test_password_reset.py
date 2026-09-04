import hashlib
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from conftest import register_and_login
from app.models.password_reset import PasswordResetToken

pytestmark = pytest.mark.asyncio


async def test_forgot_password_nonexistent_email_returns_generic_success(client):
    """No user enumeration: a real vs. fake email must look identical."""
    res = await client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
    assert res.status_code == 200
    assert "detail" not in res.json()


async def test_forgot_password_creates_token_for_real_user(client, db_session):
    user = await register_and_login(client, "resetuser")
    res = await client.post("/api/v1/auth/forgot-password", json={"email": user["email"]})
    assert res.status_code == 200

    result = await db_session.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user["user_id"]))
    token_row = result.scalar_one()
    assert token_row.used_at is None
    assert token_row.expires_at > datetime.now(timezone.utc)


async def test_reset_password_full_flow_changes_password(client, db_session):
    user = await register_and_login(client, "resetflow")
    await client.post("/api/v1/auth/forgot-password", json={"email": user["email"]})

    result = await db_session.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user["user_id"]))
    token_row = result.scalar_one()

    # The raw token only ever exists in the email (not persisted) - since
    # this test can't read the email, forge one whose hash matches what
    # forgot-password stored, by minting our own token and overwriting the
    # stored hash to match it (keeps the rest of the row - expiry etc - as
    # the real endpoint set it).
    raw_token = "test-raw-token-for-reset-flow"
    token_row.token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    await db_session.commit()

    reset = await client.post("/api/v1/auth/reset-password", json={"token": raw_token, "new_password": "NewPass456!"})
    assert reset.status_code == 200, reset.text

    old_login = await client.post("/api/v1/auth/login", json={"email": user["email"], "password": "TestPass123!"})
    assert old_login.status_code == 401

    new_login = await client.post("/api/v1/auth/login", json={"email": user["email"], "password": "NewPass456!"})
    assert new_login.status_code == 200

    # The token is single-use.
    reuse = await client.post("/api/v1/auth/reset-password", json={"token": raw_token, "new_password": "AnotherPass789!"})
    assert reuse.status_code == 400


async def test_reset_password_rejects_expired_token(client, db_session):
    user = await register_and_login(client, "resetexpired")
    await client.post("/api/v1/auth/forgot-password", json={"email": user["email"]})

    result = await db_session.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user["user_id"]))
    token_row = result.scalar_one()
    raw_token = "test-raw-token-expired"
    token_row.token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    token_row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()

    res = await client.post("/api/v1/auth/reset-password", json={"token": raw_token, "new_password": "NewPass456!"})
    assert res.status_code == 400


async def test_reset_password_rejects_unknown_token(client):
    res = await client.post("/api/v1/auth/reset-password", json={"token": "not-a-real-token", "new_password": "NewPass456!"})
    assert res.status_code == 400


async def test_reset_password_rejects_short_password(client, db_session):
    user = await register_and_login(client, "resetshort")
    await client.post("/api/v1/auth/forgot-password", json={"email": user["email"]})
    result = await db_session.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user["user_id"]))
    token_row = result.scalar_one()
    raw_token = "test-raw-token-short-pw"
    token_row.token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    await db_session.commit()

    res = await client.post("/api/v1/auth/reset-password", json={"token": raw_token, "new_password": "short"})
    assert res.status_code == 400
