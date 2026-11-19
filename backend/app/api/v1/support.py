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
from app.models.catalog import Product
from app.models.order import Order
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
        .options(
            selectinload(SupportTicket.messages).selectinload(SupportMessage.attachments),
            selectinload(SupportTicket.messages)
            .selectinload(SupportMessage.shared_order)
            .selectinload(Order.product),
            selectinload(SupportTicket.messages)
            .selectinload(SupportMessage.shared_order)
            .selectinload(Order.esim_profile),
            selectinload(SupportTicket.messages)
            .selectinload(SupportMessage.shared_product)
            .selectinload(Product.country),
        )
        .where(SupportTicket.id == ticket_id)
    )).scalar_one_or_none()
    # Same 404 either way, so ticket ids can't be probed for existence.
    if not ticket or (ticket.user_id != user.id and not support_svc.is_staff(user)):
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


async def _thread_author(db: AsyncSession, ticket: SupportTicket, viewer: User) -> tuple[str, Optional[str]]:
    """The (name, avatar_url) every non-staff message in this ticket's thread
    is shown with (serialize_message substitutes "Support"/None for staff
    messages itself) - factored out of _thread() so a caller that's adding
    exactly one new message to an already-serialized thread (reply() below)
    doesn't need to re-run this query, or re-serialize the whole thread, just
    to serialize that one message consistently."""
    owner = (await db.execute(
        select(User.username, User.avatar_url).where(User.id == ticket.user_id)
    )).first()
    name = "You" if viewer.id == ticket.user_id else ((owner.username if owner else None) or "Customer")
    avatar_url = owner.avatar_url if owner else None
    return name, avatar_url


async def _thread(db: AsyncSession, ticket: SupportTicket, viewer: User) -> list:
    name, avatar_url = await _thread_author(db, ticket, viewer)
    return [
        support_svc.serialize_message(m, author_name=name, author_avatar_url=avatar_url)
        for m in ticket.messages
    ]


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
    # NOT Form(...) - Starlette's multipart parser treats an empty-string
    # value for a *required* Form field as the field being absent
    # entirely ("missing", not "provided but empty"), rejecting the
    # request with a 422 before post_message's own body-or-share-or-
    # attachment check ever runs. Confirmed live: every share-only
    # message (no text, just an order/product) failed with exactly this
    # 422 until this default was added.
    body: str = Form(""),
    category: TicketCategory = Form(TicketCategory.OTHER),
    order_id: Optional[str] = Form(None),
    shared_order_id: Optional[str] = Form(None),
    shared_product_id: Optional[str] = Form(None),
    files: List[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        attachments = await support_svc.save_attachments(files)
        ticket, message = await support_svc.create_ticket(
            db, current_user, subject=subject, category=category, body=body,
            order_id=order_id, attachments=attachments,
            shared_order_id=shared_order_id, shared_product_id=shared_product_id,
        )
    except support_svc.SupportError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    await db.commit()
    # NOT a re-fetch of the ticket afterwards - AsyncSessionLocal is
    # configured with expire_on_commit=False (app/core/database.py), and
    # every field post_message()/create_ticket() touch (ticket.status,
    # message.id, message.created_at, ...) is a Python-side default, never
    # server-generated - so the in-memory objects are already correct right
    # now, with zero extra round trips. The stale comment this replaced
    # ("after the commit the instance is expired") was simply wrong for this
    # session's actual config; confirmed live as the real cause of several-
    # second reply latency on mobile (a full eager-loaded ticket+thread
    # requery plus a full thread re-serialization, on every single message,
    # getting slower as a thread grows - see support_svc.reply's own note).
    #
    # Real-time push, strictly after the commit above - see
    # support_svc.broadcast_message's own docstring and docs/Rules.md. This
    # is the one DB round-trip still genuinely needed: message.attachments
    # was never loaded (added via a bare FK, not the ORM collection), so it
    # has to be fetched once to serialize it below.
    await support_svc.broadcast_message(db, ticket, message, author=current_user)

    notify_svc.notify_background(
        to=current_user.email,
        subject=f"We've got your message [{ticket.reference}]",
        title="Your support ticket is open",
        intro="Thanks for getting in touch. Someone will reply here, and you'll get an email when they do.",
        rows=[("Ticket", ticket.reference), ("Subject", ticket.subject)],
        cta_label="View the ticket", cta_path=f"/support/{ticket.id}",
        system_intro=f"{current_user.username} opened a ticket: {ticket.subject}",
    )
    # A brand-new ticket's thread is just this one message - the owner is
    # always the current user for a ticket they're creating.
    new_message = support_svc.serialize_message(message, author_name="You", author_avatar_url=current_user.avatar_url)
    return support_svc.serialize_ticket(ticket, messages=[new_message])


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
    # NOT Form(...) - see create_ticket's own comment above: an empty
    # string is rejected as "missing" by Starlette's multipart parser for
    # a required Form field, which silently 422'd every share-only reply
    # (no text, just a shared order/product) before post_message's own
    # validation ever ran.
    body: str = Form(""),
    shared_order_id: Optional[str] = Form(None),
    shared_product_id: Optional[str] = Form(None),
    files: List[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """One endpoint for both sides: support_svc decides what the reply does to
    the ticket's status based on who is writing."""
    ticket = await _ticket_for(db, ticket_id, current_user)
    staff = support_svc.is_staff(current_user)
    # Serialize the thread's EXISTING messages now, before post_message()
    # adds the new one below - this is the full set of messages that's
    # going back in the response regardless of what happens next, so there
    # is no reason to ask the DB for it a second time later. See the note
    # by the commit below for why a second fetch was happening at all.
    author_name, author_avatar_url = await _thread_author(db, ticket, current_user)
    existing_messages = [
        support_svc.serialize_message(m, author_name=author_name, author_avatar_url=author_avatar_url)
        for m in ticket.messages
    ]

    try:
        attachments = await support_svc.save_attachments(files)
        message = await support_svc.post_message(
            db, ticket, current_user, body=body, attachments=attachments,
            shared_order_id=shared_order_id, shared_product_id=shared_product_id,
        )
    except support_svc.SupportError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    await db.commit()
    # NOT a second _ticket_for()/thread re-fetch afterwards - AsyncSessionLocal
    # is configured with expire_on_commit=False (app/core/database.py), and
    # every field post_message() touches (ticket.status, message.id,
    # message.created_at, ...) is a Python-side default, never server-
    # generated - so `ticket` and `message` already hold correct values right
    # now, no round trip needed. This endpoint used to re-run the full
    # eager-loaded ticket+thread query AND re-serialize every message in it
    # on every single reply (confirmed live as the real cause of several-
    # second reply latency on mobile - it got slower as a thread grew, not a
    # flat cost). The only genuine DB work left is broadcast_message's own
    # refresh of this one new message's attachments/shared_order/
    # shared_product, which were never loaded (added via a bare FK, not the
    # ORM collection) - real-time push, strictly after the commit above, see
    # support_svc.broadcast_message's own docstring and docs/Rules.md.
    await support_svc.broadcast_message(db, ticket, message, author=current_user)

    customer_email = (await db.execute(
        select(User.email).where(User.id == ticket.user_id)
    )).scalar_one_or_none()
    if customer_email:
        _notify_new_message(
            ticket, from_staff=staff,
            customer_email=customer_email, body=body,
        )

    new_message = support_svc.serialize_message(message, author_name=author_name, author_avatar_url=author_avatar_url)
    return support_svc.serialize_ticket(
        ticket, messages=existing_messages + [new_message], for_staff=staff,
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
