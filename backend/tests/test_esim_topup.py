"""Adding data to an already-delivered eSIM - esim_topup_svc.py and the
GET/POST /esims/{id}/topup* endpoints. New capability, no VivaPe
equivalent, so every test builds the eSIM Access path directly rather
than reusing a VivaPe-oriented fixture."""
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
from conftest import fund_wallet, register_and_login

pytestmark = pytest.mark.asyncio


def _topup_package(code="TOPUP_T1", price_scaled=70000, volume_gb=1, duration=7):
    return {
        "packageCode": code,
        "name": f"North America {volume_gb}GB/{duration}Days",
        "slug": code.lower(),
        "price": price_scaled,
        "volume": int(volume_gb * 1024 ** 3),
        "duration": duration,
        "durationUnit": "DAY",
    }


async def _esimaccess_profile(db_session, user_id):
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
        order_no=f"TST-{suffix}", buyer_id=user_id, beneficiary_id=user_id, product_id=product.id,
        total_amount=product.retail_price, payment_method=PaymentMethod.WALLET, status=OrderStatus.COMPLETED,
    )
    db_session.add(order)
    await db_session.flush()

    profile = ESIMProfile(order_id=order.id, beneficiary_id=user_id, iccid=f"8948{uuid.uuid4().hex[:14]}")
    db_session.add(profile)
    await db_session.commit()
    return profile, order, product


# --- esim_topup_svc.get_topup_options ------------------------------------

async def test_get_topup_options_is_empty_for_a_non_esimaccess_product(client, db_session):
    user = await register_and_login(client, "topupnonesim")
    profile, _order, product = await _esimaccess_profile(db_session, user["user_id"])
    product.supplier_reference = "worldmove_esim"
    await db_session.commit()
    options = await esim_topup_svc.get_topup_options(db_session, profile, product)
    assert options == []


async def test_get_topup_options_is_empty_without_an_iccid_yet(client, db_session):
    user = await register_and_login(client, "topupnoiccid")
    profile, _order, product = await _esimaccess_profile(db_session, user["user_id"])
    profile.iccid = None
    await db_session.commit()
    options = await esim_topup_svc.get_topup_options(db_session, profile, product)
    assert options == []


async def test_get_topup_options_returns_live_priced_options(client, db_session):
    user = await register_and_login(client, "topupoptions")
    profile, _order, product = await _esimaccess_profile(db_session, user["user_id"])

    with patch.object(
        esim_topup_svc.ESIMAccessAdapter, "list_topup_packages",
        AsyncMock(return_value=[_topup_package(price_scaled=70000, volume_gb=1, duration=7)]),
    ):
        options = await esim_topup_svc.get_topup_options(db_session, profile, product)

    assert len(options) == 1
    opt = options[0]
    assert opt["package_code"] == "TOPUP_T1"
    assert opt["data_amount_gb"] == Decimal("1.00")
    assert opt["validity_days"] == 7
    # $7.00 cost + 25% default profit = $8.75
    assert opt["retail_price"] == Decimal("8.75")


# --- esim_topup_svc.purchase_topup ----------------------------------------

async def test_purchase_topup_end_to_end(client, db_session):
    user = await register_and_login(client, "topupbuyer")
    await fund_wallet(db_session, user["user_id"], Decimal("100.00"))
    profile, _order, product = await _esimaccess_profile(db_session, user["user_id"])

    with patch.object(
        esim_topup_svc.ESIMAccessAdapter, "list_topup_packages",
        AsyncMock(return_value=[_topup_package()]),
    ), patch.object(
        esim_topup_svc.ESIMAccessAdapter, "topup_esim", AsyncMock(return_value={}),
    ) as topup_mock:
        topup = await esim_topup_svc.purchase_topup(db_session, profile, product, "TOPUP_T1", user["user_id"])

    assert topup.status == EsimTopupStatus.COMPLETED
    assert topup.retail_price == Decimal("8.75")
    topup_mock.assert_awaited_once()
    _, kwargs = topup_mock.call_args
    assert kwargs["iccid"] == profile.iccid
    assert kwargs["package_code"] == "TOPUP_T1"
    assert kwargs["amount_scaled"] == 70000  # the supplier is charged the COST, not the retail price

    wallet = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == user["user_id"], Wallet.wallet_type == WalletType.DEFAULT)
    )).scalar_one()
    assert Decimal(str(wallet.balance)) == Decimal("100.00") - Decimal("8.75")


async def test_purchase_topup_refunds_on_supplier_failure(client, db_session):
    user = await register_and_login(client, "topuprefund")
    await fund_wallet(db_session, user["user_id"], Decimal("100.00"))
    profile, _order, product = await _esimaccess_profile(db_session, user["user_id"])

    with patch.object(
        esim_topup_svc.ESIMAccessAdapter, "list_topup_packages",
        AsyncMock(return_value=[_topup_package()]),
    ), patch.object(
        esim_topup_svc.ESIMAccessAdapter, "topup_esim",
        AsyncMock(side_effect=ESIMAccessError("eSIM Access business error: expired")),
    ):
        with pytest.raises(esim_topup_svc.TopupNotAvailable):
            await esim_topup_svc.purchase_topup(db_session, profile, product, "TOPUP_T1", user["user_id"])

    wallet = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == user["user_id"], Wallet.wallet_type == WalletType.DEFAULT)
    )).scalar_one()
    assert Decimal(str(wallet.balance)) == Decimal("100.00")  # fully refunded

    saved = (await db_session.execute(
        select(EsimTopup).where(EsimTopup.esim_profile_id == profile.id)
    )).scalar_one()
    assert saved.status == EsimTopupStatus.FAILED


async def test_purchase_topup_rejects_a_stale_package_code(client, db_session):
    user = await register_and_login(client, "topupstale")
    profile, _order, product = await _esimaccess_profile(db_session, user["user_id"])
    with patch.object(
        esim_topup_svc.ESIMAccessAdapter, "list_topup_packages", AsyncMock(return_value=[]),
    ):
        with pytest.raises(esim_topup_svc.TopupNotAvailable):
            await esim_topup_svc.purchase_topup(db_session, profile, product, "TOPUP_GONE", user["user_id"])


async def test_purchase_topup_rejects_insufficient_balance(client, db_session):
    user = await register_and_login(client, "topuppoor")
    profile, _order, product = await _esimaccess_profile(db_session, user["user_id"])
    with patch.object(
        esim_topup_svc.ESIMAccessAdapter, "list_topup_packages",
        AsyncMock(return_value=[_topup_package()]),
    ):
        with pytest.raises(ValueError, match="Insufficient"):
            await esim_topup_svc.purchase_topup(db_session, profile, product, "TOPUP_T1", user["user_id"])


# --- API endpoints ---------------------------------------------------------

async def test_topup_options_endpoint_requires_ownership(client, db_session):
    owner = await register_and_login(client, "topupowner")
    stranger = await register_and_login(client, "topupstranger")
    profile, _order, _product = await _esimaccess_profile(db_session, owner["user_id"])

    forbidden = await client.get(f"/api/v1/esims/{profile.id}/topup-options", headers=stranger["headers"])
    assert forbidden.status_code == 404  # same 404 as a nonexistent id

    with patch.object(
        esim_topup_svc.ESIMAccessAdapter, "list_topup_packages",
        AsyncMock(return_value=[_topup_package()]),
    ):
        ok = await client.get(f"/api/v1/esims/{profile.id}/topup-options", headers=owner["headers"])
    assert ok.status_code == 200, ok.text
    assert ok.json()[0]["package_code"] == "TOPUP_T1"


async def test_topup_purchase_endpoint_end_to_end(client, db_session):
    user = await register_and_login(client, "topupapi")
    await fund_wallet(db_session, user["user_id"], Decimal("100.00"))
    profile, _order, _product = await _esimaccess_profile(db_session, user["user_id"])

    with patch.object(
        esim_topup_svc.ESIMAccessAdapter, "list_topup_packages",
        AsyncMock(return_value=[_topup_package()]),
    ), patch.object(
        esim_topup_svc.ESIMAccessAdapter, "topup_esim", AsyncMock(return_value={}),
    ):
        res = await client.post(
            f"/api/v1/esims/{profile.id}/topup", json={"package_code": "TOPUP_T1"}, headers=user["headers"],
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "COMPLETED"
    assert body["retail_price"] == "8.75"
