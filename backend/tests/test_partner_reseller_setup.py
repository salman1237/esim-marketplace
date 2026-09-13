import asyncio
import time
import pytest
from decimal import Decimal
from sqlalchemy import select

from conftest import register_and_login, fund_wallet, create_test_product, partner_auth_headers
from test_partner_orders import _make_partner, mock_webhook_http
from app.core.database import AsyncSessionLocal
from app.models.merchant import MerchantProfile, MerchantStatus
from app.models.partner_api import WebhookDeliveryLog
from app.models.user import User, UserRole
from app.models.wallet import Wallet, WalletType
from app.services.webhook_svc import retry_failed_webhooks

pytestmark = pytest.mark.asyncio


async def _wait_for_terminal(client, order_id: str, headers: dict, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        res = await client.get(f"/api/v1/partner/orders/{order_id}", headers=headers)
        if res.status_code == 200 and res.json()["status"] in ("COMPLETED", "FAILED"):
            return res.json()
        await asyncio.sleep(0.05)
    raise AssertionError(f"order {order_id} did not settle within {timeout}s")


async def _default_balance(user_id: str) -> Decimal:
    async with AsyncSessionLocal() as db:
        w = (await db.execute(
            select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.DEFAULT)
        )).scalar_one()
        return Decimal(str(w.balance))


# --- Onboarding an existing account as a reseller -------------------------


async def test_super_admin_makes_existing_user_a_reseller_who_can_then_get_api_access(client, promote_role):
    """A partner we onboard ourselves (not via the /reseller application)
    must end up exactly like an approved applicant: MERCHANT role,
    APPROVED profile, and able to be issued a working Partner API key."""
    sa = await register_and_login(client, "resellersetupsa")
    await promote_role(sa["user_id"], "SUPER_ADMIN")
    target = await register_and_login(client, "ovigotest")

    res = await client.post(
        f"/api/v1/admin/users/{target['user_id']}/make-reseller",
        json={"business_name": "Ovigo Travel", "contact_phone": "+8801700000000", "commission_rate_pct": 7.5},
        headers=sa["headers"],
    )
    assert res.status_code == 200, res.text
    merchant_id = res.json()["merchant_id"]

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == target["user_id"]))).scalar_one()
        merchant = (await db.execute(select(MerchantProfile).where(MerchantProfile.id == merchant_id))).scalar_one()
        assert user.role == UserRole.MERCHANT
        assert merchant.status == MerchantStatus.APPROVED
        assert Decimal(str(merchant.commission_rate_pct)) == Decimal("7.50")
        commission_wallet = (await db.execute(
            select(Wallet).where(Wallet.user_id == target["user_id"], Wallet.wallet_type == WalletType.COMMISSION)
        )).scalar_one_or_none()
        assert commission_wallet is not None

    key_res = await client.post(f"/api/v1/admin/merchants/{merchant_id}/api-key", headers=sa["headers"])
    assert key_res.status_code == 200, key_res.text
    partner_headers = await partner_auth_headers(client, key_res.json()["api_key"])
    me = await client.get("/api/v1/partner/me", headers=partner_headers)
    assert me.status_code == 200
    assert me.json()["business_name"] == "Ovigo Travel"
    assert "commission_balance" in me.json()

    again = await client.post(
        f"/api/v1/admin/users/{target['user_id']}/make-reseller",
        json={"business_name": "Ovigo Travel", "contact_phone": "+8801700000000"},
        headers=sa["headers"],
    )
    assert again.status_code == 400


async def test_make_reseller_approves_a_pending_application_in_place(client, promote_role):
    sa = await register_and_login(client, "resellerpendingsa")
    await promote_role(sa["user_id"], "SUPER_ADMIN")
    applicant = await register_and_login(client, "pendingapplicant")
    await client.post(
        "/api/v1/auth/apply-merchant",
        json={"business_name": "Old Name", "contact_phone": "+1000"},
        headers=applicant["headers"],
    )

    res = await client.post(
        f"/api/v1/admin/users/{applicant['user_id']}/make-reseller",
        json={"business_name": "New Name", "contact_phone": "+2000"},
        headers=sa["headers"],
    )
    assert res.status_code == 200, res.text

    async with AsyncSessionLocal() as db:
        profiles = (await db.execute(
            select(MerchantProfile).where(MerchantProfile.user_id == applicant["user_id"])
        )).scalars().all()
        assert len(profiles) == 1
        assert profiles[0].status == MerchantStatus.APPROVED
        assert profiles[0].business_name == "New Name"


async def test_make_reseller_is_super_admin_only_and_never_touches_staff(client, promote_role):
    admin = await register_and_login(client, "plainadminreseller")
    await promote_role(admin["user_id"], "ADMIN")
    target = await register_and_login(client, "resellertargetx")
    denied = await client.post(
        f"/api/v1/admin/users/{target['user_id']}/make-reseller",
        json={"business_name": "X", "contact_phone": "1"},
        headers=admin["headers"],
    )
    assert denied.status_code == 403

    sa = await register_and_login(client, "resellerstaffsa")
    await promote_role(sa["user_id"], "SUPER_ADMIN")
    staff = await client.post(
        f"/api/v1/admin/users/{admin['user_id']}/make-reseller",
        json={"business_name": "X", "contact_phone": "1"},
        headers=sa["headers"],
    )
    assert staff.status_code == 400


async def test_admin_user_search_finds_accounts_by_username(client, promote_role):
    sa = await register_and_login(client, "usersearchsa")
    await promote_role(sa["user_id"], "SUPER_ADMIN")
    await register_and_login(client, "findmeuniquezz")

    res = await client.get("/api/v1/admin/users?q=findmeunique", headers=sa["headers"])
    assert res.status_code == 200
    usernames = [u["username"] for u in res.json()]
    # register_and_login suffixes usernames, and the shared test DB keeps
    # earlier runs' rows - so: found, and nothing unrelated came back.
    assert usernames
    assert all(name.startswith("findmeuniquezz") for name in usernames)


# --- Partner API: safe retries, richer payloads, reconciliation -----------


async def test_retrying_an_order_with_the_same_customer_reference_never_charges_twice(client, db_session, promote_role):
    """A partner whose POST /orders response is lost to a timeout will
    retry. The retry must return the original order, not buy a second
    eSIM on their wallet."""
    headers, user_id, _ = await _make_partner(client, db_session, promote_role, "idem1")
    await fund_wallet(db_session, user_id, Decimal("100.0000"))
    product = await create_test_product(db_session, price=Decimal("10.0000"))
    body = {"product_id": product.id, "customer_reference": "ovigo-order-123"}

    first = await client.post("/api/v1/partner/orders", json=body, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["idempotent_replay"] is False

    second = await client.post("/api/v1/partner/orders", json=body, headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["idempotent_replay"] is True
    assert second.json()["order_id"] == first.json()["order_id"]

    await _wait_for_terminal(client, first.json()["order_id"], headers)
    assert await _default_balance(user_id) == Decimal("90.0000")


async def test_reusing_a_customer_reference_for_a_different_product_is_rejected(client, db_session, promote_role):
    headers, user_id, _ = await _make_partner(client, db_session, promote_role, "idem2")
    await fund_wallet(db_session, user_id, Decimal("100.0000"))
    product_a = await create_test_product(db_session, price=Decimal("5.0000"))
    product_b = await create_test_product(db_session, price=Decimal("6.0000"))

    first = await client.post(
        "/api/v1/partner/orders", json={"product_id": product_a.id, "customer_reference": "ref-x"}, headers=headers
    )
    assert first.status_code == 200
    clash = await client.post(
        "/api/v1/partner/orders", json={"product_id": product_b.id, "customer_reference": "ref-x"}, headers=headers
    )
    assert clash.status_code == 409

    await _wait_for_terminal(client, first.json()["order_id"], headers)
    assert await _default_balance(user_id) == Decimal("95.0000")


async def test_completed_order_carries_product_amount_and_install_links(client, db_session, promote_role):
    headers, user_id, _ = await _make_partner(client, db_session, promote_role, "rich1")
    await fund_wallet(db_session, user_id, Decimal("100.0000"))
    product = await create_test_product(db_session, price=Decimal("12.5000"))

    res = await client.post("/api/v1/partner/orders", json={"product_id": product.id}, headers=headers)
    assert res.status_code == 200
    created = res.json()
    assert created["status"] == "PROCESSING"
    assert created["product"]["id"] == product.id
    assert created["amount"] == "12.5000"

    order = await _wait_for_terminal(client, created["order_id"], headers)
    assert order["status"] == "COMPLETED"
    assert order["product"]["country_iso2"]
    assert order["lpa_string"].startswith("LPA:")
    assert order["smdp_address"]
    assert order["matching_id"]
    assert order["install_links"]["ios"].startswith("https://esimsetup.apple.com/")
    assert order["install_links"]["android"].startswith("https://esimsetup.android.com/")


async def test_order_list_is_filterable_and_scoped_to_the_partner(client, db_session, promote_role):
    headers_a, user_a, _ = await _make_partner(client, db_session, promote_role, "list1a")
    headers_b, user_b, _ = await _make_partner(client, db_session, promote_role, "list1b")
    await fund_wallet(db_session, user_a, Decimal("100.0000"))
    await fund_wallet(db_session, user_b, Decimal("100.0000"))
    product = await create_test_product(db_session, price=Decimal("5.0000"))

    for ref in ("list-ref-1", "list-ref-2"):
        r = await client.post("/api/v1/partner/orders", json={"product_id": product.id, "customer_reference": ref}, headers=headers_a)
        await _wait_for_terminal(client, r.json()["order_id"], headers_a)
    rb = await client.post("/api/v1/partner/orders", json={"product_id": product.id}, headers=headers_b)
    await _wait_for_terminal(client, rb.json()["order_id"], headers_b)

    everything = await client.get("/api/v1/partner/orders", headers=headers_a)
    assert everything.status_code == 200
    assert everything.json()["total"] == 2

    one = await client.get("/api/v1/partner/orders?customer_reference=list-ref-2", headers=headers_a)
    assert [o["customer_reference"] for o in one.json()["orders"]] == ["list-ref-2"]

    others = await client.get("/api/v1/partner/orders?customer_reference=list-ref-2", headers=headers_b)
    assert others.json()["total"] == 0


async def test_failed_order_webhook_is_retried_too(client, db_session, promote_role, mock_vivape):
    """A partner never told about a failure keeps waiting for an eSIM that
    won't come - failed orders get the same redelivery as completed ones."""
    mock_vivape.create_transaction.return_value = {"error": "Insufficient Balance.", "purchase_trx": []}
    headers, user_id, merchant_id = await _make_partner(
        client, db_session, promote_role, "failhook",
        webhook_url="https://partner.example.com/webhooks/esim", webhook_secret="whsec_test_secret",
    )
    await fund_wallet(db_session, user_id, Decimal("100.0000"))
    product = await create_test_product(db_session, price=Decimal("10.0000"))

    with mock_webhook_http(500):
        res = await client.post("/api/v1/partner/orders", json={"product_id": product.id}, headers=headers)
        order = await _wait_for_terminal(client, res.json()["order_id"], headers)
        await asyncio.sleep(0.2)
    assert order["status"] == "FAILED"

    async with AsyncSessionLocal() as db:
        with mock_webhook_http(200):
            await retry_failed_webhooks(db)
        logs = (await db.execute(
            select(WebhookDeliveryLog).where(WebhookDeliveryLog.merchant_id == merchant_id)
        )).scalars().all()
        assert len(logs) == 2
        assert any(log.success for log in logs)
