"""The scheduled "how was your trip" email - see app/services/trip_feedback_svc.py.

Built from a real ESIMProfile/Order/Product chain (not mocks) so the join
in send_due_trip_feedback_reminders is actually exercised, with SMTP
unconfigured in tests - EmailService._send short-circuits to False, which
is exactly the "best effort, never raises" path this sweep depends on.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.order import ESIMProfile, Order, OrderStatus, PaymentMethod
from app.services.trip_feedback_svc import send_due_trip_feedback_reminders
from conftest import create_test_product, register_and_login

pytestmark = pytest.mark.asyncio


async def _make_order_with_profile(db_session, client, *, expires_at, feedback_sent_at=None):
    user = await register_and_login(client, "tripuser")
    product = await create_test_product(db_session)
    order = Order(
        order_no=f"TST{uuid.uuid4().hex[:10].upper()}",
        buyer_id=user["user_id"], beneficiary_id=user["user_id"], product_id=product.id,
        total_amount=product.retail_price, payment_method=PaymentMethod.WALLET, status=OrderStatus.COMPLETED,
    )
    db_session.add(order)
    await db_session.flush()
    profile = ESIMProfile(
        order_id=order.id, beneficiary_id=user["user_id"],
        iccid=f"8910300000{uuid.uuid4().hex[:9]}",
        expires_at=expires_at, trip_feedback_sent_at=feedback_sent_at,
    )
    db_session.add(profile)
    await db_session.commit()
    return user, order, profile


async def test_sends_for_a_trip_that_ended_within_the_window(client, db_session):
    now = datetime.now(timezone.utc)
    _, _, profile = await _make_order_with_profile(db_session, client, expires_at=now - timedelta(hours=10))
    result = await send_due_trip_feedback_reminders(db_session)
    assert result["candidates"] == 1
    await db_session.refresh(profile)
    assert profile.trip_feedback_sent_at is not None


async def test_skips_a_trip_whose_validity_has_not_ended_yet(client, db_session):
    now = datetime.now(timezone.utc)
    await _make_order_with_profile(db_session, client, expires_at=now + timedelta(hours=5))
    result = await send_due_trip_feedback_reminders(db_session)
    assert result["candidates"] == 0


async def test_skips_a_trip_that_ended_too_long_ago(client, db_session):
    now = datetime.now(timezone.utc)
    await _make_order_with_profile(db_session, client, expires_at=now - timedelta(days=5))
    result = await send_due_trip_feedback_reminders(db_session)
    assert result["candidates"] == 0


async def test_never_resends_once_already_sent(client, db_session):
    now = datetime.now(timezone.utc)
    await _make_order_with_profile(
        db_session, client, expires_at=now - timedelta(hours=10), feedback_sent_at=now - timedelta(hours=1)
    )
    result = await send_due_trip_feedback_reminders(db_session)
    assert result["candidates"] == 0


async def test_an_uninstalled_esim_with_no_expiry_is_never_swept(client, db_session):
    """expires_at stays NULL until first activation - a purchased-but-never-
    installed eSIM must not get a "how was your trip" email for a trip that
    never happened."""
    await _make_order_with_profile(db_session, client, expires_at=None)
    result = await send_due_trip_feedback_reminders(db_session)
    assert result["candidates"] == 0
