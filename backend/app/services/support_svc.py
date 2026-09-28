"""Support tickets: posting messages, attachments, and who the ticket waits on.

Status is never set by hand at a call site. Every message routes through
`post_message`, which moves the ticket based on who spoke - so the staff queue
always answers "what is waiting on me" correctly, and a customer replying to a
resolved ticket reopens it instead of vanishing.
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.support import (
    SupportAttachment, SupportMessage, SupportTicket, TicketStatus, new_reference,
)
from app.models.user import User, UserRole

UPLOAD_DIR = Path(settings.SUPPORT_UPLOADS_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_TYPES = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
    "image/heic": ".heic", "application/pdf": ".pdf", "text/plain": ".txt",
}
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 5
MAX_BODY_CHARS = 5000

STAFF_ROLES = {UserRole.SUPER_ADMIN, UserRole.ADMIN}
# Statuses a customer can still write into. A CLOSED ticket needs a new one,
# so a months-old thread can't be resurrected as a fresh problem.
CUSTOMER_WRITABLE = {TicketStatus.OPEN, TicketStatus.ANSWERED, TicketStatus.RESOLVED}


class SupportError(Exception):
    """A rule the caller broke, surfaced as a 400 with this message."""


def is_staff(user: User) -> bool:
    return user.role in STAFF_ROLES


async def save_attachments(files: Optional[Iterable[UploadFile]]) -> list[dict]:
    """Validates and writes the files, returning what the DB rows need.

    Reads everything before writing anything, so a rejected third file does
    not leave the first two on disk attached to a message that never existed.
    """
    incoming = [f for f in (files or []) if f and f.filename]
    if not incoming:
        return []
    if len(incoming) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise SupportError(f"You can attach up to {MAX_ATTACHMENTS_PER_MESSAGE} files to a message.")

    staged = []
    for upload in incoming:
        extension = ALLOWED_TYPES.get(upload.content_type)
        if not extension:
            raise SupportError(f"{upload.filename}: that file type isn't supported.")
        contents = await upload.read()
        if len(contents) > MAX_ATTACHMENT_BYTES:
            raise SupportError(f"{upload.filename} is larger than 5MB.")
        if not contents:
            raise SupportError(f"{upload.filename} is empty.")
        staged.append({
            "stored_filename": f"{uuid.uuid4().hex}{extension}",
            "original_name": upload.filename[:255],
            "content_type": upload.content_type,
            "size_bytes": len(contents),
            "_contents": contents,
        })

    for item in staged:
        (UPLOAD_DIR / item["stored_filename"]).write_bytes(item.pop("_contents"))
    return staged


async def create_ticket(
    db: AsyncSession, user: User, *, subject: str, category, body: str,
    order_id: Optional[str], attachments: list[dict],
) -> SupportTicket:
    """Caller commits."""
    subject = (subject or "").strip()
    if len(subject) < 3:
        raise SupportError("Give your ticket a subject.")

    ticket = SupportTicket(
        reference=new_reference(),
        user_id=user.id,
        subject=subject[:200],
        category=category,
        order_id=order_id or None,
        status=TicketStatus.OPEN,
    )
    db.add(ticket)
    await db.flush()
    await post_message(db, ticket, user, body=body, attachments=attachments)
    return ticket


async def post_message(
    db: AsyncSession, ticket: SupportTicket, author: User, *, body: str, attachments: list[dict],
) -> SupportMessage:
    """Adds a message and moves the ticket to whoever it now waits on."""
    body = (body or "").strip()
    if not body and not attachments:
        raise SupportError("Write a message or attach a file.")
    if len(body) > MAX_BODY_CHARS:
        raise SupportError("That message is too long.")

    staff = is_staff(author)
    if not staff and ticket.status not in CUSTOMER_WRITABLE:
        raise SupportError("This ticket is closed. Please open a new one.")

    message = SupportMessage(
        ticket_id=ticket.id,
        author_id=author.id,
        is_staff=staff,
        body=body or "(attachment only)",
    )
    db.add(message)
    await db.flush()

    for item in attachments:
        db.add(SupportAttachment(message_id=message.id, **item))

    now = datetime.now(timezone.utc)
    ticket.last_message_at = now
    # Whoever spoke last decides who it waits on. A customer replying to a
    # resolved ticket reopens it, which is the case that matters: a problem
    # that comes back must not stay marked done.
    ticket.status = TicketStatus.ANSWERED if staff else TicketStatus.OPEN
    if not staff and ticket.resolved_at:
        ticket.resolved_at = None
    return message


async def resolve_ticket(db: AsyncSession, ticket: SupportTicket) -> None:
    if ticket.status == TicketStatus.CLOSED:
        raise SupportError("This ticket is already closed.")
    ticket.status = TicketStatus.RESOLVED
    ticket.resolved_at = datetime.now(timezone.utc)


async def close_ticket(db: AsyncSession, ticket: SupportTicket) -> None:
    if ticket.status == TicketStatus.CLOSED:
        raise SupportError("This ticket is already closed.")
    ticket.status = TicketStatus.CLOSED
    ticket.closed_at = datetime.now(timezone.utc)


def serialize_attachment(attachment: SupportAttachment) -> dict:
    return {
        "id": attachment.id,
        "name": attachment.original_name,
        "content_type": attachment.content_type,
        "size_bytes": attachment.size_bytes,
        # Fetched through the authenticated endpoint, never a static path.
        "url": f"/api/v1/support/attachments/{attachment.id}",
    }


def serialize_message(message: SupportMessage, author_name: Optional[str] = None) -> dict:
    return {
        "id": message.id,
        "body": message.body,
        "is_staff": message.is_staff,
        # Customers see "Support" rather than a staff member's username: who
        # answered is our business, not theirs.
        "author": "Support" if message.is_staff else (author_name or "You"),
        "created_at": message.created_at,
        "attachments": [serialize_attachment(a) for a in (message.attachments or [])],
    }


def serialize_ticket(
    ticket: SupportTicket, *, messages: Optional[list] = None, user: Optional[User] = None,
    assignee_name: Optional[str] = None, for_staff: bool = False,
) -> dict:
    data = {
        "id": ticket.id,
        "reference": ticket.reference,
        "subject": ticket.subject,
        "category": ticket.category.value,
        "status": ticket.status.value,
        "order_id": ticket.order_id,
        "created_at": ticket.created_at,
        "last_message_at": ticket.last_message_at,
        "resolved_at": ticket.resolved_at,
        "closed_at": ticket.closed_at,
    }
    if for_staff:
        data.update({
            "customer": {"id": user.id, "username": user.username, "email": user.email} if user else None,
            "assigned_to": assignee_name,
        })
    if messages is not None:
        data["messages"] = messages
    return data
