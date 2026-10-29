"""The support lookup: find one eSIM from whatever the customer has.

Support is handed an ICCID read off a phone screen, or an order number
from an email, or just the phone number they called from. One box has to
match all of them, including partial ICCIDs - nobody reads out all 20
digits correctly.
"""
from decimal import Decimal

import pytest

from app.models.order import ESIMProfile, Order, OrderStatus, PaymentMethod
from app.services.esim_search_svc import esim_counts, search_esims
from conftest import create_test_product, register_and_login

pytestmark = pytest.mark.asyncio


async def _delivered(db_session, user, product, *, iccid, order_no):
    order = Order(
        order_no=order_no, buyer_id=user["user_id"], beneficiary_id=user["user_id"],
        product_id=product.id, total_amount=Decimal("7.55"), payment_method=PaymentMethod.WALLET,
        status=OrderStatus.COMPLETED, external_trx_id="60999",
    )
    db_session.add(order)
    await db_session.flush()
    profile = ESIMProfile(
        order_id=order.id, beneficiary_id=user["user_id"], iccid=iccid,
        lpa_string=f"LPA:1$rsp.example.com${iccid[-6:]}",
    )
    db_session.add(profile)
    await db_session.commit()
    return order, profile


async def test_finds_an_esim_by_full_iccid(client, db_session):
    user = await register_and_login(client, "searchcust")
    product = await create_test_product(db_session)
    _, profile = await _delivered(db_session, user, product, iccid="89862100000000001111", order_no="ORD-SEARCH-1")

    res = await search_esims(db_session, query="89862100000000001111")
    assert profile.id in [i["esim_id"] for i in res["items"]]


async def test_finds_an_esim_by_a_partial_iccid(client, db_session):
    """An admin reading digits off a customer screen has the tail, not all
    twenty - an exact-match-only search would be useless on the phone."""
    user = await register_and_login(client, "partialcust")
    product = await create_test_product(db_session)
    _, profile = await _delivered(db_session, user, product, iccid="89862100000000002222", order_no="ORD-SEARCH-2")

    res = await search_esims(db_session, query="0002222")
    assert profile.id in [i["esim_id"] for i in res["items"]]


async def test_finds_by_order_number_email_and_phone(client, db_session):
    user = await register_and_login(client, "multicust")
    product = await create_test_product(db_session)
    order, _ = await _delivered(db_session, user, product, iccid="89862100000000003333", order_no="ORD-SEARCH-3")

    by_order = await search_esims(db_session, query="ORD-SEARCH-3")
    assert order.order_no in [i["order_no"] for i in by_order["items"]]

    by_email = await search_esims(db_session, query=user["email"])
    assert order.order_no in [i["order_no"] for i in by_email["items"]]

    # register_and_login sets this phone on every test account.
    by_phone = await search_esims(db_session, query="8801700000000")
    assert order.order_no in [i["order_no"] for i in by_phone["items"]]


async def test_an_order_with_no_esim_yet_still_shows_up(client, db_session):
    """A customer chasing an order that never provisioned is exactly who
    support needs to find, so these must not be filtered out by the join."""
    user = await register_and_login(client, "noesimcust")
    product = await create_test_product(db_session)
    order = Order(
        order_no="ORD-SEARCH-NOESIM", buyer_id=user["user_id"], beneficiary_id=user["user_id"],
        product_id=product.id, total_amount=Decimal("7.55"), payment_method=PaymentMethod.WALLET,
        status=OrderStatus.FAILED,
    )
    db_session.add(order)
    await db_session.commit()

    res = await search_esims(db_session, query="ORD-SEARCH-NOESIM")
    assert len(res["items"]) == 1
    assert res["items"][0]["iccid"] is None
    assert res["items"][0]["order_status"] == "FAILED"


async def test_results_are_capped(client, db_session):
    res = await search_esims(db_session, limit=500)
    assert res["capped_at"] <= 50


async def test_counts_report_installed_and_never_installed(client, db_session):
    user = await register_and_login(client, "countcust")
    product = await create_test_product(db_session)
    await _delivered(db_session, user, product, iccid="89862100000000004444", order_no="ORD-SEARCH-4")

    counts = await esim_counts(db_session)
    assert counts["total_esims"] >= 1
    # No telemetry row was created, so it counts as never installed rather
    # than being silently missing from both figures.
    assert counts["never_installed"] >= 1
    assert counts["total_esims"] >= counts["installed"]


async def test_search_requires_admin(client, db_session):
    res = await client.get("/api/v1/admin/esims/search?query=x")
    assert res.status_code in (401, 403)
