import pytest
import httpx
from app.services.shurjopay_svc import ShurjoPayService

pytestmark = pytest.mark.asyncio


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _mock_post_factory(payload: dict, status_code: int = 200):
    async def _mock_post(self, url, *args, **kwargs):
        return _FakeResponse(status_code, payload)
    return _mock_post


def _mock_post_by_url_factory(url_to_payload: dict, status_code: int = 200):
    async def _mock_post(self, url, *args, **kwargs):
        for needle, payload in url_to_payload.items():
            if needle in str(url):
                return _FakeResponse(status_code, payload)
        raise AssertionError(f"Unexpected URL in test: {url}")
    return _mock_post


async def test_authenticate_persists_payment_log_with_real_types(db_session, monkeypatch):
    """Regression test: PaymentLog.status_code is an Integer column, but the
    service previously passed str(resp.status_code) — invisible to any test
    that mocks ShurjoPayService itself (as test_shurjopay_callback.py does),
    since Python doesn't type-check ORM column assignment; it only surfaces
    as an asyncpg DataError when the INSERT actually runs. This is exactly
    how it was first caught: not by a mocked test, but by hitting the real
    endpoint against a real Postgres database. Mocking one level lower (the
    HTTP call, not the service method) reproduces that same real INSERT."""
    monkeypatch.setattr(
        httpx.AsyncClient, "post",
        _mock_post_factory({"token": "fake-token", "store_id": 1, "sp_code": "200"})
    )
    data = await ShurjoPayService.authenticate(db_session)
    await db_session.commit()
    assert data["token"] == "fake-token"


async def test_verify_payment_persists_payment_log_with_real_types(db_session, monkeypatch):
    monkeypatch.setattr(
        httpx.AsyncClient, "post",
        _mock_post_by_url_factory({
            "get_token": {"token": "fake-token", "store_id": 1, "sp_code": "200"},
            "verification": [{"order_id": "sp123", "sp_code": "1000", "customer_order_id": "TOPUP-x-y"}],
        })
    )
    data = await ShurjoPayService.verify_payment(db_session, "sp123")
    await db_session.commit()
    assert data[0]["sp_code"] == "1000"
