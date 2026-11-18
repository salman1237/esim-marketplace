"""Support tickets: posting messages, attachments, and who the ticket waits on.

Status is never set by hand at a call site. Every message routes through
`post_message`, which moves the ticket based on who spoke - so the staff queue
always answers "what is waiting on me" correctly, and a customer replying to a
resolved ticket reopens it instead of vanishing.
"""
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.core.config import settings
from app.models.catalog import Product
from app.models.order import Order
from app.models.support import (
    MessageType, SupportAttachment, SupportMessage, SupportTicket, TicketStatus, new_reference,
)
from app.models.user import User, UserRole
from app.services.supplier_settings_svc import get_enabled_suppliers, supplier_visible_filter
from app.services.ws_manager import manager

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


async def _check_shared_order(db: AsyncSession, author: User, order_id: str) -> None:
    """FR-C106/Rules.md "Sharing an order or package": a customer can only
    share THEIR OWN order (buyer or beneficiary) - never let a customer
    reference someone else's order id in a chat message. Staff can share
    any order (they're troubleshooting it). Same ownership check as
    esims.py's `_load`, not a second, divergent implementation."""
    if is_staff(author):
        order = (await db.execute(select(Order.id).where(Order.id == order_id))).scalar_one_or_none()
        if not order:
            raise SupportError("That order doesn't exist.")
        return
    order = (await db.execute(
        select(Order.id).where(
            Order.id == order_id,
            (Order.buyer_id == author.id) | (Order.beneficiary_id == author.id),
        )
    )).scalar_one_or_none()
    if not order:
        raise SupportError("You can only share your own order.")


async def _check_shared_product(db: AsyncSession, product_id: str) -> None:
    """A product is public catalog data - same visibility rule as
    `GET /catalog/products/{id}`, shareable by anyone (Rules.md)."""
    enabled = await get_enabled_suppliers(db)
    product = (await db.execute(
        select(Product.id).where(
            Product.id == product_id, Product.is_active == True,
            supplier_visible_filter(Product.supplier_reference, enabled),
        )
    )).scalar_one_or_none()
    if not product:
        raise SupportError("That package isn't available.")


async def create_ticket(
    db: AsyncSession, user: User, *, subject: str, category, body: str,
    order_id: Optional[str], attachments: list[dict],
    shared_order_id: Optional[str] = None, shared_product_id: Optional[str] = None,
) -> tuple[SupportTicket, SupportMessage]:
    """Caller commits. Returns the message too (not just the ticket) so the
    caller can broadcast it (FR-C105) without a second query."""
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
    message = await post_message(
        db, ticket, user, body=body, attachments=attachments,
        shared_order_id=shared_order_id, shared_product_id=shared_product_id,
    )
    return ticket, message


async def post_message(
    db: AsyncSession, ticket: SupportTicket, author: User, *, body: str, attachments: list[dict],
    shared_order_id: Optional[str] = None, shared_product_id: Optional[str] = None,
) -> SupportMessage:
    """Adds a message and moves the ticket to whoever it now waits on."""
    if shared_order_id and shared_product_id:
        raise SupportError("A message can share an order or a package, not both.")
    body = (body or "").strip()
    if not body and not attachments and not shared_order_id and not shared_product_id:
        raise SupportError("Write a message or attach a file.")
    if len(body) > MAX_BODY_CHARS:
        raise SupportError("That message is too long.")

    staff = is_staff(author)
    if not staff and ticket.status not in CUSTOMER_WRITABLE:
        raise SupportError("This ticket is closed. Please open a new one.")

    message_type = MessageType.TEXT
    if shared_order_id:
        await _check_shared_order(db, author, shared_order_id)
        message_type = MessageType.ORDER_SHARE
    elif shared_product_id:
        await _check_shared_product(db, shared_product_id)
        message_type = MessageType.PRODUCT_SHARE

    message = SupportMessage(
        ticket_id=ticket.id,
        author_id=author.id,
        is_staff=staff,
        body=body or "(attachment only)",
        message_type=message_type,
        shared_order_id=shared_order_id or None,
        shared_product_id=shared_product_id or None,
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


async def broadcast_message(
    db: AsyncSession, ticket: SupportTicket, message: SupportMessage, *, author: User,
) -> None:
    """Pushes a just-committed message to the ticket's WebSocket channel,
    and a lightweight summary to the staff queue channel - FR-C105. Caller
    must call this AFTER db.commit(), never before - see
    D:\\eSim\\docs\\Rules.md: writes stay REST, this only pushes what REST
    already durably wrote.

    One payload goes to every connection on the ticket channel (customer
    and any staff watching), so "author" here is the real identity, never
    the REST serializer's viewer-relative "You" - a client personalizes
    that itself by comparing author_id to its own user id.

    `message.attachments` is unloaded on a message that was only just
    created+flushed in this same session (attachments were added via a
    bare FK, never through the ORM collection) - accessing it in
    serialize_message() without this refresh first triggers an implicit
    async lazy-load, which SQLAlchemy refuses (MissingGreenlet) because
    the greenlet bridge that makes `await_only()` work has already
    returned control by the time this runs. Confirmed live while building
    this: every ticket/reply broadcast failed the whole request until this
    explicit, awaited refresh was added.
    """
    await db.refresh(message, attribute_names=["attachments", "shared_order", "shared_product"])
    if message.shared_order:
        # serialize_shared_order() also reaches into order.product.title_en
        # and order.esim_profile.id (for the card's click target) - two more
        # lazy-load hops the refresh above doesn't cover on its own, same
        # MissingGreenlet risk as the attachments refresh above.
        await db.refresh(message.shared_order, attribute_names=["product", "esim_profile"])
    if message.shared_product:
        # serialize_shared_product() reaches into product.country.name_en
        # for the card's click target - same reasoning.
        await db.refresh(message.shared_product, attribute_names=["country"])
    await manager.broadcast_to_ticket(ticket.id, {
        "type": "message",
        "message": serialize_message(message, author_name=author.username, author_avatar_url=author.avatar_url),
    })
    await manager.broadcast_to_queue({
        "type": "ticket_updated",
        "ticket_id": ticket.id,
        "status": ticket.status.value,
        "last_message_at": ticket.last_message_at.isoformat() if ticket.last_message_at else None,
    })


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


def _country_slug(name: str) -> str:
    """Mirrors catalog.py's own country_slug helper exactly (not imported -
    api/v1 depending on services is the normal direction, not the reverse;
    this one-line regex is cheaper to keep in sync than to invert that)."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def serialize_shared_order(order: Optional[Order]) -> Optional[dict]:
    """None covers both "nothing was shared" and "it was shared, but the
    order is gone now" - ON DELETE SET NULL (Rules.md) leaves the message
    readable either way, never a broken reference."""
    if not order:
        return None
    return {
        "id": order.id,
        "order_no": order.order_no,
        "status": order.status.value,
        "total_amount": str(order.total_amount),
        "currency": order.currency,
        "product_title": order.product.title_en if order.product else None,
        # The card's click target - the existing /my-esims/{id} page,
        # which already allows the order's owner OR staff (esims.py's
        # _load), so this works the same for a customer viewing the
        # panel and a staff member viewing the admin queue. None (not
        # clickable) while the order hasn't provisioned an eSIM yet.
        "esim_profile_id": order.esim_profile.id if order.esim_profile else None,
    }


def serialize_shared_product(product: Optional[Product]) -> Optional[dict]:
    if not product:
        return None
    return {
        "id": product.id,
        "title": product.title_en,
        "data_amount_gb": str(product.data_amount_gb),
        "validity_days": product.validity_days,
        "is_unlimited": product.is_unlimited,
        "retail_price": str(product.retail_price),
        "currency": product.currency,
        # The card's click target - the existing /explore/{slug} country
        # page, same slug GET /catalog/countries already computes
        # (catalog.py's country_slug helper, reused here rather than a
        # second implementation).
        "country_slug": _country_slug(product.country.name_en) if product.country else None,
    }


def serialize_attachment(attachment: SupportAttachment) -> dict:
    return {
        "id": attachment.id,
        "name": attachment.original_name,
        "content_type": attachment.content_type,
        "size_bytes": attachment.size_bytes,
        # Fetched through the authenticated endpoint, never a static path.
        "url": f"/api/v1/support/attachments/{attachment.id}",
    }


def serialize_message(
    message: SupportMessage, author_name: Optional[str] = None, author_avatar_url: Optional[str] = None,
) -> dict:
    return {
        "id": message.id,
        "body": message.body,
        "is_staff": message.is_staff,
        # Lets a client personalize "author" into "You" itself by comparing
        # this to its own user id - needed for a WebSocket broadcast, where
        # one payload reaches every viewer and the server can't know which
        # one is "me" (see broadcast_message, FR-C105).
        "author_id": message.author_id,
        # Customers see "Support" rather than a staff member's username: who
        # answered is our business, not theirs.
        "author": "Support" if message.is_staff else (author_name or "You"),
        # Same anonymization as "author" above, applied to the photo too -
        # hiding a staff member's username but showing their personal photo
        # would leak the identity "Support" is there to hide. Straight from
        # User.avatar_url, never a generated-avatar service call for someone
        # with no photo - the client shows initials instead (Rules.md).
        "author_avatar_url": None if message.is_staff else author_avatar_url,
        # message_type is explicit, never inferred from "is a shared_*_id
        # set" (Rules.md) - a client switches on this, not on field presence.
        "message_type": message.message_type.value,
        "shared_order": serialize_shared_order(message.shared_order),
        "shared_product": serialize_shared_product(message.shared_product),
        # isoformat string, not a raw datetime: this dict is also sent
        # straight through websocket.send_json() in broadcast_message,
        # which uses plain json.dumps and has no datetime encoder (unlike
        # FastAPI's REST response path, which does) - confirmed live on
        # beta: a raw datetime here silently killed every broadcast with
        # "Object of type datetime is not JSON serializable", swallowed by
        # ConnectionManager's best-effort except-and-drop.
        "created_at": message.created_at.isoformat() if message.created_at else None,
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
