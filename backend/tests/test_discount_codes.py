"""Discount codes: validation, both checkout paths, and what the reports see.

The rules worth guarding hardest are the money ones: the wallet is debited
the discounted amount, the order stores what came off so profit stays true,
and commission is calculated on the discounted price - not the list price,
which would pay a merchant more than the sale earned.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.order import Order, OrderStatus
from app.models.wallet import Wallet, WalletType
from conftest import create_test_product, fund_wallet, register_and_login, wait_for_order

pytestmark = pytest.mark.asyncio


async def _admin(client, promote_role, name="dcadmin"):
    admin = await register_and_login(client, name)
    await promote_role(admin["user_id"], "SUPER_ADMIN")
    return admin


async def _make_code(client, admin, **overrides):
    body = {
        "code": f"SAVE{datetime.now(timezone.utc).strftime('%H%M%S%f')[:10]}",
        "discount_type": "PERCENT",
        "value": "10",
    }
    body.update(overrides)
    res = await client.post("/api/v1/admin/discounts", json=body, headers=admin["headers"])
    assert res.status_code == 200, res.text
    return res.json()


async def _balance(db_session, user_id: str) -> Decimal:
    wallet = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.DEFAULT)
    )).scalar_one()
    await db_session.refresh(wallet)
    return Decimal(str(wallet.balance))


async def test_percent_code_reduces_the_charge_and_is_recorded(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    code = await _make_code(client, admin, value="25")
    product = await create_test_product(db_session, price=Decimal("20.00"))
    user = await register_and_login(client, "dc")
    await fund_wallet(db_session, user["user_id"], Decimal("50"))

    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET", "discount_code": code["code"]},
        headers=user["headers"],
    )
    assert res.status_code == 202, res.text
    body = res.json()
    # 25% off 20.00 -> charged 15.00
    assert Decimal(body["total_amount"]) == Decimal("15.0000")
    assert Decimal(body["discount_amount"]) == Decimal("5.0000")
    assert await _balance(db_session, user["user_id"]) == Decimal("35.0000")

    await wait_for_order(client, body["id"], user["headers"])
    order = (await db_session.execute(select(Order).where(Order.id == body["id"]))).scalar_one()
    await db_session.refresh(order)
    assert order.discount_code_id == code["id"]
    assert Decimal(str(order.discount_amount)) == Decimal("5.0000")


async def test_fixed_code_is_capped_at_the_price(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    code = await _make_code(client, admin, discount_type="FIXED", value="50")
    product = await create_test_product(db_session, price=Decimal("8.00"))
    user = await register_and_login(client, "dc")
    await fund_wallet(db_session, user["user_id"], Decimal("20"))

    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET", "discount_code": code["code"]},
        headers=user["headers"],
    )
    assert res.status_code == 202, res.text
    # A 50.00 code on an 8.00 eSIM makes it free, never negative.
    assert Decimal(res.json()["total_amount"]) == Decimal("0")
    assert Decimal(res.json()["discount_amount"]) == Decimal("8.0000")
    assert await _balance(db_session, user["user_id"]) == Decimal("20.0000")


async def test_percent_cap_limits_the_giveaway(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    code = await _make_code(client, admin, value="50", max_discount_amount="3")
    product = await create_test_product(db_session, price=Decimal("40.00"))
    user = await register_and_login(client, "dc")
    await fund_wallet(db_session, user["user_id"], Decimal("60"))

    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET", "discount_code": code["code"]},
        headers=user["headers"],
    )
    assert Decimal(res.json()["discount_amount"]) == Decimal("3.0000")
    assert Decimal(res.json()["total_amount"]) == Decimal("37.0000")


async def test_unknown_expired_and_inactive_codes_are_refused(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    product = await create_test_product(db_session, price=Decimal("10.00"))
    user = await register_and_login(client, "dc")
    await fund_wallet(db_session, user["user_id"], Decimal("50"))

    async def attempt(code_value):
        return await client.post(
            "/api/v1/orders/checkout",
            json={"product_id": product.id, "payment_method": "WALLET", "discount_code": code_value},
            headers=user["headers"],
        )

    unknown = await attempt("NOPE-NOT-A-CODE")
    assert unknown.status_code == 400
    assert "isn't valid" in unknown.json()["detail"]

    past = datetime.now(timezone.utc) - timedelta(days=1)
    expired = await _make_code(client, admin, ends_at=past.isoformat(), starts_at=(past - timedelta(days=5)).isoformat())
    res = await attempt(expired["code"])
    assert res.status_code == 400
    assert "expired" in res.json()["detail"]

    future = datetime.now(timezone.utc) + timedelta(days=3)
    not_yet = await _make_code(client, admin, starts_at=future.isoformat())
    res = await attempt(not_yet["code"])
    assert res.status_code == 400
    assert "isn't active yet" in res.json()["detail"]

    off = await _make_code(client, admin, is_active=False)
    res = await attempt(off["code"])
    assert res.status_code == 400

    # None of the refusals charged the wallet.
    assert await _balance(db_session, user["user_id"]) == Decimal("50.0000")


async def test_minimum_order_amount_is_enforced(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    code = await _make_code(client, admin, min_order_amount="30")
    cheap = await create_test_product(db_session, price=Decimal("10.00"))
    user = await register_and_login(client, "dc")
    await fund_wallet(db_session, user["user_id"], Decimal("50"))

    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": cheap.id, "payment_method": "WALLET", "discount_code": code["code"]},
        headers=user["headers"],
    )
    assert res.status_code == 400
    assert "at least 30" in res.json()["detail"]


async def test_per_user_limit_then_total_limit(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    code = await _make_code(client, admin, value="10", max_uses_per_user=1, max_uses=2)
    product = await create_test_product(db_session, price=Decimal("10.00"))

    first = await register_and_login(client, "dc")
    await fund_wallet(db_session, first["user_id"], Decimal("100"))
    ok = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET", "discount_code": code["code"]},
        headers=first["headers"],
    )
    assert ok.status_code == 202, ok.text

    again = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET", "discount_code": code["code"]},
        headers=first["headers"],
    )
    assert again.status_code == 400
    assert "already used" in again.json()["detail"]

    second = await register_and_login(client, "dc")
    await fund_wallet(db_session, second["user_id"], Decimal("100"))
    assert (await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET", "discount_code": code["code"]},
        headers=second["headers"],
    )).status_code == 202

    third = await register_and_login(client, "dc")
    await fund_wallet(db_session, third["user_id"], Decimal("100"))
    exhausted = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET", "discount_code": code["code"]},
        headers=third["headers"],
    )
    assert exhausted.status_code == 400
    assert "usage limit" in exhausted.json()["detail"]


async def test_first_order_only_code(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    code = await _make_code(client, admin, first_order_only=True)
    product = await create_test_product(db_session, price=Decimal("10.00"))
    user = await register_and_login(client, "dc")
    await fund_wallet(db_session, user["user_id"], Decimal("100"))

    # A full-price purchase first, so the account is no longer new.
    prior = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET"},
        headers=user["headers"],
    )
    assert prior.status_code == 202
    await wait_for_order(client, prior.json()["id"], user["headers"])

    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET", "discount_code": code["code"]},
        headers=user["headers"],
    )
    assert res.status_code == 400
    assert "first purchase" in res.json()["detail"]


async def test_country_scoped_code_only_applies_there(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    right = await create_test_product(db_session, price=Decimal("15.00"))
    wrong = await create_test_product(db_session, price=Decimal("15.00"))
    code = await _make_code(client, admin, scope="COUNTRY", country_id=right.country_id)

    user = await register_and_login(client, "dc")
    await fund_wallet(db_session, user["user_id"], Decimal("100"))

    bad = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": wrong.id, "payment_method": "WALLET", "discount_code": code["code"]},
        headers=user["headers"],
    )
    assert bad.status_code == 400
    assert "destination" in bad.json()["detail"]

    good = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": right.id, "payment_method": "WALLET", "discount_code": code["code"]},
        headers=user["headers"],
    )
    assert good.status_code == 202, good.text


async def test_product_scoped_code_only_applies_to_that_package(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    right = await create_test_product(db_session, price=Decimal("12.00"))
    wrong = await create_test_product(db_session, price=Decimal("12.00"))
    code = await _make_code(client, admin, scope="PRODUCT", product_id=right.id)

    user = await register_and_login(client, "dc")
    await fund_wallet(db_session, user["user_id"], Decimal("100"))

    bad = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": wrong.id, "payment_method": "WALLET", "discount_code": code["code"]},
        headers=user["headers"],
    )
    assert bad.status_code == 400
    assert "package" in bad.json()["detail"]


async def test_preview_endpoint_reports_the_new_total(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    code = await _make_code(client, admin, value="20")
    product = await create_test_product(db_session, price=Decimal("25.00"))
    user = await register_and_login(client, "dc")

    ok = await client.post(
        "/api/v1/discounts/preview",
        json={"code": code["code"].lower(), "product_id": product.id},  # case-insensitive
        headers=user["headers"],
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["valid"] is True
    assert Decimal(body["discount_amount"]) == Decimal("5.0000")
    assert Decimal(body["total"]) == Decimal("20.0000")

    bad = await client.post(
        "/api/v1/discounts/preview",
        json={"code": "NOT-REAL", "product_id": product.id},
        headers=user["headers"],
    )
    assert bad.status_code == 200
    assert bad.json()["valid"] is False
    assert bad.json()["reason"]

    # A preview alone must not consume anything.
    assert (await client.get(
        f"/api/v1/admin/discounts/{code['id']}/redemptions", headers=admin["headers"]
    )).json() == []


async def test_preview_requires_a_signed_in_user(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    code = await _make_code(client, admin)
    product = await create_test_product(db_session, price=Decimal("10.00"))
    res = await client.post("/api/v1/discounts/preview", json={"code": code["code"], "product_id": product.id})
    assert res.status_code == 401


async def test_commission_follows_the_discounted_price(client, db_session, promote_role):
    """A merchant must not earn commission on revenue the discount gave away."""
    from app.models.merchant import MerchantProfile, MerchantStatus

    admin = await _admin(client, promote_role)
    code = await _make_code(client, admin, value="50")
    product = await create_test_product(db_session, price=Decimal("20.00"))

    merchant = await register_and_login(client, "dcmerchant")
    await promote_role(merchant["user_id"], "MERCHANT")
    db_session.add(MerchantProfile(
        user_id=merchant["user_id"], business_name="Discount Co", contact_phone="+8801700000000",
        status=MerchantStatus.APPROVED, commission_rate_pct=Decimal("10.00"),
    ))
    await db_session.commit()
    await fund_wallet(db_session, merchant["user_id"], Decimal("100"))

    customer = await register_and_login(client, "dcbuyer")
    res = await client.post(
        "/api/v1/orders/checkout",
        json={
            "product_id": product.id, "payment_method": "WALLET", "discount_code": code["code"],
            "is_buy_for_user": True, "beneficiary_email": customer["email"],
        },
        headers=merchant["headers"],
    )
    assert res.status_code == 202, res.text
    order_id = res.json()["id"]
    assert Decimal(res.json()["total_amount"]) == Decimal("10.0000")

    await wait_for_order(client, order_id, merchant["headers"])
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    await db_session.refresh(order)
    assert order.status == OrderStatus.COMPLETED
    # 10% of the discounted 10.00, not of the 20.00 list price.
    assert Decimal(str(order.reseller_commission_amount)) == Decimal("1.0000")


async def test_failed_order_refunds_only_what_was_paid_and_frees_the_code(client, db_session, promote_role, mock_vivape):
    admin = await _admin(client, promote_role)
    code = await _make_code(client, admin, value="50", max_uses=1)
    product = await create_test_product(db_session, price=Decimal("20.00"))
    user = await register_and_login(client, "dc")
    await fund_wallet(db_session, user["user_id"], Decimal("40"))

    mock_vivape.create_transaction.side_effect = Exception("VivaPe down")
    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET", "discount_code": code["code"]},
        headers=user["headers"],
    )
    assert res.status_code == 202, res.text
    settled = await wait_for_order(client, res.json()["id"], user["headers"])
    assert settled["status"] == "FAILED"
    # Refunded the 10.00 actually charged, not the 20.00 list price.
    assert await _balance(db_session, user["user_id"]) == Decimal("40.0000")

    # The failed order gave the single use back, so the code works again.
    mock_vivape.create_transaction.side_effect = None
    mock_vivape.create_transaction.return_value = {"purchase_trx": {"id": 999002}}
    again = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET", "discount_code": code["code"]},
        headers=user["headers"],
    )
    assert again.status_code == 202, again.text


async def test_gateway_checkout_charges_the_discounted_amount(client, db_session, promote_role, monkeypatch):
    admin = await _admin(client, promote_role)
    code = await _make_code(client, admin, value="50")
    product = await create_test_product(db_session, price=Decimal("30.00"))
    user = await register_and_login(client, "dc")

    seen = {}

    async def fake_initiate(db, order_id, amount_bdt, **kwargs):
        seen["order_id"] = order_id
        seen["amount_bdt"] = Decimal(str(amount_bdt))
        return {"checkout_url": "https://example.test/pay", "sp_order_id": "sp-test-1"}

    from app.services.shurjopay_svc import ShurjoPayService
    monkeypatch.setattr(ShurjoPayService, "initiate_payment", fake_initiate)

    res = await client.post(
        "/api/v1/payments/shurjopay/order-initiate",
        json={"product_id": product.id, "payment_method": "SHURJOPAY", "discount_code": code["code"]},
        headers=user["headers"],
    )
    assert res.status_code == 200, res.text

    order = (await db_session.execute(select(Order).where(Order.id == res.json()["order_id"]))).scalar_one()
    await db_session.refresh(order)
    assert Decimal(str(order.total_amount)) == Decimal("15.0000")
    assert Decimal(str(order.discount_amount)) == Decimal("15.0000")
    assert order.status == OrderStatus.PENDING

    # The gateway was asked for the discounted amount, converted to BDT.
    from app.services.currency_svc import CurrencyService
    rate = await CurrencyService.get_effective_rate(db_session, "BDT")
    assert seen["amount_bdt"] == (Decimal("15.0000") * rate).quantize(Decimal("0.0001"))


async def test_one_code_per_order_is_all_the_request_can_carry(client, db_session, promote_role):
    """The API takes a single code field; the database also refuses a second
    redemption for the same order."""
    from app.models.discount import DiscountRedemption

    admin = await _admin(client, promote_role)
    code_a = await _make_code(client, admin, value="10")
    code_b = await _make_code(client, admin, value="20")
    product = await create_test_product(db_session, price=Decimal("20.00"))
    user = await register_and_login(client, "dc")
    await fund_wallet(db_session, user["user_id"], Decimal("100"))

    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET", "discount_code": code_a["code"]},
        headers=user["headers"],
    )
    order_id = res.json()["id"]

    db_session.add(DiscountRedemption(
        discount_code_id=code_b["id"], user_id=user["user_id"], order_id=order_id, discount_amount=Decimal("4"),
    ))
    with pytest.raises(Exception):
        await db_session.commit()
    await db_session.rollback()


async def test_admin_crud_and_usage_figures(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    code = await _make_code(client, admin, value="10", description="Launch campaign")

    listed = await client.get("/api/v1/admin/discounts", headers=admin["headers"])
    assert listed.status_code == 200
    mine = next(c for c in listed.json() if c["id"] == code["id"])
    assert mine["description"] == "Launch campaign"
    assert mine["times_used"] == 0

    edited = await client.put(
        f"/api/v1/admin/discounts/{code['id']}",
        json={"code": code["code"], "discount_type": "PERCENT", "value": "15", "is_active": True},
        headers=admin["headers"],
    )
    assert edited.status_code == 200, edited.text
    assert Decimal(edited.json()["value"]) == Decimal("15.0000")

    duplicate = await client.post(
        "/api/v1/admin/discounts",
        json={"code": code["code"].lower(), "discount_type": "PERCENT", "value": "5"},
        headers=admin["headers"],
    )
    assert duplicate.status_code == 400
    assert "already exists" in duplicate.json()["detail"]

    over_100 = await client.post(
        "/api/v1/admin/discounts",
        json={"code": "TOOMUCH1", "discount_type": "PERCENT", "value": "150"},
        headers=admin["headers"],
    )
    assert over_100.status_code == 400

    # Unused: really deleted.
    gone = await client.delete(f"/api/v1/admin/discounts/{code['id']}", headers=admin["headers"])
    assert gone.status_code == 200, gone.text
    assert gone.json()["deleted"] is True


async def test_a_used_code_is_switched_off_not_deleted(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    code = await _make_code(client, admin, value="10")
    product = await create_test_product(db_session, price=Decimal("10.00"))
    user = await register_and_login(client, "dc")
    await fund_wallet(db_session, user["user_id"], Decimal("50"))
    await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET", "discount_code": code["code"]},
        headers=user["headers"],
    )

    res = await client.delete(f"/api/v1/admin/discounts/{code['id']}", headers=admin["headers"])
    assert res.status_code == 200, res.text
    assert res.json()["deleted"] is False

    listed = (await client.get("/api/v1/admin/discounts", headers=admin["headers"])).json()
    still_there = next(c for c in listed if c["id"] == code["id"])
    assert still_there["is_active"] is False
    assert still_there["times_used"] == 1
    assert Decimal(still_there["discount_given"]) == Decimal("1.00")

    redemptions = (await client.get(
        f"/api/v1/admin/discounts/{code['id']}/redemptions", headers=admin["headers"]
    )).json()
    assert len(redemptions) == 1
    assert redemptions[0]["username"] == user["username"]


async def test_discounts_are_admin_only(client, db_session):
    user = await register_and_login(client, "dc")
    assert (await client.get("/api/v1/admin/discounts", headers=user["headers"])).status_code == 403
    assert (await client.post(
        "/api/v1/admin/discounts",
        json={"code": "SNEAKY99", "discount_type": "PERCENT", "value": "90"},
        headers=user["headers"],
    )).status_code == 403


async def test_sales_report_filters_and_totals_by_code(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    code = await _make_code(client, admin, value="50")
    product = await create_test_product(db_session, price=Decimal("20.00"))
    user = await register_and_login(client, "dc")
    await fund_wallet(db_session, user["user_id"], Decimal("100"))

    discounted = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET", "discount_code": code["code"]},
        headers=user["headers"],
    )
    await wait_for_order(client, discounted.json()["id"], user["headers"])
    full_price = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET"},
        headers=user["headers"],
    )
    await wait_for_order(client, full_price.json()["id"], user["headers"])

    only_code = (await client.get(
        f"/api/v1/admin/reports/sales?discount_code={code['code']}", headers=admin["headers"]
    )).json()
    assert only_code["totals"]["orders"] == 1
    assert Decimal(only_code["totals"]["discount"]) == Decimal("10.00")
    assert Decimal(only_code["totals"]["selling_price"]) == Decimal("10.00")
    assert Decimal(only_code["totals"]["list_price"]) == Decimal("20.00")
    row = only_code["rows"][0]
    assert row["discount_code"] == code["code"]
    assert Decimal(row["discount"]) == Decimal("10.00")
    # Profit is on what was actually received, so the discount is already in it.
    assert Decimal(row["profit"]) == Decimal("5.00")

    none_at_all = (await client.get(
        "/api/v1/admin/reports/sales?discount_code=NONE&q=" + product.title_en, headers=admin["headers"]
    )).json()
    assert all(r["discount_code"] is None for r in none_at_all["rows"])

    breakdown = (await client.get(
        f"/api/v1/admin/reports/sales/breakdown?discount_code={code['code']}", headers=admin["headers"]
    )).json()
    by_code = {c["code"]: c for c in breakdown["by_discount_code"]}
    assert by_code[code["code"]]["orders"] == 1
    assert Decimal(by_code[code["code"]]["discount"]) == Decimal("10.00")
    assert code["code"] in breakdown["discount_code_options"]

    csv_bytes = await client.get(
        f"/api/v1/admin/reports/sales.csv?discount_code={code['code']}", headers=admin["headers"]
    )
    assert csv_bytes.status_code == 200
    text = csv_bytes.text
    assert "Discount code" in text
    assert code["code"] in text
