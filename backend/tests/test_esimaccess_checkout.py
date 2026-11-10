"""checkout_svc.py's eSIM Access branch (_provision_via_esimaccess,
_complete_esimaccess_from_order_no) - the piece that makes a synced eSIM
Access Product actually purchasable, not just visible. Without this, a
product with supplier_reference="esimaccess" would hit provision_esim's old
VivaPe-only branch, find no supplier_product_id, and silently refund every
purchase - exactly the gap this file exists to prevent from reaching
production. See checkout_svc.py's _provision_via_esimaccess docstring for
what's confirmed live vs. structurally mirrored from VivaPe's own branch.

Follows the same pattern as test_async_esim_provisioning.py (the WorldMove
async-provisioning regression tests): provision_esim/complete_from_supplier_
trx are called directly against a hand-built Order rather than through the
HTTP checkout endpoint, because real provisioning runs in a background task
on a separate timeline from the request/response cycle - asserting on
order.status right after a client.post would be racing that task, not
testing it deterministically. monkeypatch shrinks _ESIM_READY_POLL_DELAYS to
(0,) * N so the real retry loop still runs (proving the polling logic
itself, not bypassing it) without real sleeps slowing the test down.
"""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.catalog import Country, Product
from app.models.order import ESIMProfile, Order, OrderStatus, PaymentMethod
from app.models.wallet import Wallet, WalletType
from app.services import checkout_svc
from app.services.esimaccess_adapter import ESIMAccessError
from conftest import register_and_login

pytestmark = pytest.mark.asyncio


async def _esimaccess_product(db_session, cost_price=Decimal("0.3000")) -> Product:
    suffix = uuid.uuid4().hex[:6]
    country = Country(
        id=int(uuid.uuid4().int % 1_000_000_000),
        iso2=f"T{suffix.upper()}",
        name_en=f"Testland {suffix}",
        is_active=True,
    )
    db_session.add(country)
    await db_session.flush()

    product = Product(
        id=str(uuid.uuid4()),
        country_id=country.id,
        title_en=f"Testland {suffix} 1GB 7Days",
        data_amount_gb=Decimal("1.00"),
        validity_days=7,
        cost_price=cost_price,
        retail_price=cost_price * Decimal("1.25"),
        currency="USD",
        is_unlimited=False,
        supplier_reference="esimaccess",
        supplier_package_code=f"PKG{suffix.upper()}",
    )
    db_session.add(product)
    await db_session.flush()
    return product


async def _order_for(db_session, product, user_id) -> Order:
    order = Order(
        order_no=f"TST-{product.id[:8]}", buyer_id=user_id, beneficiary_id=user_id,
        product_id=product.id, total_amount=product.retail_price,
        payment_method=PaymentMethod.WALLET, status=OrderStatus.PROCESSING,
    )
    db_session.add(order)
    await db_session.commit()
    return order


async def _default_balance(db_session, user_id) -> Decimal:
    wallet = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.DEFAULT)
    )).scalar_one()
    return Decimal(str(wallet.balance))


# --- the happy path -----------------------------------------------------

async def test_provision_esim_dispatches_to_esimaccess_and_builds_a_real_profile(client, db_session, mock_esimaccess):
    """The core thing this whole branch exists for: a synced eSIM Access
    product must actually deliver an eSIM, not just look purchasable."""
    user = await register_and_login(client, "esimaccessbuyer")
    product = await _esimaccess_product(db_session)
    order = await _order_for(db_session, product, user["user_id"])

    profile = await checkout_svc.provision_esim(
        db_session, order, product, user["user_id"], user["user_id"], "USER"
    )
    await db_session.commit()

    assert profile is not None
    assert order.status == OrderStatus.COMPLETED
    assert order.external_trx_id and order.external_trx_id.startswith("B")

    stored = (await db_session.execute(
        select(ESIMProfile).where(ESIMProfile.order_id == order.id)
    )).scalar_one()
    assert stored.iccid
    assert stored.lpa_string.startswith("LPA:1$")
    assert stored.smdp_address == "rsp-eu.simlessly.com"
    assert stored.matching_id
    # supplier_reference on the PROFILE holds eSIM Access's orderNo (the
    # identifier later needed to re-query status) - same role VivaPe's
    # trx_id plays there.
    assert stored.supplier_reference == order.external_trx_id

    mock_esimaccess.create_order.assert_awaited_once()
    mock_esimaccess.query_esim.assert_awaited()
    _, query_kwargs = mock_esimaccess.query_esim.call_args
    assert query_kwargs["order_no"] == order.external_trx_id


async def test_create_order_is_called_with_the_products_own_package_code_and_cost(client, db_session, mock_esimaccess):
    user = await register_and_login(client, "esimaccesspayload")
    product = await _esimaccess_product(db_session, cost_price=Decimal("0.3000"))
    order = await _order_for(db_session, product, user["user_id"])

    await checkout_svc.provision_esim(db_session, order, product, user["user_id"], user["user_id"], "USER")

    _, kwargs = mock_esimaccess.create_order.call_args
    assert kwargs["package_code"] == product.supplier_package_code
    assert kwargs["amount_scaled"] == 3000  # $0.30 -> x10,000 encoding


async def test_create_order_passes_the_products_period_num_for_a_day_pass(client, db_session, mock_esimaccess):
    """A Day Pass product is synced with supplier_period_num set to the
    specific duration variant (see catalog_parsing.py); checkout must pass
    that through to create_order so eSIM Access knows which duration was
    bought, not just which package code."""
    user = await register_and_login(client, "esimaccessdaypass")
    product = await _esimaccess_product(db_session)
    product.supplier_period_num = 7
    await db_session.flush()
    order = await _order_for(db_session, product, user["user_id"])

    await checkout_svc.provision_esim(db_session, order, product, user["user_id"], user["user_id"], "USER")

    _, kwargs = mock_esimaccess.create_order.call_args
    assert kwargs["period_num"] == 7


async def test_create_order_passes_none_period_num_for_fixed_data(client, db_session, mock_esimaccess):
    user = await register_and_login(client, "esimaccessfixed")
    product = await _esimaccess_product(db_session)
    assert product.supplier_period_num is None
    order = await _order_for(db_session, product, user["user_id"])

    await checkout_svc.provision_esim(db_session, order, product, user["user_id"], user["user_id"], "USER")

    _, kwargs = mock_esimaccess.create_order.call_args
    assert kwargs["period_num"] is None


async def test_transaction_id_is_the_orders_own_id_for_idempotent_retries(client, db_session, mock_esimaccess):
    """Unlike VivaPe (no idempotency key at all), eSIM Access's
    transactionId is designed to be reused on a retry - using order.id
    means a retried provisioning attempt for the SAME order sends the
    identical transactionId, which is what makes that protection apply."""
    user = await register_and_login(client, "esimaccesstxnid")
    product = await _esimaccess_product(db_session)
    order = await _order_for(db_session, product, user["user_id"])

    await checkout_svc.provision_esim(db_session, order, product, user["user_id"], user["user_id"], "USER")

    _, kwargs = mock_esimaccess.create_order.call_args
    assert kwargs["transaction_id"] == order.id


# --- failure / refund paths ----------------------------------------------

async def test_create_order_failure_refunds_and_never_calls_query_esim(client, db_session, mock_esimaccess):
    """eSIM Access never took the money (the call itself failed) - must
    refund in full, and must not poll for an eSIM that was never ordered."""
    mock_esimaccess.create_order.side_effect = ESIMAccessError("eSIM Access business error: insufficient balance")

    user = await register_and_login(client, "esimaccessfail")
    product = await _esimaccess_product(db_session)
    order = await _order_for(db_session, product, user["user_id"])
    balance_before = await _default_balance(db_session, user["user_id"])

    profile = await checkout_svc.provision_esim(
        db_session, order, product, user["user_id"], user["user_id"], "USER"
    )
    await db_session.commit()

    assert profile is None
    await db_session.refresh(order)
    assert order.status == OrderStatus.FAILED
    # Proves the eSIM Access path was actually entered - a product with no
    # supplier_product_id would ALSO end up FAILED/refunded via the old
    # VivaPe branch's own no-supplier-mapping fallback, so without this the
    # test would still pass if provision_esim's dispatch to
    # _provision_via_esimaccess were ever removed (caught live: deliberately
    # disabling that dispatch left this test green).
    mock_esimaccess.create_order.assert_awaited_once()
    mock_esimaccess.query_esim.assert_not_awaited()
    # _refund_failed_order credits back order.total_amount - since nothing
    # debited the wallet in this direct-provision_esim test (that happens
    # in the real /orders/checkout handler, not here), the refund just adds
    # to whatever was already there.
    assert await _default_balance(db_session, user["user_id"]) == balance_before + Decimal(str(order.total_amount))


async def test_create_order_with_no_order_no_refunds(client, db_session, mock_esimaccess):
    """A 200/success response that somehow carries no orderNo at all is
    treated the same as an outright failure - there is nothing to poll."""
    mock_esimaccess.create_order.side_effect = None
    mock_esimaccess.create_order.return_value = {"transactionId": "whatever"}  # no orderNo

    user = await register_and_login(client, "esimaccessnoorderno")
    product = await _esimaccess_product(db_session)
    order = await _order_for(db_session, product, user["user_id"])

    profile = await checkout_svc.provision_esim(
        db_session, order, product, user["user_id"], user["user_id"], "USER"
    )
    await db_session.commit()

    assert profile is None
    await db_session.refresh(order)
    assert order.status == OrderStatus.FAILED
    # Same reasoning as the sibling test above: proves the eSIM Access path
    # was actually entered, not just that some refund happened.
    mock_esimaccess.create_order.assert_awaited_once()
    mock_esimaccess.query_esim.assert_not_awaited()


async def test_esim_not_ready_after_all_polls_leaves_order_processing_unrefunded(client, db_session, mock_esimaccess, monkeypatch):
    """eSIM Access HAS already been asked to charge us once create_order
    succeeds (order_no in hand) - refunding here is exactly the mistake
    that bought and abandoned real eSIMs on VivaPe (see
    vivape-vs-esimaccess.tex's EUR28.61 finding). Must stay PROCESSING for
    recovery, not fail/refund just because every poll came back empty."""
    monkeypatch.setattr("app.services.checkout_svc._ESIM_READY_POLL_DELAYS", (0, 0))
    mock_esimaccess.query_esim.side_effect = None
    mock_esimaccess.query_esim.return_value = {"esimList": []}

    user = await register_and_login(client, "esimaccessnotready")
    product = await _esimaccess_product(db_session)
    order = await _order_for(db_session, product, user["user_id"])
    balance_before = await _default_balance(db_session, user["user_id"])

    profile = await checkout_svc.provision_esim(
        db_session, order, product, user["user_id"], user["user_id"], "USER"
    )
    await db_session.commit()

    assert profile is None
    await db_session.refresh(order)
    assert order.status == OrderStatus.PROCESSING, "a paid-for order was failed instead of left for recovery"
    assert order.external_trx_id, "lost the supplier order number - the eSIM would be unrecoverable"
    assert await _default_balance(db_session, user["user_id"]) == balance_before, "refunded an eSIM we had already paid for"


async def test_a_transient_business_error_while_polling_is_not_ready_not_a_failure(client, db_session, mock_esimaccess, monkeypatch):
    """Reproduces a real bug, live on beta (2026-11-10): a genuine customer
    purchase (Bangladesh, 1-day package) was refunded on the very first
    poll because eSIM Access answered errorCode 200010 ("the batchOrder
    has been getting resource... success:[0]") before provisioning
    finished - confirmed in production logs. call_api() correctly raises
    ESIMAccessError for any non-success response (that discipline is
    right - see its own docstring), but an earlier version of the polling
    loop had no try/except around query_esim, so that exception escaped
    straight past the loop to the outer handler and refunded an order
    eSIM Access had already been paid for, exactly like refunding on an
    empty esimList used to. Proves the eventual-success case: the first
    poll errors with 200010, the second succeeds, and the order completes
    with no refund anywhere in between."""
    monkeypatch.setattr("app.services.checkout_svc._ESIM_READY_POLL_DELAYS", (0, 0, 0))
    mock_esimaccess.query_esim.side_effect = [
        ESIMAccessError("eSIM Access business error on esim/query: errorCode='200010' errorMsg='the batchOrder has been getting resource, total:[1], success:[0]'"),
        {"esimList": [{"iccid": "89480100100541800", "ac": "LPA:1$rsp-eu.simlessly.com$ABCDEF123456"}]},
    ]

    user = await register_and_login(client, "esimaccesstransienterr")
    product = await _esimaccess_product(db_session)
    order = await _order_for(db_session, product, user["user_id"])
    balance_before = await _default_balance(db_session, user["user_id"])

    profile = await checkout_svc.provision_esim(
        db_session, order, product, user["user_id"], user["user_id"], "USER"
    )
    await db_session.commit()

    assert profile is not None
    await db_session.refresh(order)
    assert order.status == OrderStatus.COMPLETED
    assert await _default_balance(db_session, user["user_id"]) == balance_before, "a successful purchase must not also refund"
    assert mock_esimaccess.query_esim.call_count == 2


async def test_only_transient_errors_during_polling_exhausts_to_processing_not_failed(client, db_session, mock_esimaccess, monkeypatch):
    """The other half of the same fix: if EVERY poll errors (not just the
    first), the order must still end up PROCESSING for recovery, never
    FAILED/refunded - the supplier has already been paid regardless of
    how many of our own polls come back inconclusive."""
    monkeypatch.setattr("app.services.checkout_svc._ESIM_READY_POLL_DELAYS", (0, 0))
    mock_esimaccess.query_esim.side_effect = ESIMAccessError(
        "eSIM Access business error on esim/query: errorCode='200010' errorMsg='still allocating'"
    )

    user = await register_and_login(client, "esimaccessallerrors")
    product = await _esimaccess_product(db_session)
    order = await _order_for(db_session, product, user["user_id"])
    balance_before = await _default_balance(db_session, user["user_id"])

    profile = await checkout_svc.provision_esim(
        db_session, order, product, user["user_id"], user["user_id"], "USER"
    )
    await db_session.commit()

    assert profile is None
    await db_session.refresh(order)
    assert order.status == OrderStatus.PROCESSING, "a paid-for order was failed instead of left for recovery"
    assert order.external_trx_id
    assert await _default_balance(db_session, user["user_id"]) == balance_before, "refunded an eSIM we had already paid for"


async def test_recovery_treats_a_transient_business_error_as_not_ready_too(client, db_session, mock_esimaccess):
    """Same fix, same reasoning, for the crash-recovery path
    (complete_from_supplier_trx) - a transient query_esim error here must
    raise EsimNotReadyYet, not an unhandled ESIMAccessError
    recover_stuck_orders has no reason to expect from this function."""
    mock_esimaccess.query_esim.side_effect = ESIMAccessError(
        "eSIM Access business error on esim/query: errorCode='200010' errorMsg='still allocating'"
    )

    user = await register_and_login(client, "esimaccessrecoveryerr")
    product = await _esimaccess_product(db_session)
    order = await _order_for(db_session, product, user["user_id"])
    order.external_trx_id = "B26111099999997"
    await db_session.commit()

    with pytest.raises(checkout_svc.EsimNotReadyYet):
        await checkout_svc.complete_from_supplier_trx(db_session, order, product, actor_id=None, actor_role="SYSTEM")
    assert order.status == OrderStatus.PROCESSING


# --- crash recovery --------------------------------------------------------

async def test_recovery_queries_by_order_no_and_never_calls_create_order_again(client, db_session, mock_esimaccess):
    """complete_from_supplier_trx is what recover_stuck_orders calls for an
    order whose external_trx_id is already set - it must never place a
    second order for the same purchase."""
    user = await register_and_login(client, "esimaccessrecovery1")
    product = await _esimaccess_product(db_session)
    order = await _order_for(db_session, product, user["user_id"])
    order.external_trx_id = "B26111099999999"
    await db_session.commit()

    profile = await checkout_svc.complete_from_supplier_trx(db_session, order, product, actor_id=None, actor_role="SYSTEM")

    assert profile is not None
    assert order.status == OrderStatus.COMPLETED
    mock_esimaccess.create_order.assert_not_awaited()
    _, kwargs = mock_esimaccess.query_esim.call_args
    assert kwargs.get("order_no") == "B26111099999999"


async def test_recovery_raises_not_ready_rather_than_refunding_when_still_pending(client, db_session, mock_esimaccess):
    mock_esimaccess.query_esim.side_effect = None
    mock_esimaccess.query_esim.return_value = {"esimList": []}

    user = await register_and_login(client, "esimaccessrecovery2")
    product = await _esimaccess_product(db_session)
    order = await _order_for(db_session, product, user["user_id"])
    order.external_trx_id = "B26111099999998"
    await db_session.commit()

    with pytest.raises(checkout_svc.EsimNotReadyYet):
        await checkout_svc.complete_from_supplier_trx(db_session, order, product, actor_id=None, actor_role="SYSTEM")
    assert order.status == OrderStatus.PROCESSING  # untouched - caller decides what happens next
