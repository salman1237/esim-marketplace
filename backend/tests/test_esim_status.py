"""Live eSIM status: caching, access, and the activation-based validity fix.

The correctness point worth guarding hardest: an eSIM's validity starts when
the customer installs it, not when they pay. Computing expiry at purchase made
a 3-day eSIM bought a month before a trip look expired on arrival.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.esim_telemetry import ESIMTelemetry
from app.models.order import ESIMProfile
from conftest import create_test_product, fund_wallet, register_and_login, wait_for_order

pytestmark = pytest.mark.asyncio

# Shapes copied from real VivaPe responses for transaction 60318 (activated,
# installed on a Galaxy A55) and 60320 (delivered, never installed).
ACTIVE_USAGE = {
    "success": True,
    "cid": "89851000000012470842",
    "total_bytes": 174546473,
    "total_mb": 166.46,
    "total_gb": 0.16,
    "formatted_usage": "166.46 MB",
    "start_date": "2026-09-26 18:47:19",
    "end_date": "2026-09-29 18:46:59",
    "esim_status_code": 1,
    "esim_status_text": "Active",
    "daily_breakdown": [
        {"usageDate": "20260927", "mcc": "470", "code": "BD", "enus": "Bangladesh",
         "usage": "174546473", "mnc": "47003", "mnoname": "Banglalink"},
    ],
}
ACTIVE_DEVICE = {
    "success": True,
    "is_installed": True,
    "device_model": "Galaxy A55",
    "eid": "89033023525100100100039068590386",
    "cid": "89851000000012470842",
    "card_status": 1,
    "coupon_status": 2,
    "history": [
        {"event_id": 6, "event_name": "Profile Enabled", "date": "2026-09-27 01:40:11", "status": "Executed-Success"},
        {"event_id": 3, "event_name": "Profile Download Notice", "date": "2026-09-27 01:39:30", "status": "Executed-Success"},
    ],
}
# Never installed: VivaPe reports a long coupon window, NOT the plan validity.
FRESH_USAGE = {
    "success": True,
    "cid": "89851000000012484792",
    "total_bytes": 0,
    "total_mb": 0,
    "total_gb": 0,
    "formatted_usage": "0 MB",
    "start_date": "2026-09-27 16:30:15",
    "end_date": "2027-03-26 15:59:59",
    "esim_status_code": 0,
    "esim_status_text": "Unknown",
    "daily_breakdown": [],
}
FRESH_DEVICE = {
    "success": True, "is_installed": False, "device_model": "Not Yet Installed",
    "eid": None, "cid": "89851000000012484792", "card_status": 0, "coupon_status": 2, "history": [],
}


def _vivape(usage, device):
    """Patches only the two telemetry calls, leaving the autouse mock_vivape
    provisioning fixture intact."""
    import app.services.esim_telemetry_svc as svc
    return (
        patch.object(svc.VivaPeAdapter, "get_esim_usage", AsyncMock(return_value=usage)),
        patch.object(svc.VivaPeAdapter, "get_esim_device_info", AsyncMock(return_value=device)),
    )


async def _buy(client, db_session, price="10.00", data_gb="3.0", validity=3):
    """A delivered eSIM belonging to a fresh customer."""
    user = await register_and_login(client, "status")
    await fund_wallet(db_session, user["user_id"], Decimal("100"))
    product = await create_test_product(db_session, price=Decimal(price))
    product.data_amount_gb = Decimal(data_gb)
    product.validity_days = validity
    await db_session.commit()

    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET"},
        headers=user["headers"],
    )
    assert res.status_code == 202, res.text
    settled = await wait_for_order(client, res.json()["id"], user["headers"])
    assert settled["status"] == "COMPLETED"

    profile = (await db_session.execute(
        select(ESIMProfile).where(ESIMProfile.order_id == res.json()["id"])
    )).scalar_one()
    user["esim_id"] = profile.id
    user["order_id"] = res.json()["id"]
    user["product"] = product
    return user


async def test_a_new_esim_has_no_expiry_until_it_is_installed(client, db_session):
    """The bug this fixes: a 3-day eSIM bought before a trip used to be dated
    from the purchase, so it looked expired on arrival."""
    user = await _buy(client, db_session, validity=3)
    profile = (await db_session.execute(
        select(ESIMProfile).where(ESIMProfile.id == user["esim_id"])
    )).scalar_one()
    await db_session.refresh(profile)
    assert profile.expires_at is None
    assert profile.activated_at is None

    listed = (await client.get("/api/v1/orders/my-esims", headers=user["headers"])).json()
    mine = next(e for e in listed if e["id"] == user["esim_id"])
    assert mine["expires_at"] is None
    assert mine["activated_at"] is None
    assert mine["validity_days"] == 3


async def test_status_of_an_uninstalled_esim_says_validity_starts_on_install(client, db_session):
    user = await _buy(client, db_session, validity=3)
    usage_patch, device_patch = _vivape(FRESH_USAGE, FRESH_DEVICE)
    with usage_patch, device_patch:
        res = await client.get(f"/api/v1/esims/{user['esim_id']}/status", headers=user["headers"])
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["status"]["is_installed"] is False
    assert body["status"]["is_activated"] is False
    assert body["status"]["label"] == "Not installed yet"
    # VivaPe's six-month coupon window must NOT be shown as the plan's expiry.
    assert body["validity"]["expires_at"] is None
    assert body["validity"]["activated_at"] is None
    assert "starts when you install" in body["validity"]["note"]

    profile = (await db_session.execute(
        select(ESIMProfile).where(ESIMProfile.id == user["esim_id"])
    )).scalar_one()
    await db_session.refresh(profile)
    assert profile.expires_at is None


async def test_installing_it_sets_the_real_validity_window(client, db_session):
    user = await _buy(client, db_session, validity=3)
    usage_patch, device_patch = _vivape(ACTIVE_USAGE, ACTIVE_DEVICE)
    with usage_patch, device_patch:
        res = await client.get(f"/api/v1/esims/{user['esim_id']}/status", headers=user["headers"])
    body = res.json()

    assert body["status"]["is_installed"] is True
    assert body["status"]["is_activated"] is True
    assert body["status"]["label"] == "Active"
    assert body["status"]["device_model"] == "Galaxy A55"
    assert body["validity"]["note"] is None

    activated = datetime.fromisoformat(body["validity"]["activated_at"])
    expires = datetime.fromisoformat(body["validity"]["expires_at"])
    assert activated == datetime(2026, 9, 26, 18, 47, 19, tzinfo=timezone.utc)
    # Three days from activation, not from purchase.
    assert expires - activated == timedelta(days=3) - timedelta(seconds=20)

    # And it is promoted onto the profile, so lists and the print sheet agree.
    profile = (await db_session.execute(
        select(ESIMProfile).where(ESIMProfile.id == user["esim_id"])
    )).scalar_one()
    await db_session.refresh(profile)
    assert profile.activated_at == activated
    assert profile.expires_at == expires


async def test_usage_reports_remaining_data_against_the_plan(client, db_session):
    user = await _buy(client, db_session, data_gb="3.0")
    usage_patch, device_patch = _vivape(ACTIVE_USAGE, ACTIVE_DEVICE)
    with usage_patch, device_patch:
        body = (await client.get(f"/api/v1/esims/{user['esim_id']}/status", headers=user["headers"])).json()

    usage = body["usage"]
    assert Decimal(usage["used_mb"]) == Decimal("166.46")
    assert usage["formatted"] == "166.46 MB"
    # 3 GB = 3072 MB, so 2905.54 MB left - VivaPe doesn't compute this, we do.
    assert Decimal(usage["allowance_mb"]) == Decimal("3072.00")
    assert Decimal(usage["remaining_mb"]) == Decimal("2905.54")
    assert usage["remaining_formatted"] == "2.84 GB"
    assert usage["used_pct"] == pytest.approx(5.4, abs=0.1)
    assert usage["is_unlimited"] is False

    assert body["daily_breakdown"][0]["mnoname"] == "Banglalink"
    assert [h["event_name"] for h in body["history"]] == ["Profile Enabled", "Profile Download Notice"]


async def test_unlimited_plans_report_no_remaining_figure(client, db_session):
    user = await register_and_login(client, "status")
    await fund_wallet(db_session, user["user_id"], Decimal("100"))
    product = await create_test_product(db_session, price=Decimal("10.00"))
    product.is_unlimited = True
    await db_session.commit()
    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET"},
        headers=user["headers"],
    )
    await wait_for_order(client, res.json()["id"], user["headers"])
    profile = (await db_session.execute(
        select(ESIMProfile).where(ESIMProfile.order_id == res.json()["id"])
    )).scalar_one()

    usage_patch, device_patch = _vivape(ACTIVE_USAGE, ACTIVE_DEVICE)
    with usage_patch, device_patch:
        body = (await client.get(f"/api/v1/esims/{profile.id}/status", headers=user["headers"])).json()

    assert body["usage"]["is_unlimited"] is True
    # No allowance means no progress bar and no misleading "100% used".
    assert body["usage"]["allowance_mb"] is None
    assert body["usage"]["remaining_mb"] is None
    assert body["usage"]["used_pct"] is None


async def test_the_snapshot_is_cached_and_refresh_forces_a_new_poll(client, db_session):
    user = await _buy(client, db_session)
    import app.services.esim_telemetry_svc as svc

    usage_mock = AsyncMock(return_value=ACTIVE_USAGE)
    device_mock = AsyncMock(return_value=ACTIVE_DEVICE)
    with patch.object(svc.VivaPeAdapter, "get_esim_usage", usage_mock), \
         patch.object(svc.VivaPeAdapter, "get_esim_device_info", device_mock):
        await client.get(f"/api/v1/esims/{user['esim_id']}/status", headers=user["headers"])
        assert usage_mock.await_count == 1
        # Second view inside the TTL is served from the cache.
        await client.get(f"/api/v1/esims/{user['esim_id']}/status", headers=user["headers"])
        assert usage_mock.await_count == 1

        # A forced refresh asks VivaPe to poll the carrier...
        forced = await client.post(f"/api/v1/esims/{user['esim_id']}/refresh", headers=user["headers"])
        assert forced.status_code == 200, forced.text
        assert usage_mock.await_count == 2
        assert usage_mock.await_args.kwargs.get("refresh") is True

        # ...but a second immediate press is absorbed by the cooldown.
        await client.post(f"/api/v1/esims/{user['esim_id']}/refresh", headers=user["headers"])
        assert usage_mock.await_count == 2

    row = (await db_session.execute(
        select(ESIMTelemetry).where(ESIMTelemetry.esim_profile_id == user["esim_id"])
    )).scalar_one()
    await db_session.refresh(row)
    assert row.fetch_error is None
    assert row.device_model == "Galaxy A55"


async def test_a_supplier_outage_keeps_the_last_snapshot(client, db_session):
    """The moment VivaPe is down is exactly when someone is asking about an
    eSIM, so the page must still show what we last knew."""
    user = await _buy(client, db_session)
    import app.services.esim_telemetry_svc as svc

    usage_patch, device_patch = _vivape(ACTIVE_USAGE, ACTIVE_DEVICE)
    with usage_patch, device_patch:
        await client.get(f"/api/v1/esims/{user['esim_id']}/status", headers=user["headers"])

    with patch.object(svc.VivaPeAdapter, "get_esim_usage", AsyncMock(side_effect=Exception("VivaPe down"))), \
         patch.object(svc.VivaPeAdapter, "get_esim_device_info", AsyncMock(side_effect=Exception("VivaPe down"))):
        res = await client.post(f"/api/v1/esims/{user['esim_id']}/refresh", headers=user["headers"])

    assert res.status_code == 200, res.text
    body = res.json()
    # Still the last known numbers, with the failure reported alongside.
    assert Decimal(body["usage"]["used_mb"]) == Decimal("166.46")
    assert body["status"]["device_model"] == "Galaxy A55"
    assert "VivaPe down" in body["telemetry"]["error"]


async def test_first_view_during_an_outage_degrades_without_failing(client, db_session):
    user = await _buy(client, db_session)
    import app.services.esim_telemetry_svc as svc

    with patch.object(svc.VivaPeAdapter, "get_esim_usage", AsyncMock(side_effect=Exception("timeout"))), \
         patch.object(svc.VivaPeAdapter, "get_esim_device_info", AsyncMock(side_effect=Exception("timeout"))):
        res = await client.get(f"/api/v1/esims/{user['esim_id']}/status", headers=user["headers"])

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["telemetry"]["error"]
    assert body["status"]["label"] == "Not installed yet"
    # The install details come from our own database, so they still work -
    # which is the part a stuck customer actually needs.
    assert body["lpa_string"]
    assert body["iccid"]


async def test_only_the_owner_buyer_or_staff_can_see_it(client, db_session, promote_role):
    user = await _buy(client, db_session)
    stranger = await register_and_login(client, "statusother")

    usage_patch, device_patch = _vivape(FRESH_USAGE, FRESH_DEVICE)
    with usage_patch, device_patch:
        # A stranger gets the same 404 as a nonexistent id.
        assert (await client.get(
            f"/api/v1/esims/{user['esim_id']}/status", headers=stranger["headers"]
        )).status_code == 404
        assert (await client.post(
            f"/api/v1/esims/{user['esim_id']}/refresh", headers=stranger["headers"]
        )).status_code == 404

        # Staff can, for support.
        admin = await register_and_login(client, "statusadmin")
        await promote_role(admin["user_id"], "ADMIN")
        assert (await client.get(
            f"/api/v1/esims/{user['esim_id']}/status", headers=admin["headers"]
        )).status_code == 200

    # And it needs a login at all.
    assert (await client.get(f"/api/v1/esims/{user['esim_id']}/status")).status_code == 401


async def test_a_merchants_customer_esim_shows_live_status_on_the_order(client, db_session, promote_role):
    from app.models.merchant import MerchantProfile, MerchantStatus

    merchant = await register_and_login(client, "statusmerchant")
    await promote_role(merchant["user_id"], "MERCHANT")
    db_session.add(MerchantProfile(
        user_id=merchant["user_id"], business_name="Status Tours", contact_phone="+8801700000000",
        status=MerchantStatus.APPROVED, commission_rate_pct=Decimal("5.00"),
    ))
    await db_session.commit()
    await fund_wallet(db_session, merchant["user_id"], Decimal("100"))

    customer = await register_and_login(client, "statuscust")
    product = await create_test_product(db_session, price=Decimal("10.00"))
    res = await client.post(
        "/api/v1/orders/checkout",
        json={
            "product_id": product.id, "payment_method": "WALLET",
            "is_buy_for_user": True, "beneficiary_email": customer["email"],
        },
        headers=merchant["headers"],
    )
    order_id = res.json()["id"]
    await wait_for_order(client, order_id, merchant["headers"])

    usage_patch, device_patch = _vivape(ACTIVE_USAGE, ACTIVE_DEVICE)
    with usage_patch, device_patch:
        detail = await client.get(f"/api/v1/merchant/orders/{order_id}", headers=merchant["headers"])
    assert detail.status_code == 200, detail.text
    live = detail.json()["live_status"]
    assert live["status"]["device_model"] == "Galaxy A55"
    assert Decimal(live["usage"]["used_mb"]) == Decimal("166.46")


async def test_admin_orders_carry_the_esim_id_for_support_lookups(client, db_session, promote_role):
    user = await _buy(client, db_session)
    admin = await register_and_login(client, "statusadmin2")
    await promote_role(admin["user_id"], "SUPER_ADMIN")

    orders = (await client.get("/api/v1/admin/orders", headers=admin["headers"])).json()
    row = next(o for o in orders if o["id"] == user["order_id"])
    assert row["esim_id"] == user["esim_id"]
    assert row["activated_at"] is None


async def test_overview_counts_only_checked_esims_as_not_installed(client, db_session, promote_role):
    """The count must never inflate itself with eSIMs nobody has looked at."""
    user = await _buy(client, db_session)
    admin = await register_and_login(client, "statusadmin3")
    await promote_role(admin["user_id"], "SUPER_ADMIN")

    before = (await client.get("/api/v1/admin/dashboard?days=30", headers=admin["headers"])).json()
    assert "delivered_not_installed" in before["attention"]
    baseline = before["attention"]["delivered_not_installed"]

    usage_patch, device_patch = _vivape(FRESH_USAGE, FRESH_DEVICE)
    with usage_patch, device_patch:
        await client.get(f"/api/v1/esims/{user['esim_id']}/status", headers=user["headers"])

    # Checked, not installed - but delivered seconds ago, so not yet a concern.
    mid = (await client.get("/api/v1/admin/dashboard?days=30", headers=admin["headers"])).json()
    assert mid["attention"]["delivered_not_installed"] == baseline

    # Age it past the 48h threshold.
    profile = (await db_session.execute(
        select(ESIMProfile).where(ESIMProfile.id == user["esim_id"])
    )).scalar_one()
    profile.created_at = datetime.now(timezone.utc) - timedelta(hours=72)
    await db_session.commit()

    after = (await client.get("/api/v1/admin/dashboard?days=30", headers=admin["headers"])).json()
    assert after["attention"]["delivered_not_installed"] == baseline + 1


async def test_supplier_account_balance_is_reported_to_admins(client, db_session, promote_role):
    import app.api.v1.admin as admin_module

    admin = await register_and_login(client, "supplieradmin")
    await promote_role(admin["user_id"], "SUPER_ADMIN")
    admin_module._SUPPLIER_BALANCE_CACHE.update(at=0.0, value=None)

    profile_response = {
        "success": True,
        "data": {
            "id": 1622, "name": "Campus365 Seller", "email": "esimseller@campus365.pro",
            "vivape_id": "VPMR1622", "user_type": "Merchant",
            "balance": 143.14757575758, "currency": "EUR",
            "wallets": [
                {"type": "Prepaid", "balance": 143.14757575758, "currency": "EUR", "status": "Active"},
                {"type": "Postpaid", "balance": 0, "currency": "EUR", "status": "Active"},
            ],
        },
    }
    with patch.object(admin_module.VivaPeAdapter, "get_account_profile", AsyncMock(return_value=profile_response)):
        res = await client.get("/api/v1/admin/supplier/account", headers=admin["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["balance"] == "143.15"
    assert body["currency"] == "EUR"
    assert body["low_balance"] is False
    assert body["supplier_id"] == "VPMR1622"
    assert [w["type"] for w in body["wallets"]] == ["Prepaid", "Postpaid"]

    # A balance that can only cover a couple of eSIMs is flagged.
    admin_module._SUPPLIER_BALANCE_CACHE.update(at=0.0, value=None)
    broke = {"success": True, "data": {**profile_response["data"], "balance": 4.20, "wallets": []}}
    with patch.object(admin_module.VivaPeAdapter, "get_account_profile", AsyncMock(return_value=broke)):
        res = await client.get("/api/v1/admin/supplier/account", headers=admin["headers"])
    assert res.json()["low_balance"] is True

    user = await register_and_login(client, "supplieruser")
    assert (await client.get("/api/v1/admin/supplier/account", headers=user["headers"])).status_code == 403


async def test_supplier_outage_falls_back_to_the_cached_balance(client, db_session, promote_role):
    import app.api.v1.admin as admin_module

    admin = await register_and_login(client, "supplieradmin2")
    await promote_role(admin["user_id"], "SUPER_ADMIN")
    admin_module._SUPPLIER_BALANCE_CACHE.update(at=0.0, value=None)

    good = {"success": True, "data": {"email": "a@b.c", "balance": 50, "currency": "EUR", "wallets": []}}
    with patch.object(admin_module.VivaPeAdapter, "get_account_profile", AsyncMock(return_value=good)):
        await client.get("/api/v1/admin/supplier/account", headers=admin["headers"])

    with patch.object(admin_module.VivaPeAdapter, "get_account_profile", AsyncMock(side_effect=Exception("down"))):
        res = await client.get("/api/v1/admin/supplier/account?refresh=true", headers=admin["headers"])
    assert res.status_code == 200
    assert res.json()["balance"] == "50.00"
    assert res.json()["cached"] is True
    assert "down" in res.json()["error"]


async def test_the_delivery_email_carries_a_tracking_link(client, db_session):
    """The customer may have no account (a merchant can buy for them), so the
    link in the email is how they follow their own usage."""
    import app.services.order_fulfilment as fulfilment

    sent = {}

    async def fake_send(db, to_email, order_no, product_title, iccid, lpa_string, **kwargs):
        sent.update(to=to_email, order_no=order_no, **kwargs)

    with patch.object(fulfilment.EmailService, "send_order_confirmation", AsyncMock(side_effect=fake_send)):
        user = await _buy(client, db_session)

    assert sent["status_url"], "no tracking link was passed to the delivery email"
    profile = (await db_session.execute(
        select(ESIMProfile).where(ESIMProfile.id == user["esim_id"])
    )).scalar_one()
    await db_session.refresh(profile)
    assert profile.share_token
    # 128 bits of hex, not the profile id - so the link can't be walked the way
    # VivaPe's sequential status ids can.
    assert len(profile.share_token) == 32
    assert profile.share_token not in profile.id
    assert sent["status_url"].endswith(f"/track/{profile.share_token}")


async def test_the_public_link_works_with_no_login(client, db_session):
    user = await _buy(client, db_session, data_gb="3.0")
    profile = (await db_session.execute(
        select(ESIMProfile).where(ESIMProfile.id == user["esim_id"])
    )).scalar_one()
    await db_session.refresh(profile)

    usage_patch, device_patch = _vivape(ACTIVE_USAGE, ACTIVE_DEVICE)
    with usage_patch, device_patch:
        # No Authorization header at all: the recipient may have no account.
        res = await client.get(f"/api/v1/esims/public/{profile.share_token}")
    assert res.status_code == 200, res.text
    body = res.json()

    # Everything the customer needs to track and install.
    assert Decimal(body["usage"]["used_mb"]) == Decimal("166.46")
    assert body["usage"]["remaining_formatted"] == "2.84 GB"
    assert body["status"]["label"] == "Active"
    assert body["status"]["device_model"] == "Galaxy A55"
    assert body["lpa_string"] and body["qr_code_data"]
    assert body["validity"]["expires_at"]

    # But not the handset's hardware id, and not the link to itself.
    assert body["share_url"] is None
    assert all("eid" not in event for event in body["history"])


async def test_a_wrong_or_missing_token_reveals_nothing(client, db_session):
    user = await _buy(client, db_session)
    for token in ("", "short", "0" * 32, "not-a-real-token-at-all-000000000"):
        res = await client.get(f"/api/v1/esims/public/{token}")
        assert res.status_code == 404, f"{token} -> {res.status_code}"

    # The eSIM's own id is not a valid public key for it, so knowing an id
    # (which appears in our own URLs) grants nothing.
    res = await client.get(f"/api/v1/esims/public/{user['esim_id']}")
    assert res.status_code == 404


async def test_tokens_are_unique_and_unguessable(client, db_session):
    first = await _buy(client, db_session)
    second = await _buy(client, db_session)
    rows = (await db_session.execute(
        select(ESIMProfile.share_token).where(ESIMProfile.id.in_([first["esim_id"], second["esim_id"]]))
    )).scalars().all()
    assert len(set(rows)) == 2
    assert all(len(t) == 32 and all(c in "0123456789abcdef" for c in t) for t in rows)


async def test_the_owner_is_given_the_link_to_share(client, db_session):
    user = await _buy(client, db_session)
    usage_patch, device_patch = _vivape(FRESH_USAGE, FRESH_DEVICE)
    with usage_patch, device_patch:
        body = (await client.get(f"/api/v1/esims/{user['esim_id']}/status", headers=user["headers"])).json()
    assert body["share_url"].endswith("/track/" + body["share_url"].rsplit("/", 1)[-1])
    assert len(body["share_url"].rsplit("/", 1)[-1]) == 32


async def test_an_esim_from_before_tracking_links_gets_one_on_first_view(client, db_session):
    """No bulk backfill: the token is issued the first time the owner looks."""
    user = await _buy(client, db_session)
    profile = (await db_session.execute(
        select(ESIMProfile).where(ESIMProfile.id == user["esim_id"])
    )).scalar_one()
    profile.share_token = None
    await db_session.commit()

    usage_patch, device_patch = _vivape(FRESH_USAGE, FRESH_DEVICE)
    with usage_patch, device_patch:
        body = (await client.get(f"/api/v1/esims/{user['esim_id']}/status", headers=user["headers"])).json()
    assert body["share_url"]

    await db_session.refresh(profile)
    assert profile.share_token
    with usage_patch, device_patch:
        assert (await client.get(f"/api/v1/esims/public/{profile.share_token}")).status_code == 200


async def test_the_partner_webhook_carries_the_tracking_link(client, db_session):
    from app.services.webhook_svc import serialize_partner_order

    user = await _buy(client, db_session)
    profile = (await db_session.execute(
        select(ESIMProfile).where(ESIMProfile.id == user["esim_id"])
    )).scalar_one()
    await db_session.refresh(profile)

    from app.models.order import Order
    order = (await db_session.execute(select(Order).where(Order.id == user["order_id"]))).scalar_one()
    payload = serialize_partner_order(order, profile, user["product"], "BD")
    assert payload["status_url"].endswith(f"/track/{profile.share_token}")
