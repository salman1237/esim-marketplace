"""FR-C102: the WS connection manager's broadcast/fan-out behavior.

Pure in-process unit tests against a fake socket - no real network
connection, no DB, no FastAPI app involved. The real WS endpoints
(FR-C103/C104) get their own two-socket-through-the-actual-endpoint proof
when they're built; this file proves the manager itself fans out
correctly, which the endpoints then rely on.
"""
import pytest

from app.services.ws_manager import ConnectionManager

pytestmark = pytest.mark.asyncio


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
