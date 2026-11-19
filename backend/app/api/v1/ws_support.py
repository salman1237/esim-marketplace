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

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.security import decode_access_token
from app.models.support import SupportTicket
from app.models.user import User, UserStatus
from app.services import support_svc
from app.services.ws_manager import manager

logger = structlog.get_logger(__name__)
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


async def _authorize_ticket(token: Optional[str], ticket_id: str) -> tuple[int, bool, bool, bool]:
    """A short-lived session, used ONLY for the connect-time auth/ownership
    check - never held open for the connection's lifetime. Returns
    (close_code, ok, is_staff, is_guest): close_code is 0 on success, else
    WS_UNAUTHORIZED (no/invalid token, and not a matching guest_token
    either) or WS_FORBIDDEN (valid identity, not this ticket's owner or
    staff) - preserving the same distinction the REST endpoints' 401-vs-403
    makes, just via a close code.

    FR-C404: `?token=` is either a JWT or a guest_token (Architecture.md
    "Guest chat") - a browser has no way to send two different kinds of
    credential on a WS handshake, so this tries JWT auth first and falls
    back to treating the same string as a guest_token. The two namespaces
    can't collide: a JWT decodes successfully or it doesn't, and a
    guest_token is never a valid JWT.

    Deliberately NOT the same session pattern as a background task (e.g.
    the welcome email task in auth.py): those run once and finish quickly.
    A WebSocket can stay open for hours, and a WS connection's own receive
    loop touches no DB at all (typing is never persisted - see Rules.md),
    so pinning a connection open for that whole time was a real resource
    leak, confirmed live while building this - every open test connection
    left an `idle in transaction` session that, left unclosed, eventually
    deadlocks a schema reset against it. Open briefly, close immediately,
    then hold nothing."""
    async with AsyncSessionLocal() as db:
        # No token at all is always WS_UNAUTHORIZED, independent of
        # whether the ticket exists - same as before guest support, and
        # what test_ticket_socket_rejects_a_missing_token checks: a
        # missing credential is rejected before anything about the ticket
        # is even looked at.
        if not token:
            return WS_UNAUTHORIZED, False, False, False

        user = await _authenticate(token, db)
        ticket = (await db.execute(
            select(SupportTicket).where(SupportTicket.id == ticket_id)
        )).scalar_one_or_none()
        if not ticket:
            return WS_FORBIDDEN, False, False, False

        if user:
            staff = support_svc.is_staff(user)
            if ticket.user_id != user.id and not staff:
                return WS_FORBIDDEN, False, False, False
            return 0, True, staff, False

        # Not a valid JWT - try the same string as a guest_token.
        if support_svc.owns_ticket(ticket, guest_token=token):
            return 0, True, False, True

        return WS_UNAUTHORIZED, False, False, False


async def _authorize_staff(token: Optional[str]) -> tuple[int, Optional[User]]:
    async with AsyncSessionLocal() as db:
        user = await _authenticate(token, db)
        if not user:
            return WS_UNAUTHORIZED, None
        if not support_svc.is_staff(user):
            return WS_FORBIDDEN, None
        return 0, user


@router.websocket("/tickets/{ticket_id}")
async def ticket_socket(websocket: WebSocket, ticket_id: str, token: Optional[str] = Query(None)):
    close_code, ok, is_staff_viewer, _is_guest_viewer = await _authorize_ticket(token, ticket_id)
    if not ok:
        await websocket.close(code=close_code)
        return

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
    except Exception as exc:
        logger.warning("ws_ticket_socket_error", ticket_id=ticket_id, error=str(exc), error_type=type(exc).__name__)
    finally:
        manager.disconnect_ticket(ticket_id, websocket)


@router.websocket("/queue")
async def queue_socket(websocket: WebSocket, token: Optional[str] = Query(None)):
    """Staff-only. Pushes ticket_updated whenever any ticket changes, so
    the admin queue list updates live - without this, "real-time support"
    is only real-time for the customer (see Architecture.md)."""
    close_code, user = await _authorize_staff(token)
    if not user:
        await websocket.close(code=close_code)
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
