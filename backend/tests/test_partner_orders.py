import json
import asyncio
import contextlib
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import select
from conftest import register_and_login, fund_wallet, create_test_product
import app.services.webhook_svc as webhook_svc_module
from app.models.partner_api import WebhookDeliveryLog
from app.models.wallet import Wallet, WalletType
from app.services.webhook_svc import retry_failed_webhooks, MAX_ATTEMPTS
from app.core.database import AsyncSessionLocal

pytestmark = pytest.mark.asyncio


@contextlib.contextmanager
def mock_webhook_http(status_code: int):
    """Mocks only webhook_svc's `httpx` name (not the global httpx module),
    so the test's own AsyncClient calls into the app are unaffected -
    patching httpx.AsyncClient.post directly intercepts every AsyncClient
    instance, including the ASGI test client itself."""
    mock_response = MagicMock()
    mock_response.status_code = status_code

    client_instance = AsyncMock()
    client_instance.__aenter__.return_value = client_instance
    client_instance.__aexit__.return_value = False
    client_instance.post = AsyncMock(return_value=mock_response)

    fake_httpx = MagicMock()
    fake_httpx.AsyncClient = MagicMock(return_value=client_instance)

    with patch.object(webhook_svc_module, "httpx", fake_httpx):
        yield client_instance.post


async def _make_partner(client, db_session, promote_role, suffix: str, webhook_url: str | None = None, webhook_secret: str | None = None):
    admin = await register_and_login(client, f"poadmin{suffix}")
    await promote_role(admin["user_id"], "SUPER_ADMIN")

    merchant_user = await register_and_login(client, f"pomerchant{suffix}")
    await client.post(
        "/api/v1/auth/apply-merchant",
        json={"business_name": f"Order Partner {suffix}", "contact_phone": "+1000000000"},
        headers=merchant_user["headers"],
    )
    queue = await client.get("/api/v1/admin/merchants/queue", headers=admin["headers"])
    entry = next(m for m in queue.json() if m["user_id"] == merchant_user["user_id"])
    await client.post(f"/api/v1/admin/merchants/{entry['id']}/approve", headers=admin["headers"])

    key_res = await client.post(f"/api/v1/admin/merchants/{entry['id']}/api-key", headers=admin["headers"])
    raw_key = key_res.json()["api_key"]

    if webhook_url:
        # No self-service endpoint yet (Phase D) - set directly via DB, same
        # way an admin stopgap would until partners can configure it themselves.
        from app.models.merchant import MerchantProfile
        m_res = await db_session.execute(select(MerchantProfile).where(MerchantProfile.id == entry["id"]))
        m = m_res.scalar_one()
        m.webhook_url = webhook_url
        m.webhook_secret = webhook_secret
        await db_session.commit()

    return {"X-API-Key": raw_key}, merchant_user["user_id"], entry["id"]


async def test_create_order_requires_sufficient_balance(client, db_session, promote_role):
    headers, user_id, _ = await _make_partner(client, db_session, promote_role, "1")
    product = await create_test_product(db_session, price=Decimal("50.0000"))

    res = await client.post("/api/v1/partner/orders", json={"product_id": product.id}, headers=headers)
    assert res.status_code == 400


async def test_create_order_provisions_in_background_and_polling_reflects_it(client, db_session, promote_role):
    headers, user_id, _ = await _make_partner(client, db_session, promote_role, "2")
    await fund_wallet(db_session, user_id, Decimal("100.0000"))
    product = await create_test_product(db_session, price=Decimal("10.0000"))

    res = await client.post(
        "/api/v1/partner/orders",
        json={"product_id": product.id, "customer_reference": "cust-42"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "PROCESSING"
    order_id = body["order_id"]

    # The background task (provisioning + webhook attempt) runs on the same
    # event loop as this test's client - give it a beat to finish.
    await asyncio.sleep(0.3)

    poll = await client.get(f"/api/v1/partner/orders/{order_id}", headers=headers)
    assert poll.status_code == 200
    poll_body = poll.json()
    assert poll_body["status"] == "COMPLETED"
    assert poll_body["iccid"] is not None
    assert poll_body["customer_reference"] == "cust-42"
    assert poll_body["is_mock_fallback"] is False

    async with AsyncSessionLocal() as verify_db:
        w_res = await verify_db.execute(select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.DEFAULT))
        wallet = w_res.scalar_one()
        assert Decimal(str(wallet.balance)) == Decimal("90.0000")


async def test_create_order_refunds_wallet_when_vivape_fails(client, db_session, promote_role, mock_vivape):
    """Partner orders go through the same shared provision_esim as the web
    UI - a VivaPe failure here must refund the merchant's DEFAULT wallet
    and mark the order FAILED, discoverable via polling."""
    mock_vivape.create_transaction.return_value = {"error": "Insufficient Balance.", "purchase_trx": []}

    headers, user_id, _ = await _make_partner(client, db_session, promote_role, "7")
    await fund_wallet(db_session, user_id, Decimal("100.0000"))
    product = await create_test_product(db_session, price=Decimal("10.0000"))

    res = await client.post("/api/v1/partner/orders", json={"product_id": product.id}, headers=headers)
    assert res.status_code == 200, res.text
    order_id = res.json()["order_id"]

    await asyncio.sleep(0.3)

    poll = await client.get(f"/api/v1/partner/orders/{order_id}", headers=headers)
    assert poll.status_code == 200
    poll_body = poll.json()
    assert poll_body["status"] == "FAILED"
    assert poll_body["iccid"] is None

    async with AsyncSessionLocal() as verify_db:
        w_res = await verify_db.execute(select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.DEFAULT))
        wallet = w_res.scalar_one()
        assert Decimal(str(wallet.balance)) == Decimal("100.0000")  # debited then refunded, net unchanged


async def test_create_order_credits_commission_wallet(client, db_session, promote_role):
    headers, user_id, _ = await _make_partner(client, db_session, promote_role, "3")
    await fund_wallet(db_session, user_id, Decimal("100.0000"))
    product = await create_test_product(db_session, price=Decimal("20.0000"))

    res = await client.post("/api/v1/partner/orders", json={"product_id": product.id}, headers=headers)
    assert res.status_code == 200
    await asyncio.sleep(0.3)

    async with AsyncSessionLocal() as verify_db:
        cw_res = await verify_db.execute(select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.COMMISSION))
        comm_wallet = cw_res.scalar_one()
        # Default flat merchant commission_rate_pct is 5.00%
        assert Decimal(str(comm_wallet.balance)) == Decimal("1.0000")


async def test_orders_are_scoped_to_the_owning_partner(client, db_session, promote_role):
    headers_a, user_id_a, _ = await _make_partner(client, db_session, promote_role, "4a")
    headers_b, _, _ = await _make_partner(client, db_session, promote_role, "4b")
    await fund_wallet(db_session, user_id_a, Decimal("100.0000"))
    product = await create_test_product(db_session, price=Decimal("5.0000"))

    res = await client.post("/api/v1/partner/orders", json={"product_id": product.id}, headers=headers_a)
    order_id = res.json()["order_id"]

    cross = await client.get(f"/api/v1/partner/orders/{order_id}", headers=headers_b)
    assert cross.status_code == 404

    own = await client.get(f"/api/v1/partner/orders/{order_id}", headers=headers_a)
    assert own.status_code == 200


async def test_webhook_delivered_with_valid_hmac_signature(client, db_session, promote_role):
    headers, user_id, merchant_id = await _make_partner(
        client, db_session, promote_role, "5",
        webhook_url="https://partner.example.com/webhooks/esim", webhook_secret="whsec_test_secret"
    )
    await fund_wallet(db_session, user_id, Decimal("100.0000"))
    product = await create_test_product(db_session, price=Decimal("10.0000"))

    with mock_webhook_http(200) as mock_post:
        res = await client.post(
            "/api/v1/partner/orders",
            json={"product_id": product.id, "customer_reference": "cust-99"},
            headers=headers,
        )
        assert res.status_code == 200
        await asyncio.sleep(0.3)

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args.kwargs
    assert call_kwargs["content"] is not None
    sent_body = call_kwargs["content"]
    sent_signature = call_kwargs["headers"]["X-Webhook-Signature"]

    import hmac, hashlib
    expected_signature = hmac.new(b"whsec_test_secret", sent_body, hashlib.sha256).hexdigest()
    assert sent_signature == expected_signature

    payload = json.loads(sent_body)
    assert payload["customer_reference"] == "cust-99"
    assert payload["status"] == "COMPLETED"
    assert payload["iccid"] is not None

    async with AsyncSessionLocal() as verify_db:
        log_res = await verify_db.execute(select(WebhookDeliveryLog).where(WebhookDeliveryLog.merchant_id == merchant_id))
        logs = log_res.scalars().all()
        assert len(logs) == 1
        assert logs[0].success is True
        assert logs[0].response_status == 200


async def test_retry_sweep_redelivers_failed_webhook_up_to_max_attempts(client, db_session, promote_role):
    headers, user_id, merchant_id = await _make_partner(
        client, db_session, promote_role, "6",
        webhook_url="https://partner.example.com/webhooks/esim", webhook_secret="whsec_test_secret"
    )
    await fund_wallet(db_session, user_id, Decimal("100.0000"))
    product = await create_test_product(db_session, price=Decimal("10.0000"))

    with mock_webhook_http(500):
        res = await client.post("/api/v1/partner/orders", json={"product_id": product.id}, headers=headers)
        assert res.status_code == 200
        await asyncio.sleep(0.3)

    async with AsyncSessionLocal() as verify_db:
        log_res = await verify_db.execute(select(WebhookDeliveryLog).where(WebhookDeliveryLog.merchant_id == merchant_id))
        assert len(log_res.scalars().all()) == 1  # first attempt, failed (500)

        with mock_webhook_http(500):
            result = await retry_failed_webhooks(verify_db)
        assert result["retried"] == 1

        log_res2 = await verify_db.execute(select(WebhookDeliveryLog).where(WebhookDeliveryLog.merchant_id == merchant_id))
        attempts = log_res2.scalars().all()
        assert len(attempts) == 2
        assert all(not a.success for a in attempts)

        # A third failed sweep should hit MAX_ATTEMPTS and stop retrying.
        with mock_webhook_http(500):
            result2 = await retry_failed_webhooks(verify_db)
        assert result2["retried"] == 1  # attempt #3 (== MAX_ATTEMPTS) still allowed

        with mock_webhook_http(500):
            result3 = await retry_failed_webhooks(verify_db)
        assert result3["retried"] == 0  # MAX_ATTEMPTS exhausted, no further retries

        log_res3 = await verify_db.execute(select(WebhookDeliveryLog).where(WebhookDeliveryLog.merchant_id == merchant_id))
        assert len(log_res3.scalars().all()) == MAX_ATTEMPTS
