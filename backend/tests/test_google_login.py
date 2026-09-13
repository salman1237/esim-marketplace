import time
import uuid
import pytest
from unittest.mock import AsyncMock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt
from sqlalchemy import select

from conftest import register_and_login
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.user import User, UserStatus
from app.models.wallet import Wallet, WalletType
import app.services.google_auth as google_auth
from app.services.google_auth import GoogleTokenError, verify_google_id_token

pytestmark = pytest.mark.asyncio

CLIENT_ID = "test-client.apps.googleusercontent.com"
KID = "test-signing-key"


def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private_pem, public_pem


PRIVATE_PEM, PUBLIC_PEM = _keypair()
# A different key, to forge a token that claims Google's key id.
FORGER_PRIVATE_PEM, _ = _keypair()
JWKS = {"keys": [{**jwk.construct(PUBLIC_PEM, "RS256").to_dict(), "kid": KID, "use": "sig"}]}


def _token(kid: str = KID, private_pem: str = PRIVATE_PEM, **claims) -> str:
    now = int(time.time())
    payload = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": uuid.uuid4().hex,
        "email": f"ada_{uuid.uuid4().hex[:8]}@gmail.com",
        "email_verified": True,
        "name": "Ada Lovelace",
        "given_name": "Ada",
        "picture": "https://lh3.googleusercontent.com/a/photo-1",
        "iat": now,
        "exp": now + 3600,
    }
    payload.update(claims)
    return jwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def google_keys(monkeypatch):
    """Google configured, with its signing keys served locally instead of
    fetched from googleapis.com."""
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", CLIENT_ID)
    google_auth._reset_cache()
    fetch = AsyncMock(return_value=(JWKS, 3600))
    with patch.object(google_auth, "_fetch_google_jwks", fetch):
        yield fetch
    google_auth._reset_cache()


# --- Token verification ---------------------------------------------------


async def test_valid_google_token_is_verified(google_keys):
    claims = await verify_google_id_token(_token(email="grace@gmail.com"), CLIENT_ID)
    assert claims["email"] == "grace@gmail.com"
    # Cached: a second verification doesn't refetch Google's keys.
    await verify_google_id_token(_token(), CLIENT_ID)
    assert google_keys.await_count == 1


@pytest.mark.parametrize("bad_token", [
    lambda: _token(aud="some-other-app.apps.googleusercontent.com"),
    lambda: _token(iss="https://evil.example.com"),
    lambda: _token(iat=int(time.time()) - 7200, exp=int(time.time()) - 3600),
    lambda: _token(private_pem=FORGER_PRIVATE_PEM),
    lambda: _token(email=None),
    lambda: "not-a-jwt",
])
async def test_invalid_google_tokens_are_rejected(google_keys, bad_token):
    with pytest.raises(GoogleTokenError):
        await verify_google_id_token(bad_token(), CLIENT_ID)


async def test_unknown_signing_key_triggers_one_refetch_then_fails(google_keys):
    with pytest.raises(GoogleTokenError):
        await verify_google_id_token(_token(kid="rotated-key"), CLIENT_ID)
    assert google_keys.await_count == 2


# --- POST /auth/google ----------------------------------------------------


async def test_first_google_sign_in_creates_account_with_photo_name_and_wallets(client, google_keys):
    sub = uuid.uuid4().hex
    email = f"Ada.Lovelace_{uuid.uuid4().hex[:6]}@Gmail.com"
    res = await client.post("/api/v1/auth/google", json={"credential": _token(sub=sub, email=email)})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["role"] == "USER"

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    profile = me.json()
    assert profile["email"] == email.lower()
    assert profile["full_name"] == "Ada Lovelace"
    assert profile["avatar_url"] == "https://lh3.googleusercontent.com/a/photo-1"
    assert profile["email_verified"] is True
    assert profile["has_google"] is True
    assert profile["username"].startswith("adalovelace")
    assert any(w["wallet_type"] == "DEFAULT" for w in profile["wallets"])

    # Signing in again finds the same account and picks up a new photo.
    again = await client.post(
        "/api/v1/auth/google",
        json={"credential": _token(sub=sub, email=email, picture="https://lh3.googleusercontent.com/a/photo-2")},
    )
    assert again.status_code == 200
    assert again.json()["user_id"] == body["user_id"]
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == body["user_id"]))).scalar_one()
        assert user.avatar_url == "https://lh3.googleusercontent.com/a/photo-2"
        wallets = (await db.execute(select(Wallet).where(Wallet.user_id == user.id, Wallet.wallet_type == WalletType.DEFAULT))).scalars().all()
        assert len(wallets) == 1


async def test_google_sign_in_links_an_existing_account_by_verified_email(client, google_keys):
    existing = await register_and_login(client, "googlelink")
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == existing["user_id"]))).scalar_one()
        email, password_hash = user.email, user.hashed_password

    res = await client.post("/api/v1/auth/google", json={"credential": _token(email=email.upper())})
    assert res.status_code == 200, res.text
    assert res.json()["user_id"] == existing["user_id"]

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == existing["user_id"]))).scalar_one()
        assert user.google_sub is not None
        assert user.email_verified is True
        # Their password still works - linking never replaces it.
        assert user.hashed_password == password_hash


async def test_unverified_google_email_cannot_create_or_link_an_account(client, google_keys):
    existing = await register_and_login(client, "googleunverified")
    async with AsyncSessionLocal() as db:
        email = (await db.execute(select(User.email).where(User.id == existing["user_id"]))).scalar_one()

    takeover = await client.post("/api/v1/auth/google", json={"credential": _token(email=email, email_verified=False)})
    assert takeover.status_code == 400
    fresh = await client.post("/api/v1/auth/google", json={"credential": _token(email_verified=False)})
    assert fresh.status_code == 400


async def test_email_already_linked_to_another_google_account_is_rejected(client, google_keys):
    email = f"shared_{uuid.uuid4().hex[:8]}@gmail.com"
    first = await client.post("/api/v1/auth/google", json={"credential": _token(email=email)})
    assert first.status_code == 200
    second = await client.post("/api/v1/auth/google", json={"credential": _token(email=email)})  # new sub
    assert second.status_code == 409


async def test_suspended_account_cannot_sign_in_with_google(client, google_keys):
    sub = uuid.uuid4().hex
    first = await client.post("/api/v1/auth/google", json={"credential": _token(sub=sub)})
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == first.json()["user_id"]))).scalar_one()
        user.status = UserStatus.SUSPENDED
        await db.commit()

    res = await client.post("/api/v1/auth/google", json={"credential": _token(sub=sub, email=user.email)})
    assert res.status_code == 403


async def test_forged_google_credential_is_rejected(client, google_keys):
    res = await client.post("/api/v1/auth/google", json={"credential": _token(private_pem=FORGER_PRIVATE_PEM)})
    assert res.status_code == 401


async def test_google_sign_in_is_hidden_and_refused_when_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    assert (await client.get("/api/v1/settings/public")).json()["google_client_id"] is None
    res = await client.post("/api/v1/auth/google", json={"credential": "anything"})
    assert res.status_code == 503

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", CLIENT_ID)
    assert (await client.get("/api/v1/settings/public")).json()["google_client_id"] == CLIENT_ID
