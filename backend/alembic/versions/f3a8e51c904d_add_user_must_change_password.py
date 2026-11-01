"""add users.must_change_password for merchant-created customer accounts

When a merchant sells an eSIM to a walk-in customer we now create a real
account on their own email, with their phone number as the password so the
merchant can tell them how to get in. A phone number is often public, and
these accounts hold wallet balance and eSIMs, so that credential is
treated as single-use: it signs them in and nothing else until they set a
real password.

Existing accounts are left false - they chose their own passwords.

Revision ID: f3a8e51c904d
Revises: e2b7d4c91a53
Create Date: 2026-11-01 07:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a8e51c904d'
down_revision: Union[str, None] = 'e2b7d4c91a53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('users', 'must_change_password')
