import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.vivape_adapter import VivaPeAdapter

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def mock_vivape():
    """Overrides conftest's autouse mock_vivape, which patches
    VivaPeAdapter.create_transaction globally - this file tests that real
    implementation directly, so it must not be patched away here."""
    yield


@pytest.fixture(autouse=True)
def _reset_token_cache():
    """VivaPeAdapter caches its token on class attributes, not per-instance -
    tests must not leak cached state into each other."""
    VivaPeAdapter._token = None
    VivaPeAdapter._token_expiry = 0
    VivaPeAdapter._token_generation = 0
    VivaPeAdapter._token_lock = asyncio.Lock()
    yield
    VivaPeAdapter._token = None
    VivaPeAdapter._token_expiry = 0
    VivaPeAdapter._token_generation = 0
    VivaPeAdapter._token_lock = asyncio.Lock()


@pytest.fixture(autouse=True)
def _no_retry_delay():
    """create_transaction sleeps between retries in production (VivaPe
    needs a short settle window) - tests don't need to actually wait."""
    with patch("app.services.vivape_adapter.asyncio.sleep", new=AsyncMock()):
        yield


def _resp(json_body, status_code=200):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body
    r.text = str(json_body)
    return r


async def test_create_transaction_retries_with_fresh_token_on_empty_result(db_session):
    """Reproduces the live 2026-09-10 incident: VivaPe returned HTTP 200
    with a generic error body (no purchase_trx.id) for a stale cached
    token - indistinguishable by message from a real failure - and a
    fresh login immediately succeeded for the identical payload. Since no
    purchase_trx.id means nothing was actually charged, retrying once
    with a forced fresh login must be safe and must recover the sale."""
    login_responses = [
        _resp({"access_token": "stale-token-from-earlier-login"}),
        _resp({"access_token": "fresh-token-after-retry"}),
    ]
    post_responses = [
        _resp({"error": "Insufficient Balance."}),  # stale-token call
        _resp({"success": "Transaction Successful.", "purchase_trx": {"id": 60231}}),  # fresh-token retry
    ]

    async def fake_post(url, headers=None, data=None, **kwargs):
        if url.endswith("/login"):
            return login_responses.pop(0)
        return post_responses.pop(0)

    mock_client = AsyncMock()
    mock_client.post.side_effect = fake_post
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await VivaPeAdapter.create_transaction(db_session, 16394, Decimal("1.215"))

    assert result["purchase_trx"]["id"] == 60231
    assert mock_client.post.call_count == 4  # login, create-tx, login (forced), create-tx


async def test_create_transaction_does_not_retry_on_success(db_session):
    login_responses = [_resp({"access_token": "good-token"})]
    post_responses = [_resp({"success": "Transaction Successful.", "purchase_trx": {"id": 999}})]

    async def fake_post(url, headers=None, data=None, **kwargs):
        if url.endswith("/login"):
            return login_responses.pop(0)
        return post_responses.pop(0)

    mock_client = AsyncMock()
    mock_client.post.side_effect = fake_post
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await VivaPeAdapter.create_transaction(db_session, 16394, Decimal("1.215"))

    assert result["purchase_trx"]["id"] == 999
    assert mock_client.post.call_count == 2  # login, create-tx only - no retry


async def test_create_transaction_gives_up_after_exhausting_retries(db_session):
    """A genuine, persistent failure (real insufficient balance, not a
    stale token) must still surface as a failure after retries are
    exhausted - the retry logic must not mask real failures forever."""
    post_responses = [_resp({"error": "Insufficient Balance."}) for _ in range(3)]
    login_responses = [_resp({"access_token": f"token-{i}"}) for i in range(3)]

    async def fake_post(url, headers=None, data=None, **kwargs):
        if url.endswith("/login"):
            return login_responses.pop(0)
        return post_responses.pop(0)

    mock_client = AsyncMock()
    mock_client.post.side_effect = fake_post
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await VivaPeAdapter.create_transaction(db_session, 16291, Decimal("21.627"))

    assert result["error"] == "Insufficient Balance."
    assert mock_client.post.call_count == 6  # 3x (login + create-tx)


async def test_get_token_reuses_cache_within_window(db_session):
    VivaPeAdapter._token = "cached"
    VivaPeAdapter._token_expiry = time.time() + 1000

    mock_client = AsyncMock()
    with patch("httpx.AsyncClient", return_value=mock_client):
        token = await VivaPeAdapter.get_token(db_session)

    assert token == "cached"
    mock_client.post.assert_not_called()


async def test_concurrent_get_token_calls_only_login_once(db_session):
    """Reproduces the live root cause: catalog sync and a live checkout
    (or a checkout and its own retry) can call get_token() concurrently
    when the cache is empty/expired. Without a lock, both fire a login,
    and VivaPe invalidates whichever token isn't the most recent -
    silently breaking the other caller even though its token looked
    freshly obtained. All concurrent callers must share one login."""
    login_call_count = 0

    async def fake_post(url, headers=None, data=None, **kwargs):
        nonlocal login_call_count
        assert url.endswith("/login"), "only login calls expected in this test"
        login_call_count += 1
        await asyncio.sleep(0.05)  # simulate real network latency
        return _resp({"access_token": f"token-{login_call_count}"})

    mock_client = AsyncMock()
    mock_client.post.side_effect = fake_post
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with patch("httpx.AsyncClient", return_value=mock_client):
        tokens = await asyncio.gather(*[
            VivaPeAdapter.get_token(db_session) for _ in range(5)
        ])

    assert login_call_count == 1
    assert len(set(tokens)) == 1


async def test_get_token_force_refresh_bypasses_cache(db_session):
    VivaPeAdapter._token = "cached"
    VivaPeAdapter._token_expiry = time.time() + 1000

    mock_client = AsyncMock()
    mock_client.post.return_value = _resp({"access_token": "brand-new-token"})
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with patch("httpx.AsyncClient", return_value=mock_client):
        token = await VivaPeAdapter.get_token(db_session, force_refresh=True)

    assert token == "brand-new-token"
    mock_client.post.assert_called_once()
