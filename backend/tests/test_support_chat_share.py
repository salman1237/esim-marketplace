"""FR-C106: sharing an order or a package in a support message.

Ownership rule (Rules.md "Sharing an order or package"): a customer can only
share THEIR OWN order (buyer or beneficiary) - never someone else's; staff
can share any order. A product is public catalog data, shareable by anyone,
same visibility rule as GET /catalog/products/{id}.

WS evidence for this FR reuses the FakeWebSocket pattern already proven in
FR-C105's own tests (not fastapi.testclient.TestClient - see that file's
module docstring for why a real dual-socket TestClient test deadlocks
non-deterministically on this Windows/anyio stack). What's new here is the
payload shape (message_type/shared_order/shared_product), not the delivery
mechanism, which FR-C103/C104 already proved with a real socket.
"""
import json
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.catalog import Product
from app.models.order import ESIMProfile, Order, OrderStatus, PaymentMethod
from app.services.ws_manager import manager
from conftest import create_test_product, register_and_login

pytestmark = pytest.mark.asyncio


class FakeWebSocket:
    def __init__(self):
        self.received: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.received.append(json.loads(json.dumps(payload)))


async def _open_ticket(client, user):
    res = await client.post(
        "/api/v1/support/tickets",
        data={"subject": "Question about an order", "body": "Hi", "category": "OTHER"},
        headers=user["headers"],
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _own_an_order(db_session, user, price=Decimal("10.00")):
    """Builds a completed order directly, owned by `user` - this FR tests
    chat-sharing ownership logic, not checkout/provisioning, so it skips
    POST /orders/checkout entirely rather than going through the real
    checkout+background-provisioning pipeline (whose own settlement timing
    is covered - and occasionally flakes on this environment, pre-existing
    and unrelated - by tests/test_support.py's own order-linking test)."""
    product = await create_test_product(db_session, price=price)
    order = Order(
        order_no=f"ORD-TEST-{uuid.uuid4().hex[:10].upper()}",
        buyer_id=user["user_id"],
        beneficiary_id=user["user_id"],
        product_id=product.id,
        total_amount=price,
        currency="EUR",
        payment_method=PaymentMethod.WALLET,
        status=OrderStatus.COMPLETED,
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    return order.id, product


async def test_a_customer_can_share_their_own_order(client, db_session):
    user = await register_and_login(client, "sharerowner")
    order_id, product = await _own_an_order(db_session, user)
    ticket_id = await _open_ticket(client, user)

    res = await client.post(
        f"/api/v1/support/tickets/{ticket_id}/messages",
        data={"body": "Check this out", "shared_order_id": order_id},
        headers=user["headers"],
    )
    assert res.status_code == 200, res.text
    message = res.json()["messages"][-1]
    assert message["message_type"] == "ORDER_SHARE"
    assert message["shared_order"]["id"] == order_id
    assert message["shared_order"]["product_title"] == product.title_en
    assert message["shared_product"] is None
    # No eSIM yet (this order was built directly, bypassing provisioning) -
    # the card has nothing to link to, so the frontend renders it as plain
    # text rather than a dead link (TicketThread.tsx's SharedOrderCard).
    assert message["shared_order"]["esim_profile_id"] is None


async def test_a_shared_orders_card_links_to_its_esim_once_one_exists(client, db_session):
    """esim_profile_id is the click target TicketThread.tsx's SharedOrderCard
    uses to link to the existing /my-esims/{id} page (esims.py's _load
    already allows the order's owner - no new auth path)."""
    user = await register_and_login(client, "sharerwithesim")
    order_id, _ = await _own_an_order(db_session, user)
    profile = ESIMProfile(order_id=order_id, beneficiary_id=user["user_id"])
    db_session.add(profile)
    await db_session.commit()
    await db_session.refresh(profile)
    ticket_id = await _open_ticket(client, user)

    res = await client.post(
        f"/api/v1/support/tickets/{ticket_id}/messages",
        data={"body": "Check this out", "shared_order_id": order_id},
        headers=user["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["messages"][-1]["shared_order"]["esim_profile_id"] == profile.id


async def test_a_shared_products_card_links_to_its_destination_page(client, db_session):
    """country_slug is the click target TicketThread.tsx's SharedProductCard
    uses to link to /explore/{slug} - the exact slug GET /catalog/countries
    already computes (catalog.py's country_slug helper)."""
    user = await register_and_login(client, "sharerwithslug")
    product = await create_test_product(db_session, price=Decimal("5.00"))
    ticket_id = await _open_ticket(client, user)

    res = await client.post(
        f"/api/v1/support/tickets/{ticket_id}/messages",
        data={"body": "Check this out", "shared_product_id": product.id},
        headers=user["headers"],
    )
    assert res.status_code == 200, res.text
    slug = res.json()["messages"][-1]["shared_product"]["country_slug"]
    assert slug and slug == slug.lower()
    assert " " not in slug


async def test_a_customer_cannot_share_someone_elses_order(client, db_session):
    owner = await register_and_login(client, "sharerowner2")
    order_id, _ = await _own_an_order(db_session, owner)

    stranger = await register_and_login(client, "sharerstranger")
    ticket_id = await _open_ticket(client, stranger)

    res = await client.post(
        f"/api/v1/support/tickets/{ticket_id}/messages",
        data={"body": "Check this out", "shared_order_id": order_id},
        headers=stranger["headers"],
    )
    assert res.status_code == 400, res.text


async def test_staff_can_share_any_customers_order(client, db_session, promote_role):
    owner = await register_and_login(client, "sharerowner3")
    order_id, _ = await _own_an_order(db_session, owner)

    staff = await register_and_login(client, "sharerstaff")
    await promote_role(staff["user_id"], "ADMIN")
    ticket_id = await _open_ticket(client, owner)

    res = await client.post(
        f"/api/v1/support/tickets/{ticket_id}/messages",
        data={"body": "Check this out", "shared_order_id": order_id},
        headers=staff["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["messages"][-1]["message_type"] == "ORDER_SHARE"


async def test_anyone_can_share_a_public_product(client, db_session):
    user = await register_and_login(client, "sharerproduct")
    product = await create_test_product(db_session, price=Decimal("5.00"))
    ticket_id = await _open_ticket(client, user)

    res = await client.post(
        f"/api/v1/support/tickets/{ticket_id}/messages",
        data={"body": "Check this out", "shared_product_id": product.id},
        headers=user["headers"],
    )
    assert res.status_code == 200, res.text
    message = res.json()["messages"][-1]
    assert message["message_type"] == "PRODUCT_SHARE"
    assert message["shared_product"]["id"] == product.id
    assert message["shared_product"]["title"] == product.title_en
    assert message["shared_order"] is None


async def test_sharing_a_package_with_no_extra_text_still_works(client, db_session):
    """Confirmed live on beta: the real chat widget's share picker sends
    body="" (no accompanying text) alongside shared_product_id - Starlette's
    multipart parser treats an empty string for a *required* Form field as
    the field being absent entirely, 422'ing before post_message's own
    body-or-share-or-attachment check ever ran. Fixed in support.py by
    giving `body` a Form("") default instead of Form(...). This is the one
    real-world case the other share tests, which all pass a non-empty body
    alongside the share, never actually exercised."""
    user = await register_and_login(client, "sharernotext")
    product = await create_test_product(db_session, price=Decimal("5.00"))
    ticket_id = await _open_ticket(client, user)

    res = await client.post(
        f"/api/v1/support/tickets/{ticket_id}/messages",
        data={"body": "", "shared_product_id": product.id},
        headers=user["headers"],
    )
    assert res.status_code == 200, res.text
    message = res.json()["messages"][-1]
    assert message["message_type"] == "PRODUCT_SHARE"
    assert message["shared_product"]["id"] == product.id


async def test_sharing_an_inactive_product_is_rejected(client, db_session):
    user = await register_and_login(client, "shareroff")
    product = await create_test_product(db_session, price=Decimal("5.00"))
    product_row = (await db_session.execute(select(Product).where(Product.id == product.id))).scalar_one()
    product_row.is_active = False
    await db_session.commit()
    ticket_id = await _open_ticket(client, user)

    res = await client.post(
        f"/api/v1/support/tickets/{ticket_id}/messages",
        data={"body": "Check this out", "shared_product_id": product.id},
        headers=user["headers"],
    )
    assert res.status_code == 400, res.text


async def test_a_message_cannot_share_both_an_order_and_a_product(client, db_session):
    user = await register_and_login(client, "sharerboth")
    order_id, product = await _own_an_order(db_session, user)
    ticket_id = await _open_ticket(client, user)

    res = await client.post(
        f"/api/v1/support/tickets/{ticket_id}/messages",
        data={"body": "Check this out", "shared_order_id": order_id, "shared_product_id": product.id},
        headers=user["headers"],
    )
    assert res.status_code == 400, res.text


async def test_sharing_a_product_broadcasts_the_summary_over_the_ticket_socket(client, db_session):
    """WS evidence (non-negotiable, Functional_Requirements.md SS F): a
    second connection on the ticket channel genuinely receives the
    shared-product summary, not just a bare message_type flag."""
    user = await register_and_login(client, "sharerws")
    product = await create_test_product(db_session, price=Decimal("7.50"))
    ticket_id = await _open_ticket(client, user)

    watcher = FakeWebSocket()
    manager.connect_ticket(ticket_id, watcher)
    try:
        res = await client.post(
            f"/api/v1/support/tickets/{ticket_id}/messages",
            data={"body": "Check this out", "shared_product_id": product.id},
            headers=user["headers"],
        )
        assert res.status_code == 200, res.text
    finally:
        manager.disconnect_ticket(ticket_id, watcher)

    assert len(watcher.received) == 1
    payload = watcher.received[0]
    assert payload["type"] == "message"
    assert payload["message"]["message_type"] == "PRODUCT_SHARE"
    assert payload["message"]["shared_product"]["id"] == product.id
    assert payload["message"]["shared_product"]["title"] == product.title_en
