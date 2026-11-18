"""In-process WebSocket fan-out for real-time support chat.

Deliberately a plain in-memory dict/set, not Redis-backed - correct ONLY
because esim-backend/esim-backend-beta run as a single container each
today (confirmed in docker-compose*.yml, see D:\\eSim\\docs\\Architecture.md
and D:\\eSim\\CLAUDE.md's Hard Constraints). If this backend is ever scaled
past one instance, a message sent while the recipient's socket is attached
to a different instance silently won't reach them - that is a known,
accepted gap (D:\\eSim\\docs\\Rules.md), not something to paper over here.

Two independent channels:
- one set of sockets per ticket_id (customer + any staff viewing that thread)
- one flat set for the staff-only queue channel (ticket_updated events)

A socket that raises on send (closed/dying connection) is dropped from
future broadcasts rather than allowed to break delivery to everyone else
on the same channel - best-effort delivery, per Rules.md.
"""
from typing import Any, Dict, Set


class ConnectionManager:
    def __init__(self) -> None:
        self._ticket_sockets: Dict[str, Set[Any]] = {}
        self._queue_sockets: Set[Any] = set()

    # --- per-ticket channel ---------------------------------------------

    def connect_ticket(self, ticket_id: str, websocket: Any) -> None:
        self._ticket_sockets.setdefault(ticket_id, set()).add(websocket)

    def disconnect_ticket(self, ticket_id: str, websocket: Any) -> None:
        sockets = self._ticket_sockets.get(ticket_id)
        if sockets is None:
            return
        sockets.discard(websocket)
        if not sockets:
            self._ticket_sockets.pop(ticket_id, None)

    async def broadcast_to_ticket(self, ticket_id: str, payload: dict) -> None:
        for websocket in list(self._ticket_sockets.get(ticket_id, ())):
            try:
                await websocket.send_json(payload)
            except Exception:
                self.disconnect_ticket(ticket_id, websocket)

    def ticket_connection_count(self, ticket_id: str) -> int:
        return len(self._ticket_sockets.get(ticket_id, ()))

    # --- staff queue channel ---------------------------------------------

    def connect_queue(self, websocket: Any) -> None:
        self._queue_sockets.add(websocket)

    def disconnect_queue(self, websocket: Any) -> None:
        self._queue_sockets.discard(websocket)

    async def broadcast_to_queue(self, payload: dict) -> None:
        for websocket in list(self._queue_sockets):
            try:
                await websocket.send_json(payload)
            except Exception:
                self.disconnect_queue(websocket)

    def queue_connection_count(self) -> int:
        return len(self._queue_sockets)


# One manager per process - exactly matches the single-instance assumption
# this module's docstring depends on. Imported by app/api/v1/ws_support.py
# (the endpoints, FR-C103/C104) and app/services/support_svc.py (the
# broadcast-on-write hook, FR-C105).
manager = ConnectionManager()
