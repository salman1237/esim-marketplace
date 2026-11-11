"""Admin lifecycle actions for an eSIM Access eSIM (suspend/unsuspend/
revoke/cancel/SMS) and the account-level balance/webhook endpoints -
confirmed against the real partner console (console.esimaccess.com,
2026-11-12): an In-Use eSIM's own Action tab offers exactly Top Up /
Suspend / Revoke; an unused one additionally offers Cancel, matching
the reference doc's "cancel is unused/inactive only" note.
"""
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

import app.api.v1.admin as admin_module
from app.models.catalog import Country, Product
from app.models.order import ESIMProfile, ESIMStatus, Order, OrderStatus, PaymentMethod
from app.services.esimaccess_adapter import ESIMAccessError
from conftest import register_and_login

pytestmark = pytest.mark.asyncio


async def _esimaccess_profile(client, db_session, status=ESIMStatus.RELEASED, iccid=None):
    user = await register_and_login(client, "esimlifecycleowner")
    suffix = uuid.uuid4().hex[:6]
    country = Country(
        id=int(uuid.uuid4().int % 1_000_000_000), iso2=f"T{suffix.upper()}",
        name_en=f"Testland {suffix}", is_active=True,
    )
    db_session.add(country)
    await db_session.flush()

    product = Product(
        id=str(uuid.uuid4()), country_id=country.id, title_en=f"Testland {suffix} 1GB 7Days",
        data_amount_gb=Decimal("1.00"), validity_days=7, cost_price=Decimal("3.00"),
        retail_price=Decimal("4.00"), currency="USD", is_active=True,
        supplier_reference="esimaccess", supplier_package_code=f"PKG{suffix.upper()}",
    )
    db_session.add(product)
    await db_session.flush()

    order = Order(
        order_no=f"TST-{suffix}", buyer_id=user["user_id"], beneficiary_id=user["user_id"],
        product_id=product.id, total_amount=product.retail_price, payment_method=PaymentMethod.WALLET,
        status=OrderStatus.COMPLETED, external_trx_id=f"ORD{suffix.upper()}",
    )
    db_session.add(order)
    await db_session.flush()

    profile = ESIMProfile(
        order_id=order.id, beneficiary_id=order.beneficiary_id,
        iccid=iccid or f"8948{uuid.uuid4().hex[:14]}", supplier_reference=order.external_trx_id,
        status=status,
    )
    db_session.add(profile)
    await db_session.commit()
    return profile, order, product


async def _vivape_profile(client, db_session):
    user = await register_and_login(client, "esimlifecyclevivape")
    suffix = uuid.uuid4().hex[:6]
    country = Country(
        id=int(uuid.uuid4().int % 1_000_000_000), iso2=f"V{suffix.upper()[:4]}",
        name_en=f"Vivaland {suffix}", is_active=True,
    )
    db_session.add(country)
    await db_session.flush()
    product = Product(
        id=str(uuid.uuid4()), country_id=country.id, title_en=f"Vivaland {suffix} 1GB 7Days",
        data_amount_gb=Decimal("1.00"), validity_days=7, cost_price=Decimal("3.00"),
        retail_price=Decimal("4.00"), currency="EUR", is_active=True,
        supplier_reference="worldmove_esim",
    )
    db_session.add(product)
    await db_session.flush()
    order = Order(
        order_no=f"VIV-{suffix}", buyer_id=user["user_id"], beneficiary_id=user["user_id"],
        product_id=product.id, total_amount=product.retail_price, payment_method=PaymentMethod.WALLET,
        status=OrderStatus.COMPLETED,
    )
    db_session.add(order)
    await db_session.flush()
    profile = ESIMProfile(order_id=order.id, beneficiary_id=order.beneficiary_id, iccid=f"891{uuid.uuid4().hex[:15]}")
    db_session.add(profile)
    await db_session.commit()
    return profile


async def _admin(client, promote_role):
    admin = await register_and_login(client, "esimlifecycle")
    await promote_role(admin["user_id"], "ADMIN")
    return admin


# --- lifecycle actions -----------------------------------------------------

async def test_suspend_calls_adapter_and_updates_status(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    profile, _order, _product = await _esimaccess_profile(client, db_session)

    with patch.object(admin_module.ESIMAccessAdapter, "suspend_esim", AsyncMock(return_value={})) as mock:
        res = await client.post(f"/api/v1/admin/esims/{profile.id}/suspend", headers=admin["headers"])
    assert res.status_code == 200, res.text
    mock.assert_awaited_once()
    _, kwargs = mock.call_args
    assert kwargs["iccid"] == profile.iccid
    await db_session.refresh(profile)
    assert profile.status == ESIMStatus.SUSPENDED


async def test_unsuspend_calls_adapter_and_updates_status(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    profile, _order, _product = await _esimaccess_profile(client, db_session, status=ESIMStatus.SUSPENDED)

    with patch.object(admin_module.ESIMAccessAdapter, "unsuspend_esim", AsyncMock(return_value={})) as mock:
        res = await client.post(f"/api/v1/admin/esims/{profile.id}/unsuspend", headers=admin["headers"])
    assert res.status_code == 200, res.text
    mock.assert_awaited_once()
    await db_session.refresh(profile)
    assert profile.status == ESIMStatus.ACTIVE


async def test_revoke_is_not_refundable_and_updates_status(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    profile, _order, _product = await _esimaccess_profile(client, db_session)

    with patch.object(admin_module.ESIMAccessAdapter, "revoke_esim", AsyncMock(return_value={})) as mock:
        res = await client.post(f"/api/v1/admin/esims/{profile.id}/revoke", headers=admin["headers"])
    assert res.status_code == 200, res.text
    mock.assert_awaited_once()
    await db_session.refresh(profile)
    assert profile.status == ESIMStatus.REVOKED


async def test_cancel_calls_adapter_and_updates_status(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    profile, _order, _product = await _esimaccess_profile(client, db_session)

    with patch.object(admin_module.ESIMAccessAdapter, "cancel_esim", AsyncMock(return_value={})) as mock:
        res = await client.post(f"/api/v1/admin/esims/{profile.id}/cancel", headers=admin["headers"])
    assert res.status_code == 200, res.text
    mock.assert_awaited_once()
    await db_session.refresh(profile)
    assert profile.status == ESIMStatus.CANCELLED


async def test_send_sms_passes_message_through(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    profile, _order, _product = await _esimaccess_profile(client, db_session)

    with patch.object(admin_module.ESIMAccessAdapter, "send_sms", AsyncMock(return_value={})) as mock:
        res = await client.post(
            f"/api/v1/admin/esims/{profile.id}/send-sms", json={"message": "Your eSIM is ready"},
            headers=admin["headers"],
        )
    assert res.status_code == 200, res.text
    _, kwargs = mock.call_args
    assert kwargs["message"] == "Your eSIM is ready"
    assert kwargs["iccid"] == profile.iccid


async def test_lifecycle_action_rejects_a_non_esimaccess_esim(client, db_session, promote_role):
    """These actions don't exist for VivaPe at all (reference doc: "No
    VivaPe equivalent exists") - calling one on a VivaPe-sourced eSIM
    must fail loudly, never silently no-op."""
    admin = await _admin(client, promote_role)
    profile = await _vivape_profile(client, db_session)

    res = await client.post(f"/api/v1/admin/esims/{profile.id}/suspend", headers=admin["headers"])
    assert res.status_code == 400


async def test_lifecycle_action_surfaces_a_supplier_error(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    profile, _order, _product = await _esimaccess_profile(client, db_session)

    with patch.object(
        admin_module.ESIMAccessAdapter, "suspend_esim",
        AsyncMock(side_effect=ESIMAccessError("eSIM Access business error: already suspended")),
    ):
        res = await client.post(f"/api/v1/admin/esims/{profile.id}/suspend", headers=admin["headers"])
    assert res.status_code == 400
    await db_session.refresh(profile)
    assert profile.status != ESIMStatus.SUSPENDED  # the supplier call failed, so the status must not change


async def test_lifecycle_actions_require_admin(client, db_session):
    plain = await register_and_login(client, "esimlifecyclenobody")
    profile, _order, _product = await _esimaccess_profile(client, db_session)
    res = await client.post(f"/api/v1/admin/esims/{profile.id}/suspend", headers=plain["headers"])
    assert res.status_code == 403


# --- account-level balance/webhook -----------------------------------------

async def test_get_balance(client, promote_role):
    admin = await _admin(client, promote_role)
    with patch.object(admin_module.ESIMAccessAdapter, "get_balance", AsyncMock(return_value=Decimal("50.00"))):
        res = await client.get("/api/v1/admin/esimaccess/balance", headers=admin["headers"])
    assert res.status_code == 200, res.text
    assert res.json()["balance"] == "50.00"


async def test_set_webhook_defaults_to_this_projects_own_receiver(client, promote_role):
    admin = await _admin(client, promote_role)
    with patch.object(admin_module.ESIMAccessAdapter, "set_webhook_url", AsyncMock(return_value={})) as mock:
        res = await client.post("/api/v1/admin/esimaccess/webhook", json={}, headers=admin["headers"])
    assert res.status_code == 200, res.text
    assert res.json()["webhook_url"].endswith("/api/v1/webhooks/esimaccess")
    args, _kwargs = mock.call_args
    assert args[-1].endswith("/api/v1/webhooks/esimaccess")


async def test_get_webhook_url(client, promote_role):
    admin = await _admin(client, promote_role)
    with patch.object(
        admin_module.ESIMAccessAdapter, "get_webhook_url",
        AsyncMock(return_value={"webhook": "https://example.test/hook"}),
    ):
        res = await client.get("/api/v1/admin/esimaccess/webhook", headers=admin["headers"])
    assert res.status_code == 200, res.text
    assert res.json()["webhook_url"] == "https://example.test/hook"
