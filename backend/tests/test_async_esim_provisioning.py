"""A supplier that hasn't issued the eSIM YET must not be treated as a failure.

Production, 28 Oct 2026: WorldMove provisions asynchronously and answers
"World Move eSIM Transaction Pending" with a null iccid for the first
seconds. The old code asked once, ~300ms after paying, took the null as a
dead answer, refunded the customer and walked away from an eSIM VivaPe had
already charged for. One customer retried five times and bought five of
them; seven were abandoned in total.

The rule these tests pin down: once the supplier has taken the money (we
hold a transaction id), the order is NEVER refunded on the strength of one
look - it stays PROCESSING for recover_stuck_orders to finish.
"""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.order import Order, OrderStatus, PaymentMethod
from app.models.wallet import Wallet, WalletType
from app.services.checkout_svc import EsimNotReadyYet, complete_from_supplier_trx, provision_esim
from app.models.user import User
from conftest import create_test_product, register_and_login

pytestmark = pytest.mark.asyncio

# The real payload, captured from production trx 60451.
WORLDMOVE_PENDING = {
    "esim_order": {
        "id": 387, "iccid": None, "qrcode": None, "qrcodeContent": None,
        "orderId": "b0001cd2610280004", "purchase_id": 60451,
        "note": "World Move eSIM Transaction Pending",
        "resultmsg": None,
    }
}


async def _order_for(db_session, client, product, user):
    order = Order(
        order_no=f"TST-{product.id[:8]}", buyer_id=user["user_id"], beneficiary_id=user["user_id"],
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


async def test_a_pending_esim_is_not_refunded_and_stays_processing(client, db_session, mock_vivape, monkeypatch):
    """The core regression. VivaPe charged us; the eSIM is merely not ready."""
    monkeypatch.setattr("app.services.checkout_svc._ESIM_READY_POLL_DELAYS", (0, 0))
    mock_vivape.get_esim_by_trx.side_effect = None
    mock_vivape.get_esim_by_trx.return_value = WORLDMOVE_PENDING

    user = await register_and_login(client, "pendingbuyer")
    product = await create_test_product(db_session)
    order = await _order_for(db_session, client, product, user)
    balance_before = await _default_balance(db_session, user["user_id"])

    profile = await provision_esim(
        db_session, order, product, user["user_id"], user["user_id"], "USER"
    )
    await db_session.commit()

    assert profile is None
    await db_session.refresh(order)
    assert order.status == OrderStatus.PROCESSING, "a paid-for order was failed instead of left for recovery"
    assert order.external_trx_id is not None, "lost the supplier transaction id - the eSIM would be unrecoverable"
    assert await _default_balance(db_session, user["user_id"]) == balance_before, "refunded an eSIM we had paid for"


async def test_polling_picks_up_an_esim_that_arrives_a_moment_later(client, db_session, mock_vivape, monkeypatch):
    """The common case: WorldMove is pending on the first look and ready on
    a later one, so the customer still gets the QR without any recovery."""
    monkeypatch.setattr("app.services.checkout_svc._ESIM_READY_POLL_DELAYS", (0, 0, 0))
    ready = {"iccid": "8988211111111111111", "qrcodeContent": "LPA:1$rsp.example.com$ABC123"}
    mock_vivape.get_esim_by_trx.side_effect = [WORLDMOVE_PENDING, WORLDMOVE_PENDING, ready]

    user = await register_and_login(client, "slowbuyer")
    product = await create_test_product(db_session)
    order = await _order_for(db_session, client, product, user)

    profile = await provision_esim(
        db_session, order, product, user["user_id"], user["user_id"], "USER"
    )
    await db_session.commit()

    assert profile is not None
    assert profile.iccid == "8988211111111111111"
    await db_session.refresh(order)
    assert order.status == OrderStatus.COMPLETED


async def test_recovery_raises_not_ready_rather_than_refunding(client, db_session, mock_vivape):
    """recover_stuck_orders decides when to give up, using its own 60-minute
    window. complete_from_supplier_trx must not pre-empt that by refunding
    the first time it sees a pending eSIM."""
    mock_vivape.get_esim_by_trx.side_effect = None
    mock_vivape.get_esim_by_trx.return_value = WORLDMOVE_PENDING

    user = await register_and_login(client, "recoverybuyer")
    product = await create_test_product(db_session)
    order = await _order_for(db_session, client, product, user)
    order.external_trx_id = "60451"
    await db_session.commit()
    balance_before = await _default_balance(db_session, user["user_id"])

    with pytest.raises(EsimNotReadyYet):
        await complete_from_supplier_trx(db_session, order, product, user["user_id"], "USER")

    await db_session.refresh(order)
    assert order.status == OrderStatus.PROCESSING
    assert await _default_balance(db_session, user["user_id"]) == balance_before


async def test_recovery_completes_the_order_once_the_esim_appears(client, db_session, mock_vivape):
    """And the other side of it: the moment the supplier produces the eSIM,
    the same already-paid transaction is turned into a delivered order -
    never a second purchase."""
    mock_vivape.get_esim_by_trx.side_effect = None
    mock_vivape.get_esim_by_trx.return_value = {
        "esim_order": {
            "iccid": "8988233333333333333",
            "qrcodeContent": "LPA:1$rsp.example.com$XYZ789",
            "note": "World Move eSIM Transaction Redeem", "resultmsg": "Success",
        }
    }

    user = await register_and_login(client, "recovereddbuyer")
    product = await create_test_product(db_session)
    order = await _order_for(db_session, client, product, user)
    order.external_trx_id = "60451"
    await db_session.commit()

    profile = await complete_from_supplier_trx(db_session, order, product, user["user_id"], "USER")
    await db_session.commit()

    assert profile is not None
    assert profile.iccid == "8988233333333333333"
    await db_session.refresh(order)
    assert order.status == OrderStatus.COMPLETED
    mock_vivape.create_transaction.assert_not_called()


async def test_a_supplier_that_never_took_the_money_is_still_refunded(client, db_session, mock_vivape):
    """The distinction that makes the rest safe: no transaction id means
    nothing was bought, so the customer must get their money back at once."""
    mock_vivape.create_transaction.return_value = {"error": "insufficient supplier balance"}

    user = await register_and_login(client, "refundbuyer")
    product = await create_test_product(db_session)
    order = await _order_for(db_session, client, product, user)
    balance_before = await _default_balance(db_session, user["user_id"])

    profile = await provision_esim(
        db_session, order, product, user["user_id"], user["user_id"], "USER"
    )
    await db_session.commit()

    assert profile is None
    await db_session.refresh(order)
    assert order.status == OrderStatus.FAILED
    assert await _default_balance(db_session, user["user_id"]) > balance_before, "customer not refunded"
