"""add guest chat support: nullable user_id, guest_token, guest_email

Guest (non-logged-in) support chat (FR-C401) - a visitor can open a ticket
identified by a bare guest_token instead of a JWT's user_id. See
D:\\eSim\\docs\\Architecture.md "Guest chat". A ticket owns exactly one of
user_id/guest_token, never both, never neither - enforced by a
CheckConstraint, not just convention in the service layer. Every existing
row already has user_id set and guest_token NULL, so this is additive -
no existing ticket's ownership changes.

Revision ID: a8d2c40f916e
Revises: c3f7a2e81d94
Create Date: 2026-11-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8d2c40f916e'
down_revision: Union[str, None] = 'c3f7a2e81d94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('support_tickets', 'user_id', existing_type=sa.String(length=36), nullable=True)
    op.add_column('support_tickets', sa.Column('guest_token', sa.String(length=36), nullable=True))
    op.add_column('support_tickets', sa.Column('guest_email', sa.String(length=255), nullable=True))
    # NOT unique - exactly like user_id, one guest identity can own many
    # tickets over time (open one, come back later, open another).
    op.create_index('ix_support_tickets_guest_token', 'support_tickets', ['guest_token'])
    op.create_check_constraint(
        'ck_support_tickets_owner_xor', 'support_tickets',
        '(user_id IS NOT NULL) != (guest_token IS NOT NULL)',
    )


def downgrade() -> None:
    op.drop_constraint('ck_support_tickets_owner_xor', 'support_tickets', type_='check')
    op.drop_index('ix_support_tickets_guest_token', table_name='support_tickets')
    op.drop_column('support_tickets', 'guest_email')
    op.drop_column('support_tickets', 'guest_token')
    op.alter_column('support_tickets', 'user_id', existing_type=sa.String(length=36), nullable=False)
