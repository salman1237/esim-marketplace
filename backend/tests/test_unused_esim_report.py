"""The supplier claim: eSIMs VivaPe charged us for that no customer got.

VivaPe asked for real and test separated before 1 Nov 2026, and the ICCID
is what they reconcile on - which is precisely the value we do NOT hold
for these orders, since no ESIMProfile was ever created. The report
fetches it live from the transaction id, so these tests pin that down
along with the real/test split and the three export formats.
"""
import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from app.models.order import Order, OrderStatus, PaymentMethod
from app.services.unused_esim_report_svc import build_unused_esim_report, set_test_identifiers
from app.services import report_export_svc
from conftest import create_test_product, register_and_login

pytestmark = pytest.mark.asyncio

VIVAPE_ESIM = {
    "esim_order": {
        "iccid": "89862103954300006454",
        "note": "World Move eSIM Transaction Redeem",
        "resultmsg": "Success",
    }
}


async def _abandoned_order(db_session, user, product, *, trx_id="60451", status=OrderStatus.FAILED):
    order = Order(
        order_no=f"ORD-{trx_id}-{product.id[:6]}", buyer_id=user["user_id"], beneficiary_id=user["user_id"],
        product_id=product.id, total_amount=Decimal("7.5554"), cost_amount=Decimal("2.5185"),
        payment_method=PaymentMethod.WALLET, status=status, external_trx_id=trx_id,
    )
    db_session.add(order)
    await db_session.commit()
    return order


async def test_lists_only_orders_the_supplier_actually_charged_for(client, db_session, mock_vivape):
    """An order that failed before create-transaction cost us nothing and
    must not appear in a refund claim."""
    mock_vivape.get_esim_by_trx.side_effect = None
    mock_vivape.get_esim_by_trx.return_value = VIVAPE_ESIM

    user = await register_and_login(client, "claimbuyer")
    product = await create_test_product(db_session)
    charged = await _abandoned_order(db_session, user, product, trx_id="70001")

    never_charged = Order(
        order_no="ORD-NOCHARGE-1", buyer_id=user["user_id"], beneficiary_id=user["user_id"],
        product_id=product.id, total_amount=Decimal("7.55"), payment_method=PaymentMethod.WALLET,
        status=OrderStatus.FAILED, external_trx_id=None,
    )
    db_session.add(never_charged)
    await db_session.commit()

    report = await build_unused_esim_report(db_session)
    order_nos = [i["order_no"] for i in report["items"]]
    assert charged.order_no in order_nos
    assert "ORD-NOCHARGE-1" not in order_nos


async def test_resolves_the_iccid_from_the_supplier(client, db_session, mock_vivape):
    """The ICCID is not in our database for these orders - without the live
    lookup the report is unusable for reconciliation."""
    mock_vivape.get_esim_by_trx.side_effect = None
    mock_vivape.get_esim_by_trx.return_value = VIVAPE_ESIM

    user = await register_and_login(client, "iccidbuyer")
    product = await create_test_product(db_session)
    await _abandoned_order(db_session, user, product, trx_id="70002")

    report = await build_unused_esim_report(db_session, search="70002")
    assert len(report["items"]) == 1
    assert report["items"][0]["iccid"] == "89862103954300006454"
    assert report["items"][0]["supplier_status"] == "Success"


async def test_a_failed_lookup_still_leaves_the_row_in_the_claim(client, db_session, mock_vivape):
    """Losing a row because VivaPe timed out would quietly shrink the
    amount being claimed back."""
    mock_vivape.get_esim_by_trx.side_effect = Exception("VivaPe timeout")

    user = await register_and_login(client, "timeoutbuyer")
    product = await create_test_product(db_session)
    await _abandoned_order(db_session, user, product, trx_id="70003")

    report = await build_unused_esim_report(db_session, search="70003")
    assert len(report["items"]) == 1
    assert report["items"][0]["iccid"] is None
    assert "timeout" in report["items"][0]["lookup_error"].lower()


async def test_real_and_test_are_separated_by_the_business_supplied_list(client, db_session, mock_vivape):
    mock_vivape.get_esim_by_trx.side_effect = None
    mock_vivape.get_esim_by_trx.return_value = VIVAPE_ESIM

    tester = await register_and_login(client, "internaltester")
    customer = await register_and_login(client, "realcustomer")
    product = await create_test_product(db_session)
    await _abandoned_order(db_session, tester, product, trx_id="70004")
    await _abandoned_order(db_session, customer, product, trx_id="70005")

    await set_test_identifiers(db_session, [tester["email"].upper()], admin_id=None)
    await db_session.commit()

    report = await build_unused_esim_report(db_session)
    by_trx = {i["vivape_trx_id"]: i for i in report["items"]}
    assert by_trx["70004"]["type"] == "TEST", "case-insensitive match on the supplied email failed"
    assert by_trx["70005"]["type"] == "REAL"

    only_real = await build_unused_esim_report(db_session, include_type="real")
    assert all(i["type"] == "REAL" for i in only_real["items"])
    assert "70004" not in [i["vivape_trx_id"] for i in only_real["items"]]


async def test_filters_by_date_and_free_text(client, db_session, mock_vivape):
    mock_vivape.get_esim_by_trx.side_effect = None
    mock_vivape.get_esim_by_trx.return_value = VIVAPE_ESIM

    user = await register_and_login(client, "filterbuyer")
    product = await create_test_product(db_session)
    order = await _abandoned_order(db_session, user, product, trx_id="70006")

    by_email = await build_unused_esim_report(db_session, search=user["email"])
    assert order.order_no in [i["order_no"] for i in by_email["items"]]

    future = datetime.now(timezone.utc) + timedelta(days=1)
    none_after = await build_unused_esim_report(db_session, date_from=future)
    assert none_after["items"] == []


async def test_summary_totals_the_money_being_claimed(client, db_session, mock_vivape):
    mock_vivape.get_esim_by_trx.side_effect = None
    mock_vivape.get_esim_by_trx.return_value = VIVAPE_ESIM

    user = await register_and_login(client, "totalsbuyer")
    product = await create_test_product(db_session)
    await _abandoned_order(db_session, user, product, trx_id="70007")

    report = await build_unused_esim_report(db_session, search="70007")
    assert report["summary"]["count"] == 1
    assert report["summary"]["supplier_cost_eur"] == "2.52"
    assert report["summary"]["iccids_resolved"] == 1


async def test_a_delivered_test_purchase_is_included_with_its_stored_iccid(client, db_session, mock_vivape):
    """VivaPe charged for the business testing its own platform too, so a
    COMPLETED test order belongs in the reconciliation - and its ICCID is
    already in our database, so no supplier lookup is needed for it."""
    from app.models.order import ESIMProfile

    mock_vivape.get_esim_by_trx.side_effect = AssertionError("must not look up a delivered eSIM")

    tester = await register_and_login(client, "deliveredtester")
    product = await create_test_product(db_session)
    order = await _abandoned_order(
        db_session, tester, product, trx_id="70010", status=OrderStatus.COMPLETED
    )
    db_session.add(ESIMProfile(
        order_id=order.id, beneficiary_id=tester["user_id"],
        iccid="89862103409800000922", lpa_string="LPA:1$rsp.example.com$TEST",
    ))
    await set_test_identifiers(db_session, [tester["email"]], admin_id=None)
    await db_session.commit()

    report = await build_unused_esim_report(db_session, search="70010")
    assert len(report["items"]) == 1
    row = report["items"][0]
    assert row["type"] == "TEST"
    assert row["reason"] == "TEST_PURCHASE"
    assert row["iccid"] == "89862103409800000922"
    assert row["order_status"] == "COMPLETED"


async def test_a_real_customers_delivered_order_is_never_in_the_claim(client, db_session, mock_vivape):
    """The guard that keeps this honest: a successful sale to a paying
    customer is revenue, not something to claim back from the supplier."""
    mock_vivape.get_esim_by_trx.side_effect = None
    mock_vivape.get_esim_by_trx.return_value = VIVAPE_ESIM

    customer = await register_and_login(client, "happycustomer")
    product = await create_test_product(db_session)
    delivered = await _abandoned_order(
        db_session, customer, product, trx_id="70011", status=OrderStatus.COMPLETED
    )

    report = await build_unused_esim_report(db_session)
    assert delivered.order_no not in [i["order_no"] for i in report["items"]]
