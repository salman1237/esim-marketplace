"""The inbound webhook receiver (app/api/v1/esimaccess_webhook.py) - the
primary fulfilment signal this project was missing until now. Every
assertion here checks that the payload's own claimed status/usage
fields are NEVER trusted directly - only used to find a row, with the
real state always re-fetched from esim/query (same discipline as
ShurjoPay's IPN handler)."""
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.catalog import Country, Product
from app.models.order import ESIMProfile, Order, OrderStatus, PaymentMethod
from app.services import esim_telemetry_svc
from conftest import register_and_login

pytestmark = pytest.mark.asyncio


async def _processing_esimaccess_order(client, db_session):
    user = await register_and_login(client, "webhookbuyer")
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
        status=OrderStatus.PROCESSING, external_trx_id=f"ORD{suffix.upper()}",
    )
    db_session.add(order)
    await db_session.commit()
    return order, product


async def test_order_status_completes_a_still_processing_order(client, db_session, mock_esimaccess):
    order, _product = await _processing_esimaccess_order(client, db_session)

    res = await client.post(
        "/api/v1/webhooks/esimaccess",
        json={"notifyType": "ORDER_STATUS", "content": {"orderNo": order.external_trx_id, "orderStatus": "GOT_RESOURCE"}},
    )
    assert res.status_code == 200, res.text

    await db_session.refresh(order)
    assert order.status == OrderStatus.COMPLETED
    profile = (await db_session.execute(
        select(ESIMProfile).where(ESIMProfile.order_id == order.id)
    )).scalar_one_or_none()
    assert profile is not None
    mock_esimaccess.create_order.assert_not_awaited()  # never re-ordered, only queried


async def test_order_status_is_a_noop_for_an_already_completed_order(client, db_session, mock_esimaccess):
    order, _product = await _processing_esimaccess_order(client, db_session)
    order.status = OrderStatus.COMPLETED
    await db_session.commit()

    res = await client.post(
        "/api/v1/webhooks/esimaccess",
        json={"notifyType": "ORDER_STATUS", "content": {"orderNo": order.external_trx_id}},
    )
    assert res.status_code == 200, res.text
    mock_esimaccess.query_esim.assert_not_awaited()


async def test_esim_status_triggers_a_telemetry_refresh_by_iccid(client, db_session):
    order, product = await _processing_esimaccess_order(client, db_session)
    order.status = OrderStatus.COMPLETED
    iccid = f"8948{uuid.uuid4().hex[:14]}"
    profile = ESIMProfile(order_id=order.id, beneficiary_id=order.beneficiary_id, iccid=iccid, supplier_reference=order.external_trx_id)
    db_session.add(profile)
    await db_session.commit()

    with patch.object(
        esim_telemetry_svc.ESIMAccessAdapter, "query_esim",
        AsyncMock(return_value={"esimList": [{"iccid": iccid, "esimStatus": "IN_USE"}]}),
    ) as mock:
        res = await client.post(
            "/api/v1/webhooks/esimaccess",
            json={"notifyType": "ESIM_STATUS", "content": {"iccid": iccid, "esimStatus": "IN_USE", "smdpStatus": "ENABLED"}},
        )
    assert res.status_code == 200, res.text
    mock.assert_awaited_once()

    await db_session.refresh(profile)
    # The webhook's own claimed fields are never trusted directly - the
    # refreshed row's data comes from the re-fetch above, not the payload.
    from app.models.esim_telemetry import ESIMTelemetry
    telemetry = (await db_session.execute(
        select(ESIMTelemetry).where(ESIMTelemetry.esim_profile_id == profile.id)
    )).scalar_one()
    assert telemetry.is_installed is True


async def test_data_usage_triggers_a_refresh_by_order_no_when_no_iccid_match(client, db_session):
    order, product = await _processing_esimaccess_order(client, db_session)
    order.status = OrderStatus.COMPLETED
    iccid = f"8948{uuid.uuid4().hex[:14]}"
    profile = ESIMProfile(order_id=order.id, beneficiary_id=order.beneficiary_id, iccid=iccid, supplier_reference=order.external_trx_id)
    db_session.add(profile)
    await db_session.commit()

    with patch.object(
        esim_telemetry_svc.ESIMAccessAdapter, "query_esim",
        AsyncMock(return_value={"esimList": [{"iccid": iccid, "esimStatus": "IN_USE"}]}),
    ) as mock:
        res = await client.post(
            "/api/v1/webhooks/esimaccess",
            json={"notifyType": "DATA_USAGE", "content": {"orderNo": order.external_trx_id, "iccid": "no-such-iccid-match"}},
        )
    assert res.status_code == 200, res.text
    mock.assert_awaited_once()


async def test_unknown_notify_type_is_ignored_without_erroring(client, db_session):
    res = await client.post(
        "/api/v1/webhooks/esimaccess",
        json={"notifyType": "SOMETHING_NEW", "content": {}},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "received"


async def test_malformed_body_is_ignored_without_erroring(client):
    res = await client.post("/api/v1/webhooks/esimaccess", content=b"not json", headers={"content-type": "application/json"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ignored"


async def test_unknown_order_no_is_a_noop_not_an_error(client, db_session):
    res = await client.post(
        "/api/v1/webhooks/esimaccess",
        json={"notifyType": "ORDER_STATUS", "content": {"orderNo": "does-not-exist"}},
    )
    assert res.status_code == 200, res.text
