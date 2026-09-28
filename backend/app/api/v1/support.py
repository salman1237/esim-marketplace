"""Support tickets, for customers and for staff.

Both sides live here so the thread is serialized once - a customer and the
admin answering them are always looking at the same conversation. Staff
endpoints are gated with require_admin, which is how manual deposits, KYC and
withdrawals already work, so sub-admins can handle support without Super Admin.

Attachments are served only through this router, to the ticket's owner or to
staff; the files never sit under the public uploads mount.
"""
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.core.logging import get_logger
from app.models.support import (
    SupportAttachment, SupportMessage, SupportTicket, TicketCategory, TicketStatus,
)
from app.models.user import User
from app.services import notify_svc, support_svc

logger = get_logger(__name__)
router = APIRouter(prefix="/support", tags=["Support"])

UPLOAD_DIR = Path(settings.SUPPORT_UPLOADS_DIR)


async def _ticket_for(db: AsyncSession, ticket_id: str, user: User) -> SupportTicket:
    ticket = (await db.execute(
        select(SupportTicket)
        .options(selectinload(SupportTicket.messages).selectinload(SupportMessage.attachments))
        .where(SupportTicket.id == ticket_id)
    )).scalar_one_or_none()
    # Same 404 either way, so ticket ids can't be probed for existence.
    if not ticket or (ticket.user_id != user.id and not support_svc.is_staff(user)):
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


async def _thread(db: AsyncSession, ticket: SupportTicket, viewer: User) -> list:
    owner = (await db.execute(select(User.username).where(User.id == ticket.user_id))).scalar_one_or_none()
    name = "You" if viewer.id == ticket.user_id else (owner or "Customer")
    return [support_svc.serialize_message(m, author_name=name) for m in ticket.messages]


def _notify_new_message(ticket: SupportTicket, *, from_staff: bool, customer_email: str, body: str) -> None:
    """Keeps the mail thread alive in both directions. The reference travels in
    the subject so replies stay grouped in whatever mail client they use."""
    preview = (body[:280] + "…") if len(body) > 280 else body
    if from_staff:
        notify_svc.notify_background(
            to=customer_email,
            subject=f"Re: {ticket.subject} [{ticket.reference}]",
            title="Support has replied",
            intro=preview,
            rows=[("Ticket", ticket.reference), ("Subject", ticket.subject)],
            cta_label="Open the ticket", cta_path=f"/support/{ticket.id}",
            copy_system=False,
        )
    else:
        notify_svc.notify_background(
            to=None,
            subject=f"Support: {ticket.subject} [{ticket.reference}]",
            title="A customer replied on a ticket",
            intro=preview,
            rows=[("Ticket", ticket.reference), ("Customer", customer_email), ("Status", "Waiting on support")],
        )


# --- Customer ---------------------------------------------------------------

@router.get("/categories")
async def list_categories():
    """So the form's options and the backend's enum can't drift apart."""
    labels = {
        "ESIM": "eSIM not working",
        "PAYMENT": "Payment or top-up",
        "REFUND": "Refund request",
        "ACCOUNT": "My account",
        "PARTNER": "Partner or agent",
        "OTHER": "Something else",
    }
    return [{"value": c.value, "label": labels.get(c.value, c.value.title())} for c in TicketCategory]


@router.get("/tickets")
async def my_tickets(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tickets = (await db.execute(
        select(SupportTicket)
        .where(SupportTicket.user_id == current_user.id)
        .order_by(SupportTicket.last_message_at.desc())
        .limit(100)
    )).scalars().all()
    return [support_svc.serialize_ticket(t) for t in tickets]


@router.post("/tickets")
async def create_ticket(
    subject: str = Form(...),
    body: str = Form(...),
    category: TicketCategory = Form(TicketCategory.OTHER),
    order_id: Optional[str] = Form(None),
    files: List[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        attachments = await support_svc.save_attachments(files)
        ticket = await support_svc.create_ticket(
            db, current_user, subject=subject, category=category, body=body,
            order_id=order_id, attachments=attachments,
        )
    except support_svc.SupportError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    await db.commit()
    # Re-read with the thread eagerly loaded: after the commit the instance is
    # expired, and touching ticket.messages would be a lazy load in async
    # context, which SQLAlchemy refuses rather than blocking the event loop.
    ticket = await _ticket_for(db, ticket.id, current_user)

    notify_svc.notify_background(
        to=current_user.email,
        subject=f"We've got your message [{ticket.reference}]",
        title="Your support ticket is open",
        intro="Thanks for getting in touch. Someone will reply here, and you'll get an email when they do.",
        rows=[("Ticket", ticket.reference), ("Subject", ticket.subject)],
        cta_label="View the ticket", cta_path=f"/support/{ticket.id}",
        system_intro=f"{current_user.username} opened a ticket: {ticket.subject}",
    )
    return support_svc.serialize_ticket(ticket, messages=await _thread(db, ticket, current_user))


@router.get("/tickets/{ticket_id}")
async def get_ticket(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ticket = await _ticket_for(db, ticket_id, current_user)
    staff = support_svc.is_staff(current_user)
    owner = (await db.execute(select(User).where(User.id == ticket.user_id))).scalar_one_or_none()
    assignee = None
    if staff and ticket.assigned_to_id:
        assignee = (await db.execute(
            select(User.username).where(User.id == ticket.assigned_to_id)
        )).scalar_one_or_none()
    return support_svc.serialize_ticket(
        ticket, messages=await _thread(db, ticket, current_user),
        user=owner, assignee_name=assignee, for_staff=staff,
    )


@router.post("/tickets/{ticket_id}/messages")
async def reply(
    ticket_id: str,
    body: str = Form(...),
    files: List[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """One endpoint for both sides: support_svc decides what the reply does to
    the ticket's status based on who is writing."""
    ticket = await _ticket_for(db, ticket_id, current_user)
    try:
        attachments = await support_svc.save_attachments(files)
        await support_svc.post_message(db, ticket, current_user, body=body, attachments=attachments)
    except support_svc.SupportError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    await db.commit()
    await db.refresh(ticket)

    customer_email = (await db.execute(
        select(User.email).where(User.id == ticket.user_id)
    )).scalar_one_or_none()
    if customer_email:
        _notify_new_message(
            ticket, from_staff=support_svc.is_staff(current_user),
            customer_email=customer_email, body=body,
        )

    refreshed = await _ticket_for(db, ticket_id, current_user)
    return support_svc.serialize_ticket(
        refreshed, messages=await _thread(db, refreshed, current_user),
        for_staff=support_svc.is_staff(current_user),
    )


@router.post("/tickets/{ticket_id}/close")
async def close(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ticket = await _ticket_for(db, ticket_id, current_user)
    try:
        await support_svc.close_ticket(db, ticket)
    except support_svc.SupportError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(ticket)
    return support_svc.serialize_ticket(ticket)


@router.get("/attachments/{attachment_id}")
async def download_attachment(
    attachment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(SupportAttachment, SupportTicket)
        .join(SupportMessage, SupportAttachment.message_id == SupportMessage.id)
        .join(SupportTicket, SupportMessage.ticket_id == SupportTicket.id)
        .where(SupportAttachment.id == attachment_id)
    )).first()
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found")

    attachment, ticket = row
    if ticket.user_id != current_user.id and not support_svc.is_staff(current_user):
        raise HTTPException(status_code=404, detail="Attachment not found")

    path = UPLOAD_DIR / attachment.stored_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing from storage")
    return FileResponse(path, media_type=attachment.content_type, filename=attachment.original_name)


# --- Staff ------------------------------------------------------------------

@router.get("/queue", dependencies=[Depends(require_admin)])
async def ticket_queue(
    status: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Oldest waiting first, because that is the one someone is still waiting on."""
    query = (
        select(SupportTicket, User)
        .join(User, SupportTicket.user_id == User.id)
        .order_by(SupportTicket.last_message_at.asc())
        .limit(limit)
    )
    wanted = (status or "").upper()
    if wanted == "ALL":
        pass  # every status, including resolved and closed
    elif wanted:
        try:
            query = query.where(SupportTicket.status == TicketStatus(wanted))
        except ValueError:
            raise HTTPException(status_code=400, detail="Unknown ticket status")
    else:
        # No filter asked for: show work to do, not an archive.
        query = query.where(SupportTicket.status.in_([TicketStatus.OPEN, TicketStatus.ANSWERED]))

    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.where(or_(
            SupportTicket.reference.ilike(like), SupportTicket.subject.ilike(like),
            User.email.ilike(like), User.username.ilike(like),
        ))

    rows = (await db.execute(query)).all()
    counts = dict((await db.execute(
        select(SupportTicket.status, func.count(SupportTicket.id)).group_by(SupportTicket.status)
    )).all())
    return {
        "counts": {s.value: counts.get(s, 0) for s in TicketStatus},
        "tickets": [support_svc.serialize_ticket(t, user=u, for_staff=True) for t, u in rows],
    }


@router.post("/tickets/{ticket_id}/resolve", dependencies=[Depends(require_admin)])
async def resolve(
    ticket_id: str,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    ticket = await _ticket_for(db, ticket_id, current_user)
    try:
        await support_svc.resolve_ticket(db, ticket)
    except support_svc.SupportError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    await db.refresh(ticket)

    customer_email = (await db.execute(
        select(User.email).where(User.id == ticket.user_id)
    )).scalar_one_or_none()
    if customer_email:
        notify_svc.notify_background(
            to=customer_email,
            subject=f"Resolved: {ticket.subject} [{ticket.reference}]",
            title="Your ticket has been resolved",
            intro="We've marked this as sorted. If it isn't, reply on the ticket and it reopens straight away.",
            rows=[("Ticket", ticket.reference), ("Subject", ticket.subject)],
            cta_label="View the ticket", cta_path=f"/support/{ticket.id}",
            copy_system=False,
        )
    return support_svc.serialize_ticket(ticket)


@router.post("/tickets/{ticket_id}/assign", dependencies=[Depends(require_admin)])
async def assign_to_me(
    ticket_id: str,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Claims a ticket, so two admins don't answer the same one."""
    ticket = await _ticket_for(db, ticket_id, current_user)
    ticket.assigned_to_id = current_user.id
    await db.commit()
    return {"status": "success", "assigned_to": current_user.username}
