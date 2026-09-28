"""Support tickets: a customer's thread with the support team.

Status is driven by who spoke last rather than set by hand, because the one
question staff actually need answered is "which of these is waiting on me".
A customer replying to a resolved ticket reopens it, so a problem that comes
back doesn't quietly disappear from the queue.

Attachments are stored like KYC documents and payout proofs - private filenames
on disk, served only through an authenticated endpoint - because a customer
troubleshooting an eSIM will photograph a screen showing their own details.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class TicketStatus(str, enum.Enum):
    OPEN = "OPEN"            # waiting on support
    ANSWERED = "ANSWERED"    # support replied, waiting on the customer
    RESOLVED = "RESOLVED"    # support considers it done
    CLOSED = "CLOSED"        # closed by the customer, or after resolution


class TicketCategory(str, enum.Enum):
    ESIM = "ESIM"
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"
    ACCOUNT = "ACCOUNT"
    PARTNER = "PARTNER"
    OTHER = "OTHER"


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Quotable in an email subject, which is what keeps a mail thread together.
    reference = Column(String(24), unique=True, nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    subject = Column(String(200), nullable=False)
    category = Column(Enum(TicketCategory), default=TicketCategory.OTHER, nullable=False)
    status = Column(Enum(TicketStatus), default=TicketStatus.OPEN, nullable=False, index=True)

    # Optional link to the order the customer is complaining about, so staff
    # don't have to ask for it.
    order_id = Column(String(36), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)

    assigned_to_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # Drives the queue ordering: oldest unanswered first.
    last_message_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", foreign_keys=[user_id])
    assignee = relationship("User", foreign_keys=[assigned_to_id])
    messages = relationship(
        "SupportMessage", back_populates="ticket", cascade="all, delete-orphan",
        order_by="SupportMessage.created_at",
    )


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id = Column(String(36), ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Recorded at write time rather than derived from the author's role later:
    # a staff member's role can change, and that must not rewrite who was
    # speaking as support in an old thread.
    is_staff = Column(Boolean, default=False, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    ticket = relationship("SupportTicket", back_populates="messages")
    attachments = relationship("SupportAttachment", back_populates="message", cascade="all, delete-orphan")


class SupportAttachment(Base):
    __tablename__ = "support_attachments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id = Column(String(36), ForeignKey("support_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    # Filename on disk only, resolved against settings.SUPPORT_UPLOADS_DIR.
    stored_filename = Column(String(255), nullable=False)
    original_name = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    message = relationship("SupportMessage", back_populates="attachments")


def new_reference() -> str:
    return f"TKT-{datetime.now(timezone.utc).strftime('%y%m%d')}-{uuid.uuid4().hex[:5].upper()}"
