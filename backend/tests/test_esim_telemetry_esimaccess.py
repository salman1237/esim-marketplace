"""esim_telemetry_svc.py's eSIM Access branch - before this, get_telemetry
always called VivaPeAdapter regardless of supplier, so an eSIM Access
customer's status page either errored or showed another eSIM's VivaPe
data. See esim_telemetry_svc.py's _merge_esimaccess for what's confirmed
live vs. read defensively from the reference doc's documented shape."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.models.catalog import Country, Product
from app.models.order import ESIMProfile, Order, OrderStatus, PaymentMethod
from app.services import esim_telemetry_svc
from app.services.esimaccess_adapter import ESIMAccessError
from conftest import register_and_login

pytestmark = pytest.mark.asyncio


async def _esimaccess_profile(client, db_session, iccid=None):
    user = await register_and_login(client, "telemetryuser")
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
    )
    db_session.add(profile)
    await db_session.commit()
    return profile, order, product


async def test_telemetry_dispatches_to_esimaccess_not_vivape(client, db_session):
    profile, order, product = await _esimaccess_profile(client, db_session)

    with patch.object(
        esim_telemetry_svc.ESIMAccessAdapter, "query_esim",
        AsyncMock(return_value={"esimList": [{"iccid": profile.iccid, "esimStatus": "GOT_RESOURCE"}]}),
    ) as query_mock, patch.object(
        esim_telemetry_svc.VivaPeAdapter, "get_esim_usage", AsyncMock(),
    ) as vivape_usage_mock:
        await esim_telemetry_svc.get_telemetry(db_session, profile, product, order)

    query_mock.assert_awaited_once()
    _, kwargs = query_mock.call_args
    assert kwargs["order_no"] == profile.supplier_reference
    assert kwargs["iccid"] == profile.iccid
    vivape_usage_mock.assert_not_awaited()


async def test_in_use_status_marks_installed_and_reads_the_real_activation_time(client, db_session):
    """activateTime is a real, confirmed-live field (a SupplierTransactionLog
    row from this project's own account, 2026-11-12) - not derived by
    walking totalDuration back from expiredTime, which an earlier,
    unconfirmed version of this function did before that real response
    surfaced the actual field."""
    profile, order, product = await _esimaccess_profile(client, db_session)
    expired_time = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
    activate_time = datetime(2026, 11, 13, 6, 0, 0, tzinfo=timezone.utc)

    with patch.object(
        esim_telemetry_svc.ESIMAccessAdapter, "query_esim", AsyncMock(return_value={"esimList": [{
            "iccid": profile.iccid,
            "eid": "89033023525100100100039068590386",
            "esimStatus": "IN_USE",
            "smdpStatus": "ENABLED",
            "totalVolume": 1024 * 1024 * 1024,  # 1 GB
            "orderUsage": 200 * 1024 * 1024,    # 200 MB used
            "totalDuration": 7,
            "durationUnit": "DAY",
            "activateTime": activate_time.isoformat(),
            "expiredTime": expired_time.isoformat(),
        }]}),
    ):
        row = await esim_telemetry_svc.get_telemetry(db_session, profile, product, order)

    assert row.is_installed is True
    assert row.status_text == "IN_USE"
    assert row.data_used_mb == Decimal("200.00")
    assert row.expires_at == expired_time
    assert row.activated_at == activate_time
    assert row.eid == "89033023525100100100039068590386"
    await db_session.refresh(profile)
    assert profile.activated_at == activate_time
    assert profile.expires_at == expired_time


async def test_serialize_shows_the_real_total_after_a_topup_not_the_stale_product_total(client, db_session):
    """Confirmed live (2026-11-12): a 1GB/7Days purchase, topped up once,
    becomes totalVolume 2GB/totalDuration 14 in eSIM Access's own
    account - but Product.data_amount_gb/validity_days are frozen at
    the ORIGINAL 1GB/7Days forever. The storefront was showing the
    stale 1GB/7Days ("0.00 MB left of 1024.00 MB") instead of the real
    2GB/14Days total until this was fixed."""
    profile, order, product = await _esimaccess_profile(client, db_session)
    assert product.data_amount_gb == Decimal("1.00")
    assert product.validity_days == 7

    with patch.object(
        esim_telemetry_svc.ESIMAccessAdapter, "query_esim", AsyncMock(return_value={"esimList": [{
            "iccid": profile.iccid,
            "esimStatus": "IN_USE",
            "totalVolume": 2 * 1024 * 1024 * 1024,   # 2GB real total after a top-up
            "orderUsage": 1024 * 1024 * 1024,        # 1GB used
            "totalDuration": 14,                      # 7 (base) + 7 (top-up)
            "durationUnit": "DAY",
            "activateTime": "2026-11-11T12:06:00+00:00",
            "expiredTime": "2026-11-25T12:06:00+00:00",
        }]}),
    ):
        row = await esim_telemetry_svc.get_telemetry(db_session, profile, product, order)

    assert row.total_volume_bytes == 2 * 1024 * 1024 * 1024
    assert row.total_duration_days == 14

    data = esim_telemetry_svc.serialize(row, profile, product, order)
    assert data["usage"]["allowance_mb"] == "2048.00"
    assert data["usage"]["remaining_mb"] == "1024.00"
    assert data["validity"]["days"] == 14


async def test_an_unconfirmed_esim_status_is_not_assumed_installed(client, db_session):
    """GOT_RESOURCE means the order is ready to download (an ORDER_STATUS
    value per the reference doc, §5) - not that the profile has been
    installed. Only the confirmed-live "IN_USE" value marks the eSIM as
    activated; anything else must not claim a validity window that isn't
    real yet."""
    profile, order, product = await _esimaccess_profile(client, db_session)

    with patch.object(
        esim_telemetry_svc.ESIMAccessAdapter, "query_esim", AsyncMock(return_value={"esimList": [{
            "iccid": profile.iccid,
            "esimStatus": "GOT_RESOURCE",
            "totalVolume": 1024 * 1024 * 1024,
            "orderUsage": 0,
            "totalDuration": 7,
            "durationUnit": "DAY",
            "expiredTime": "2026-11-20T12:00:00+00:00",
        }]}),
    ):
        row = await esim_telemetry_svc.get_telemetry(db_session, profile, product, order)

    assert row.is_installed is False
    assert row.expires_at is None
    assert row.activated_at is None
    await db_session.refresh(profile)
    assert profile.activated_at is None
    assert profile.expires_at is None


async def test_empty_esim_list_is_handled_without_crashing(client, db_session):
    """esim/order is asynchronous (reference doc §4.2) - an empty esimList
    is a normal "not ready yet" state for a freshly-created profile whose
    iccid is already known from the order response but whose carrier
    record isn't queryable yet, not an error."""
    profile, order, product = await _esimaccess_profile(client, db_session)

    with patch.object(
        esim_telemetry_svc.ESIMAccessAdapter, "query_esim", AsyncMock(return_value={"esimList": []}),
    ):
        row = await esim_telemetry_svc.get_telemetry(db_session, profile, product, order)

    assert row is not None
    assert row.is_installed is False
    assert row.fetch_error is None


async def test_a_supplier_failure_keeps_the_previous_snapshot_and_records_the_error(client, db_session):
    profile, order, product = await _esimaccess_profile(client, db_session)
    with patch.object(
        esim_telemetry_svc.ESIMAccessAdapter, "query_esim",
        AsyncMock(side_effect=ESIMAccessError("eSIM Access business error: timeout")),
    ):
        row = await esim_telemetry_svc.get_telemetry(db_session, profile, product, order)

    assert row is not None
    assert "timeout" in row.fetch_error
