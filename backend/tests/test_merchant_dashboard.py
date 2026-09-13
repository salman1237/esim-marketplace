import asyncio
import hashlib
import hmac
import json
import time
import pytest
from decimal import Decimal
from sqlalchemy import select

from conftest import register_and_login, fund_wallet, create_test_product, wait_for_order, partner_auth_headers
from test_partner_orders import mock_webhook_http
from app.core.database import AsyncSessionLocal
from app.models.wallet import LedgerRefType, WalletLedgerEntry

pytestmark = pytest.mark.asyncio


async def _approved_merchant(client, promote_role, suffix: str):
    sa = await register_and_login(client, f"mdsa{suffix}")
    await promote_role(sa["user_id"], "SUPER_ADMIN")
    merchant = await register_and_login(client, f"mdm{suffix}")
    res = await client.post(
        f"/api/v1/admin/users/{merchant['user_id']}/make-reseller",
        json={"business_name": f"Dash Travel {suffix}", "contact_phone": "+8801700000000"},
        headers=sa["headers"],
    )
    assert res.status_code == 200, res.text
    return merchant, res.json()["merchant_id"], sa


async def _buy_for_customer(client, merchant, product_id: str) -> dict:
    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product_id, "payment_method": "WALLET", "is_buy_for_user": True, "auto_create_user": True},
        headers=merchant["headers"],
    )
    assert res.status_code == 202, res.text
    return await wait_for_order(client, res.json()["id"], merchant["headers"])


async def _wait_partner_order(client, order_id: str, headers: dict, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        res = await client.get(f"/api/v1/partner/orders/{order_id}", headers=headers)
        if res.status_code == 200 and res.json()["status"] in ("COMPLETED", "FAILED"):
            return res.json()
        await asyncio.sleep(0.05)
    raise AssertionError(f"partner order {order_id} did not settle")


async def test_dashboard_requires_an_approved_merchant(client):
    user = await register_and_login(client, "mdplainuser")
    assert (await client.get("/api/v1/merchant/overview", headers=user["headers"])).status_code == 403

    await client.post(
        "/api/v1/auth/apply-merchant",
        json={"business_name": "Pending Co", "contact_phone": "+1000"},
        headers=user["headers"],
    )
    # Applied but not approved: still no dashboard, and /auth/me tells the
    # portal to show "under review" instead of the application form again.
    assert (await client.get("/api/v1/merchant/orders", headers=user["headers"])).status_code == 403
    me = await client.get("/api/v1/auth/me", headers=user["headers"])
    assert me.json()["merchant_profile"]["status"] == "PENDING"
    assert "rejection_reason" in me.json()["merchant_profile"]


async def test_overview_reports_balances_sales_and_success_rate(client, db_session, promote_role, mock_vivape):
    merchant, _, _ = await _approved_merchant(client, promote_role, "ov")
    await fund_wallet(db_session, merchant["user_id"], Decimal("100.0000"))
    product = await create_test_product(db_session, price=Decimal("10.0000"))

    for _ in range(2):
        assert (await _buy_for_customer(client, merchant, product.id))["status"] == "COMPLETED"
    mock_vivape.create_transaction.return_value = {"error": "Insufficient Balance.", "purchase_trx": []}
    assert (await _buy_for_customer(client, merchant, product.id))["status"] == "FAILED"

    res = await client.get("/api/v1/merchant/overview", headers=merchant["headers"])
    assert res.status_code == 200, res.text
    body = res.json()

    all_time = body["stats"]["all_time"]
    assert (all_time["orders"], all_time["completed"], all_time["failed"], all_time["in_progress"]) == (3, 2, 1, 0)
    assert all_time["volume_usd"] == "20.0000"
    # Both completed orders were placed below any volume tier: 5% of $10 each.
    assert all_time["commission_usd"] == "1.0000"
    assert all_time["success_rate_pct"] == 66.7
    assert body["stats"]["last_30_days"]["orders"] == 3

    # 3 x $10 charged, the failed one refunded.
    assert body["wallets"]["wallet_balance"] == "80.0000"
    assert body["wallets"]["commission_balance"] == "1.0000"
    assert body["business"]["name"] == "Dash Travel ov"
    assert body["commission"]["completed_volume_usd"] == "20.0000"
    assert len(body["recent_orders"]) == 3
    assert body["api"]["key_active"] is False


async def test_orders_separate_web_and_api_sales_and_expose_esim_details(client, db_session, promote_role):
    merchant, merchant_id, sa = await _approved_merchant(client, promote_role, "ord")
    await fund_wallet(db_session, merchant["user_id"], Decimal("100.0000"))
    product = await create_test_product(db_session, price=Decimal("5.0000"))

    web_order = await _buy_for_customer(client, merchant, product.id)

    key = await client.post(f"/api/v1/admin/merchants/{merchant_id}/api-key", headers=sa["headers"])
    partner_headers = await partner_auth_headers(client, key.json()["api_key"])
    api_res = await client.post(
        "/api/v1/partner/orders",
        json={"product_id": product.id, "customer_reference": "dash-ref-77"},
        headers=partner_headers,
    )
    api_order_id = api_res.json()["order_id"]
    await _wait_partner_order(client, api_order_id, partner_headers)

    api_only = (await client.get("/api/v1/merchant/orders?source=api", headers=merchant["headers"])).json()
    assert api_only["total"] == 1
    assert api_only["orders"][0]["source"] == "api"
    assert api_only["orders"][0]["customer_reference"] == "dash-ref-77"
    assert api_only["orders"][0]["customer"] is None

    web_only = (await client.get("/api/v1/merchant/orders?source=web", headers=merchant["headers"])).json()
    assert web_only["total"] == 1
    assert web_only["orders"][0]["order_id"] == web_order["id"]
    assert web_only["orders"][0]["customer"]["username"]

    found = (await client.get("/api/v1/merchant/orders?q=dash-ref-77", headers=merchant["headers"])).json()
    assert [o["order_id"] for o in found["orders"]] == [api_order_id]

    completed = (await client.get("/api/v1/merchant/orders?status=COMPLETED", headers=merchant["headers"])).json()
    assert completed["total"] == 2

    detail = await client.get(f"/api/v1/merchant/orders/{api_order_id}", headers=merchant["headers"])
    assert detail.status_code == 200
    assert detail.json()["status"] == "COMPLETED"
    assert detail.json()["lpa_string"].startswith("LPA:")
    assert detail.json()["install_links"]["ios"].startswith("https://esimsetup.apple.com/")
    assert detail.json()["webhook_deliveries"] == []

    other, _, _ = await _approved_merchant(client, promote_role, "ord2")
    assert (await client.get(f"/api/v1/merchant/orders/{api_order_id}", headers=other["headers"])).status_code == 404
    assert (await client.get("/api/v1/merchant/orders", headers=other["headers"])).json()["total"] == 0


async def test_commission_can_be_moved_into_the_main_wallet(client, db_session, promote_role):
    merchant, _, _ = await _approved_merchant(client, promote_role, "com")
    await fund_wallet(db_session, merchant["user_id"], Decimal("100.0000"))
    product = await create_test_product(db_session, price=Decimal("20.0000"))
    await _buy_for_customer(client, merchant, product.id)  # $20 charged, $1 commission

    url = "/api/v1/merchant/commission/transfer"
    assert (await client.post(url, json={"amount": "5"}, headers=merchant["headers"])).status_code == 400
    assert (await client.post(url, json={"amount": "0"}, headers=merchant["headers"])).status_code == 400
    assert (await client.post(url, json={"amount": "abc"}, headers=merchant["headers"])).status_code == 400

    part = await client.post(url, json={"amount": "0.4"}, headers=merchant["headers"])
    assert part.status_code == 200, part.text
    assert part.json() == {"transferred": "0.4000", "commission_balance": "0.6000", "wallet_balance": "80.4000"}

    rest = await client.post(url, json={}, headers=merchant["headers"])
    assert rest.status_code == 200, rest.text
    assert rest.json() == {"transferred": "0.6000", "commission_balance": "0.0000", "wallet_balance": "81.0000"}

    assert (await client.post(url, json={}, headers=merchant["headers"])).status_code == 400

    async with AsyncSessionLocal() as db:
        from app.models.wallet import Wallet
        wallet_ids = (await db.execute(
            select(Wallet.id).where(Wallet.user_id == merchant["user_id"])
        )).scalars().all()
        legs = (await db.execute(
            select(WalletLedgerEntry).where(
                WalletLedgerEntry.wallet_id.in_(wallet_ids),
                WalletLedgerEntry.reference_type == LedgerRefType.COMMISSION_TRANSFER,
            )
        )).scalars().all()
        assert len(legs) == 4  # two transfers, each a debit + a credit


async def test_merchant_manages_webhook_from_the_dashboard_and_sends_a_signed_test(client, db_session, promote_role):
    merchant, merchant_id, sa = await _approved_merchant(client, promote_role, "hook")
    headers = merchant["headers"]

    access = (await client.get("/api/v1/merchant/api-access", headers=headers)).json()
    assert access["key"]["active"] is False
    assert access["webhook"]["configured"] is False
    assert access["base_url"].endswith("/api/v1/partner")

    key = await client.post(f"/api/v1/admin/merchants/{merchant_id}/api-key", headers=sa["headers"])
    access = (await client.get("/api/v1/merchant/api-access", headers=headers)).json()
    assert access["key"]["active"] is True
    assert access["key"]["prefix"] == key.json()["key_prefix"]
    assert key.json()["api_key"] not in json.dumps(access)

    assert (await client.post("/api/v1/merchant/webhook-test", headers=headers)).status_code == 400
    for bad in ("http://partner.example.com/hook", "https://127.0.0.1/hook", "https://localhost/hook", "not a url"):
        res = await client.put("/api/v1/merchant/webhook-config", json={"webhook_url": bad}, headers=headers)
        assert res.status_code == 400, bad

    ok = await client.put(
        "/api/v1/merchant/webhook-config",
        json={"webhook_url": "https://partner.example.com/hooks/triptel"},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    secret = ok.json()["webhook_secret"]
    assert secret.startswith("whsec_")

    partner_headers = await partner_auth_headers(client, key.json()["api_key"])
    assert (await client.get("/api/v1/partner/me", headers=partner_headers)).json()["webhook_configured"] is True

    with mock_webhook_http(200) as mock_post:
        test = await client.post("/api/v1/merchant/webhook-test", headers=headers)
    assert test.status_code == 200, test.text
    assert test.json() == {"delivered": True, "status_code": 200, "error": None}
    sent = mock_post.call_args.kwargs
    assert sent["headers"]["X-Webhook-Event"] == "webhook.test"
    assert sent["headers"]["X-Webhook-Signature"] == hmac.new(secret.encode(), sent["content"], hashlib.sha256).hexdigest()
    assert json.loads(sent["content"])["event"] == "webhook.test"

    # A real API order's delivery then shows up in the dashboard.
    await fund_wallet(db_session, merchant["user_id"], Decimal("50.0000"))
    product = await create_test_product(db_session, price=Decimal("5.0000"))
    with mock_webhook_http(200) as mock_post:
        res = await client.post("/api/v1/partner/orders", json={"product_id": product.id}, headers=partner_headers)
        await _wait_partner_order(client, res.json()["order_id"], partner_headers)
        await asyncio.sleep(0.3)
    assert mock_post.call_args.kwargs["headers"]["X-Webhook-Event"] == "order.updated"

    access = (await client.get("/api/v1/merchant/api-access", headers=headers)).json()
    assert access["recent_deliveries"][0]["success"] is True
    assert access["recent_deliveries"][0]["order_no"].startswith("PTR-")

    cleared = await client.put("/api/v1/merchant/webhook-config", json={"webhook_url": None}, headers=headers)
    assert cleared.json() == {"webhook_url": None, "webhook_secret": None}
    assert (await client.get("/api/v1/merchant/api-access", headers=headers)).json()["webhook"]["configured"] is False
