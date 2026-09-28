"""add support tickets, messages and attachments

A customer thread with the support team. Status is derived from who spoke
last, so the staff queue answers "what is waiting on me" without anyone
maintaining it by hand.

Attachments store a filename only and are served through an authenticated
endpoint, like KYC documents and payout proofs - a customer troubleshooting an
eSIM will photograph a screen showing their own details.

Revision ID: a4d81c6e29f7
Revises: f7c2e91b30d5
Create Date: 2026-09-28 11:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4d81c6e29f7'
down_revision: Union[str, None] = 'f7c2e91b30d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'support_tickets',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('reference', sa.String(length=24), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('subject', sa.String(length=200), nullable=False),
        sa.Column(
            'category',
            sa.Enum('ESIM', 'PAYMENT', 'REFUND', 'ACCOUNT', 'PARTNER', 'OTHER', name='ticketcategory'),
            nullable=False,
        ),
        sa.Column(
            'status',
            sa.Enum('OPEN', 'ANSWERED', 'RESOLVED', 'CLOSED', name='ticketstatus'),
            nullable=False,
        ),
        sa.Column('order_id', sa.String(length=36), nullable=True),
        sa.Column('assigned_to_id', sa.String(length=36), nullable=True),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['assigned_to_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_support_tickets_assigned_to_id'), 'support_tickets', ['assigned_to_id'], unique=False)
    op.create_index(op.f('ix_support_tickets_created_at'), 'support_tickets', ['created_at'], unique=False)
    op.create_index(op.f('ix_support_tickets_last_message_at'), 'support_tickets', ['last_message_at'], unique=False)
    op.create_index(op.f('ix_support_tickets_reference'), 'support_tickets', ['reference'], unique=True)
    op.create_index(op.f('ix_support_tickets_status'), 'support_tickets', ['status'], unique=False)
    op.create_index(op.f('ix_support_tickets_user_id'), 'support_tickets', ['user_id'], unique=False)

    op.create_table(
        'support_messages',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('ticket_id', sa.String(length=36), nullable=False),
        sa.Column('author_id', sa.String(length=36), nullable=True),
        sa.Column('is_staff', sa.Boolean(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['ticket_id'], ['support_tickets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_support_messages_created_at'), 'support_messages', ['created_at'], unique=False)
    op.create_index(op.f('ix_support_messages_ticket_id'), 'support_messages', ['ticket_id'], unique=False)

    op.create_table(
        'support_attachments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('message_id', sa.String(length=36), nullable=False),
        sa.Column('stored_filename', sa.String(length=255), nullable=False),
        sa.Column('original_name', sa.String(length=255), nullable=False),
        sa.Column('content_type', sa.String(length=100), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['message_id'], ['support_messages.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_support_attachments_message_id'), 'support_attachments', ['message_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_support_attachments_message_id'), table_name='support_attachments')
    op.drop_table('support_attachments')
    op.drop_index(op.f('ix_support_messages_ticket_id'), table_name='support_messages')
    op.drop_index(op.f('ix_support_messages_created_at'), table_name='support_messages')
    op.drop_table('support_messages')
    for index in (
        'ix_support_tickets_user_id', 'ix_support_tickets_status', 'ix_support_tickets_reference',
        'ix_support_tickets_last_message_at', 'ix_support_tickets_created_at',
        'ix_support_tickets_assigned_to_id',
    ):
        op.drop_index(op.f(index), table_name='support_tickets')
    op.drop_table('support_tickets')
    sa.Enum(name='ticketstatus').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='ticketcategory').drop(op.get_bind(), checkfirst=True)
