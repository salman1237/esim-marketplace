"""FR-C101: SupportMessage gains message_type/shared_order_id/shared_product_id.

Real-time chat extends the existing ticket system (see
D:\\eSim\\docs\\Architecture.md) - these are the new columns only. Ownership
checks for sharing live in support_svc.py (FR-C106), not here.
"""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.catalog import Country, Product
from app.models.order import Order, PaymentMethod, OrderStatus
from app.models.support import MessageType, SupportMessage, SupportTicket, TicketCategory
from app.models.user import User, UserRole, UserStatus
from app.core.security import get_password_hash

pytestmark = pytest.mark.asyncio


async def _user(db_session) -> User:
    tag = uuid.uuid4().hex[:8]
    user = User(
        email=f"{tag}@example.com", username=f"u{tag}", hashed_password=get_password_hash("x"),
        role=UserRole.USER, status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _ticket(db_session, user: User) -> SupportTicket:
    ticket = SupportTicket(
        reference=f"TKT-TEST-{uuid.uuid4().hex[:6].upper()}", user_id=user.id,
        subject="Test", category=TicketCategory.OTHER,
    )
    db_session.add(ticket)
    await db_session.flush()
    return ticket


async def _order(db_session, buyer_id: str) -> Order:
    tag = uuid.uuid4().hex[:6]
    country = Country(id=int(uuid.uuid4().int % 1_000_000_000), iso2=f"C{tag[:5].upper()}", name_en=f"Chatland {tag}", is_active=True)
    db_session.add(country)
    await db_session.flush()
    product = Product(
        country_id=country.id, title_en=f"Chat 3GB {tag}", data_amount_gb=Decimal("3"), validity_days=7,
        cost_price=Decimal("5.0000"), retail_price=Decimal("9.9900"), currency="EUR", is_active=True,
    )
    db_session.add(product)
    await db_session.flush()
    order = Order(
        order_no=f"ORD-CHAT-{tag}", buyer_id=buyer_id, beneficiary_id=buyer_id, product_id=product.id,
        total_amount=Decimal("9.9900"), cost_amount=Decimal("5.0000"), currency="EUR",
        payment_method=PaymentMethod.WALLET, status=OrderStatus.COMPLETED,
    )
    db_session.add(order)
    await db_session.commit()
    return order


async def test_a_new_message_defaults_to_text_with_no_shares(db_session):
    user = await _user(db_session)
    ticket = await _ticket(db_session, user)
    msg = SupportMessage(ticket_id=ticket.id, author_id=user.id, is_staff=False, body="hello")
    db_session.add(msg)
    await db_session.commit()
    await db_session.refresh(msg)

    assert msg.message_type == MessageType.TEXT
    assert msg.shared_order_id is None
    assert msg.shared_product_id is None


async def test_a_message_can_share_an_order(db_session):
    user = await _user(db_session)
    ticket = await _ticket(db_session, user)
    order = await _order(db_session, user.id)

    msg = SupportMessage(
        ticket_id=ticket.id, author_id=user.id, is_staff=False, body="here's my order",
        message_type=MessageType.ORDER_SHARE, shared_order_id=order.id,
    )
    db_session.add(msg)
    await db_session.commit()
    await db_session.refresh(msg)

    assert msg.message_type == MessageType.ORDER_SHARE
    assert msg.shared_order_id == order.id


async def test_a_message_can_share_a_product(db_session):
    user = await _user(db_session)
    ticket = await _ticket(db_session, user)
    order = await _order(db_session, user.id)  # reuse the product it created
    product_id = order.product_id

    msg = SupportMessage(
        ticket_id=ticket.id, author_id=user.id, is_staff=False, body="this package",
        message_type=MessageType.PRODUCT_SHARE, shared_product_id=product_id,
    )
    db_session.add(msg)
    await db_session.commit()
    await db_session.refresh(msg)

    assert msg.message_type == MessageType.PRODUCT_SHARE
    assert msg.shared_product_id == product_id


async def test_deleting_a_shared_order_sets_the_message_field_null_not_cascades(db_session):
    """ON DELETE SET NULL, not CASCADE - the message itself must survive."""
    user = await _user(db_session)
    ticket = await _ticket(db_session, user)
    order = await _order(db_session, user.id)

    msg = SupportMessage(
        ticket_id=ticket.id, author_id=user.id, is_staff=False, body="my order",
        message_type=MessageType.ORDER_SHARE, shared_order_id=order.id,
    )
    db_session.add(msg)
    await db_session.commit()
    msg_id = msg.id

    await db_session.delete(order)
    await db_session.commit()
    # The DB-level ON DELETE SET NULL already happened in Postgres, but this
    # session's identity map still holds `msg` with its old in-memory
    # shared_order_id - expire it so the re-query actually reads the real
    # post-delete row instead of silently reusing stale attribute state.
    db_session.expire_all()

    refreshed = (await db_session.execute(
        select(SupportMessage).where(SupportMessage.id == msg_id)
    )).scalar_one()
    assert refreshed.shared_order_id is None
    assert refreshed.body == "my order"
