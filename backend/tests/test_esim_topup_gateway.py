"""ShurjoPay-paid eSIM data top-up - the same wallet-vs-gateway choice
the initial eSIM purchase already has (payments.py's /shurjopay/
order-initiate), applied to esim_topup_svc.py. Mirrors
test_gateway_checkout.py's own patterns for the order flow."""
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.catalog import Country, Product
from app.models.order import ESIMProfile, EsimTopup, EsimTopupStatus, Order, OrderStatus, PaymentMethod
from app.models.wallet import Wallet, WalletType
from app.services import esim_topup_svc
from app.services.esimaccess_adapter import ESIMAccessError
from conftest import register_and_login

pytestmark = pytest.mark.asyncio

FAKE_INITIATE_RESPONSE = {"checkout_url": "https://sandbox.shurjopayment.com/pay/fake123", "sp_order_id": "spFAKE123"}


def _paid_response(customer_order_id: str, amount: str = "10.0000"):
    return [{
        "order_id": "sp6a99c460a9300", "amount": amount,
        "customer_order_id": customer_order_id, "sp_code": "1000", "sp_message": "Success",
    }]


def _unpaid_response(customer_order_id: str):
    return [{
        "order_id": "sp6a99c2d29fb09", "amount": "10.0000",
        "customer_order_id": customer_order_id, "sp_code": "1068", "sp_message": "initiated",
    }]


def _topup_package(code="TOPUP_T1", price_scaled=70000, volume_gb=1, duration=7):
    return {
        "packageCode": code, "name": f"North America {volume_gb}GB/{duration}Days", "slug": code.lower(),
        "price": price_scaled, "volume": int(volume_gb * 1024 ** 3), "duration": duration, "durationUnit": "DAY",
    }


async def _esimaccess_profile(client, db_session):
    user = await register_and_login(client, "topupgateway")
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
        status=OrderStatus.COMPLETED,
    )
    db_session.add(order)
    await db_session.flush()
    profile = ESIMProfile(order_id=order.id, beneficiary_id=user["user_id"], iccid=f"8948{uuid.uuid4().hex[:14]}")
    db_session.add(profile)
    await db_session.commit()
    return user, profile, product


async def test_esim_topup_initiate_creates_pending_topup_and_returns_checkout_url(client, db_session):
    user, profile, _product = await _esimaccess_profile(client, db_session)

    with patch.object(
        esim_topup_svc.ESIMAccessAdapter, "list_topup_packages", AsyncMock(return_value=[_topup_package()]),
    ), patch("app.api.v1.payments.ShurjoPayService.initiate_payment", return_value=FAKE_INITIATE_RESPONSE):
        res = await client.post(
            f"/api/v1/payments/shurjopay/esim-topup-initiate?esim_id={profile.id}",
            json={"package_code": "TOPUP_T1"}, headers=user["headers"],
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["checkout_url"] == FAKE_INITIATE_RESPONSE["checkout_url"]
    assert body["topup_id"]

    topup = (await db_session.execute(select(EsimTopup).where(EsimTopup.id == body["topup_id"]))).scalar_one()
    assert topup.status == EsimTopupStatus.PENDING
    assert topup.payment_method == PaymentMethod.SHURJOPAY


async def test_esim_topup_callback_completes_and_calls_supplier(client, db_session):
    user, profile, _product = await _esimaccess_profile(client, db_session)

    with patch.object(
        esim_topup_svc.ESIMAccessAdapter, "list_topup_packages", AsyncMock(return_value=[_topup_package()]),
    ), patch("app.api.v1.payments.ShurjoPayService.initiate_payment", return_value=FAKE_INITIATE_RESPONSE):
        initiate = await client.post(
            f"/api/v1/payments/shurjopay/esim-topup-initiate?esim_id={profile.id}",
            json={"package_code": "TOPUP_T1"}, headers=user["headers"],
        )
    topup_id = initiate.json()["topup_id"]

    response = _paid_response(f"ESIMTOPUP-{topup_id}")
    with patch.object(
        esim_topup_svc.ESIMAccessAdapter, "topup_esim", AsyncMock(return_value={}),
    ) as topup_mock, patch("app.api.v1.payments.ShurjoPayService.verify_payment", return_value=response):
        callback = await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c460a9300"})
    assert callback.status_code == 302
    assert f"/my-esims/{profile.id}?topup=success" in callback.headers["location"]
    topup_mock.assert_awaited_once()
    _, kwargs = topup_mock.call_args
    assert kwargs["iccid"] == profile.iccid
    assert kwargs["amount_scaled"] == 70000  # the supplier is charged the stored COST, not the retail price

    await db_session.refresh(profile)
    topup = (await db_session.execute(select(EsimTopup).where(EsimTopup.id == topup_id))).scalar_one()
    assert topup.status == EsimTopupStatus.COMPLETED


async def test_esim_topup_callback_replay_does_not_call_supplier_twice(client, db_session):
    user, profile, _product = await _esimaccess_profile(client, db_session)

    with patch.object(
        esim_topup_svc.ESIMAccessAdapter, "list_topup_packages", AsyncMock(return_value=[_topup_package()]),
    ), patch("app.api.v1.payments.ShurjoPayService.initiate_payment", return_value=FAKE_INITIATE_RESPONSE):
        initiate = await client.post(
            f"/api/v1/payments/shurjopay/esim-topup-initiate?esim_id={profile.id}",
            json={"package_code": "TOPUP_T1"}, headers=user["headers"],
        )
    topup_id = initiate.json()["topup_id"]
    response = _paid_response(f"ESIMTOPUP-{topup_id}")

    with patch.object(
        esim_topup_svc.ESIMAccessAdapter, "topup_esim", AsyncMock(return_value={}),
    ) as topup_mock, patch("app.api.v1.payments.ShurjoPayService.verify_payment", return_value=response):
        await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c460a9300"})
        await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c460a9300"})

    topup_mock.assert_awaited_once()


async def test_esim_topup_callback_refunds_to_wallet_on_supplier_failure(client, db_session):
    user, profile, _product = await _esimaccess_profile(client, db_session)

    with patch.object(
        esim_topup_svc.ESIMAccessAdapter, "list_topup_packages", AsyncMock(return_value=[_topup_package()]),
    ), patch("app.api.v1.payments.ShurjoPayService.initiate_payment", return_value=FAKE_INITIATE_RESPONSE):
        initiate = await client.post(
            f"/api/v1/payments/shurjopay/esim-topup-initiate?esim_id={profile.id}",
            json={"package_code": "TOPUP_T1"}, headers=user["headers"],
        )
    topup_id = initiate.json()["topup_id"]
    response = _paid_response(f"ESIMTOPUP-{topup_id}")

    wallet_before = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == user["user_id"], Wallet.wallet_type == WalletType.DEFAULT)
    )).scalar_one()
    balance_before = Decimal(str(wallet_before.balance))

    with patch.object(
        esim_topup_svc.ESIMAccessAdapter, "topup_esim",
        AsyncMock(side_effect=ESIMAccessError("eSIM Access business error: expired")),
    ), patch("app.api.v1.payments.ShurjoPayService.verify_payment", return_value=response):
        callback = await client.get("/api/v1/payments/shurjopay/callback", params={"order_id": "sp6a99c460a9300"})
    assert f"/my-esims/{profile.id}?topup=failed" in callback.headers["location"]

    topup = (await db_session.execute(select(EsimTopup).where(EsimTopup.id == topup_id))).scalar_one()
    assert topup.status == EsimTopupStatus.FAILED

    await db_session.refresh(wallet_before)
    wallet_after = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == user["user_id"], Wallet.wallet_type == WalletType.DEFAULT)
    )).scalar_one()
    # Payment happened at the gateway (no wallet debit) - the failure
    # compensation is a wallet CREDIT, same pattern as a failed
    # gateway-paid Order.
    assert Decimal(str(wallet_after.balance)) == balance_before + Decimal(str(topup.retail_price))
