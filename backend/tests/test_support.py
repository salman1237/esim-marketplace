"""Support tickets: the thread, who it waits on, and who can read it.

The status rule is the one worth guarding: it follows whoever spoke last, so
the staff queue means something, and a customer replying to a resolved ticket
reopens it rather than the problem quietly disappearing.
"""
import io
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.support import SupportTicket, TicketStatus
from conftest import register_and_login

pytestmark = pytest.mark.asyncio

PNG = ("screenshot.png", io.BytesIO(b"\x89PNG\r\n\x1a\nfake-image-bytes"), "image/png")


def png(name="screenshot.png"):
    return (name, io.BytesIO(b"\x89PNG\r\n\x1a\nfake-image-bytes"), "image/png")


async def _staff(client, promote_role, name="supportadmin", role="ADMIN"):
    admin = await register_and_login(client, name)
    await promote_role(admin["user_id"], role)
    return admin


async def _open_ticket(client, user, subject="My eSIM won't install", body="It says invalid QR code."):
    res = await client.post(
        "/api/v1/support/tickets",
        data={"subject": subject, "body": body, "category": "ESIM"},
        headers=user["headers"],
    )
    assert res.status_code == 200, res.text
    return res.json()


async def test_opening_a_ticket_starts_a_thread(client, db_session):
    user = await register_and_login(client, "support")
    ticket = await _open_ticket(client, user)

    assert ticket["reference"].startswith("TKT-")
    assert ticket["status"] == "OPEN"
    assert ticket["category"] == "ESIM"
    assert len(ticket["messages"]) == 1
    assert ticket["messages"][0]["body"] == "It says invalid QR code."
    assert ticket["messages"][0]["is_staff"] is False

    listed = (await client.get("/api/v1/support/tickets", headers=user["headers"])).json()
    assert [t["id"] for t in listed] == [ticket["id"]]


async def test_a_ticket_needs_a_subject_and_something_to_say(client, db_session):
    user = await register_and_login(client, "support")
    short = await client.post(
        "/api/v1/support/tickets",
        data={"subject": "hi", "body": "help", "category": "OTHER"},
        headers=user["headers"],
    )
    assert short.status_code == 400
    assert "subject" in short.json()["detail"].lower()

    empty = await client.post(
        "/api/v1/support/tickets",
        data={"subject": "A real subject", "body": "   ", "category": "OTHER"},
        headers=user["headers"],
    )
    assert empty.status_code == 400


async def test_the_ticket_waits_on_whoever_did_not_speak_last(client, db_session, promote_role):
    user = await register_and_login(client, "support")
    admin = await _staff(client, promote_role, "supportadmin1")
    ticket = await _open_ticket(client, user)

    # Customer spoke -> waiting on support.
    assert ticket["status"] == "OPEN"

    replied = await client.post(
        f"/api/v1/support/tickets/{ticket['id']}/messages",
        data={"body": "Could you send a screenshot of the error?"},
        headers=admin["headers"],
    )
    assert replied.status_code == 200, replied.text
    assert replied.json()["status"] == "ANSWERED"

    # Customer answers -> back to support.
    back = await client.post(
        f"/api/v1/support/tickets/{ticket['id']}/messages",
        data={"body": "Attached."},
        headers=user["headers"],
    )
    assert back.json()["status"] == "OPEN"
    assert [m["is_staff"] for m in back.json()["messages"]] == [False, True, False]


async def test_a_customer_reply_reopens_a_resolved_ticket(client, db_session, promote_role):
    """The case that matters: a problem that comes back must not stay done."""
    user = await register_and_login(client, "support")
    admin = await _staff(client, promote_role, "supportadmin2")
    ticket = await _open_ticket(client, user)

    resolved = await client.post(
        f"/api/v1/support/tickets/{ticket['id']}/resolve", headers=admin["headers"]
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "RESOLVED"
    assert resolved.json()["resolved_at"]

    again = await client.post(
        f"/api/v1/support/tickets/{ticket['id']}/messages",
        data={"body": "It's happening again."},
        headers=user["headers"],
    )
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "OPEN"

    row = (await db_session.execute(
        select(SupportTicket).where(SupportTicket.id == ticket["id"])
    )).scalar_one()
    await db_session.refresh(row)
    assert row.status == TicketStatus.OPEN
    assert row.resolved_at is None


async def test_a_closed_ticket_cannot_be_written_to(client, db_session):
    user = await register_and_login(client, "support")
    ticket = await _open_ticket(client, user)

    closed = await client.post(f"/api/v1/support/tickets/{ticket['id']}/close", headers=user["headers"])
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "CLOSED"

    res = await client.post(
        f"/api/v1/support/tickets/{ticket['id']}/messages",
        data={"body": "One more thing"},
        headers=user["headers"],
    )
    assert res.status_code == 400
    assert "closed" in res.json()["detail"].lower()

    # Closing twice is refused rather than silently repeated.
    assert (await client.post(
        f"/api/v1/support/tickets/{ticket['id']}/close", headers=user["headers"]
    )).status_code == 400


async def test_attachments_go_both_ways_and_are_private(client, db_session, promote_role):
    user = await register_and_login(client, "support")
    admin = await _staff(client, promote_role, "supportadmin3")
    stranger = await register_and_login(client, "supportnosy")

    created = await client.post(
        "/api/v1/support/tickets",
        data={"subject": "Install error screenshot", "body": "Here's what I see.", "category": "ESIM"},
        files=[("files", png("error.png"))],
        headers=user["headers"],
    )
    assert created.status_code == 200, created.text
    attachment = created.json()["messages"][0]["attachments"][0]
    assert attachment["name"] == "error.png"
    assert attachment["url"].startswith("/api/v1/support/attachments/")

    # The owner can fetch it, staff can fetch it, a stranger cannot.
    assert (await client.get(attachment["url"], headers=user["headers"])).status_code == 200
    assert (await client.get(attachment["url"], headers=admin["headers"])).status_code == 200
    assert (await client.get(attachment["url"], headers=stranger["headers"])).status_code == 404
    # And it is not public.
    assert (await client.get(attachment["url"])).status_code == 401

    # Staff can attach too.
    replied = await client.post(
        f"/api/v1/support/tickets/{created.json()['id']}/messages",
        data={"body": "Try these settings."},
        files=[("files", png("settings.pdf"))],
        headers=admin["headers"],
    )
    assert replied.status_code == 200, replied.text
    staff_attachment = replied.json()["messages"][-1]["attachments"][0]
    assert (await client.get(staff_attachment["url"], headers=user["headers"])).status_code == 200


async def test_bad_attachments_are_refused_without_leaving_files(client, db_session):
    user = await register_and_login(client, "support")

    wrong_type = await client.post(
        "/api/v1/support/tickets",
        data={"subject": "Executable please", "body": "Here", "category": "OTHER"},
        files=[("files", ("payload.exe", io.BytesIO(b"MZ"), "application/x-msdownload"))],
        headers=user["headers"],
    )
    assert wrong_type.status_code == 400
    assert "isn't supported" in wrong_type.json()["detail"]

    too_many = await client.post(
        "/api/v1/support/tickets",
        data={"subject": "Lots of files", "body": "Here", "category": "OTHER"},
        files=[("files", png(f"{i}.png")) for i in range(6)],
        headers=user["headers"],
    )
    assert too_many.status_code == 400
    assert "up to 5" in too_many.json()["detail"]

    # Neither attempt left a ticket behind.
    assert (await client.get("/api/v1/support/tickets", headers=user["headers"])).json() == []


async def test_one_customer_cannot_read_anothers_ticket(client, db_session):
    owner = await register_and_login(client, "support")
    stranger = await register_and_login(client, "supportother")
    ticket = await _open_ticket(client, owner)

    # Same 404 as a nonexistent id, so ticket ids can't be probed.
    assert (await client.get(
        f"/api/v1/support/tickets/{ticket['id']}", headers=stranger["headers"]
    )).status_code == 404
    assert (await client.post(
        f"/api/v1/support/tickets/{ticket['id']}/messages",
        data={"body": "nosy"}, headers=stranger["headers"],
    )).status_code == 404
    assert (await client.get("/api/v1/support/tickets", headers=stranger["headers"])).json() == []


async def test_the_customer_never_sees_which_admin_replied(client, db_session, promote_role):
    user = await register_and_login(client, "support")
    admin = await _staff(client, promote_role, "supportagentname")
    ticket = await _open_ticket(client, user)
    await client.post(
        f"/api/v1/support/tickets/{ticket['id']}/messages",
        data={"body": "Looking into it."}, headers=admin["headers"],
    )

    seen = (await client.get(f"/api/v1/support/tickets/{ticket['id']}", headers=user["headers"])).json()
    staff_message = next(m for m in seen["messages"] if m["is_staff"])
    assert staff_message["author"] == "Support"
    assert admin["username"] not in str(seen)


async def test_the_queue_shows_work_and_is_staff_only(client, db_session, promote_role):
    user = await register_and_login(client, "supportqueue")
    admin = await _staff(client, promote_role, "supportadmin4")
    ticket = await _open_ticket(client, user, subject="Queue me")

    queue = await client.get("/api/v1/support/queue", headers=admin["headers"])
    assert queue.status_code == 200, queue.text
    body = queue.json()
    mine = next(t for t in body["tickets"] if t["id"] == ticket["id"])
    assert mine["customer"]["email"] == user["email"]
    assert body["counts"]["OPEN"] >= 1

    # Resolved tickets drop out of the default view but are still findable.
    await client.post(f"/api/v1/support/tickets/{ticket['id']}/resolve", headers=admin["headers"])
    default_view = (await client.get("/api/v1/support/queue", headers=admin["headers"])).json()
    assert all(t["id"] != ticket["id"] for t in default_view["tickets"])
    resolved_view = (await client.get(
        "/api/v1/support/queue?status=RESOLVED", headers=admin["headers"]
    )).json()
    assert any(t["id"] == ticket["id"] for t in resolved_view["tickets"])

    searched = (await client.get(
        f"/api/v1/support/queue?status=ALL&q={user['email']}", headers=admin["headers"]
    )).json()
    assert any(t["id"] == ticket["id"] for t in searched["tickets"])

    assert (await client.get("/api/v1/support/queue", headers=user["headers"])).status_code == 403


async def test_both_admin_and_super_admin_can_work_tickets(client, db_session, promote_role):
    """Per the client's answer: sub-admins handle support."""
    user = await register_and_login(client, "supportroles")
    ticket = await _open_ticket(client, user)

    sub_admin = await _staff(client, promote_role, "supportsub", role="ADMIN")
    super_admin = await _staff(client, promote_role, "supportsuper", role="SUPER_ADMIN")

    for staff in (sub_admin, super_admin):
        assert (await client.get("/api/v1/support/queue", headers=staff["headers"])).status_code == 200
        assert (await client.post(
            f"/api/v1/support/tickets/{ticket['id']}/messages",
            data={"body": f"Reply from {staff['username']}"}, headers=staff["headers"],
        )).status_code == 200

    assigned = await client.post(
        f"/api/v1/support/tickets/{ticket['id']}/assign", headers=sub_admin["headers"]
    )
    assert assigned.status_code == 200
    assert assigned.json()["assigned_to"] == sub_admin["username"]

    staff_view = (await client.get(
        f"/api/v1/support/tickets/{ticket['id']}", headers=super_admin["headers"]
    )).json()
    assert staff_view["assigned_to"] == sub_admin["username"]
    assert staff_view["customer"]["username"] == user["username"]


async def test_emails_keep_the_thread_alive_in_both_directions(client, db_session, promote_role):
    import app.services.notify_svc as svc
    from unittest.mock import AsyncMock, patch

    user = await register_and_login(client, "supportmail")
    admin = await _staff(client, promote_role, "supportadmin5")

    sent = []

    async def capture(db, **kwargs):
        sent.append(kwargs)

    with patch.object(svc, "send_notice", AsyncMock(side_effect=capture)):
        ticket = await _open_ticket(client, user, subject="Mail me")
        import asyncio
        for _ in range(6):
            await asyncio.sleep(0.02)

        opened = [s for s in sent if s.get("to") == user["email"]]
        assert opened, "the customer was not told their ticket is open"
        assert ticket["reference"] in opened[0]["subject"]

        sent.clear()
        await client.post(
            f"/api/v1/support/tickets/{ticket['id']}/messages",
            data={"body": "Here's how to fix it."}, headers=admin["headers"],
        )
        for _ in range(6):
            await asyncio.sleep(0.02)

    replies = [s for s in sent if s.get("to") == user["email"]]
    assert replies, "the customer was not emailed the reply"
    # The reference travels in the subject so replies stay grouped.
    assert ticket["reference"] in replies[0]["subject"]
    # A support reply is between us and the customer; it doesn't need to be
    # copied to the platform mailbox as well.
    assert replies[0]["copy_system"] is False


async def test_a_ticket_can_name_the_order_it_is_about(client, db_session):
    from conftest import create_test_product, fund_wallet, wait_for_order

    user = await register_and_login(client, "supportorder")
    await fund_wallet(db_session, user["user_id"], Decimal("50"))
    product = await create_test_product(db_session, price=Decimal("10.00"))
    order = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET"},
        headers=user["headers"],
    )
    order_id = order.json()["id"]
    await wait_for_order(client, order_id, user["headers"])

    created = await client.post(
        "/api/v1/support/tickets",
        data={"subject": "This order failed", "body": "No QR arrived.", "category": "ESIM", "order_id": order_id},
        headers=user["headers"],
    )
    assert created.status_code == 200, created.text
    assert created.json()["order_id"] == order_id


async def test_categories_come_from_the_backend(client, db_session):
    res = await client.get("/api/v1/support/categories")
    assert res.status_code == 200
    values = [c["value"] for c in res.json()]
    assert "ESIM" in values and "REFUND" in values
    assert all(c["label"] for c in res.json())
