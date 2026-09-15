import pytest
import httpx
from types import SimpleNamespace
from sqlalchemy import select

from conftest import register_and_login
from app.models.settings import PlatformSetting
from app.services.gateway_config_svc import SHURJOPAY_KEY, get_shurjopay_config
from app.services import shurjopay_svc
from app.services.shurjopay_svc import ShurjoPayService

pytestmark = pytest.mark.asyncio

URL = "/api/v1/admin/payment-gateways/shurjopay"
FAKE = {"mode": "live", "username": "teststore", "password": "not-a-real-pass-9x!", "prefix": "tst"}


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload, self.status_code = payload, status_code

    def json(self):
        return self._payload


def _fake_gateway(monkeypatch, post):
    """Fakes only the HTTP client inside the ShurjoPay service. Patching
    httpx.AsyncClient globally would also hijack the test client's own
    requests to our API."""
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, *args, **kwargs):
            return await post(url, **kwargs)

    monkeypatch.setattr(shurjopay_svc, "httpx", SimpleNamespace(AsyncClient=FakeClient))


async def _super_admin(client, promote_role, name):
    sa = await register_and_login(client, name)
    await promote_role(sa["user_id"], "SUPER_ADMIN")
    return sa


async def test_saved_credentials_are_encrypted_masked_and_used(client, db_session, promote_role, monkeypatch):
    sa = await _super_admin(client, promote_role, "spcfgsuper")
    try:
        before = (await client.get(URL, headers=sa["headers"])).json()
        assert before["source"] == "environment"
        assert before["urls"]["ipn_url"].endswith("/api/v1/payments/shurjopay/ipn")

        saved = await client.put(URL, json=FAKE, headers=sa["headers"])
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["source"] == "admin" and body["mode"] == "live"
        assert body["base_url"] == "https://engine.shurjopayment.com"
        assert body["prefix"] == "TST" and body["password_set"] is True
        assert FAKE["password"] not in saved.text

        row = (await db_session.execute(select(PlatformSetting).where(PlatformSetting.key == SHURJOPAY_KEY))).scalar_one()
        assert row.is_public is False
        assert FAKE["password"] not in str(row.value)

        public = await client.get("/api/v1/settings/public")
        assert "teststore" not in public.text

        logs = await client.get("/api/v1/admin/audit-logs", headers=sa["headers"])
        assert any(l["action"] == "UPDATE_SHURJOPAY_CONFIG" for l in logs.json())
        assert FAKE["password"] not in logs.text

        # The payment service now logs in with the saved credentials.
        sent = {}

        async def fake_post(url, **kwargs):
            sent["url"], sent["json"] = str(url), kwargs.get("json")
            return _Resp({"token": "tok-123", "store_id": 7})

        _fake_gateway(monkeypatch, fake_post)
        await ShurjoPayService.authenticate(db_session)
        assert sent["url"] == "https://engine.shurjopayment.com/api/get_token"
        assert sent["json"] == {"username": "teststore", "password": FAKE["password"]}

        # Blank password keeps the saved one.
        kept = await client.put(URL, json={**FAKE, "mode": "sandbox", "password": ""}, headers=sa["headers"])
        assert kept.status_code == 200 and kept.json()["mode"] == "sandbox"
        db_session.expire_all()
        config = await get_shurjopay_config(db_session)
        assert config.password == FAKE["password"] and config.base_url == "https://sandbox.shurjopayment.com"

        reset = await client.delete(URL, headers=sa["headers"])
        assert reset.json()["source"] == "environment"
    finally:
        await client.delete(URL, headers=sa["headers"])


async def test_test_connection_reports_result_without_token(client, promote_role, monkeypatch):
    sa = await _super_admin(client, promote_role, "spcfgtest")

    async def accepted(url, **kwargs):
        return _Resp({"token": "secret-bearer-token", "store_id": 42})

    _fake_gateway(monkeypatch, accepted)
    ok = await client.post(f"{URL}/test", json=FAKE, headers=sa["headers"])
    assert ok.status_code == 200
    assert ok.json()["ok"] is True and ok.json()["store_id"] == 42
    assert "secret-bearer-token" not in ok.text

    async def rejected(url, **kwargs):
        return _Resp({"sp_code": "1064", "message": "Unauthorized"}, 401)

    _fake_gateway(monkeypatch, rejected)
    bad = await client.post(f"{URL}/test", json=FAKE, headers=sa["headers"])
    assert bad.json() == {"ok": False, "mode": "live", "message": "Unauthorized"}

    async def unreachable(url, **kwargs):
        raise httpx.ConnectError("boom")

    _fake_gateway(monkeypatch, unreachable)
    down = await client.post(f"{URL}/test", json=FAKE, headers=sa["headers"])
    assert down.json()["ok"] is False


async def test_config_validation_and_permissions(client, promote_role):
    sa = await _super_admin(client, promote_role, "spcfgvalid")
    try:
        assert (await client.put(URL, json={**FAKE, "mode": "https://evil.example"}, headers=sa["headers"])).status_code == 422
        assert (await client.put(URL, json={**FAKE, "prefix": "t-1"}, headers=sa["headers"])).status_code == 400
        # First save must include a password.
        assert (await client.put(URL, json={**FAKE, "password": None}, headers=sa["headers"])).status_code == 400
    finally:
        await client.delete(URL, headers=sa["headers"])

    admin = await register_and_login(client, "spcfgadmin")
    await promote_role(admin["user_id"], "ADMIN")
    assert (await client.get(URL, headers=admin["headers"])).status_code == 403
    assert (await client.put(URL, json=FAKE, headers=admin["headers"])).status_code == 403
    assert (await client.post(f"{URL}/test", json=FAKE, headers=admin["headers"])).status_code == 403
