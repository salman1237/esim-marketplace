"""Real-time delivery for support chat (FR-C103/C104).

Writes stay REST (POST /support/tickets/{id}/messages, unchanged) - these
endpoints only push what REST already wrote, plus a never-persisted typing
event. See D:\\eSim\\docs\\Architecture.md and D:\\eSim\\docs\\Rules.md.

A WS handshake has no Authorization header from a browser - the token
travels as ?token=, decoded with the exact same app.core.security
helper the HTTP Authorization dependency uses (never a second,
divergent implementation - see D:\\eSim\\docs\\Rules.md).
"""
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.security import decode_access_token
from app.models.support import SupportTicket
from app.models.user import User, UserStatus
from app.services import support_svc
from app.services.ws_manager import manager

router = APIRouter(prefix="/ws/support", tags=["Support Chat (WebSocket)"])

# Same close-code family FastAPI/Starlette reserve for app-defined reasons
# (4000-4999). Not documented in the response body - see Rules.md: don't
# leak "ticket doesn't exist" vs "not yours" via the close reason text.
WS_UNAUTHORIZED = 4401
WS_FORBIDDEN = 4403


async def _authenticate(token: Optional[str], db: AsyncSession) -> Optional[User]:
    """Mirrors app.core.deps.get_current_user's decode+lookup exactly, just
    returning None instead of raising - a WS handshake rejects by closing,
    not by an HTTP exception."""
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload or payload.get("role") == "PARTNER_API":
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user or user.status == UserStatus.SUSPENDED:
        return None
    return user


@router.websocket("/tickets/{ticket_id}")
async def ticket_socket(websocket: WebSocket, ticket_id: str, token: Optional[str] = Query(None)):
    # A fresh session, not a request-scoped one - a WS connection outlives
    # any single HTTP request/response cycle (same reasoning as the
    # background-task sessions elsewhere in this codebase, e.g. the welcome
    # email task in auth.py).
    async with AsyncSessionLocal() as db:
        user = await _authenticate(token, db)
        if not user:
            await websocket.close(code=WS_UNAUTHORIZED)
            return

        ticket = (await db.execute(
            select(SupportTicket).where(SupportTicket.id == ticket_id)
        )).scalar_one_or_none()
        # Same 404-shaped check support.py's REST endpoints use (owner or
        # staff) - here expressed as a close code, since a WebSocket
        # handshake has no response body to put a 404 detail in.
        if not ticket or (ticket.user_id != user.id and not support_svc.is_staff(user)):
            await websocket.close(code=WS_FORBIDDEN)
            return

        is_staff_viewer = support_svc.is_staff(user)
        await websocket.accept()
        manager.connect_ticket(ticket_id, websocket)
        try:
            while True:
                data = await websocket.receive_json()
                if not isinstance(data, dict):
                    continue
                if data.get("type") == "typing":
                    # Never persisted - see Rules.md. Broadcast to everyone
                    # ELSE on this ticket's channel; a sender doesn't need
                    # to see their own typing indicator echoed back.
                    await manager.broadcast_to_ticket_except(
                        ticket_id, websocket,
                        {"type": "typing", "from": "staff" if is_staff_viewer else "customer"},
                    )
        except WebSocketDisconnect:
            pass
        finally:
            manager.disconnect_ticket(ticket_id, websocket)


@router.websocket("/queue")
async def queue_socket(websocket: WebSocket, token: Optional[str] = Query(None)):
    """Staff-only. Pushes ticket_updated whenever any ticket changes, so
    the admin queue list updates live - without this, "real-time support"
    is only real-time for the customer (see Architecture.md)."""
    async with AsyncSessionLocal() as db:
        user = await _authenticate(token, db)
        if not user:
            await websocket.close(code=WS_UNAUTHORIZED)
            return
        if not support_svc.is_staff(user):
            await websocket.close(code=WS_FORBIDDEN)
            return

        await websocket.accept()
        manager.connect_queue(websocket)
        try:
            while True:
                # Staff don't send anything on this channel today - just
                # keep the connection open and notice when it drops.
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            manager.disconnect_queue(websocket)
