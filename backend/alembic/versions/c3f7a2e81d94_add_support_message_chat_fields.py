"""add support_messages.message_type/shared_order_id/shared_product_id for real-time chat

Real-time support chat (FR-C101) extends the existing support ticket
system rather than a new one - see D:\\eSim\\docs\\Architecture.md. Adds an
explicit message_type (never inferred from a non-null shared_*_id - see
D:\\eSim\\docs\\Rules.md), and two nullable, ON DELETE SET NULL FKs for
sharing an order or a package inline in a message. Defaults every existing
row to TEXT with both shares null - no behavior change for any existing
ticket.

Revision ID: c3f7a2e81d94
Revises: b8e4f2a917c3
Create Date: 2026-11-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f7a2e81d94'
down_revision: Union[str, None] = 'b8e4f2a917c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

message_type_enum = sa.Enum('TEXT', 'ORDER_SHARE', 'PRODUCT_SHARE', name='messagetype')


def upgrade() -> None:
    message_type_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'support_messages',
        sa.Column('message_type', message_type_enum, nullable=False, server_default='TEXT'),
    )
    op.add_column('support_messages', sa.Column('shared_order_id', sa.String(length=36), nullable=True))
    op.add_column('support_messages', sa.Column('shared_product_id', sa.String(length=36), nullable=True))
    op.create_foreign_key(
        'fk_support_messages_shared_order_id', 'support_messages', 'orders',
        ['shared_order_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_support_messages_shared_product_id', 'support_messages', 'products',
        ['shared_product_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_support_messages_shared_order_id', 'support_messages', ['shared_order_id'])
    op.create_index('ix_support_messages_shared_product_id', 'support_messages', ['shared_product_id'])


def downgrade() -> None:
    op.drop_index('ix_support_messages_shared_product_id', table_name='support_messages')
    op.drop_index('ix_support_messages_shared_order_id', table_name='support_messages')
    op.drop_constraint('fk_support_messages_shared_product_id', 'support_messages', type_='foreignkey')
    op.drop_constraint('fk_support_messages_shared_order_id', 'support_messages', type_='foreignkey')
    op.drop_column('support_messages', 'shared_product_id')
    op.drop_column('support_messages', 'shared_order_id')
    op.drop_column('support_messages', 'message_type')
    message_type_enum.drop(op.get_bind(), checkfirst=True)
