"""add Google sign-in fields to users

google_sub (Google's stable account id), avatar_url (profile photo) and
email_verified, populated by POST /auth/google.

Revision ID: 3b8d6a1f2c90
Revises: 7c1e2f9a4b6d
Create Date: 2026-09-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3b8d6a1f2c90'
down_revision: Union[str, None] = '7c1e2f9a4b6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('google_sub', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('avatar_url', sa.String(length=1024), nullable=True))
    op.add_column('users', sa.Column('email_verified', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_index(op.f('ix_users_google_sub'), 'users', ['google_sub'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_users_google_sub'), table_name='users')
    op.drop_column('users', 'email_verified')
    op.drop_column('users', 'avatar_url')
    op.drop_column('users', 'google_sub')
