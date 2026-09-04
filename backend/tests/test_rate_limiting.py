import uuid
import pytest
from app.core.rate_limit import limiter

pytestmark = pytest.mark.asyncio


async def test_register_rate_limit_blocks_after_threshold(client, monkeypatch):
    """The limiter is disabled outside production (see rate_limit.py) so
    the rest of the suite isn't flaky - force it on here to prove the
    5/minute limit on /auth/register actually engages when it matters."""
    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()

    statuses = []
    for _ in range(6):
        suffix = uuid.uuid4().hex[:8]
        res = await client.post(
            "/api/v1/auth/register",
            json={"email": f"ratelimit_{suffix}@example.com", "username": f"ratelimit_{suffix}", "password": "TestPass123!"},
        )
        statuses.append(res.status_code)

    assert statuses[:5] == [200] * 5
    assert statuses[5] == 429


async def test_login_rate_limit_blocks_after_threshold(client, monkeypatch):
    from conftest import register_and_login
    user = await register_and_login(client, "ratelimitlogin")

    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()

    statuses = []
    for _ in range(11):
        res = await client.post("/api/v1/auth/login", json={"email": user["email"], "password": "wrong-password"})
        statuses.append(res.status_code)

    assert statuses[:10] == [401] * 10  # wrong password, but not yet rate-limited
    assert statuses[10] == 429
