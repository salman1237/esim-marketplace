"""Guest (non-logged-in) support chat - FR-C401-C405.

A visitor is identified by a bare guest_token (not a cookie session - see
docs/Architecture.md "Guest chat"), minted by POST /support/guest/session,
sent back exactly where a JWT would go. These tests prove: a guest can open
and reply to a ticket, a guest can't read/reply to someone else's ticket, a
guest can't share an order (no verifiable ownership) but can share a
product, and claiming reassigns every one of a guest's tickets to the
account that just logged in - without touching messages already posted.
"""
import pytest

from conftest import create_test_product, register_and_login

pytestmark = pytest.mark.asyncio


async def _guest_token(client) -> str:
    res = await client.post("/api/v1/support/guest/session")
    assert res.status_code == 200, res.text
    token = res.json()["guest_token"]
    assert token
    return token


async def test_guest_can_open_and_reply_to_a_ticket(client, db_session):
    token = await _guest_token(client)

    opened = await client.post(
        "/api/v1/support/guest/tickets",
        data={
            "guest_token": token, "guest_email": "visitor@example.com",
            "subject": "Can't activate my eSIM", "body": "QR scan fails every time.",
            "category": "ESIM",
        },
    )
    assert opened.status_code == 200, opened.text
    ticket = opened.json()
    assert ticket["status"] == "OPEN"
    assert ticket["is_guest"] is True
    assert len(ticket["messages"]) == 1
    assert ticket["messages"][0]["author"] == "You"

    replied = await client.post(
        f"/api/v1/support/guest/tickets/{ticket['id']}/messages",
        data={"guest_token": token, "body": "Still broken after a retry."},
    )
    assert replied.status_code == 200, replied.text
    bodies = [m["body"] for m in replied.json()["messages"]]
    assert bodies == ["QR scan fails every time.", "Still broken after a retry."]

    fetched = await client.get(
        f"/api/v1/support/guest/tickets/{ticket['id']}", params={"guest_token": token},
    )
    assert fetched.status_code == 200, fetched.text
    assert len(fetched.json()["messages"]) == 2


async def test_a_guest_cannot_read_or_reply_to_someone_elses_ticket(client, db_session):
    token_a = await _guest_token(client)
    token_b = await _guest_token(client)

    opened = (await client.post(
        "/api/v1/support/guest/tickets",
        data={"guest_token": token_a, "subject": "My own problem", "body": "Help please."},
    )).json()

    forbidden_read = await client.get(
        f"/api/v1/support/guest/tickets/{opened['id']}", params={"guest_token": token_b},
    )
    assert forbidden_read.status_code == 404

    forbidden_reply = await client.post(
        f"/api/v1/support/guest/tickets/{opened['id']}/messages",
        data={"guest_token": token_b, "body": "Trying to butt in."},
    )
    assert forbidden_reply.status_code == 404


async def test_a_guest_can_share_a_product_but_not_an_order(client, db_session):
    token = await _guest_token(client)
    product = await create_test_product(db_session)

    opened = await client.post(
        "/api/v1/support/guest/tickets",
        data={
            "guest_token": token, "subject": "Which package should I get",
            "body": "", "shared_product_id": product.id,
        },
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["messages"][0]["message_type"] == "PRODUCT_SHARE"

    order_share = await client.post(
        "/api/v1/support/guest/tickets",
        data={
            "guest_token": token, "subject": "About my order",
            "body": "Any order details?", "shared_order_id": "not-a-real-id",
        },
    )
    # The guest router never declares a shared_order_id field at all
    # (FR-C403) - FastAPI silently drops the unrecognized form field, so
    # this succeeds as a plain text message, proving a guest has no route
    # to even attempt an order share (not just that it would be rejected).
    assert order_share.status_code == 200, order_share.text
    assert order_share.json()["messages"][0]["message_type"] == "TEXT"


async def test_claim_reassigns_every_guest_ticket_without_touching_messages(client, db_session):
    token = await _guest_token(client)
    opened = (await client.post(
        "/api/v1/support/guest/tickets",
        data={"guest_token": token, "subject": "Before I signed up", "body": "First message."},
    )).json()
    await client.post(
        f"/api/v1/support/guest/tickets/{opened['id']}/messages",
        data={"guest_token": token, "body": "Second message, still a guest."},
    )

    user = await register_and_login(client, "claimedguest")
    claim = await client.post(
        "/api/v1/support/guest/claim", data={"guest_token": token}, headers=user["headers"],
    )
    assert claim.status_code == 200, claim.text
    assert claim.json()["claimed"] == 1

    # Claimed - now reachable through the authed endpoint, not the guest one.
    mine = await client.get("/api/v1/support/tickets", headers=user["headers"])
    assert [t["id"] for t in mine.json()] == [opened["id"]]

    fetched = await client.get(f"/api/v1/support/tickets/{opened['id']}", headers=user["headers"])
    assert fetched.status_code == 200, fetched.text
    bodies = [m["body"] for m in fetched.json()["messages"]]
    assert bodies == ["First message.", "Second message, still a guest."]

    # The guest_token no longer owns anything - the old guest endpoint 404s now.
    stale = await client.get(
        f"/api/v1/support/guest/tickets/{opened['id']}", params={"guest_token": token},
    )
    assert stale.status_code == 404


async def test_claim_does_not_touch_tickets_the_account_already_owns(client, db_session):
    user = await register_and_login(client, "ownsalready")
    own = await client.post(
        "/api/v1/support/tickets",
        data={"subject": "My own ticket", "body": "Already mine.", "category": "OTHER"},
        headers=user["headers"],
    )
    assert own.status_code == 200, own.text

    token = await _guest_token(client)
    claim = await client.post(
        "/api/v1/support/guest/claim", data={"guest_token": token}, headers=user["headers"],
    )
    assert claim.status_code == 200, claim.text
    assert claim.json()["claimed"] == 0

    mine = await client.get("/api/v1/support/tickets", headers=user["headers"])
    assert len(mine.json()) == 1
