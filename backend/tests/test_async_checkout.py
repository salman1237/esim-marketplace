import uuid
import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import select

from conftest import register_and_login, fund_wallet, create_test_product, wait_for_order
from app.models.order import Order, OrderStatus, PaymentMethod, ESIMProfile
from app.models.wallet import Wallet, WalletType
from app.services.order_fulfilment import recover_stuck_orders

pytestmark = pytest.mark.asyncio


async def _stuck_order(db_session, user_id, product, *, minutes_ago: int, trx_id: str | None):
    """An order left PROCESSING as if its background task died - e.g. a
    deploy restarted the process mid-provisioning."""
    order = Order(
        order_no=f"ORD-STUCK-{uuid.uuid4().hex[:8].upper()}",
        buyer_id=user_id,
        beneficiary_id=user_id,
        product_id=product.id,
        total_amount=Decimal("9.9900"),
        currency="USD",
        payment_method=PaymentMethod.WALLET,
        status=OrderStatus.PROCESSING,
        external_trx_id=trx_id,
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    return order


async def _default_balance(db_session, user_id) -> Decimal:
    wallet = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.DEFAULT)
    )).scalar_one()
    await db_session.refresh(wallet)
    return Decimal(str(wallet.balance))


async def _park(db_session, order):
    """Stops a deliberately-unfinished order being picked up by recovery
    in a later test sharing this database."""
    order.status = OrderStatus.CANCELLED
    await db_session.commit()


async def test_order_is_hidden_from_other_users(client, db_session):
    """An order id alone must not reveal someone else's eSIM - and a
    stranger gets the same 404 as a nonexistent id, so ids can't be
    probed for existence."""
    buyer = await register_and_login(client, "orderowner")
    await fund_wallet(db_session, buyer["user_id"], Decimal("50.0000"))
    product = await create_test_product(db_session)

    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET"},
        headers=buyer["headers"],
    )
    assert res.status_code == 202, res.text
    order_id = res.json()["id"]
    await wait_for_order(client, order_id, buyer["headers"])

    stranger = await register_and_login(client, "nosyuser")
    peek = await client.get(f"/api/v1/orders/{order_id}", headers=stranger["headers"])
    assert peek.status_code == 404

    missing = await client.get(f"/api/v1/orders/{uuid.uuid4()}", headers=buyer["headers"])
    assert missing.status_code == 404


async def test_recovery_fetches_already_paid_esim_without_buying_again(client, db_session, mock_vivape):
    """VivaPe already charged for this order (external_trx_id is set), so
    recovery must fetch that existing eSIM - never call create-transaction,
    which would charge a second time for the same order."""
    user = await register_and_login(client, "recoverpaid")
    product = await create_test_product(db_session)
    order = await _stuck_order(db_session, user["user_id"], product, minutes_ago=10, trx_id="777001")

    result = await recover_stuck_orders()

    mock_vivape.create_transaction.assert_not_called()
    await db_session.refresh(order)
    assert order.status == OrderStatus.COMPLETED
    profile = (await db_session.execute(
        select(ESIMProfile).where(ESIMProfile.order_id == order.id)
    )).scalar_one()
    assert profile.supplier_reference == "777001"
    assert profile.iccid
    assert result["recovered"] >= 1


async def test_recovery_refunds_order_with_no_supplier_transaction(client, db_session, mock_vivape):
    """No external_trx_id means the task died before or during
    create-transaction, so we can't know whether VivaPe charged. The
    customer must not be left paying for nothing: refund and flag it."""
    user = await register_and_login(client, "recoverrefund")
    product = await create_test_product(db_session)
    order = await _stuck_order(db_session, user["user_id"], product, minutes_ago=10, trx_id=None)

    await recover_stuck_orders()

    mock_vivape.create_transaction.assert_not_called()
    await db_session.refresh(order)
    assert order.status == OrderStatus.FAILED
    assert await _default_balance(db_session, user["user_id"]) == Decimal("9.9900")


async def test_recovery_leaves_orders_that_may_still_be_provisioning(client, db_session):
    """A just-placed order is legitimately mid-provisioning - touching it
    would race the live background task."""
    user = await register_and_login(client, "recoverrecent")
    product = await create_test_product(db_session)
    order = await _stuck_order(db_session, user["user_id"], product, minutes_ago=0, trx_id=None)

    await recover_stuck_orders()

    await db_session.refresh(order)
    assert order.status == OrderStatus.PROCESSING
    assert await _default_balance(db_session, user["user_id"]) == Decimal("0.0000")
    await _park(db_session, order)


async def test_recovery_defers_rather_than_refunding_when_supplier_unreachable(client, db_session, mock_vivape):
    """A network error doesn't mean the eSIM doesn't exist. Refunding on a
    blip would hand the customer both their money and a working eSIM we
    paid for, so recovery retries on later runs instead."""
    mock_vivape.get_esim_by_trx.side_effect = RuntimeError("VivaPe unreachable")

    user = await register_and_login(client, "recoverdefer")
    product = await create_test_product(db_session)
    order = await _stuck_order(db_session, user["user_id"], product, minutes_ago=10, trx_id="777002")

    result = await recover_stuck_orders()

    await db_session.refresh(order)
    assert order.status == OrderStatus.PROCESSING
    assert await _default_balance(db_session, user["user_id"]) == Decimal("0.0000")
    assert result["deferred"] >= 1
    await _park(db_session, order)


async def test_recovered_partner_order_notifies_merchant_by_webhook_not_email(client, db_session, promote_role):
    """Partner API orders are delivered to the merchant's webhook - their
    background task would have sent it. A recovered one must still send
    it (else the merchant never learns the eSIM exists), and must not
    email the placeholder end-customer account the partner flow creates."""
    from unittest.mock import AsyncMock, patch
    import app.services.order_fulfilment as fulfilment_module
    from test_partner_orders import _make_partner, mock_webhook_http

    _, merchant_user_id, _ = await _make_partner(
        client, db_session, promote_role, "recover",
        webhook_url="https://partner.example.com/webhooks/esim", webhook_secret="whsec_test_secret",
    )
    product = await create_test_product(db_session)
    order = Order(
        order_no=f"PTR-STUCK-{uuid.uuid4().hex[:8].upper()}",
        buyer_id=merchant_user_id,
        beneficiary_id=merchant_user_id,
        product_id=product.id,
        total_amount=Decimal("9.9900"),
        currency="USD",
        payment_method=PaymentMethod.WALLET,
        status=OrderStatus.PROCESSING,
        is_reseller_order=True,
        external_trx_id="777003",
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    db_session.add(order)
    await db_session.commit()

    send_email = AsyncMock()
    with mock_webhook_http(200) as webhook_post, \
         patch.object(fulfilment_module.EmailService, "send_order_confirmation", send_email):
        await recover_stuck_orders()

    await db_session.refresh(order)
    assert order.status == OrderStatus.COMPLETED
    webhook_post.assert_called_once()
    send_email.assert_not_called()
