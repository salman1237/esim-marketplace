"""FR-C102: the WS connection manager's broadcast/fan-out behavior.
FR-C103/C104 (below the manager tests): the real endpoints, proven with
actual WebSocket connections through fastapi.testclient.TestClient - not
the async httpx client fixture used elsewhere in this suite.

Both WS-touching endpoints open their own AsyncSessionLocal() directly
against the real shared `engine` (a WS connection outlives a single
request's dependency injection). That same `engine`/connection pool is
also what pytest's own async test loop uses elsewhere in this suite - and
asyncpg connections are bound to the event loop that created them.
TestClient's WS/lifespan support runs the ASGI app in its OWN background
thread+event loop (a "portal"), so touching the shared engine directly
from pytest's main loop IN THE SAME TEST as a TestClient WS connection
corrupts the pool ("attached to a different loop", confirmed live while
building this). The fix has two parts:
1. Every test below does ALL its setup (register a user, log in, create a
   ticket) THROUGH TestClient itself, so every DB touch for that test
   happens on the one portal loop - never a raw AsyncSessionLocal() call
   from pytest's own loop in these specific tests. Staff auth reuses the
   Super Admin `lifespan` seeds on first boot (superadmin@esim.local)
   rather than a raw DB promote, for the same reason.
2. Each `with TestClient(app) as tc:` block spins up its OWN short-lived
   portal thread+loop that dies when the block exits - a pooled connection
   it touched is now attached to a dead loop and poisons the shared global
   `engine`'s pool for whatever test runs next (another TestClient block,
   or pytest's own main loop), independent of (1). `_dispose_engine`
   below disposes the pool before and after every test in this file so
   nothing stale ever gets handed to the next consumer. Confirmed this was
   the real remaining cause: without it, tests failed depending on run
   order/combination even once (1) was fixed; with it, order stopped
   mattering.
"""
import uuid

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.core.database import engine
from app.main import app
from app.services.ws_manager import ConnectionManager, manager
from conftest import register_and_login

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine():
    await engine.dispose()
    yield
    await engine.dispose()

SUPERADMIN_EMAIL = "superadmin@esim.local"
SUPERADMIN_PASSWORD = "SuperAdmin2026!"


class FakeWebSocket:
    """Duck-types the one method ConnectionManager calls. Records every
    payload sent to it so a test can assert exactly what it received."""
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.received: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        if self.fail:
            raise RuntimeError("socket is closed")
        self.received.append(payload)


def test_a_manager_starts_with_no_connections():
    mgr = ConnectionManager()
    assert mgr.ticket_connection_count("t1") == 0
    assert mgr.queue_connection_count() == 0


async def test_broadcast_reaches_every_socket_connected_to_the_same_ticket():
    mgr = ConnectionManager()
    ws_a = FakeWebSocket()
    ws_b = FakeWebSocket()
    mgr.connect_ticket("ticket-1", ws_a)
    mgr.connect_ticket("ticket-1", ws_b)

    await mgr.broadcast_to_ticket("ticket-1", {"type": "message", "body": "hi"})

    assert ws_a.received == [{"type": "message", "body": "hi"}]
    assert ws_b.received == [{"type": "message", "body": "hi"}]


async def test_broadcast_to_one_ticket_never_reaches_a_different_ticket():
    mgr = ConnectionManager()
    ws_ticket1 = FakeWebSocket()
    ws_ticket2 = FakeWebSocket()
    mgr.connect_ticket("ticket-1", ws_ticket1)
    mgr.connect_ticket("ticket-2", ws_ticket2)

    await mgr.broadcast_to_ticket("ticket-1", {"type": "message", "body": "only for ticket-1"})

    assert ws_ticket1.received == [{"type": "message", "body": "only for ticket-1"}]
    assert ws_ticket2.received == []


async def test_disconnect_removes_a_socket_from_future_broadcasts():
    mgr = ConnectionManager()
    ws = FakeWebSocket()
    mgr.connect_ticket("ticket-1", ws)
    mgr.disconnect_ticket("ticket-1", ws)

    await mgr.broadcast_to_ticket("ticket-1", {"type": "message", "body": "too late"})

    assert ws.received == []
    assert mgr.ticket_connection_count("ticket-1") == 0


async def test_a_dead_socket_is_dropped_without_blocking_delivery_to_others():
    mgr = ConnectionManager()
    dying = FakeWebSocket(fail=True)
    alive = FakeWebSocket()
    mgr.connect_ticket("ticket-1", dying)
    mgr.connect_ticket("ticket-1", alive)

    await mgr.broadcast_to_ticket("ticket-1", {"type": "message", "body": "hello"})

    assert alive.received == [{"type": "message", "body": "hello"}]
    assert mgr.ticket_connection_count("ticket-1") == 1  # the dying one was pruned


async def test_queue_broadcast_reaches_every_staff_socket():
    mgr = ConnectionManager()
    staff_a = FakeWebSocket()
    staff_b = FakeWebSocket()
    mgr.connect_queue(staff_a)
    mgr.connect_queue(staff_b)

    await mgr.broadcast_to_queue({"type": "ticket_updated", "ticket_id": "t1"})

    assert staff_a.received == [{"type": "ticket_updated", "ticket_id": "t1"}]
    assert staff_b.received == [{"type": "ticket_updated", "ticket_id": "t1"}]


async def test_queue_broadcast_never_reaches_a_ticket_channel_socket():
    """The two channels are genuinely separate - a customer in a ticket
    thread must never see staff-only queue events."""
    mgr = ConnectionManager()
    customer = FakeWebSocket()
    staff = FakeWebSocket()
    mgr.connect_ticket("ticket-1", customer)
    mgr.connect_queue(staff)

    await mgr.broadcast_to_queue({"type": "ticket_updated", "ticket_id": "ticket-1"})

    assert staff.received == [{"type": "ticket_updated", "ticket_id": "ticket-1"}]
    assert customer.received == []


# --- FR-C103: the real ticket WebSocket endpoint ----------------------------

def _register(tc: TestClient) -> tuple[str, str]:
    """Returns (user_id, access_token). A real registration, through the
    same TestClient/portal loop as everything else in these tests."""
    tag = uuid.uuid4().hex[:8]
    res = tc.post("/api/v1/auth/register", json={
        "email": f"{tag}@example.com", "username": f"ws{tag}", "password": "testpassword123",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    return body["user_id"], body["access_token"]


def _login_superadmin(tc: TestClient) -> str:
    """The Super Admin lifespan seeds on first boot - real staff auth
    without a raw DB write, same loop as everything else here."""
    res = tc.post("/api/v1/auth/login", json={"email": SUPERADMIN_EMAIL, "password": SUPERADMIN_PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _create_ticket(tc: TestClient, token: str) -> str:
    # The route has a File() param (files, default []), which forces FastAPI
    # to require a real multipart/form-data body even with zero files -
    # passing files={} (not None) is what makes httpx actually encode this
    # as multipart instead of application/x-www-form-urlencoded.
    res = tc.post(
        "/api/v1/support/tickets",
        data={"subject": "WS test", "body": "hello", "category": "OTHER"},
        files={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


def test_ticket_socket_rejects_a_missing_token():
    # No token means _authenticate never even looks up the ticket - any id
    # (even a fake one) is enough to prove this rejection path.
    with TestClient(app) as tc:
        try:
            with tc.websocket_connect("/api/v1/ws/support/tickets/does-not-matter"):
                pass
            assert False, "expected the handshake to be rejected"
        except Exception as e:
            # Starlette raises on a rejected handshake - assert the close
            # code via whichever attribute this version exposes, not a
            # specific exception type.
            code = getattr(e, "code", None) or getattr(e, "status_code", None)
            assert code == 4401, f"expected close code 4401, got {code!r} from {e!r}"


def test_ticket_socket_rejects_someone_who_is_not_the_owner_or_staff():
    with TestClient(app) as tc:
        _owner_id, owner_token = _register(tc)
        ticket_id = _create_ticket(tc, owner_token)
        _stranger_id, stranger_token = _register(tc)
        try:
            with tc.websocket_connect(f"/api/v1/ws/support/tickets/{ticket_id}?token={stranger_token}"):
                pass
            assert False, "expected the handshake to be rejected"
        except Exception as e:
            code = getattr(e, "code", None) or getattr(e, "status_code", None)
            assert code == 4403, f"expected close code 4403, got {code!r} from {e!r}"


def test_ticket_socket_two_real_connections_exchange_a_typing_event():
    """The non-vacuous proof Functional_Requirements.md SS F asks for: two
    REAL WebSocket connections to the same ticket, one triggers a typing
    event, the OTHER one actually receives it - and the sender does not
    get its own event echoed back."""
    with TestClient(app) as tc:
        _customer_id, customer_token = _register(tc)
        ticket_id = _create_ticket(tc, customer_token)
        staff_token = _login_superadmin(tc)

        with tc.websocket_connect(
            f"/api/v1/ws/support/tickets/{ticket_id}?token={customer_token}"
        ) as ws_customer, tc.websocket_connect(
            f"/api/v1/ws/support/tickets/{ticket_id}?token={staff_token}"
        ) as ws_staff:
            ws_customer.send_json({"type": "typing"})
            received_by_staff = ws_staff.receive_json()
            assert received_by_staff == {"type": "typing", "from": "customer"}

            # Prove the reverse direction too, and that the customer socket
            # is genuinely receiving (not just "the channel is broken" in a
            # way that happened to not show up above).
            ws_staff.send_json({"type": "typing"})
            received_by_customer = ws_customer.receive_json()
            assert received_by_customer == {"type": "typing", "from": "staff"}


# --- FR-C104: the staff-only queue WebSocket endpoint -----------------------

def test_queue_socket_rejects_a_missing_token():
    with TestClient(app) as tc:
        try:
            with tc.websocket_connect("/api/v1/ws/support/queue"):
                pass
            assert False, "expected the handshake to be rejected"
        except Exception as e:
            code = getattr(e, "code", None) or getattr(e, "status_code", None)
            assert code == 4401, f"expected close code 4401, got {code!r} from {e!r}"


def test_queue_socket_rejects_a_non_staff_user():
    with TestClient(app) as tc:
        _user_id, customer_token = _register(tc)
        try:
            with tc.websocket_connect(f"/api/v1/ws/support/queue?token={customer_token}"):
                pass
            assert False, "expected the handshake to be rejected"
        except Exception as e:
            code = getattr(e, "code", None) or getattr(e, "status_code", None)
            assert code == 4403, f"expected close code 4403, got {code!r} from {e!r}"


def test_queue_socket_accepts_a_staff_user():
    with TestClient(app) as tc:
        staff_token = _login_superadmin(tc)
        with tc.websocket_connect(f"/api/v1/ws/support/queue?token={staff_token}"):
            pass  # connecting and cleanly closing is the assertion here


# --- FR-C105: creating a ticket / replying broadcasts over the sockets ------
#
# These deliberately do NOT use fastapi.testclient.TestClient. Mixing an
# HTTP POST with one or two simultaneously-open WebSocket connections on
# TestClient's background-thread portal was found to deadlock
# non-deterministically on this Windows/anyio combination - confirmed
# live, repeatedly, across several different structural rewrites (close-
# then-reopen, two-sockets-no-POST, one-socket-with-POST all individually
# fine in isolation, but the combination still hung unpredictably with
# zero DB-side locks involved - a portal-thread race, not a feature bug).
# Real two-socket WS delivery is already proven with TestClient by
# test_ticket_socket_two_real_connections_exchange_a_typing_event above
# (FR-C103) - that doesn't mix in a concurrent REST call, and has never
# hung. What FR-C105 actually needs to prove is narrower: that a REST
# write calls support_svc.broadcast_message with the right data. Proving
# THAT reliably means going back to this suite's normal, rock-solid async
# `client`/`db_session` fixtures (used by hundreds of other tests here
# without incident) for the REST write, and registering a FakeWebSocket
# directly on the shared `manager` - the same proven pattern FR-C102's own
# tests already use - instead of a real network socket for the "did it
# arrive" check.

async def test_creating_a_ticket_broadcasts_to_the_queue_channel(client, db_session, promote_role):
    staff = await register_and_login(client, "chatbroadcast1staff")
    await promote_role(staff["user_id"], "ADMIN")
    customer = await register_and_login(client, "chatbroadcast1cust")

    fake_queue = FakeWebSocket()
    manager.connect_queue(fake_queue)
    try:
        res = await client.post(
            "/api/v1/support/tickets",
            data={"subject": "Broadcast test", "body": "hello from REST", "category": "OTHER"},
            headers=customer["headers"],
        )
        assert res.status_code == 200, res.text
        ticket_id = res.json()["id"]

        assert len(fake_queue.received) == 1
        assert fake_queue.received[0]["type"] == "ticket_updated"
        assert fake_queue.received[0]["ticket_id"] == ticket_id
    finally:
        manager.disconnect_queue(fake_queue)


async def test_replying_to_a_ticket_broadcasts_to_both_channels(client, db_session, promote_role):
    staff = await register_and_login(client, "chatbroadcast2staff")
    await promote_role(staff["user_id"], "ADMIN")
    customer = await register_and_login(client, "chatbroadcast2cust")

    res = await client.post(
        "/api/v1/support/tickets",
        data={"subject": "Reply broadcast test", "body": "hello", "category": "OTHER"},
        headers=customer["headers"],
    )
    assert res.status_code == 200, res.text
    ticket_id = res.json()["id"]

    fake_ticket_ws = FakeWebSocket()
    fake_queue = FakeWebSocket()
    manager.connect_ticket(ticket_id, fake_ticket_ws)
    manager.connect_queue(fake_queue)
    try:
        res = await client.post(
            f"/api/v1/support/tickets/{ticket_id}/messages",
            data={"body": "a reply"},
            headers=staff["headers"],
        )
        assert res.status_code == 200, res.text

        assert len(fake_ticket_ws.received) == 1
        message_event = fake_ticket_ws.received[0]
        assert message_event["type"] == "message"
        assert message_event["message"]["body"] == "a reply"
        assert message_event["message"]["is_staff"] is True
        # The identity is real (not the REST response's viewer-relative
        # "You") - see broadcast_message's docstring.
        assert message_event["message"]["author"] != "You"

        assert len(fake_queue.received) == 1
        queue_event = fake_queue.received[0]
        assert queue_event["type"] == "ticket_updated"
        assert queue_event["ticket_id"] == ticket_id
        assert queue_event["status"] == "ANSWERED"
    finally:
        manager.disconnect_ticket(ticket_id, fake_ticket_ws)
        manager.disconnect_queue(fake_queue)


async def test_creating_a_ticket_with_a_file_attachment_still_broadcasts(client, db_session):
    """Specifically exercises the one real risk this wiring has: a freshly
    created SupportMessage's `attachments` relationship is unloaded in this
    same session, and serialize_message() touches it - if that triggers an
    async lazy-load instead of using already-available data, broadcasting
    would raise instead of silently doing nothing, which is exactly the
    kind of bug that must be caught here, not assumed away. (This is the
    test that first caught the real MissingGreenlet bug - see
    support_svc.broadcast_message's docstring for the fix.)"""
    customer = await register_and_login(client, "chatbroadcastattach")

    fake_queue = FakeWebSocket()
    manager.connect_queue(fake_queue)
    try:
        res = await client.post(
            "/api/v1/support/tickets",
            data={"subject": "With attachment", "body": "see attached", "category": "OTHER"},
            files={"files": ("note.txt", b"hello world", "text/plain")},
            headers=customer["headers"],
        )
        assert res.status_code == 200, res.text
        ticket_id = res.json()["id"]

        assert len(fake_queue.received) == 1
        assert fake_queue.received[0]["type"] == "ticket_updated"
        assert fake_queue.received[0]["ticket_id"] == ticket_id
    finally:
        manager.disconnect_queue(fake_queue)
