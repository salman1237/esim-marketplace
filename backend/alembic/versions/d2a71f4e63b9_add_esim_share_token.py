"""add esim_profiles.share_token for the public tracking link

128 bits of randomness, never the profile id: VivaPe's own status page is
unauthenticated on a SEQUENTIAL transaction id, so anyone can count upwards
and read other customers' eSIMs. A random token can't be walked.

Existing eSIMs are left NULL and get a token the first time their owner opens
the status page, so there is no bulk backfill.

Revision ID: d2a71f4e63b9
Revises: c9e3b71d5028
Create Date: 2026-09-27 20:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2a71f4e63b9'
down_revision: Union[str, None] = 'c9e3b71d5028'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('esim_profiles', sa.Column('share_token', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_esim_profiles_share_token'), 'esim_profiles', ['share_token'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_esim_profiles_share_token'), table_name='esim_profiles')
    op.drop_column('esim_profiles', 'share_token')
